"""Full chat orchestration endpoint (/v1/chat)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from api.config import Settings
from api.core import ChatMessage, LLMClient
from api.models import ChatRequest, ChatResultOut
from api.service import run_chat, run_chat_stream

from .deps import get_llm_client, get_settings
from .helpers import build_resolve_body, chat_result_to_out, resolve_backend_model, to_chat_messages

router = APIRouter()


def _title_only_result(title: str) -> ChatResultOut:
    return ChatResultOut(
        response=title,
        persona="none",
        persona_source="default",
        textbook_context=None,
        web_search_context=None,
        attempts=0,
        reflection=None,
        revised=False,
        status_events=[],
        logs=[],
        textbook=None,
        web_search=None,
        math_tool=[],
        used_safe_fallback=False,
        chat_title=title,
    )


async def _title_event_stream(title: str) -> Any:
    yield {
        "event": "chunk",
        "data": json.dumps({"text": title}, ensure_ascii=False),
    }
    yield {
        "event": "title",
        "data": json.dumps({"title": title}, ensure_ascii=False),
    }
    yield {"event": "done", "data": _title_only_result(title).model_dump_json()}


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
        elif etype == "title":
            yield {
                "event": "title",
                "data": json.dumps({"title": event["title"]}, ensure_ascii=False),
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


@router.post("/v1/chat", response_model=ChatResultOut, tags=["Chat"])
async def chat_endpoint(
    req: ChatRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    backend_model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    body = build_resolve_body(req.metadata)

    # Some clients request a chat title through /v1/chat (not completions).
    if settings.enable_chat_title:
        from api.core import (
            generate_chat_title,
            looks_like_title_generation_request,
        )

        if looks_like_title_generation_request(
            messages, metadata=req.metadata
        ):
            title = await generate_chat_title(
                llm_client,
                backend_model=backend_model,
                messages=messages,
                min_user_messages=settings.chat_title_min_user_messages,
            )
            if req.stream:
                return EventSourceResponse(_title_event_stream(title))
            return _title_only_result(title)

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
