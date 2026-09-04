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
    # Optional per-call HTTP timeout (seconds). None → client default.
    timeout_sec: float | None = None


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
    min_lesson: int | None = None
    max_lesson: int | None = None
    min_chapter: int | None = None
    max_chapter: int | None = None
    lesson: int | None = None
    chapter: int | None = None
    available_grades: list[int] | None = None

@dataclass(frozen=True)
class TextbookScope:
    """Structured textbook position resolved from chat (no NL query round-trip)."""

    grade: int | None = None
    subject: str | None = None  # subject key, e.g. "persian"
    subject_id: str | None = None  # catalog id, e.g. «persian»
    page: int | None = None
    lesson: int | None = None  # child unit number (lesson/session/skill/project)
    chapter: int | None = None  # parent unit number (chapter/section)
    kind: str | None = None  # lesson|session|project|skill|topic
    wants_outline: bool = False
    # Free-text leftover for topic search only (proper names and similar).
    topic_query: str | None = None

    def has_page_lookup(self) -> bool:
        return (
            self.grade is not None
            and self.subject_id is not None
            and self.page is not None
        )

    def has_lesson_lookup(self) -> bool:
        return (
            self.grade is not None
            and self.subject_id is not None
            and self.lesson is not None
        )

    def has_chapter_lookup(self) -> bool:
        return (
            self.grade is not None
            and self.subject_id is not None
            and self.chapter is not None
        )

    def has_outline_lookup(self) -> bool:
        return (
            self.wants_outline
            and self.grade is not None
            and self.subject_id is not None
        )

    def can_retrieve(self) -> bool:
        """True when structured fields can hit a specific book.

        Page/lesson/chapter/outline already require grade+subject.
        Free-text topic search also needs both — never guess across grades
        (e.g. "chapter 3 of maths" without a grade must ask, not open grade 3 via FTS).
        """
        if (
            self.has_page_lookup()
            or self.has_lesson_lookup()
            or self.has_chapter_lookup()
            or self.has_outline_lookup()
        ):
            return True
        if self.topic_query and self.topic_query.strip():
            return self.grade is not None and bool(self.subject_id)
        return False

    def debug_label(self) -> str:
        """Human-readable scope for logs/debug — not used as a parser input."""
        parts: list[str] = []
        if self.wants_outline:
            parts.append("فهرست")
        if self.chapter is not None:
            parts.append(f"فصل/بخش {self.chapter}")
        if self.lesson is not None:
            kind_label = {
                "session": "جلسه",
                "project": "پروژه",
                "skill": "مهارت",
                "topic": "موضوع",
            }.get(self.kind or "", "درس")
            parts.append(f"{kind_label} {self.lesson}")
        if self.page is not None:
            parts.append(f"صفحه {self.page}")
        label = (
            {
                "math": "ریاضی",
                "science": "علوم",
                "persian": "فارسی",
                "writing": "نگارش",
                "social": "مطالعات اجتماعی",
                "quran": "قرآن",
                "gifts": "هدیه های آسمان",
                "thinking": "تفکر",
                "technology": "فناوری",
            }.get(self.subject_id or "")
            or self.subject
        )
        if label:
            parts.append(label)
        if self.grade is not None:
            parts.append(_GRADE_INT_LABELS.get(self.grade, f"پایه {self.grade}"))
        if self.topic_query:
            parts.append(f"موضوع:{self.topic_query}")
        return " | ".join(parts) if parts else "(empty)"

    def compose_query(self, *, user_message: str | None = None) -> str:
        """Legacy NL string for diagnostics / topic search fallback only."""
        parts: list[str] = []
        if user_message and user_message.strip():
            parts.append(user_message.strip())
        if self.wants_outline:
            parts.append("فهرست کتاب")
        if self.chapter is not None:
            parts.append(f"فصل {self.chapter}")
        if self.lesson is not None:
            kind_label = {
                "session": "جلسه",
                "project": "پروژه",
                "skill": "مهارت",
                "topic": "موضوع",
            }.get(self.kind or "", "درس")
            parts.append(f"{kind_label} {self.lesson}")
        if self.page is not None:
            parts.append(f"صفحه {self.page}")
        _labels = {
            "math": "ریاضی",
            "science": "علوم",
            "persian": "فارسی",
            "writing": "نگارش",
            "social": "مطالعات اجتماعی",
            "quran": "قرآن",
            "gifts": "هدیه های آسمان",
            "thinking": "تفکر",
            "technology": "فناوری",
        }
        subject_label = (
            _labels.get(self.subject_id) if self.subject_id else None
        ) or self.subject
        if subject_label:
            parts.append(subject_label)
        if self.grade is not None:
            parts.append(_GRADE_INT_LABELS.get(self.grade, f"پایه {self.grade}"))
        return " ".join(parts).strip()

    def to_metadata(self) -> dict[str, int | str | bool]:
        payload: dict[str, int | str | bool] = {}
        if self.grade is not None:
            payload["grade"] = self.grade
        if self.subject_id:
            payload["subject"] = self.subject_id
        if self.page is not None:
            payload["page"] = self.page
        if self.lesson is not None:
            payload["lesson"] = self.lesson
        if self.chapter is not None:
            payload["chapter"] = self.chapter
        if self.kind:
            payload["kind"] = self.kind
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
