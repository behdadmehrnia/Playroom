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
