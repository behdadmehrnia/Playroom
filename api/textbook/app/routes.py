from __future__ import annotations

import threading
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from api.textbook.app.config import API_KEY, DATA_DIR, INDEX_PATH, PAGES_DIR, PDFS_DIR
from api.textbook.app.models import (
    HealthResponse,
    ParseJobStatus,
    ParsePdfRequest,
    ParsePdfResponse,
    RetrieveRequest,
    RetrieveResponse,
    UploadIndexResponse,
    UploadPagesResponse,
    UploadPdfResponse,
)
from api.textbook.app.retrieve_service import retrieve_context
from api.textbook.app.store import (
    CatalogBook,
    find_book_by_file,
    get_page,
    index_exists,
    load_catalog,
    page_count,
    resolve_image_path,
    upsert_book,
)

router = APIRouter()

_jobs: dict[str, ParseJobStatus] = {}
_jobs_lock = threading.Lock()


def verify_api_key(authorization: str | None = Header(default=None)) -> None:
    if not API_KEY:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    if token != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        index_exists=index_exists(),
        page_count=page_count(),
        catalog_books=len(load_catalog()),
    )


@router.post("/retrieve", response_model=RetrieveResponse)
def retrieve(
    request: RetrieveRequest,
    _: None = Depends(verify_api_key),
) -> RetrieveResponse:
    return retrieve_context(request)


@router.get("/page-image")
def page_image(
    grade: int = Query(..., ge=3, le=6),
    subject: str = Query(..., min_length=1),
    page: int = Query(..., ge=1),
    _: None = Depends(verify_api_key),
) -> FileResponse:
    record = get_page(grade, subject, page)
    if not record:
        raise HTTPException(status_code=404, detail="Page not found")
    image_path = resolve_image_path(record.image_path)
    if not image_path or not image_path.is_file():
        raise HTTPException(status_code=404, detail="Page image not found")
    return FileResponse(image_path, media_type="image/png")


def _sanitize_pdf_filename(name: str | None, fallback: str = "upload.pdf") -> str:
    """Strip path components and enforce a .pdf extension."""
    if not name:
        return fallback
    base = Path(name).name  # drop any directory traversal
    if not base:
        return fallback
    if not base.lower().endswith(".pdf"):
        base = base + ".pdf"
    return base


@router.post("/upload-pdf", response_model=UploadPdfResponse)
async def upload_pdf(
    file: UploadFile = File(..., description="فایل PDF کتاب درسی"),
    filename: str | None = Form(
        default=None, description="نام دلخواه برای ذخیره (پیش‌فرض: نام فایل آپلودی)"
    ),
    grade: int | None = Form(default=None, ge=3, le=6),
    subject: str | None = Form(default=None, description="شناسه درس مثل math"),
    title: str | None = Form(default=None),
    page_offset: int = Form(default=0, ge=0),
    register_in_catalog: bool = Form(
        default=True, description="افزودن/به‌روزرسانی در catalog.json (نیازمند grade و subject)"
    ),
    _: None = Depends(verify_api_key),
) -> UploadPdfResponse:
    saved_name = _sanitize_pdf_filename(filename or file.filename)
    if not file.content_type or "pdf" not in file.content_type.lower():
        # Trust the extension but warn via 415 when neither hint says PDF.
        if not saved_name.lower().endswith(".pdf"):
            raise HTTPException(status_code=415, detail="Only PDF files are accepted")

    if register_in_catalog and (grade is None or not subject):
        raise HTTPException(
            status_code=422,
            detail="register_in_catalog=true requires both grade and subject",
        )

    PDFS_DIR.mkdir(parents=True, exist_ok=True)
    dest = PDFS_DIR / saved_name

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    dest.write_bytes(content)

    registered = False
    if register_in_catalog:
        book = CatalogBook(
            file=saved_name,
            grade=grade,
            subject=subject.strip(),
            title=(title or subject.strip()),
            page_offset=page_offset,
        )
        registered = upsert_book(book)

    return UploadPdfResponse(
        filename=saved_name,
        saved_path=str(dest),
        size_bytes=len(content),
        registered=registered,
        catalog_books=len(load_catalog()),
    )


@router.post("/parse-pdfs", response_model=ParsePdfResponse)
def parse_pdfs(
    request: ParsePdfRequest,
    _: None = Depends(verify_api_key),
) -> ParsePdfResponse:
    from api.textbook.indexer.build_index import build_index, index_book

    use_ocr = not request.no_ocr

    if request.filename:
        book = find_book_by_file(request.filename)
        if book is None:
            raise HTTPException(
                status_code=404,
                detail=f"No catalog entry for file '{request.filename}'. "
                "Upload with register_in_catalog=true or add it to catalog.json first.",
            )
        try:
            pages_indexed = index_book(
                book,
                ocr_engine=request.ocr_engine,
                mineru_backend=request.mineru_backend,
                mineru_lang=request.mineru_lang,
                mineru_force=request.mineru_force,
                use_ocr=use_ocr,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return ParsePdfResponse(
            mode="single",
            filename=request.filename,
            pages_indexed=pages_indexed,
            total_page_count=page_count(),
            index_exists=index_exists(),
            ocr_engine=request.ocr_engine,
        )

    job_id = uuid.uuid4().hex[:12]
    job = ParseJobStatus(job_id=job_id, status="running", ocr_engine=request.ocr_engine)
    with _jobs_lock:
        _jobs[job_id] = job

    def _run_build() -> None:
        try:
            n = build_index(
                PDFS_DIR,
                ocr_engine=request.ocr_engine,
                mineru_backend=request.mineru_backend,
                mineru_lang=request.mineru_lang,
                mineru_force=request.mineru_force,
                use_ocr=use_ocr,
            )
            with _jobs_lock:
                job.status = "done"
                job.pages_indexed = n
                job.total_page_count = page_count()
        except Exception as exc:
            with _jobs_lock:
                job.status = "failed"
                job.error = str(exc)[:500]

    t = threading.Thread(target=_run_build, daemon=True)
    t.start()

    return ParsePdfResponse(
        mode="full",
        job_id=job_id,
        pages_indexed=None,
        total_page_count=page_count(),
        index_exists=index_exists(),
        ocr_engine=request.ocr_engine,
    )


@router.get("/parse-status/{job_id}", response_model=ParseJobStatus)
def parse_status(
    job_id: str,
    _: None = Depends(verify_api_key),
) -> ParseJobStatus:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job_id: {job_id}")
    return job


@router.post("/upload-index", response_model=UploadIndexResponse)
async def upload_index(
    file: UploadFile = File(..., description="index.sqlite file"),
    _: None = Depends(verify_api_key),
) -> UploadIndexResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_bytes(content)

    return UploadIndexResponse(
        filename="index.sqlite",
        size_bytes=len(content),
        page_count=page_count(),
        index_exists=index_exists(),
    )


@router.post("/upload-pages", response_model=UploadPagesResponse)
async def upload_pages(
    file: UploadFile = File(..., description="ZIP archive of page PNGs"),
    _: None = Depends(verify_api_key),
) -> UploadPagesResponse:
    import shutil
    import tempfile

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        await file.seek(0)
        with tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name

        try:
            zf = zipfile.ZipFile(tmp_path)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid ZIP file") from exc

        PAGES_DIR.mkdir(parents=True, exist_ok=True)
        extracted = 0
        with zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name
                if not name.lower().endswith(".png"):
                    continue
                target = PAGES_DIR / name
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                extracted += 1
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return UploadPagesResponse(
        files_extracted=extracted,
        pages_dir=str(PAGES_DIR),
    )
