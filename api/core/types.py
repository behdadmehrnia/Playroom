"""Domain models and the LLMClient protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from .constants import PersonaId, ReflectionStatus
from .math_tool import MathToolUsage

class IntentDetectionResult(BaseModel):
    persona: PersonaId
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class PersonaResolution(BaseModel):
    """Result of sticky persona resolution (may ask before switching)."""

    persona: PersonaId
    pending_switch_to: PersonaId | None = None
    ask_confirmation: bool = False


class ReflectionResult(BaseModel):
    status: ReflectionStatus
    reasons: list[str] | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None


class TextbookContext(BaseModel):
    matched: bool = False
    match_type: str | None = None
    grade: int | None = None
    subject: str | None = None
    subject_title: str | None = None
    page: int | None = None
    context_text: str | None = None
    needs_image: bool = False
    image_base64: str | None = None
    images_base64: list[str] = Field(default_factory=list)
    page_query_failed: bool = False
    page_out_of_range: bool = False
    need_info: bool = False
    text_usable: bool = True
    error: str | None = None
    failure_reason: str | None = None
    min_page: int | None = None
    max_page: int | None = None

@dataclass(frozen=True)
class TextbookScope:
    """Structured textbook position resolved from chat (grade, book, page)."""

    grade: int | None = None
    subject: str | None = None  # Persian keyword, e.g. «فارسی»
    subject_id: str | None = None  # catalog id, e.g. «persian»
    page: int | None = None

    def has_page_lookup(self) -> bool:
        return (
            self.grade is not None
            and self.subject_id is not None
            and self.page is not None
        )

    def compose_query(self, *, user_message: str | None = None) -> str:
        parts: list[str] = []
        if user_message and user_message.strip():
            parts.append(user_message.strip())
        if self.page is not None:
            parts.append(f"صفحه {self.page}")
        if self.subject:
            parts.append(self.subject)
        if self.grade is not None:
            parts.append(_GRADE_INT_LABELS.get(self.grade, f"پایه {self.grade}"))
        return " ".join(parts).strip()

    def to_metadata(self) -> dict[str, int | str]:
        payload: dict[str, int | str] = {}
        if self.grade is not None:
            payload["grade"] = self.grade
        if self.subject_id:
            payload["subject"] = self.subject_id
        if self.page is not None:
            payload["page"] = self.page
        return payload


_GRADE_INT_LABELS: dict[int, str] = {
    3: "سوم",
    4: "چهارم",
    5: "پنجم",
    6: "ششم",
}


class WebSearchResult(BaseModel):
    title: str = ""
    url: str | None = None
    snippet: str = ""


class WebSearchContext(BaseModel):
    matched: bool = False
    query: str | None = None
    results: list[WebSearchResult] = Field(default_factory=list)
    context_text: str | None = None
    provider: str | None = None
    error: str | None = None


class TextbookQueryDiag(BaseModel):
    """Diagnostics for textbook context lookup."""

    query_sent: str | None = None
    matched: bool = False
    context_preview: str | None = None
    grade: int | None = None
    subject: str | None = None
    subject_title: str | None = None
    page: int | None = None
    error: str | None = None
    need_info: bool = False
    page_query_failed: bool = False
    page_out_of_range: bool = False
    failure_reason: str | None = None
    min_page: int | None = None
    max_page: int | None = None


class WebSearchQueryDiag(BaseModel):
    """Diagnostics for web search lookup."""

    query_sent: str | None = None
    provider_used: str | None = None
    matched: bool = False
    results_count: int = 0
    error: str | None = None


class LLMClient(Protocol):
    async def complete(self, request: LLMCompletionRequest) -> str: ...


IntentDetectionResult.model_rebuild()
ReflectionResult.model_rebuild()
ChatMessage.model_rebuild()
MathToolUsage.model_rebuild()
TextbookQueryDiag.model_rebuild()
WebSearchQueryDiag.model_rebuild()
