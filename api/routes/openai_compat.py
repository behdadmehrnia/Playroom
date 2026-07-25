"""OpenAI-compatible /v1/chat/completions and /v1/responses endpoints."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from api.config import Settings
from api.core import MODEL_ID, ChatMessage, LLMClient
from api.models import OpenAIChatCompletionsRequest, OpenAIResponsesRequest
from api.service import run_chat, run_chat_stream

from .deps import get_llm_client, get_settings
from .helpers import (
    build_resolve_body,
    chat_result_to_yarkids_meta,
    openai_messages_to_chat_messages,
    resolve_backend_model_optional,
    responses_input_to_messages,
)

router = APIRouter()

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

    # OpenWebUI title-generation calls — answer with Persian child-friendly titles
    # instead of running the full chat pipeline (and avoid English "Introduction…").
    from api.core import (
        generate_chat_title,
        looks_like_title_generation_request,
    )

    if settings.enable_chat_title and looks_like_title_generation_request(
        messages, metadata=req.metadata
    ):
        title = await generate_chat_title(
            llm_client,
            backend_model=backend_model,
            messages=messages,
            min_user_messages=settings.chat_title_min_user_messages,
        )
        completion_id = _openai_completion_id()
        created = int(time.time())
        if req.stream:

            async def title_stream():
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL_ID,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": title},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                final = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": MODEL_ID,
                    "choices": [
                        {"index": 0, "delta": {}, "finish_reason": "stop"}
                    ],
                }
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(title_stream(), media_type="text/event-stream")

        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": MODEL_ID,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": title},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
            "yarkids": {"chat_title": title, "title_generation": True},
        }

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


@router.post("/v1/chat/completions", tags=["OpenAI Compatible"])
async def openai_chat_completions(
    req: OpenAIChatCompletionsRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    return await _handle_chat_completions(req, settings, llm_client)


@router.post("/v1/chat/completion", tags=["OpenAI Compatible"])
async def openai_chat_completion_alias(
    req: OpenAIChatCompletionsRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
):
    """Alias for clients that use the singular path."""
    return await _handle_chat_completions(req, settings, llm_client)


@router.post("/v1/responses", tags=["OpenAI Compatible"])
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
