"""HTTP routes for the standalone Yar Kids API.

Endpoints mirror the chat stages (intent, persona, textbook, web search,
generation, reflection) and mount the embedded textbook package under ``/v1``.
Also exposes OpenAI-compatible ``/v1/chat/completions`` and ``/v1/responses``.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

from api.core import (
    MODEL_ID,
    PERSONA_DROPDOWN_OPTIONS,
    SUPPORTED_PERSONAS,
    TEXTBOOK_PERSONAS,
    WEB_SEARCH_PERSONAS,
    ChatMessage,
    LLMClient,
    TextbookContext,
    VALID_PERSONAS,
    _format_textbook_debug,
    _format_web_search_debug,
    _get_latest_user_message,
    build_textbook_query,
    build_web_search_query,
    fetch_textbook_context,
    fetch_web_search_context,
    generate_response,
    looks_like_textbook_help_request,
    looks_like_textbook_page_query,
    looks_like_web_search_request,
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
    OpenAIChatCompletionsRequest,
    OpenAIResponsesRequest,
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
    WebSearchQueryRequest,
    WebSearchQueryResponse,
    WebSearchRetrieveRequest,
    WebSearchRetrieveResponse,
    YarKidsMeta,
)
from api.service import detect_intent_for, run_chat, run_chat_stream
from api.textbook.app.routes import router as textbook_router

router = APIRouter()
router.include_router(textbook_router, prefix="/v1")


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
    """Convert inbound messages via ``api.core.normalize_messages``."""
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
    logs = list(getattr(result, "logs", None) or result.status_events or [])
    return ChatResultOut(
        response=result.response,
        persona=result.persona,
        persona_source=result.persona_source,
        textbook_context=result.textbook_context,
        web_search_context=result.web_search_context,
        attempts=result.attempts,
        reflection=result.reflection,
        revised=result.revised,
        status_events=result.status_events,
        logs=logs,
        textbook=getattr(result, "textbook", None),
        web_search=getattr(result, "web_search", None),
        math_tool=list(getattr(result, "math_tool", None) or []),
        used_safe_fallback=result.used_safe_fallback,
    )


def chat_result_to_yarkids_meta(result: Any) -> YarKidsMeta:
    out = chat_result_to_out(result)
    return YarKidsMeta(
        persona=out.persona,
        persona_source=out.persona_source,
        logs=out.logs,
        textbook=out.textbook,
        web_search=out.web_search,
        math_tool=out.math_tool,
        attempts=out.attempts,
        reflection=out.reflection,
        revised=out.revised,
        used_safe_fallback=out.used_safe_fallback,
    )


def build_resolve_body(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not metadata:
        return None
    return {"metadata": metadata}


def _extract_text_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
                elif "content" in item:
                    parts.append(_extract_text_content(item.get("content")))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return _extract_text_content(content.get("text") or content.get("content"))
    return str(content)


def openai_messages_to_chat_messages(raw_messages: list[Any]) -> list[ChatMessage]:
    payload: list[dict[str, Any]] = []
    for msg in raw_messages:
        if hasattr(msg, "model_dump"):
            data = msg.model_dump()
        elif isinstance(msg, dict):
            data = msg
        else:
            continue
        role = str(data.get("role") or "user").strip().lower()
        if role not in {"system", "user", "assistant"}:
            role = "user"
        payload.append({"role": role, "content": _extract_text_content(data.get("content"))})
    return normalize_messages(payload)


def responses_input_to_messages(req: OpenAIResponsesRequest) -> list[ChatMessage]:
    if req.messages:
        return openai_messages_to_chat_messages(req.messages)

    raw = req.input
    if raw is None:
        return []
    if isinstance(raw, str):
        return normalize_messages([{"role": "user", "content": raw}])
    if isinstance(raw, list):
        # May be a list of messages or content parts
        if raw and isinstance(raw[0], dict) and "role" in raw[0]:
            return openai_messages_to_chat_messages(raw)
        return normalize_messages(
            [{"role": "user", "content": _extract_text_content(raw)}]
        )
    if isinstance(raw, dict):
        if "role" in raw:
            return openai_messages_to_chat_messages([raw])
        return normalize_messages(
            [{"role": "user", "content": _extract_text_content(raw)}]
        )
    return normalize_messages([{"role": "user", "content": str(raw)}])


def resolve_backend_model_optional(
    settings: Settings, requested: str | None
) -> str:
    """Prefer env backend model; ignore client model for OpenAI-compatible routes."""
    model = settings.backend_model.strip()
    if not model:
        # Fall back only if env is empty — still allow a client override as last resort
        model = (requested or "").strip()
    if not model:
        raise HTTPException(
            status_code=400,
            detail=(
                "هیچ مدل پشتیبانی تنظیم نشده. "
                "YARKIDS_BACKEND_MODEL را تنظیم کنید."
            ),
        )
    return model


# ---------------------------------------------------------------------------
# Root / health / meta
# ---------------------------------------------------------------------------


@router.get("/")
async def root() -> dict[str, str]:
    return {
        "name": "Yar Kids API",
        "version": __version__,
        "docs": "/docs",
        "description": (
            "دستیار کودک‌دوست — API مستقل با معماری Persona، Intent Detection و Reflection. "
            "اندپوینت‌های OpenAI-compatible: /v1/chat/completions و /v1/responses"
        ),
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

    textbook_mode = "embedded" if settings.uses_embedded_textbook() else "external"

    llm_ready = bool(
        settings.backend_model and settings.llm_api_key and settings.llm_base_url
    )
    return HealthResponse(
        status="ok",
        version=__version__,
        backend_model=settings.backend_model,
        llm_base_url=settings.llm_base_url,
        llm_ready=llm_ready,
        textbook_api_url=settings.textbook_api_url or "embedded",
        textbook_enabled=settings.enable_textbook_context,
        textbook_mode=textbook_mode,
        web_search_enabled=settings.enable_web_search,
        web_search_provider=settings.normalized_web_search_provider(),
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
        web_search_personas=sorted(WEB_SEARCH_PERSONAS),
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
        llm_client=llm_client, backend_model=model, messages=messages, current_persona=req.persona
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

    from api.core import (
        _detect_explicit_persona_request,
        _get_latest_user_message,
        resolve_active_persona,
        resolve_manual_persona,
    )

    latest = _get_latest_user_message(messages)
    explicit = _detect_explicit_persona_request(latest) if latest else None
    manual = resolve_manual_persona(user_persona=req.persona, body=body)

    persona = await resolve_active_persona(
        llm_client,
        backend_model=model,
        messages=messages,
        user_persona=req.persona,
        body=body,
    )

    if explicit and persona == explicit:
        return PersonaResolveResponse(persona=persona, source="intent", confidence=0.98)
    if manual and persona == manual:
        return PersonaResolveResponse(persona=manual, source="manual")
    if persona == "none":
        return PersonaResolveResponse(persona="none", source="default")
    return PersonaResolveResponse(persona=persona, source="intent")


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
    if req.query is not None:
        query = req.query.strip()
    elif req.messages:
        query = build_textbook_query(to_chat_messages(req.messages))
    else:
        query = ""

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

    gate_blocked = False
    gate_reason: str | None = None
    eligible = persona is None or persona in TEXTBOOK_PERSONAS
    if persona is not None and not eligible:
        gate_blocked = True
        gate_reason = "persona_not_eligible"
    elif not ctx_enabled:
        gate_blocked = True
        gate_reason = "textbook_context_disabled"

    should_fetch = bool(ctx_enabled and query and eligible)

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
                query=query,
                api_url=settings.textbook_api_url or "embedded",
                context=context,
            )
    elif (
        ctx_enabled
        and not gate_blocked
        and not query
        and persona in TEXTBOOK_PERSONAS
        and looks_like_textbook_help_request(user_message)
    ):
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
# Web search query building + retrieval
# ---------------------------------------------------------------------------


@router.post("/v1/web-search/query", response_model=WebSearchQueryResponse)
async def web_search_query_endpoint(
    req: WebSearchQueryRequest,
) -> WebSearchQueryResponse:
    messages = to_chat_messages(req.messages)
    query = build_web_search_query(messages)
    latest = _get_latest_user_message(messages)
    return WebSearchQueryResponse(
        query=query,
        looks_like_search_request=looks_like_web_search_request(
            latest, persona=req.persona
        ),
        latest_user_message=latest,
        persona=req.persona,
    )


@router.post("/v1/web-search/retrieve", response_model=WebSearchRetrieveResponse)
async def retrieve_web_search_endpoint(
    req: WebSearchRetrieveRequest,
    settings: Settings = Depends(get_settings),
) -> WebSearchRetrieveResponse:
    messages = to_chat_messages(req.messages) if req.messages else []

    if req.query is not None:
        query = req.query.strip()
    elif messages:
        query = build_web_search_query(messages)
    else:
        query = ""

    if req.user_message is not None:
        user_message = req.user_message.strip()
    elif messages:
        user_message = _get_latest_user_message(messages)
    else:
        user_message = ""

    persona = req.persona
    search_enabled = (
        req.enable_web_search
        if req.enable_web_search is not None
        else settings.enable_web_search
    )

    gate_blocked = False
    gate_reason: str | None = None
    eligible = persona is None or persona in WEB_SEARCH_PERSONAS
    if persona is not None and not eligible:
        gate_blocked = True
        gate_reason = "persona_not_eligible"
    elif not search_enabled:
        gate_blocked = True
        gate_reason = "web_search_disabled"

    needs_heuristic = (
        looks_like_web_search_request(user_message, persona=persona)
        if user_message
        else True
    )
    should_fetch = bool(
        search_enabled
        and query
        and eligible
        and (req.force or needs_heuristic or persona is None)
    )

    context = None
    fetched = False
    debug: str | None = None

    if should_fetch:
        provider = (req.provider or settings.normalized_web_search_provider()).strip().lower()
        if provider not in {"auto", "api", "duckduckgo", "perplexity"}:
            provider = "auto"
        timeout = (
            req.timeout_sec
            if req.timeout_sec is not None
            else settings.web_search_request_timeout_sec
        )
        max_results = (
            req.max_results
            if req.max_results is not None
            else settings.web_search_max_results
        )
        context = await fetch_web_search_context(
            query,
            provider=provider,
            api_url=settings.web_search_api_url,
            api_key=settings.web_search_api_key or None,
            perplexity_url=settings.web_search_perplexity_url,
            max_results=max_results,
            timeout_sec=timeout,
        )
        fetched = True
        debug_enabled = req.debug if req.debug is not None else settings.web_search_debug
        if debug_enabled and context:
            debug = _format_web_search_debug(
                query=query, provider=provider, context=context
            )
    elif not gate_blocked and not needs_heuristic and not req.force:
        gate_blocked = True
        gate_reason = "not_a_search_request"

    return WebSearchRetrieveResponse(
        query=query,
        fetched=fetched,
        gate_blocked=gate_blocked,
        gate_reason=gate_reason,
        web_search_context=context,
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
        web_search_context=req.web_search_context,
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
        web_search_context=req.web_search_context,
    )
    return ReflectResponse(reflection=reflection)


# ---------------------------------------------------------------------------
# Full chat orchestration
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
        enable_web_search=req.enable_web_search,
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
        enable_web_search=req.enable_web_search,
        on_status=None,
    )
    return chat_result_to_out(result)


# ---------------------------------------------------------------------------
# OpenAI-compatible: /v1/chat/completions (+ alias) and /v1/responses
# ---------------------------------------------------------------------------


def _openai_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def _openai_response_id() -> str:
    return f"resp_{uuid.uuid4().hex[:24]}"


def _build_chat_completion_payload(
    *,
    result: Any,
    completion_id: str,
    created: int,
) -> dict[str, Any]:
    meta = chat_result_to_yarkids_meta(result)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.response},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "yarkids": meta.model_dump(mode="json"),
    }


def _build_responses_payload(
    *,
    result: Any,
    response_id: str,
    created: int,
) -> dict[str, Any]:
    meta = chat_result_to_yarkids_meta(result)
    message_id = f"msg_{uuid.uuid4().hex[:20]}"
    return {
        "id": response_id,
        "object": "response",
        "created_at": created,
        "status": "completed",
        "model": MODEL_ID,
        "output": [
            {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": result.response,
                    }
                ],
            }
        ],
        "output_text": result.response,
        "yarkids": meta.model_dump(mode="json"),
    }


async def _openai_chat_completions_stream(
    *,
    settings: Settings,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    persona: str | None,
    body: dict[str, Any] | None,
    temperature: float | None,
    enable_reflection: bool | None,
    enable_textbook_context: bool | None,
    enable_web_search: bool | None,
) -> Any:
    completion_id = _openai_completion_id()
    created = int(time.time())

    async def event_gen():
        # role preamble
        preamble = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant"},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(preamble, ensure_ascii=False)}\n\n"

        result = None
        async for event in run_chat_stream(
            settings=settings,
            llm_client=llm_client,
            backend_model=backend_model,
            messages=messages,
            persona=persona,
            body=body,
            temperature=temperature,
            enable_reflection=enable_reflection,
            enable_textbook_context=enable_textbook_context,
            enable_web_search=enable_web_search,
            enable_status=False,
        ):
            etype = event["type"]
            if etype == "chunk":
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": event["text"]},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            elif etype == "error":
                err = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": f"\n[error] {event['message']}"},
                            "finish_reason": "stop",
                        }
                    ],
                    "yarkids": {"error": event["message"]},
                }
                yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            elif etype == "done":
                result = event["result"]

        final = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
            "yarkids": chat_result_to_yarkids_meta(result).model_dump(mode="json")
            if result
            else None,
        }
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


async def _openai_responses_stream(
    *,
    settings: Settings,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    persona: str | None,
    body: dict[str, Any] | None,
    temperature: float | None,
    enable_reflection: bool | None,
    enable_textbook_context: bool | None,
    enable_web_search: bool | None,
) -> Any:
    response_id = _openai_response_id()
    created = int(time.time())
    message_id = f"msg_{uuid.uuid4().hex[:20]}"
    item_id = f"item_{uuid.uuid4().hex[:16]}"

    async def event_gen():
        created_evt = {
            "type": "response.created",
            "response": {
                "id": response_id,
                "object": "response",
                "created_at": created,
                "status": "in_progress",
                "model": MODEL_ID,
                "output": [],
            },
        }
        yield f"event: response.created\ndata: {json.dumps(created_evt, ensure_ascii=False)}\n\n"

        output_item = {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        }
        yield (
            f"event: response.output_item.added\n"
            f"data: {json.dumps(output_item, ensure_ascii=False)}\n\n"
        )

        content_part = {
            "type": "response.content_part.added",
            "item_id": message_id,
            "output_index": 0,
            "content_index": 0,
            "part": {"type": "output_text", "text": ""},
        }
        yield (
            f"event: response.content_part.added\n"
            f"data: {json.dumps(content_part, ensure_ascii=False)}\n\n"
        )

        result = None
        async for event in run_chat_stream(
            settings=settings,
            llm_client=llm_client,
            backend_model=backend_model,
            messages=messages,
            persona=persona,
            body=body,
            temperature=temperature,
            enable_reflection=enable_reflection,
            enable_textbook_context=enable_textbook_context,
            enable_web_search=enable_web_search,
            enable_status=False,
        ):
            etype = event["type"]
            if etype == "chunk":
                delta = {
                    "type": "response.output_text.delta",
                    "item_id": message_id,
                    "output_index": 0,
                    "content_index": 0,
                    "delta": event["text"],
                }
                yield (
                    f"event: response.output_text.delta\n"
                    f"data: {json.dumps(delta, ensure_ascii=False)}\n\n"
                )
            elif etype == "error":
                failed = {
                    "type": "response.failed",
                    "response": {
                        "id": response_id,
                        "object": "response",
                        "status": "failed",
                        "error": {"message": event["message"]},
                    },
                }
                yield f"event: response.failed\ndata: {json.dumps(failed, ensure_ascii=False)}\n\n"
                return
            elif etype == "done":
                result = event["result"]

        done_text = {
            "type": "response.output_text.done",
            "item_id": message_id,
            "output_index": 0,
            "content_index": 0,
            "text": result.response if result else "",
        }
        yield (
            f"event: response.output_text.done\n"
            f"data: {json.dumps(done_text, ensure_ascii=False)}\n\n"
        )

        completed = {
            "type": "response.completed",
            "response": _build_responses_payload(
                result=result,
                response_id=response_id,
                created=created,
            )
            if result
            else {
                "id": response_id,
                "object": "response",
                "status": "completed",
                "model": MODEL_ID,
                "output": [],
            },
        }
        # silence unused
        _ = item_id
        yield (
            f"event: response.completed\n"
            f"data: {json.dumps(completed, ensure_ascii=False)}\n\n"
        )

    return StreamingResponse(event_gen(), media_type="text/event-stream")


async def _handle_chat_completions(
    req: OpenAIChatCompletionsRequest,
    settings: Settings,
    llm_client: LLMClient,
):
    backend_model = resolve_backend_model_optional(settings, req.model)
    messages = openai_messages_to_chat_messages(req.messages)
    if not messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")
    body = build_resolve_body(req.metadata)

    if req.stream:
        return await _openai_chat_completions_stream(
            settings=settings,
            llm_client=llm_client,
            backend_model=backend_model,
            messages=messages,
            persona=req.persona,
            body=body,
            temperature=req.temperature,
            enable_reflection=req.enable_reflection,
            enable_textbook_context=req.enable_textbook_context,
            enable_web_search=req.enable_web_search,
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
        enable_web_search=req.enable_web_search,
        on_status=None,
    )
    return _build_chat_completion_payload(
        result=result,
        completion_id=_openai_completion_id(),
        created=int(time.time()),
    )


@router.post("/v1/chat/completions")
async def openai_chat_completions(
    req: OpenAIChatCompletionsRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    return await _handle_chat_completions(req, settings, llm_client)


@router.post("/v1/chat/completion")
async def openai_chat_completion_alias(
    req: OpenAIChatCompletionsRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """Alias for clients that use the singular path."""
    return await _handle_chat_completions(req, settings, llm_client)


@router.post("/v1/responses")
async def openai_responses(
    req: OpenAIResponsesRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    backend_model = resolve_backend_model_optional(settings, req.model)
    messages = responses_input_to_messages(req)
    if not messages:
        raise HTTPException(
            status_code=400, detail="input or messages must not be empty"
        )
    body = build_resolve_body(req.metadata)

    if req.stream:
        return await _openai_responses_stream(
            settings=settings,
            llm_client=llm_client,
            backend_model=backend_model,
            messages=messages,
            persona=req.persona,
            body=body,
            temperature=req.temperature,
            enable_reflection=req.enable_reflection,
            enable_textbook_context=req.enable_textbook_context,
            enable_web_search=req.enable_web_search,
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
        enable_web_search=req.enable_web_search,
        on_status=None,
    )
    return _build_responses_payload(
        result=result,
        response_id=_openai_response_id(),
        created=int(time.time()),
    )
