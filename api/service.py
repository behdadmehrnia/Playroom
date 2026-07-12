"""Core chat orchestration, separated from the OpenWebUI ``Pipe``.

This module reproduces the logic of ``Pipe._run_chat`` / ``Pipe._stream_chat``
/ ``Pipe._finish_chat`` but parameterized by a ``Settings`` object (env vars)
instead of ``self.valves``, and driven by any ``pipe.LLMClient`` instead of
the OpenWebUI-internal ``OpenWebUILLMClient``.

All reusable primitives — persona resolution, intent detection, textbook-query
building, textbook-service retrieval, prompt building, generation and
reflection — are imported from ``pipe`` so there is a single source of truth.
Only the response loop is reimplemented here (mirroring
``pipe.run_response_loop``) so we can surface ``attempts`` and the final
``ReflectionResult`` to API callers.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pipe import (
    MAX_GENERATION_ATTEMPTS,
    SAFE_FALLBACK_RESPONSE,
    STATUS_DISPLAY_PAUSE_SEC,
    STREAM_CHUNK_SIZE,
    ChatMessage,
    IntentDetectionResult,
    LLMClient,
    PersonaId,
    ReflectionResult,
    TextbookContext,
    TEXTBOOK_PERSONAS,
    _format_textbook_debug,
    _get_latest_user_message,
    build_textbook_query,
    detect_intent,
    fetch_textbook_context,
    generate_response,
    iter_text_chunks,
    looks_like_textbook_help_request,
    looks_like_textbook_page_query,
    reflect_on_response,
    resolve_active_persona,
    resolve_manual_persona,
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
    attempts: int = 0
    reflection: ReflectionResult | None = None
    revised: bool = False
    used_safe_fallback: bool = False
    status_events: list[str] = field(default_factory=list)


async def _resolve_persona(
    *,
    llm_client: LLMClient,
    backend_model: str,
    messages: list[ChatMessage],
    manual_persona_value: str | None,
    body: dict[str, Any] | None,
    emit: Callable[[str], Awaitable[None]],
) -> tuple[PersonaId, str]:
    """Resolve the active persona and emit the appropriate status messages.

    Mirrors the persona-resolution block of ``Pipe._run_chat``.
    """
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

    if manual_persona:
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
) -> TextbookContext | None:
    """Fetch textbook context using the same gate and heuristics as the Pipe."""
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
        and settings.textbook_api_url.strip()
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
                    api_url=settings.textbook_api_url,
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
        return textbook_context

    if (
        ctx_enabled
        and persona in TEXTBOOK_PERSONAS
        and looks_like_textbook_help_request(user_message)
    ):
        # Child is asking about their schoolbook but lacks enough detail to
        # run a lookup — ask for the missing info instead of guessing.
        return TextbookContext(need_info=True)

    return None


async def _run_response_loop(
    *,
    llm_client: LLMClient,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    temperature: float | None,
    textbook_context: TextbookContext | None,
    enable_reflection: bool,
    emit: Callable[[str], Awaitable[None]],
) -> tuple[str, int, ReflectionResult | None, bool, bool]:
    """Generate (and optionally reflect on) the response.

    Mirrors ``pipe.run_response_loop`` but returns metadata: the final text,
    number of attempts, the last reflection result, whether the response was
    revised before passing, and whether the safe fallback was used.
    """
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
        )

        await emit(status_reviewing_response())
        reflection = await reflect_on_response(
            llm_client,
            backend_model=backend_model,
            user_message=user_message,
            candidate_response=candidate,
            textbook_context=textbook_context,
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
    on_status: StatusEmitter = None,
) -> ChatResult:
    """Run the full chat orchestration (mirrors ``Pipe._run_chat``).

    ``on_status`` — when provided — receives live status descriptions (the same
    Persian status strings the Pipe emits to OpenWebUI's status bar). All
    emitted statuses are also collected into ``ChatResult.status_events`` so
    non-streaming callers can see the progression.
    """
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

    textbook_context = await _resolve_textbook_context(
        settings=settings,
        messages=messages,
        persona=resolved_persona,
        enable_textbook_context=enable_textbook_context,
        emit=emit,
    )

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
        enable_reflection=refl_enabled,
        emit=emit,
    )

    return ChatResult(
        response=response,
        persona=resolved_persona,
        persona_source=persona_source,
        textbook_context=textbook_context,
        attempts=attempts,
        reflection=reflection,
        revised=revised,
        used_safe_fallback=used_fallback,
        status_events=status_events,
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
    enable_status: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Stream a chat run as a sequence of event dicts.

    Event types:
      - ``{"type": "status", "description": str}`` — live status updates
      - ``{"type": "status_clear"}`` — status bar should be hidden
      - ``{"type": "chunk", "text": str}`` — a piece of the final response
      - ``{"type": "done", "result": ChatResult}`` — final metadata

    Mirrors ``Pipe._stream_chat``: status events are emitted live while the
    generation loop runs; only after it completes is the final response
    chunked and streamed (the backing LLM is always called non-streaming).
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
                on_status=on_status,
            )
        finally:
            await status_queue.put(None)  # sentinel: statuses are done

    task = asyncio.create_task(_run())

    # Drain live status events until the run finishes (sentinel received).
    while True:
        description = await status_queue.get()
        if description is None:
            break
        if enable_status:
            yield {"type": "status", "description": description}

    chat_result = await task

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
) -> tuple[IntentDetectionResult, str]:
    """Run intent detection and return the result plus the latest user message."""
    user_text = _get_latest_user_message(messages)
    intent = await detect_intent(
        llm_client, backend_model=backend_model, messages=messages
    )
    return intent, user_text
