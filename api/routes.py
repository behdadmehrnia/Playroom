"""HTTP routes exposing every piece of the Pipe's logic as an API.

The endpoints mirror the stages of ``Pipe._run_chat`` and also expose the
individual primitives (intent detection, persona resolution, textbook-query
building, textbook retrieval, generation, reflection) so a custom UI can drive
the assistant step-by-step. All heavy lifting is delegated to ``pipe`` helpers
and ``api.service``.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from pipe import (
    PERSONA_DROPDOWN_OPTIONS,
    SUPPORTED_PERSONAS,
    TEXTBOOK_PERSONAS,
    ChatMessage,
    LLMClient,
    TextbookContext,
    VALID_PERSONAS,
    _format_textbook_debug,
    _get_latest_user_message,
    build_textbook_query,
    fetch_textbook_context,
    generate_response,
    looks_like_textbook_help_request,
    looks_like_textbook_page_query,
    normalize_messages,
    reflect_on_response,
    resolve_manual_persona,
)

from api import __version__
from api.config import Settings
from api.llm import OpenAICompatibleLLMClient
from api.models import (
    ChatRequest,
    ChatResultOut,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    IntentRequest,
    IntentResponse,
    MessageIn,
    PersonaInfo,
    PersonaResolveRequest,
    PersonaResolveResponse,
    PersonasResponse,
    ReflectRequest,
    ReflectResponse,
    TextbookQueryRequest,
    TextbookQueryResponse,
    TextbookRetrieveRequest,
    TextbookRetrieveResponse,
)
from api.service import detect_intent_for, run_chat, run_chat_stream

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def to_chat_messages(messages: list[MessageIn]) -> list[ChatMessage]:
    """Convert inbound messages to ``pipe.ChatMessage`` via pipe.normalize_messages."""
    return normalize_messages([m.model_dump() for m in messages])


def resolve_backend_model(settings: Settings, requested: str | None) -> str:
    model = (requested or settings.backend_model).strip()
    if not model:
        raise HTTPException(
            status_code=400,
            detail=(
                "هیچ مدل پشتیبانی تنظیم نشده. "
                "YARKIDS_BACKEND_MODEL را تنظیم کنید یا «model» را در درخواست بفرستید."
            ),
        )
    return model


def chat_result_to_out(result: Any) -> ChatResultOut:
    return ChatResultOut(
        response=result.response,
        persona=result.persona,
        persona_source=result.persona_source,
        textbook_context=result.textbook_context,
        attempts=result.attempts,
        reflection=result.reflection,
        revised=result.revised,
        status_events=result.status_events,
        used_safe_fallback=result.used_safe_fallback,
    )


def build_resolve_body(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    return {"metadata": metadata}


# ---------------------------------------------------------------------------
# Root / health / meta
# ---------------------------------------------------------------------------


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Yar Kids API",
        "version": __version__,
        "docs": "/docs",
        "description": "دستیار کودک‌دوست — API مستقل با معماری Persona، Intent Detection و Reflection",
    }


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
    llm_client: OpenAICompatibleLLMClient = Depends(get_llm_client),
) -> HealthResponse:
    warnings: list[str] = []
    if not settings.backend_model:
        warnings.append("YARKIDS_BACKEND_MODEL not set")
    if not settings.llm_api_key:
        warnings.append("YARKIDS_LLM_API_KEY not set")
    if not settings.textbook_api_url.strip():
        warnings.append("YARKIDS_TEXTBOOK_API_URL not set")

    llm_ready = bool(
        settings.backend_model and settings.llm_api_key and settings.llm_base_url
    )
    return HealthResponse(
        status="ok",
        version=__version__,
        backend_model=settings.backend_model,
        llm_base_url=settings.llm_base_url,
        llm_ready=llm_ready,
        textbook_api_url=settings.textbook_api_url,
        textbook_enabled=settings.enable_textbook_context,
        reflection_enabled=settings.enable_reflection,
        warnings=warnings,
    )


@router.get("/v1/personas", response_model=PersonasResponse)
async def personas() -> PersonasResponse:
    return PersonasResponse(
        personas=[
            PersonaInfo(value=opt["value"], label=opt["label"])
            for opt in PERSONA_DROPDOWN_OPTIONS
        ],
        textbook_personas=sorted(TEXTBOOK_PERSONAS),
    )


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------


@router.post("/v1/intent", response_model=IntentResponse)
async def detect_intent_endpoint(
    req: IntentRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> IntentResponse:
    model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    intent, user_text = await detect_intent_for(
        llm_client=llm_client, backend_model=model, messages=messages
    )
    return IntentResponse(intent=intent, latest_user_message=user_text)


# ---------------------------------------------------------------------------
# Persona resolution
# ---------------------------------------------------------------------------


@router.post("/v1/persona/resolve", response_model=PersonaResolveResponse)
async def resolve_persona_endpoint(
    req: PersonaResolveRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> PersonaResolveResponse:
    model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    body = build_resolve_body(req.metadata)

    manual = resolve_manual_persona(user_persona=req.persona, body=body)
    if manual:
        return PersonaResolveResponse(persona=manual, source="manual")

    intent, _ = await detect_intent_for(
        llm_client=llm_client, backend_model=model, messages=messages
    )
    if intent.persona == "none":
        return PersonaResolveResponse(
            persona="none", source="default", confidence=intent.confidence
        )
    return PersonaResolveResponse(
        persona=intent.persona, source="intent", confidence=intent.confidence
    )


# ---------------------------------------------------------------------------
# Textbook query building + retrieval
# ---------------------------------------------------------------------------


@router.post("/v1/textbook/query", response_model=TextbookQueryResponse)
async def textbook_query_endpoint(
    req: TextbookQueryRequest,
) -> TextbookQueryResponse:
    messages = to_chat_messages(req.messages)
    query = build_textbook_query(messages)
    latest = _get_latest_user_message(messages)
    return TextbookQueryResponse(
        query=query,
        looks_like_page_query=looks_like_textbook_page_query(query),
        looks_like_help_request=looks_like_textbook_help_request(latest),
        latest_user_message=latest,
    )


@router.post("/v1/textbook/retrieve", response_model=TextbookRetrieveResponse)
async def retrieve_textbook_endpoint(
    req: TextbookRetrieveRequest,
    settings: Settings = Depends(get_settings),
) -> TextbookRetrieveResponse:
    # Resolve the query: explicit query wins, else build from messages.
    if req.query is not None:
        query = req.query.strip()
    elif req.messages:
        query = build_textbook_query(to_chat_messages(req.messages))
    else:
        query = ""

    # Resolve the latest user message (for the help-request heuristic).
    if req.user_message is not None:
        user_message = req.user_message.strip()
    elif req.messages:
        user_message = _get_latest_user_message(to_chat_messages(req.messages))
    else:
        user_message = ""

    persona = req.persona
    ctx_enabled = (
        req.enable_textbook_context
        if req.enable_textbook_context is not None
        else settings.enable_textbook_context
    )

    # Gate — mirror of Pipe._run_chat's should_fetch_textbook condition.
    gate_blocked = False
    gate_reason: str | None = None
    eligible = persona is None or persona in TEXTBOOK_PERSONAS
    if persona is not None and not eligible:
        gate_blocked = True
        gate_reason = "persona_not_eligible"
    elif not ctx_enabled:
        gate_blocked = True
        gate_reason = "textbook_context_disabled"
    elif not settings.textbook_api_url.strip():
        gate_blocked = True
        gate_reason = "no_textbook_api_url"

    should_fetch = bool(
        ctx_enabled
        and query
        and settings.textbook_api_url.strip()
        and eligible
    )

    context: TextbookContext | None = None
    fetched = False
    debug: str | None = None

    if should_fetch:
        include_image = (req.include_image or settings.textbook_include_image)
        include_image = include_image.strip().lower()
        if include_image not in {"never", "auto", "always"}:
            include_image = "auto"
        timeout = (
            req.timeout_sec
            if req.timeout_sec is not None
            else settings.textbook_request_timeout_sec
        )
        neighbors = (
            req.include_neighbors
            if req.include_neighbors is not None
            else settings.textbook_neighbor_pages
        )
        context = await fetch_textbook_context(
            query,
            api_url=settings.textbook_api_url,
            api_key=settings.textbook_api_key or None,
            include_neighbors=neighbors,
            include_image=include_image,  # type: ignore[arg-type]
            timeout_sec=timeout,
        )
        fetched = True
        if context and not context.matched:
            if looks_like_textbook_page_query(query):
                context.page_query_failed = True
            else:
                context.need_info = True
        debug_enabled = req.debug if req.debug is not None else settings.textbook_debug
        if debug_enabled and context:
            debug = _format_textbook_debug(
                query=query, api_url=settings.textbook_api_url, context=context
            )
    elif (
        ctx_enabled
        and not gate_blocked
        and not query
        and persona in TEXTBOOK_PERSONAS
        and looks_like_textbook_help_request(user_message)
    ):
        # Mirrors the Pipe's elif branch: child references their schoolbook but
        # hasn't given enough detail (grade + book + page) to run a lookup.
        context = TextbookContext(need_info=True)

    return TextbookRetrieveResponse(
        query=query,
        fetched=fetched,
        gate_blocked=gate_blocked,
        gate_reason=gate_reason,
        textbook_context=context,
        debug=debug,
    )


# ---------------------------------------------------------------------------
# Single-shot generation + reflection
# ---------------------------------------------------------------------------


@router.post("/v1/generate", response_model=GenerateResponse)
async def generate_endpoint(
    req: GenerateRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> GenerateResponse:
    if req.persona not in VALID_PERSONAS:
        raise HTTPException(
            status_code=400,
            detail=f"persona must be one of: {', '.join(sorted(SUPPORTED_PERSONAS))} or none",
        )
    model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    temperature = (
        req.temperature if req.temperature is not None else settings.temperature
    )
    response = await generate_response(
        llm_client,
        backend_model=model,
        persona=req.persona,  # type: ignore[arg-type]
        conversation_messages=messages,
        revision_reasons=req.revision_reasons,
        temperature=temperature,
        textbook_context=req.textbook_context,
    )
    return GenerateResponse(response=response)


@router.post("/v1/reflect", response_model=ReflectResponse)
async def reflect_endpoint(
    req: ReflectRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> ReflectResponse:
    model = resolve_backend_model(settings, req.model)
    reflection = await reflect_on_response(
        llm_client,
        backend_model=model,
        user_message=req.user_message,
        candidate_response=req.candidate_response,
        textbook_context=req.textbook_context,
    )
    return ReflectResponse(reflection=reflection)


# ---------------------------------------------------------------------------
# Full chat orchestration (mirrors Pipe.pipe / _run_chat)
# ---------------------------------------------------------------------------


async def _chat_event_stream(
    *,
    settings: Settings,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    req: ChatRequest,
    body: dict[str, Any] | None,
) -> Any:
    enable_status = settings.enable_status_updates
    async for event in run_chat_stream(
        settings=settings,
        llm_client=llm_client,
        backend_model=backend_model,
        messages=messages,
        persona=req.persona,
        body=body,
        temperature=req.temperature,
        enable_reflection=req.enable_reflection,
        enable_textbook_context=req.enable_textbook_context,
        enable_status=enable_status,
    ):
        etype = event["type"]
        if etype == "status":
            yield {
                "event": "status",
                "data": json.dumps(
                    {"description": event["description"]}, ensure_ascii=False
                ),
            }
        elif etype == "status_clear":
            yield {"event": "status_clear", "data": "{}"}
        elif etype == "chunk":
            yield {
                "event": "chunk",
                "data": json.dumps({"text": event["text"]}, ensure_ascii=False),
            }
        elif etype == "error":
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": event["message"]}, ensure_ascii=False
                ),
            }
        elif etype == "done":
            out = chat_result_to_out(event["result"])
            yield {"event": "done", "data": out.model_dump_json()}


@router.post("/v1/chat", response_model=ChatResultOut)
async def chat_endpoint(
    req: ChatRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    backend_model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    body = build_resolve_body(req.metadata)

    if req.stream:
        # EventSourceResponse is a Response subclass, so FastAPI bypasses the
        # response_model and streams Server-Sent Events directly.
        return EventSourceResponse(
            _chat_event_stream(
                settings=settings,
                llm_client=llm_client,
                backend_model=backend_model,
                messages=messages,
                req=req,
                body=body,
            )
        )

    result = await run_chat(
        settings=settings,
        llm_client=llm_client,
        backend_model=backend_model,
        messages=messages,
        persona=req.persona,
        body=body,
        temperature=req.temperature,
        enable_reflection=req.enable_reflection,
        enable_textbook_context=req.enable_textbook_context,
        on_status=None,
    )
    return chat_result_to_out(result)
