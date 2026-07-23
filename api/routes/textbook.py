"""Textbook query and retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.config import Settings
from api.core import (
    TEXTBOOK_PERSONAS,
    TextbookContext,
    _format_textbook_debug,
    _get_latest_user_message,
    build_textbook_query,
    fetch_textbook_context,
    looks_like_textbook_help_request,
    looks_like_textbook_page_query,
    resolve_textbook_scope,
)
from api.models import (
    TextbookQueryRequest,
    TextbookQueryResponse,
    TextbookRetrieveRequest,
    TextbookRetrieveResponse,
)

from .deps import get_settings
from .helpers import to_chat_messages

router = APIRouter()

@router.post("/v1/textbook/query", response_model=TextbookQueryResponse, tags=["Textbook"])
async def textbook_query_endpoint(
    req: TextbookQueryRequest,
) -> TextbookQueryResponse:
    messages = to_chat_messages(req.messages)
    scope = resolve_textbook_scope(messages)
    query = (
        scope.debug_label()
        if scope.can_retrieve()
        else build_textbook_query(messages)
    )
    latest = _get_latest_user_message(messages)
    return TextbookQueryResponse(
        query=query,
        looks_like_page_query=looks_like_textbook_page_query(query)
        or scope.page is not None
        or scope.lesson is not None,
        looks_like_help_request=looks_like_textbook_help_request(latest),
        latest_user_message=latest,
    )


@router.post("/v1/textbook/retrieve", response_model=TextbookRetrieveResponse, tags=["Textbook"])
async def retrieve_textbook_endpoint(
    req: TextbookRetrieveRequest,
    settings: Settings = Depends(get_settings),
) -> TextbookRetrieveResponse:
    messages = to_chat_messages(req.messages) if req.messages else []
    scope = resolve_textbook_scope(messages) if messages else None

    if req.query is not None:
        query = req.query.strip()
    elif scope is not None and scope.can_retrieve():
        query = scope.debug_label()
    elif messages:
        query = build_textbook_query(messages)
    else:
        query = ""

    if req.user_message is not None:
        user_message = req.user_message.strip()
    elif messages:
        user_message = _get_latest_user_message(messages)
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

    use_scope = scope is not None and scope.can_retrieve()
    should_fetch = bool(ctx_enabled and eligible and (use_scope or bool(query)))

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
        if use_scope and scope is not None:
            context = await fetch_textbook_context(
                scope.topic_query or "",
                api_url=settings.textbook_api_url,
                api_key=settings.textbook_api_key or None,
                include_neighbors=neighbors,
                include_image=include_image,  # type: ignore[arg-type]
                timeout_sec=timeout,
                grade=scope.grade,
                subject=scope.subject_id,
                page=scope.page,
                lesson=scope.lesson if scope.page is None else None,
            )
        else:
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
            reason = context.failure_reason
            if context.page_out_of_range or reason == "page_out_of_range":
                context.page_out_of_range = True
                context.page_query_failed = True
            elif reason == "need_grade_or_subject":
                context.need_info = True
            elif reason == "lesson_missing":
                context.page_query_failed = True
            elif looks_like_textbook_page_query(query) or (
                scope is not None and (scope.page is not None or scope.lesson is not None)
            ):
                context.page_query_failed = True
            else:
                context.need_info = True
        debug_enabled = req.debug if req.debug is not None else settings.textbook_debug
        if debug_enabled and context:
            debug = _format_textbook_debug(
                query=query or (scope.debug_label() if scope else ""),
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
