"""Web search query and retrieval endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.config import Settings
from api.core import (
    WEB_SEARCH_PERSONAS,
    _format_web_search_debug,
    _get_latest_user_message,
    build_web_search_query,
    fetch_web_search_context,
    looks_like_web_search_request,
)
from api.models import (
    WebSearchQueryRequest,
    WebSearchQueryResponse,
    WebSearchRetrieveRequest,
    WebSearchRetrieveResponse,
)

from .deps import get_settings
from .helpers import to_chat_messages

router = APIRouter()

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
