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
    ACTIVE_TEXTBOOK_SCOPE_METADATA_KEY,
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
    detect_intent,
    fetch_textbook_context,
    generate_response,
    iter_text_chunks,
    looks_like_textbook_help_request,
    looks_like_textbook_page_query,
    reflect_on_response,
    resolve_active_persona,
    resolve_manual_persona,
    resolve_textbook_scope,
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
    chat_title: str | None = None


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

    resolution = await resolve_active_persona(
        llm_client,
        backend_model=backend_model,
        messages=messages,
        user_persona=manual_persona_value,
        body=body,
        on_detecting_status=emit_detecting if not manual_persona else None,
    )

    resolved = resolution.persona

    # Persist for multi-turn continuity (clients should echo metadata back).
    if body is not None:
        from api.core import (
            ACTIVE_PERSONA_METADATA_KEY,
            PENDING_PERSONA_METADATA_KEY,
        )

        metadata = body.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            body["metadata"] = metadata
        if resolved and resolved != "none":
            metadata[ACTIVE_PERSONA_METADATA_KEY] = resolved
        if resolution.ask_confirmation and resolution.pending_switch_to:
            metadata[PENDING_PERSONA_METADATA_KEY] = resolution.pending_switch_to
        else:
            metadata.pop(PENDING_PERSONA_METADATA_KEY, None)

    if resolution.ask_confirmation and resolution.pending_switch_to:
        from api.core import (
            append_persona_marker,
            format_persona_switch_confirmation,
        )

        await emit(status_persona_selected(resolved))
        # Encode confirmation ask into a special status; chat layer should short-circuit.
        body_flag = body if isinstance(body, dict) else None
        if body_flag is not None:
            body_flag["_yarkids_confirmation_message"] = append_persona_marker(
                format_persona_switch_confirmation(
                    resolved, resolution.pending_switch_to
                ),
                resolved,
            )
        return resolved, "confirm"

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
    body: dict[str, Any] | None = None,
    emit: Callable[[str], Awaitable[None]],
    llm_client: LLMClient | None = None,
    backend_model: str | None = None,
) -> tuple[TextbookContext | None, str | None]:
    """Fetch textbook context using the same gate and heuristics as chat."""
    ctx_enabled = (
        enable_textbook_context
        if enable_textbook_context is not None
        else settings.enable_textbook_context
    )
    user_message = _get_latest_user_message(messages)
    sticky_scope: dict[str, Any] | None = None
    if isinstance(body, dict):
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            raw_scope = metadata.get(ACTIVE_TEXTBOOK_SCOPE_METADATA_KEY)
            if isinstance(raw_scope, dict):
                sticky_scope = raw_scope

    scope = resolve_textbook_scope(messages, sticky=sticky_scope)
    # Prefer structured scope for retrieve; keep a debug label (not a re-parsed NL query).
    textbook_query = scope.debug_label() if scope.can_retrieve() else build_textbook_query(
        messages, sticky=sticky_scope
    )
    # Topic-only path still needs free text. When the child named a lesson
    # title, prefer that over chapter-start lookup (فصل ۳ ≠ درس «ارزش علم»).
    # Never let a topic query override an explicit page number.
    retrieve_query = scope.topic_query or ""
    prefer_named_topic = bool(retrieve_query.strip()) and scope.page is None

    should_fetch = bool(
        ctx_enabled
        and scope.can_retrieve()
        and persona in TEXTBOOK_PERSONAS
    )

    if should_fetch:
        await emit(status_fetching_textbook())
        textbook_context = await fetch_textbook_context(
            retrieve_query,
            api_url=settings.textbook_api_url,
            api_key=settings.textbook_api_key or None,
            include_neighbors=settings.textbook_neighbor_pages,
            include_image=settings.normalized_include_image(),
            timeout_sec=settings.textbook_request_timeout_sec,
            grade=scope.grade,
            subject=scope.subject_id,
            page=scope.page,
            # Prefer exact page; only fall back to lesson/chapter when page unknown.
            # Named titles skip chapter so TOC/FTS can find the real lesson.
            lesson=scope.lesson if scope.page is None else None,
            chapter=(
                None
                if prefer_named_topic
                else (scope.chapter if scope.page is None else None)
            ),
            llm_client=llm_client,
            backend_model=backend_model,
        )
        if settings.textbook_debug and textbook_context:
            await emit(
                _format_textbook_debug(
                    query=textbook_query or retrieve_query or scope.debug_label(),
                    api_url=settings.textbook_api_url or "embedded",
                    context=textbook_context,
                )
            )
            await asyncio.sleep(1.2)
        if textbook_context and not textbook_context.matched:
            reason = textbook_context.failure_reason
            if (
                textbook_context.page_out_of_range
                or reason == "page_out_of_range"
            ):
                textbook_context.page_out_of_range = True
                textbook_context.page_query_failed = True
            elif reason == "need_grade_or_subject":
                textbook_context.need_info = True
            elif reason in {
                "lesson_missing",
                "lesson_out_of_range",
            }:
                textbook_context.page_query_failed = True
            elif reason == "book_unavailable":
                # Do not mark as generic page_query_failed — that steers the
                # model toward «عکس صفحه بفرست» instead of «این پایه این کتاب را ندارد».
                pass
            elif looks_like_textbook_page_query(textbook_query) or scope.lesson or scope.page:
                textbook_context.page_query_failed = True
            else:
                textbook_context.need_info = True
            if not settings.textbook_debug:
                await emit(status_textbook_unavailable())
        if (
            textbook_context
            and textbook_context.matched
            and isinstance(body, dict)
        ):
            metadata = body.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                body["metadata"] = metadata
            metadata[ACTIVE_TEXTBOOK_SCOPE_METADATA_KEY] = {
                "grade": textbook_context.grade,
                "subject": textbook_context.subject,
                "page": textbook_context.page,
                "lesson": textbook_context.lesson or scope.lesson,
                "chapter": textbook_context.chapter or scope.chapter,
            }
        return textbook_context, textbook_query or None

    if (
        ctx_enabled
        and persona in TEXTBOOK_PERSONAS
        and looks_like_textbook_help_request(user_message)
    ):
        from api.core.persona import _is_activity_continuation

        if not _is_activity_continuation(user_message, persona):
            # Partial scope → ask only for missing slots.
            partial = TextbookContext(
                need_info=True,
                failure_reason="need_grade_or_subject",
                grade=scope.grade,
                subject=scope.subject_id,
                subject_title=(
                    {
                        "math": "ریاضی",
                        "science": "علوم تجربی",
                        "persian": "فارسی",
                        "writing": "نگارش",
                        "social": "مطالعات اجتماعی",
                        "quran": "قرآن",
                        "gifts": "هدیه های آسمان",
                        "thinking": "تفکر و پژوهش",
                        "technology": "کار و فناوری",
                    }.get(scope.subject_id or "")
                    if scope.subject_id
                    else None
                ),
                page=scope.page,
                lesson=scope.lesson,
                chapter=scope.chapter,
            )
            return partial, textbook_query or None

    return None, textbook_query or None


async def _resolve_web_search_context(
    *,
    settings: Settings,
    messages: list[ChatMessage],
    persona: PersonaId,
    enable_web_search: bool | None,
    emit: Callable[[str], Awaitable[None]],
    llm_client: LLMClient | None = None,
    backend_model: str | None = None,
) -> tuple[WebSearchContext | None, str | None]:
    """Delegate to ``api.core.resolve_web_search_context``."""
    search_enabled = (
        enable_web_search if enable_web_search is not None else settings.enable_web_search
    )
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
        llm_client=llm_client,
        backend_model=backend_model or settings.backend_model,
    )
    if context is None:
        return None, None
    return context, context.query or None


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

    # Sticky switch confirmation: return the ask message without running tools/LLM.
    if isinstance(body, dict) and body.get("_yarkids_confirmation_message"):
        confirm_msg = str(body.pop("_yarkids_confirmation_message"))
        return ChatResult(
            response=confirm_msg,
            persona=resolved_persona,
            persona_source=persona_source,
            attempts=0,
            status_events=status_events,
            logs=list(status_events),
        )

    textbook_context, textbook_query = await _resolve_textbook_context(
        settings=settings,
        messages=messages,
        persona=resolved_persona,
        enable_textbook_context=enable_textbook_context,
        body=body,
        emit=emit,
        llm_client=llm_client,
        backend_model=backend_model,
    )

    from api.core.generation import compose_textbook_failure_reply

    canned_textbook = (
        compose_textbook_failure_reply(textbook_context) if textbook_context else None
    )
    if canned_textbook:
        response = canned_textbook
        if resolved_persona and resolved_persona != "none":
            from api.core import append_persona_marker

            response = append_persona_marker(response, resolved_persona)
        textbook_diag = build_textbook_diag(
            query_sent=textbook_query, context=textbook_context
        )
        return ChatResult(
            response=response,
            persona=resolved_persona,
            persona_source=persona_source,
            attempts=0,
            status_events=status_events,
            logs=list(status_events),
            textbook_context=textbook_context,
            textbook=textbook_diag,
            reflection=None,
            revised=False,
            used_safe_fallback=False,
        )

    web_search_context, web_search_query = await _resolve_web_search_context(
        settings=settings,
        messages=messages,
        persona=resolved_persona,
        enable_web_search=enable_web_search,
        emit=emit,
        llm_client=llm_client,
        backend_model=backend_model,
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

    if resolved_persona and resolved_persona != "none":
        from api.core import append_persona_marker

        response = append_persona_marker(response, resolved_persona)
    else:
        from api.core import strip_persona_markers

        response = strip_persona_markers(response)

    textbook_diag = build_textbook_diag(
        query_sent=textbook_query, context=textbook_context
    )
    web_search_diag = build_web_search_diag(
        query_sent=web_search_query, context=web_search_context
    )

    chat_title: str | None = None
    if settings.enable_chat_title:
        from api.core import (
            CHAT_TITLE_METADATA_KEY,
            generate_chat_title,
            should_emit_chat_title,
        )

        current_title = None
        if isinstance(body, dict):
            metadata = body.get("metadata")
            if isinstance(metadata, dict):
                for key in (
                    CHAT_TITLE_METADATA_KEY,
                    "chat_title",
                    "title",
                ):
                    raw_title = metadata.get(key)
                    if isinstance(raw_title, str) and raw_title.strip():
                        current_title = raw_title.strip()
                        break
        if should_emit_chat_title(
            messages,
            current_title=current_title,
            min_user_messages=settings.chat_title_min_user_messages,
        ):
            chat_title = await generate_chat_title(
                llm_client,
                backend_model=backend_model,
                messages=messages,
                min_user_messages=settings.chat_title_min_user_messages,
            )
            if isinstance(body, dict) and chat_title:
                metadata = body.get("metadata")
                if not isinstance(metadata, dict):
                    metadata = {}
                    body["metadata"] = metadata
                metadata[CHAT_TITLE_METADATA_KEY] = chat_title

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
        chat_title=chat_title,
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
      - ``{"type": "title", "title": str}``
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

    if chat_result.chat_title:
        yield {"type": "title", "title": chat_result.chat_title}

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
