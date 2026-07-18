"""Core chat orchestration for the standalone Yar Kids API.

Parameterized by ``Settings`` (env vars) and driven by any ``api.core.LLMClient``.
Reusable primitives (persona resolution, intent, textbook, prompts, generation,
reflection) live in ``api.core``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from api.core import (
    MAX_GENERATION_ATTEMPTS,
    SAFE_FALLBACK_RESPONSE,
    STATUS_DISPLAY_PAUSE_SEC,
    STREAM_CHUNK_SIZE,
    ChatMessage,
    IntentDetectionResult,
    LLMClient,
    MathToolUsage,
    PersonaId,
    ReflectionResult,
    TextbookContext,
    TextbookQueryDiag,
    TEXTBOOK_PERSONAS,
    WebSearchContext,
    WebSearchQueryDiag,
    _format_textbook_debug,
    _get_latest_user_message,
    build_textbook_diag,
    build_textbook_query,
    build_web_search_diag,
    build_web_search_query,
    detect_intent,
    fetch_textbook_context,
    generate_response,
    iter_text_chunks,
    looks_like_textbook_help_request,
    looks_like_textbook_page_query,
    reflect_on_response,
    resolve_active_persona,
    resolve_manual_persona,
    resolve_web_search_context,
    run_math_tool_for_message,
    status_calculating_math,
    status_detecting_persona,
    status_fetching_textbook,
    status_generating_response,
    status_persona_selected,
    status_reflection_disabled,
    status_reviewing_response,
    status_textbook_unavailable,
)

from api.config import Settings

StatusEmitter = Callable[[str], Awaitable[None]] | None


@dataclass
class ChatResult:
    """Outcome of a full chat run, including diagnostic metadata."""

    response: str
    persona: PersonaId
    persona_source: str  # "manual" | "intent" | "default"
    textbook_context: TextbookContext | None = None
    web_search_context: WebSearchContext | None = None
    attempts: int = 0
    reflection: ReflectionResult | None = None
    revised: bool = False
    used_safe_fallback: bool = False
    status_events: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    textbook: TextbookQueryDiag | None = None
    web_search: WebSearchQueryDiag | None = None
    math_tool: list[MathToolUsage] = field(default_factory=list)


async def _resolve_persona(
    *,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    manual_persona_value: str | None,
    body: dict[str, Any] | None,
    emit: Callable[[str], Awaitable[None]],
) -> tuple[PersonaId, str]:
    """Resolve the active persona and emit the appropriate status messages."""
    manual_persona = resolve_manual_persona(
        user_persona=manual_persona_value, body=body
    )

    async def emit_detecting() -> None:
        await emit(status_detecting_persona())

    resolved = await resolve_active_persona(
        llm_client,
        backend_model=backend_model,
        messages=messages,
        user_persona=manual_persona_value,
        body=body,
        on_detecting_status=emit_detecting if not manual_persona else None,
    )

    # Persist for multi-turn continuity (clients should echo metadata back).
    if body is not None and resolved and resolved != "none":
        from api.core import ACTIVE_PERSONA_METADATA_KEY

        metadata = body.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            body["metadata"] = metadata
        metadata[ACTIVE_PERSONA_METADATA_KEY] = resolved

    if manual_persona and resolved == manual_persona:
        await emit(status_persona_selected(manual_persona))
        source = "manual"
    elif resolved != "none":
        await emit(status_persona_selected(resolved))
        source = "intent"
    else:
        source = "default"

    return resolved, source


async def _resolve_textbook_context(
    *,
    settings: Settings,
    messages: list[ChatMessage],
    persona: PersonaId,
    enable_textbook_context: bool | None,
    emit: Callable[[str], Awaitable[None]],
) -> tuple[TextbookContext | None, str | None]:
    """Fetch textbook context using the same gate and heuristics as chat."""
    ctx_enabled = (
        enable_textbook_context
        if enable_textbook_context is not None
        else settings.enable_textbook_context
    )
    user_message = _get_latest_user_message(messages)
    textbook_query = build_textbook_query(messages)

    should_fetch = bool(
        ctx_enabled
        and textbook_query
        and persona in TEXTBOOK_PERSONAS
    )

    if should_fetch:
        await emit(status_fetching_textbook())
        textbook_context = await fetch_textbook_context(
            textbook_query,
            api_url=settings.textbook_api_url,
            api_key=settings.textbook_api_key or None,
            include_neighbors=settings.textbook_neighbor_pages,
            include_image=settings.normalized_include_image(),
            timeout_sec=settings.textbook_request_timeout_sec,
        )
        if settings.textbook_debug and textbook_context:
            await emit(
                _format_textbook_debug(
                    query=textbook_query,
                    api_url=settings.textbook_api_url or "embedded",
                    context=textbook_context,
                )
            )
            await asyncio.sleep(1.2)
        if textbook_context and not textbook_context.matched:
            if looks_like_textbook_page_query(textbook_query):
                textbook_context.page_query_failed = True
            else:
                textbook_context.need_info = True
            if not settings.textbook_debug:
                await emit(status_textbook_unavailable())
        return textbook_context, textbook_query

    if (
        ctx_enabled
        and persona in TEXTBOOK_PERSONAS
        and looks_like_textbook_help_request(user_message)
    ):
        return TextbookContext(need_info=True), textbook_query or None

    return None, textbook_query or None


async def _resolve_web_search_context(
    *,
    settings: Settings,
    messages: list[ChatMessage],
    persona: PersonaId,
    enable_web_search: bool | None,
    emit: Callable[[str], Awaitable[None]],
) -> tuple[WebSearchContext | None, str | None]:
    """Delegate to ``api.core.resolve_web_search_context``."""
    search_enabled = (
        enable_web_search if enable_web_search is not None else settings.enable_web_search
    )
    query = build_web_search_query(messages)
    context = await resolve_web_search_context(
        messages=messages,
        persona=persona,
        enable_web_search=search_enabled,
        provider=settings.normalized_web_search_provider(),
        api_url=settings.web_search_api_url,
        api_key=settings.web_search_api_key or None,
        perplexity_url=settings.web_search_perplexity_url,
        max_results=settings.web_search_max_results,
        timeout_sec=settings.web_search_request_timeout_sec,
        debug=settings.web_search_debug,
        on_status=emit,
    )
    if context is None and not query:
        return None, None
    return context, query or (context.query if context else None)


async def _run_response_loop(
    *,
    llm_client: LLMClient,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    temperature: float | None,
    textbook_context: TextbookContext | None,
    web_search_context: WebSearchContext | None,
    math_tool_usages: list[MathToolUsage] | None,
    enable_reflection: bool,
    emit: Callable[[str], Awaitable[None]],
) -> tuple[str, int, ReflectionResult | None, bool, bool]:
    """Generate (and optionally reflect on) the response."""
    user_message = _get_latest_user_message(conversation_messages)

    if not enable_reflection:
        await emit(status_reflection_disabled())
        await emit(status_generating_response(1, 1))
        response = await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=None,
            temperature=temperature,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        )
        return response, 1, None, False, False

    revision_reasons: list[str] = []
    attempts = 0
    final_reflection: ReflectionResult | None = None
    response = SAFE_FALLBACK_RESPONSE
    used_fallback = True

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        attempts = attempt
        await emit(status_generating_response(attempt, MAX_GENERATION_ATTEMPTS))

        candidate = await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons or None,
            temperature=temperature,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        )

        await emit(status_reviewing_response())
        reflection = await reflect_on_response(
            llm_client,
            backend_model=backend_model,
            user_message=user_message,
            candidate_response=candidate,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
        )
        final_reflection = reflection

        if reflection.status == "PASS":
            response = candidate
            used_fallback = False
            revised = attempt > 1
            return response, attempts, final_reflection, revised, used_fallback

        revision_reasons = reflection.reasons or ["پاسخ نیاز به اصلاح دارد."]

    return response, attempts, final_reflection, False, used_fallback


async def run_chat(
    *,
    settings: Settings,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    persona: str | None = None,
    body: dict[str, Any] | None = None,
    temperature: float | None = None,
    enable_reflection: bool | None = None,
    enable_textbook_context: bool | None = None,
    enable_web_search: bool | None = None,
    on_status: StatusEmitter = None,
) -> ChatResult:
    """Run the full chat orchestration."""
    status_events: list[str] = []

    async def emit(description: str) -> None:
        status_events.append(description)
        if on_status:
            await on_status(description)

    resolved_persona, persona_source = await _resolve_persona(
        llm_client=llm_client,
        backend_model=backend_model,
        messages=messages,
        manual_persona_value=persona,
        body=body,
        emit=emit,
    )

    textbook_context, textbook_query = await _resolve_textbook_context(
        settings=settings,
        messages=messages,
        persona=resolved_persona,
        enable_textbook_context=enable_textbook_context,
        emit=emit,
    )

    web_search_context, web_search_query = await _resolve_web_search_context(
        settings=settings,
        messages=messages,
        persona=resolved_persona,
        enable_web_search=enable_web_search,
        emit=emit,
    )

    user_message = _get_latest_user_message(messages)
    math_tool_usages = run_math_tool_for_message(
        user_message, persona=resolved_persona
    )
    if math_tool_usages:
        await emit(status_calculating_math())

    refl_enabled = (
        enable_reflection if enable_reflection is not None else settings.enable_reflection
    )
    temp = temperature if temperature is not None else settings.temperature

    response, attempts, reflection, revised, used_fallback = await _run_response_loop(
        llm_client=llm_client,
        backend_model=backend_model,
        persona=resolved_persona,
        conversation_messages=messages,
        temperature=temp,
        textbook_context=textbook_context,
        web_search_context=web_search_context,
        math_tool_usages=math_tool_usages,
        enable_reflection=refl_enabled,
        emit=emit,
    )

    textbook_diag = build_textbook_diag(
        query_sent=textbook_query, context=textbook_context
    )
    web_search_diag = build_web_search_diag(
        query_sent=web_search_query, context=web_search_context
    )

    return ChatResult(
        response=response,
        persona=resolved_persona,
        persona_source=persona_source,
        textbook_context=textbook_context,
        web_search_context=web_search_context,
        attempts=attempts,
        reflection=reflection,
        revised=revised,
        used_safe_fallback=used_fallback,
        status_events=status_events,
        logs=list(status_events),
        textbook=textbook_diag,
        web_search=web_search_diag,
        math_tool=math_tool_usages,
    )


async def run_chat_stream(
    *,
    settings: Settings,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    persona: str | None = None,
    body: dict[str, Any] | None = None,
    temperature: float | None = None,
    enable_reflection: bool | None = None,
    enable_textbook_context: bool | None = None,
    enable_web_search: bool | None = None,
    enable_status: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat run as a sequence of event dicts.

    Event types:
      - ``{"type": "status", "description": str}``
      - ``{"type": "status_clear"}``
      - ``{"type": "chunk", "text": str}``
      - ``{"type": "error", "message": str}``
      - ``{"type": "done", "result": ChatResult}``
    """
    status_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def on_status(description: str) -> None:
        await status_queue.put(description)

    async def _run() -> ChatResult:
        try:
            return await run_chat(
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
                on_status=on_status,
            )
        finally:
            await status_queue.put(None)

    task = asyncio.create_task(_run())

    while True:
        description = await status_queue.get()
        if description is None:
            break
        if enable_status:
            yield {"type": "status", "description": description}

    try:
        chat_result = await task
    except Exception as exc:  # noqa: BLE001 — surface as SSE error, don't crash
        if enable_status:
            await asyncio.sleep(STATUS_DISPLAY_PAUSE_SEC)
            yield {"type": "status_clear"}
        yield {"type": "error", "message": f"{type(exc).__name__}: {exc}"}
        return

    if enable_status:
        await asyncio.sleep(STATUS_DISPLAY_PAUSE_SEC)
        yield {"type": "status_clear"}

    for chunk in iter_text_chunks(chat_result.response, STREAM_CHUNK_SIZE):
        yield {"type": "chunk", "text": chunk}
        await asyncio.sleep(0)

    yield {"type": "done", "result": chat_result}


async def detect_intent_for(
    *,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    current_persona: PersonaId | None = None,
) -> tuple[IntentDetectionResult, str]:
    """Run intent detection and return the result plus the latest user message."""
    user_text = _get_latest_user_message(messages)
    intent = await detect_intent(
        llm_client, backend_model=backend_model, messages=messages, current_persona=current_persona
    )
    return intent, user_text
