from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IncludeImageMode = Literal["never", "auto", "always"]
MatchType = Literal["exact_page", "lesson", "lesson_span", "topic_search", "none"]


class RetrieveRequest(BaseModel):
    query: str = Field(..., min_length=1, description="پیام کاربر به فارسی")
    include_neighbors: int = Field(default=1, ge=0, le=3)
    include_image: IncludeImageMode = "auto"
    grade: int | None = Field(default=None, ge=3, le=6)
    subject: str | None = Field(default=None, description="شناسه درس مثل math")
    page: int | None = Field(default=None, ge=1)


class RetrieveResponse(BaseModel):
    matched: bool
    match_type: MatchType = "none"
    grade: int | None = None
    subject: str | None = None
    subject_title: str | None = None
    page: int | None = None
    context_text: str | None = None
    needs_image: bool = False
    image_url: str | None = None
    image_base64: str | None = None
    confidence: float | None = None
    detected_topic: str | None = None
    detected_topic_label: str | None = None
    text_usable: bool = True


class HealthResponse(BaseModel):
    status: str
    index_exists: bool
    page_count: int
    catalog_books: int


class UploadPdfResponse(BaseModel):
    filename: str
    saved_path: str
    size_bytes: int
    registered: bool
    catalog_books: int


class ParsePdfRequest(BaseModel):
    filename: str | None = Field(
        default=None,
        description="نام فایل PDF داخل data/pdfs. اگر خالی باشد، کل ایندکس بازسازی می‌شود.",
    )
    ocr_engine: Literal["mineru", "tesseract"] = "mineru"
    mineru_backend: str = "pipeline"
    mineru_lang: str = "arabic"
    mineru_force: bool = Field(
        default=False, description="اجرای دوبارهٔ MinerU حتی اگر کش موجود باشد"
    )
    no_ocr: bool = False


class ParsePdfResponse(BaseModel):
    mode: Literal["single", "full"]
    filename: str | None = None
    pages_indexed: int | None = None
    total_page_count: int
    index_exists: bool
    ocr_engine: str
    job_id: str | None = None


class ParseJobStatus(BaseModel):
    job_id: str
    status: Literal["running", "done", "failed"]
    pages_indexed: int = 0
    total_page_count: int = 0
    ocr_engine: str | None = None
    error: str | None = None


class UploadIndexResponse(BaseModel):
    filename: str
    size_bytes: int
    page_count: int
    index_exists: bool


class UploadPagesResponse(BaseModel):
    files_extracted: int
    pages_dir: str
