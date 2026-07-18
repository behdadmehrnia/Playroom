"""Request/response schemas for the Yar Kids API.

Domain models (``ChatMessage``, ``IntentDetectionResult``, ``ReflectionResult``,
``TextbookContext``, ``WebSearchContext``) live in ``api.core``. The models here
are API-facing wrappers and per-endpoint request bodies.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from api.core import (
    IntentDetectionResult,
    MathToolUsage,
    ReflectionResult,
    TextbookContext,
    TextbookQueryDiag,
    WebSearchContext,
    WebSearchQueryDiag,
)

Role = Literal["system", "user", "assistant"]
PersonaSource = Literal["manual", "intent", "default"]


class MessageIn(BaseModel):
    """Inbound chat message (normalized via ``api.core.normalize_messages``)."""

    role: Role
    content: str


class HealthResponse(BaseModel):
    status: str
    version: str
    backend_model: str
    llm_base_url: str
    llm_ready: bool
    textbook_api_url: str
    textbook_enabled: bool
    textbook_mode: str
    web_search_enabled: bool
    web_search_provider: str
    reflection_enabled: bool
    warnings: list[str] = Field(default_factory=list)


class PersonaInfo(BaseModel):
    value: str
    label: str


class PersonasResponse(BaseModel):
    personas: list[PersonaInfo]
    textbook_personas: list[str]
    web_search_personas: list[str]


class IntentRequest(BaseModel):
    model: str | None = None
    messages: list[MessageIn]
    persona: str | None = None


class IntentResponse(BaseModel):
    intent: IntentDetectionResult
    latest_user_message: str


class PersonaResolveRequest(BaseModel):
    model: str | None = None
    messages: list[MessageIn]
    persona: str | None = None
    metadata: dict[str, Any] | None = None


class PersonaResolveResponse(BaseModel):
    persona: str
    source: PersonaSource
    confidence: float | None = None


class TextbookQueryRequest(BaseModel):
    messages: list[MessageIn]


class TextbookQueryResponse(BaseModel):
    query: str
    looks_like_page_query: bool
    looks_like_help_request: bool
    latest_user_message: str


class TextbookRetrieveRequest(BaseModel):
    """Retrieve textbook context from the embedded textbook package.

    Either ``query`` (raw) or ``messages`` (conversation to build the query
    from) may be supplied. When ``persona`` is provided and is not one of the
    textbook personas, the same gate as the chat flow is applied.
    """

    query: str | None = None
    messages: list[MessageIn] | None = None
    persona: str | None = None
    user_message: str | None = None
    include_neighbors: int | None = Field(default=None, ge=0, le=3)
    include_image: str | None = None
    timeout_sec: float | None = Field(default=None, ge=1.0, le=30.0)
    enable_textbook_context: bool | None = None
    debug: bool | None = None


class TextbookRetrieveResponse(BaseModel):
    query: str
    fetched: bool
    gate_blocked: bool = False
    gate_reason: str | None = None
    textbook_context: TextbookContext | None = None
    debug: str | None = None


class WebSearchQueryRequest(BaseModel):
    messages: list[MessageIn]
    persona: str | None = None


class WebSearchQueryResponse(BaseModel):
    query: str
    looks_like_search_request: bool
    latest_user_message: str
    persona: str | None = None


class WebSearchRetrieveRequest(BaseModel):
    """Retrieve web search context (creative / storyteller / gamer personas)."""

    query: str | None = None
    messages: list[MessageIn] | None = None
    persona: str | None = None
    user_message: str | None = None
    provider: str | None = None
    max_results: int | None = Field(default=None, ge=1, le=10)
    timeout_sec: float | None = Field(default=None, ge=1.0, le=30.0)
    enable_web_search: bool | None = None
    force: bool = Field(
        default=False,
        description="اگر True باشد heuristic را رد می‌کند و حتماً جستجو می‌کند.",
    )
    debug: bool | None = None


class WebSearchRetrieveResponse(BaseModel):
    query: str
    fetched: bool
    gate_blocked: bool = False
    gate_reason: str | None = None
    web_search_context: WebSearchContext | None = None
    debug: str | None = None


class GenerateRequest(BaseModel):
    model: str | None = None
    persona: str
    messages: list[MessageIn]
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    textbook_context: TextbookContext | None = None
    web_search_context: WebSearchContext | None = None
    revision_reasons: list[str] | None = None


class GenerateResponse(BaseModel):
    response: str


class ReflectRequest(BaseModel):
    model: str | None = None
    user_message: str
    candidate_response: str
    textbook_context: TextbookContext | None = None
    web_search_context: WebSearchContext | None = None


class ReflectResponse(BaseModel):
    reflection: ReflectionResult


class ChatRequest(BaseModel):
    """Full chat orchestration request."""

    model: str | None = None
    messages: list[MessageIn]
    persona: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    enable_reflection: bool | None = None
    enable_textbook_context: bool | None = None
    enable_web_search: bool | None = None
    metadata: dict[str, Any] | None = None
    stream: bool = False


class YarKidsMeta(BaseModel):
    """Diagnostics embedded in OpenAI-compatible and custom chat responses."""

    persona: str
    persona_source: PersonaSource
    logs: list[str] = Field(default_factory=list)
    textbook: TextbookQueryDiag | None = None
    web_search: WebSearchQueryDiag | None = None
    math_tool: list[MathToolUsage] = Field(default_factory=list)
    attempts: int = 0
    reflection: ReflectionResult | None = None
    revised: bool = False
    used_safe_fallback: bool = False


class ChatResultOut(BaseModel):
    response: str
    persona: str
    persona_source: PersonaSource
    textbook_context: TextbookContext | None = None
    web_search_context: WebSearchContext | None = None
    attempts: int
    reflection: ReflectionResult | None = None
    revised: bool
    status_events: list[str] = Field(default_factory=list)
    logs: list[str] = Field(default_factory=list)
    textbook: TextbookQueryDiag | None = None
    web_search: WebSearchQueryDiag | None = None
    math_tool: list[MathToolUsage] = Field(default_factory=list)
    used_safe_fallback: bool


# ---------------------------------------------------------------------------
# OpenAI-compatible request/response models
# ---------------------------------------------------------------------------


class OpenAIChatMessageIn(BaseModel):
    role: str
    content: Any = None
    name: str | None = None


class OpenAIChatCompletionsRequest(BaseModel):
    """OpenAI Chat Completions body. ``model`` is optional and ignored."""

    model: str | None = None
    messages: list[OpenAIChatMessageIn]
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    stream: bool = False
    persona: str | None = None
    metadata: dict[str, Any] | None = None
    enable_reflection: bool | None = None
    enable_textbook_context: bool | None = None
    enable_web_search: bool | None = None


class OpenAIResponsesInputMessage(BaseModel):
    role: str
    content: Any = None


class OpenAIResponsesRequest(BaseModel):
    """OpenAI Responses API body. ``model`` is optional and ignored."""

    model: str | None = None
    input: Any = None
    messages: list[OpenAIChatMessageIn] | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    stream: bool = False
    persona: str | None = None
    metadata: dict[str, Any] | None = None
    enable_reflection: bool | None = None
    enable_textbook_context: bool | None = None
    enable_web_search: bool | None = None
