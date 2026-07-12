"""Request/response schemas for the Yar Kids API.

The core domain models (``ChatMessage``, ``IntentDetectionResult``,
``ReflectionResult``, ``TextbookContext``) are reused directly from ``pipe``
so the API can never drift from the Pipe's data shapes. The models here are
either thin API-facing wrappers around those, or per-endpoint request bodies.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from pipe import (
    IntentDetectionResult,
    ReflectionResult,
    TextbookContext,
)

Role = Literal["system", "user", "assistant"]
PersonaSource = Literal["manual", "intent", "default"]


class MessageIn(BaseModel):
    """Inbound chat message (tolerant: validated/normalized via pipe.normalize_messages)."""

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
    reflection_enabled: bool
    warnings: list[str] = Field(default_factory=list)


class PersonaInfo(BaseModel):
    value: str
    label: str


class PersonasResponse(BaseModel):
    personas: list[PersonaInfo]
    textbook_personas: list[str]


class IntentRequest(BaseModel):
    model: str | None = None
    messages: list[MessageIn]


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
    """Retrieve textbook context from the textbook-service.

    Either ``query`` (raw) or ``messages`` (conversation to build the query
    from) may be supplied. When ``persona`` is provided and is not one of the
    textbook personas, the same gate as the Pipe is applied and nothing is
    fetched. When ``persona`` is omitted the endpoint behaves as a standalone
    retrieval/diagnostic tool and fetches regardless of persona.
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


class GenerateRequest(BaseModel):
    model: str | None = None
    persona: str
    messages: list[MessageIn]
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    textbook_context: TextbookContext | None = None
    revision_reasons: list[str] | None = None


class GenerateResponse(BaseModel):
    response: str


class ReflectRequest(BaseModel):
    model: str | None = None
    user_message: str
    candidate_response: str
    textbook_context: TextbookContext | None = None


class ReflectResponse(BaseModel):
    reflection: ReflectionResult


class ChatRequest(BaseModel):
    """Full chat orchestration request (mirrors ``Pipe.pipe``)."""

    model: str | None = None
    messages: list[MessageIn]
    persona: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    enable_reflection: bool | None = None
    enable_textbook_context: bool | None = None
    metadata: dict[str, Any] | None = None
    stream: bool = False


class ChatResultOut(BaseModel):
    response: str
    persona: str
    persona_source: PersonaSource
    textbook_context: TextbookContext | None = None
    attempts: int
    reflection: ReflectionResult | None = None
    revised: bool
    status_events: list[str] = Field(default_factory=list)
    used_safe_fallback: bool
