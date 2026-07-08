from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

IncludeImageMode = Literal["never", "auto", "always"]
MatchType = Literal["exact_page", "lesson", "topic_search", "none"]


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
