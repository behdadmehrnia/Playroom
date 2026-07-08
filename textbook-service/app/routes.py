from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import API_KEY
from app.models import HealthResponse, RetrieveRequest, RetrieveResponse
from app.retrieve_service import retrieve_context
from app.store import get_page, index_exists, load_catalog, page_count, resolve_image_path

router = APIRouter()


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


@router.post("/v1/retrieve", response_model=RetrieveResponse)
def retrieve(
    request: RetrieveRequest,
    _: None = Depends(verify_api_key),
) -> RetrieveResponse:
    return retrieve_context(request)


@router.get("/v1/page-image")
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
