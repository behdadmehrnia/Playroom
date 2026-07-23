"""Shared route helpers (message conversion, result mapping, model resolution)."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from api.core import ChatMessage, normalize_messages
from api.config import Settings
from api.models import (
    ChatResultOut,
    MessageIn,
    OpenAIResponsesRequest,
    YarKidsMeta,
)

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
        chat_title=getattr(result, "chat_title", None),
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
        chat_title=out.chat_title,
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
