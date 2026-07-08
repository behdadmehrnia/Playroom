"""
title: یار کودک
author: Yar Kids
version: 0.5.0
description: دستیار کودک‌دوست با معماری Persona، Intent Detection و Reflection
required_open_webui_version: 0.5.0
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import re
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol, Union

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_ID = "yarkids"
MODEL_NAME = "یار کودک"
MAX_GENERATION_ATTEMPTS = 3
INTENT_CONFIDENCE_THRESHOLD = 0.7
MANUAL_PERSONA_METADATA_KEY = "yarkids_persona"
PERSONA_AUTO_VALUE = "auto"
SUPPORTED_PERSONAS = ("creative", "storyteller", "teacher", "homework")
REVISION_INSTRUCTION_HEADER = "بازبینی لازم است. پاسخ قبلی مناسب نبود. دلایل:"
TEXTBOOK_CONTEXT_HEADER = (
    "متن کتاب درسی بازیابی‌شده (مرجع — برای راهنمایی آموزشی؛ جواب نهایی را بدون آموزش روش نده):"
)
DEFAULT_TEXTBOOK_TIMEOUT_SEC = 5.0

SAFE_FALLBACK_RESPONSE = (
    "متأسفم، الان نتوانستم پاسخ مناسبی برایت بدهم. "
    "بیایید با هم یک موضوع دیگر را امتحان کنیم! "
    "می‌توانی دربارهٔ یک داستان، یک سوال درسی، یا یک ایدهٔ خلاقانه از من بپرسی."
)

# Child-friendly labels for persona dropdown and status messages.
PERSONA_UI_LABELS: dict[str, str] = {
    "auto": "✨ خودکار",
    "creative": "🎨 خلاق",
    "storyteller": "📖 داستان‌گو",
    "teacher": "📚 معلم",
    "homework": "✏️ کمک‌درس",
    "none": "😊 یار کودک",
}

PERSONA_DROPDOWN_OPTIONS: list[dict[str, str]] = [
    {"value": "auto", "label": "✨ خودکار — خودم انتخاب می‌کنم!"},
    {"value": "creative", "label": "🎨 خلاق"},
    {"value": "storyteller", "label": "📖 داستان‌گو"},
    {"value": "teacher", "label": "📚 معلم"},
    {"value": "homework", "label": "✏️ کمک‌درس"},
]

STREAM_CHUNK_SIZE = 16
# Brief pause so the UI can paint status before it is cleared for streaming.
STATUS_DISPLAY_PAUSE_SEC = 0.12

PROMPTS_DIR = Path(__file__).parent / "prompts"

PersonaId = Literal["creative", "storyteller", "teacher", "homework", "none"]
ReflectionStatus = Literal["PASS", "REVISE"]
VALID_PERSONAS: set[PersonaId] = {
    "creative",
    "storyteller",
    "teacher",
    "homework",
    "none",
}
TEXTBOOK_PERSONAS: frozenset[PersonaId] = frozenset({"teacher", "homework"})

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class IntentDetectionResult(BaseModel):
    persona: PersonaId
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ReflectionResult(BaseModel):
    status: ReflectionStatus
    reasons: list[str] | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None


class TextbookContext(BaseModel):
    matched: bool = False
    match_type: str | None = None
    grade: int | None = None
    subject: str | None = None
    subject_title: str | None = None
    page: int | None = None
    context_text: str | None = None
    needs_image: bool = False
    image_base64: str | None = None


class LLMClient(Protocol):
    async def complete(self, request: LLMCompletionRequest) -> str: ...


IntentDetectionResult.model_rebuild()
ReflectionResult.model_rebuild()
ChatMessage.model_rebuild()


# ---------------------------------------------------------------------------
# Prompt loading (from .md files next to pipe.py)
# ---------------------------------------------------------------------------

_prompt_cache: dict[str, str] = {}


def _load_prompt(relative_path: str) -> str:
    """Load and cache a markdown prompt file from the prompts directory."""
    if relative_path in _prompt_cache:
        return _prompt_cache[relative_path]

    path = PROMPTS_DIR / relative_path
    text = path.read_text(encoding="utf-8").strip()
    _prompt_cache[relative_path] = text
    return text


def get_core_prompt() -> str:
    return _load_prompt("core.md")


def get_persona_prompt(persona: PersonaId) -> str | None:
    if persona == "none":
        return None
    if persona not in SUPPORTED_PERSONAS:
        return None
    return _load_prompt(f"personas/{persona}.md")


def get_intent_detection_prompt() -> str:
    return _load_prompt("intent_detection.md")


def get_reflection_prompt() -> str:
    template = _load_prompt("reflection.md")
    return template.replace("{{CORE_PROMPT}}", get_core_prompt())


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


async def _await_if_needed(value: Any) -> Any:
    """Await coroutines; return plain values unchanged (OpenWebUI version compat)."""
    if inspect.isawaitable(value):
        return await value
    return value


def get_persona_ui_label(persona: PersonaId | str) -> str:
    """Return a child-friendly persona label for UI status messages."""
    return PERSONA_UI_LABELS.get(str(persona), PERSONA_UI_LABELS["none"])


def status_detecting_persona() -> str:
    return "😊 دارم شخصیت مناسب رو پیدا می‌کنم..."


def status_persona_selected(persona: PersonaId) -> str:
    label = get_persona_ui_label(persona)
    return f"🎭 شخصیت {label} انتخاب شد! بزن بریم..."


def status_generating_response(attempt: int, max_attempts: int) -> str:
    return f"✨ دارم جواب قشنگت رو می‌نویسم... ({attempt} از {max_attempts})"


def status_reviewing_response() -> str:
    return "🔍 یه لحظه! دارم چک می‌کنم همه‌چیز عالی باشه..."


def status_fetching_textbook() -> str:
    return "📖 دارم صفحهٔ کتاب درسی رو پیدا می‌کنم..."


async def clear_status_message(
    __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
) -> None:
    """Hide the status bar after the response is complete (OpenWebUI events API)."""
    if not __event_emitter__:
        return
    await __event_emitter__(
        {
            "type": "status",
            "data": {"description": "", "done": True, "hidden": True},
        }
    )


def extract_text_from_completion(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return str(response).strip()

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return str(response).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def normalize_messages(raw_messages: list[dict[str, Any]]) -> list[ChatMessage]:
    normalized: list[ChatMessage] = []
    for item in raw_messages:
        role = item.get("role")
        content = item.get("content")
        if role not in {"system", "user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        normalized.append(ChatMessage(role=role, content=content))
    return normalized


def _get_latest_user_message(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return ""


def _normalize_persona(value: str | None) -> PersonaId | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"", "none", "auto", "automatic"}:
        return None
    if normalized in SUPPORTED_PERSONAS:
        return normalized  # type: ignore[return-value]
    return None


def iter_text_chunks(text: str, chunk_size: int = STREAM_CHUNK_SIZE) -> Iterator[str]:
    """Split text into chunks for simulated streaming in OpenWebUI pipes."""
    if not text:
        yield ""
        return
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


# ---------------------------------------------------------------------------
# Textbook context client (calls external textbook-service API)
# ---------------------------------------------------------------------------


def _normalize_api_base_url(api_url: str) -> str:
    return api_url.strip().rstrip("/")


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout_sec: float,
) -> dict[str, Any] | None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None


def _http_get_bytes(
    url: str,
    *,
    headers: dict[str, str],
    timeout_sec: float,
) -> bytes | None:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        return response.read()


async def fetch_textbook_context(
    query: str,
    *,
    api_url: str,
    api_key: str | None = None,
    include_neighbors: int = 1,
    include_image: str = "auto",
    timeout_sec: float = DEFAULT_TEXTBOOK_TIMEOUT_SEC,
) -> TextbookContext | None:
    """
    Call textbook-service POST /v1/retrieve. Returns None on failure (graceful degrade).
    """
    base = _normalize_api_base_url(api_url)
    if not base:
        return None

    headers: dict[str, str] = {}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = {
        "query": query,
        "include_neighbors": include_neighbors,
        "include_image": include_image,
    }

    def _retrieve() -> dict[str, Any] | None:
        try:
            return _http_post_json(
                f"{base}/v1/retrieve",
                payload,
                headers=headers,
                timeout_sec=timeout_sec,
            )
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
            return None

    data = await asyncio.to_thread(_retrieve)
    if not data or not data.get("matched"):
        return TextbookContext(matched=False)

    context = TextbookContext(
        matched=True,
        match_type=str(data.get("match_type")) if data.get("match_type") else None,
        grade=int(data["grade"]) if data.get("grade") is not None else None,
        subject=str(data["subject"]) if data.get("subject") else None,
        subject_title=str(data["subject_title"]) if data.get("subject_title") else None,
        page=int(data["page"]) if data.get("page") is not None else None,
        context_text=str(data["context_text"]) if data.get("context_text") else None,
        needs_image=bool(data.get("needs_image")),
        image_base64=str(data["image_base64"]) if data.get("image_base64") else None,
    )

    if context.needs_image and not context.image_base64:
        image_url = data.get("image_url")
        if isinstance(image_url, str) and image_url.strip():

            def _fetch_image() -> bytes | None:
                full_url = image_url if image_url.startswith("http") else f"{base}{image_url}"
                try:
                    return _http_get_bytes(full_url, headers=headers, timeout_sec=timeout_sec)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                    return None

            image_bytes = await asyncio.to_thread(_fetch_image)
            if image_bytes:
                context.image_base64 = base64.b64encode(image_bytes).decode("ascii")

    return context


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_system_prompt(
    persona: PersonaId,
    revision_reasons: list[str] | None = None,
    textbook_context: TextbookContext | None = None,
) -> str:
    sections: list[str] = [get_core_prompt()]

    persona_prompt = get_persona_prompt(persona)
    if persona_prompt:
        sections.append(persona_prompt)

    if textbook_context and textbook_context.matched and textbook_context.context_text:
        meta_parts: list[str] = []
        if textbook_context.subject_title:
            meta_parts.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_parts.append(f"پایه {textbook_context.grade}")
        if textbook_context.page:
            meta_parts.append(f"صفحه {textbook_context.page}")
        meta = " — ".join(meta_parts)
        header = TEXTBOOK_CONTEXT_HEADER
        if meta:
            header = f"{header}\n({meta})"
        sections.append(f"{header}\n{textbook_context.context_text}")

    if revision_reasons:
        reasons_text = "\n".join(f"- {reason}" for reason in revision_reasons)
        sections.append(f"{REVISION_INSTRUCTION_HEADER}\n{reasons_text}")

    return "\n\n".join(sections)


def _attach_textbook_image_to_messages(
    messages: list[dict[str, Any]],
    textbook_context: TextbookContext | None,
) -> list[dict[str, Any]]:
    if not textbook_context or not textbook_context.needs_image:
        return messages
    if not textbook_context.image_base64:
        return messages

    data_uri = f"data:image/png;base64,{textbook_context.image_base64}"
    image_note = "تصویر صفحهٔ کتاب درسی پیوست شده — اگر تمرین شکل یا جدول دارد از تصویر هم استفاده کن."

    updated = list(messages)
    for index in range(len(updated) - 1, -1, -1):
        if updated[index].get("role") != "user":
            continue
        original = updated[index].get("content", "")
        text_part = original if isinstance(original, str) else image_note
        updated[index] = {
            "role": "user",
            "content": [
                {"type": "text", "text": f"{text_part}\n\n{image_note}"},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ],
        }
        break
    return updated


def build_prompt_messages(
    *,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
    textbook_context: TextbookContext | None = None,
) -> list[dict[str, Any]]:
    llm_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                persona,
                revision_reasons,
                textbook_context=textbook_context,
            ),
        },
    ]
    for message in conversation_messages:
        if message.role != "system":
            llm_messages.append({"role": message.role, "content": message.content})
    return _attach_textbook_image_to_messages(llm_messages, textbook_context)


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------


def parse_intent_detection_output(raw_output: str) -> IntentDetectionResult:
    payload = _extract_json_object(raw_output)
    if not payload:
        return IntentDetectionResult(persona="none")

    persona_raw = str(payload.get("persona", "none")).strip().lower()
    if persona_raw not in VALID_PERSONAS:
        return IntentDetectionResult(persona="none")

    persona: PersonaId = persona_raw  # type: ignore[assignment]
    if persona == "none":
        return IntentDetectionResult(persona="none")

    confidence_raw = payload.get("confidence")
    if confidence_raw is None:
        return IntentDetectionResult(persona="none")

    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        return IntentDetectionResult(persona="none")

    if confidence < INTENT_CONFIDENCE_THRESHOLD:
        return IntentDetectionResult(persona="none")

    return IntentDetectionResult(persona=persona, confidence=confidence)


async def detect_intent(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
) -> IntentDetectionResult:
    user_text = _get_latest_user_message(messages)
    if not user_text:
        return IntentDetectionResult(persona="none")

    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": get_intent_detection_prompt()},
            {"role": "user", "content": user_text},
        ],
    )
    return parse_intent_detection_output(await llm_client.complete(request))


# ---------------------------------------------------------------------------
# Persona selection
# ---------------------------------------------------------------------------


def resolve_manual_persona(
    *,
    user_persona: str | None = None,
    body: dict[str, Any] | None = None,
) -> PersonaId | None:
    """
    Resolve manually selected persona from chat UserValves or request metadata.

    OpenWebUI exposes UserValves in Chat Controls → Valves sidebar.
    When persona is "auto" or empty, returns None so intent detection runs.
    """
    manual = _normalize_persona(user_persona)
    if manual:
        return manual

    if not body:
        return None

    metadata = body.get("metadata") or {}
    if isinstance(metadata, dict):
        metadata_persona = metadata.get(MANUAL_PERSONA_METADATA_KEY)
        if isinstance(metadata_persona, str):
            manual = _normalize_persona(metadata_persona)
            if manual:
                return manual

    # Custom frontend (e.g. Yar UI): send persona directly on the request body.
    for key in ("yarkids_persona", "persona", "PERSONA"):
        direct = body.get(key)
        if isinstance(direct, str):
            manual = _normalize_persona(direct)
            if manual:
                return manual

    params = body.get("params") or {}
    if isinstance(params, dict):
        params_persona = params.get("PERSONA") or params.get("persona")
        if isinstance(params_persona, str):
            manual = _normalize_persona(params_persona)
            if manual:
                return manual

    return None


def get_user_persona_selection(__user__: dict[str, Any] | None) -> str | None:
    """Read persona from OpenWebUI UserValves (Chat Controls sidebar)."""
    if not __user__:
        return None

    valves = __user__.get("valves")
    if valves is None:
        return None

    persona = dict(valves).get("PERSONA")
    if isinstance(persona, str) and persona.strip():
        return persona.strip()

    return None


async def resolve_active_persona(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    user_persona: str | None = None,
    body: dict[str, Any] | None = None,
    on_detecting_status: Callable[[], Awaitable[None]] | None = None,
) -> PersonaId:
    manual_persona = resolve_manual_persona(user_persona=user_persona, body=body)
    if manual_persona:
        return manual_persona

    if on_detecting_status:
        await on_detecting_status()

    intent = await detect_intent(llm_client, backend_model=backend_model, messages=messages)
    return intent.persona


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


class OpenWebUILLMClient:
    def __init__(self, request: Any, user: Any) -> None:
        self._request = request
        self._user = user

    async def complete(self, request: LLMCompletionRequest) -> str:
        from open_webui.utils.chat import generate_chat_completion

        body: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "stream": request.stream,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature

        response = await _await_if_needed(
            generate_chat_completion(self._request, body, self._user)
        )
        return extract_text_from_completion(response)


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------


async def generate_response(
    llm_client: LLMClient,
    *,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
    temperature: float | None = None,
    textbook_context: TextbookContext | None = None,
) -> str:
    request = LLMCompletionRequest(
        model=backend_model,
        messages=build_prompt_messages(
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons,
            textbook_context=textbook_context,
        ),
        stream=False,
        temperature=temperature,
    )
    return await llm_client.complete(request)


# ---------------------------------------------------------------------------
# Reflection agent
# ---------------------------------------------------------------------------


def parse_reflection_output(raw_output: str) -> ReflectionResult:
    payload = _extract_json_object(raw_output)
    if not payload:
        return ReflectionResult(status="REVISE", reasons=["خروجی بازبین قابل parse نبود."])

    status_raw = str(payload.get("status", "")).strip().upper()
    if status_raw == "PASS":
        return ReflectionResult(status="PASS")

    reasons_raw = payload.get("reasons", [])
    reasons: list[str] = []
    if isinstance(reasons_raw, list):
        reasons = [str(item).strip() for item in reasons_raw if str(item).strip()]

    if not reasons:
        reasons = ["پاسخ برای کودک مناسب تشخیص داده نشد."]

    return ReflectionResult(status="REVISE", reasons=reasons)


async def reflect_on_response(
    llm_client: LLMClient,
    *,
    backend_model: str,
    user_message: str,
    candidate_response: str,
) -> ReflectionResult:
    review_prompt = (
        f"پیام کودک:\n{user_message}\n\n"
        f"پاسخ پیشنهادی:\n{candidate_response}\n\n"
        "فقط JSON خروجی بده."
    )
    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": get_reflection_prompt()},
            {"role": "user", "content": review_prompt},
        ],
    )
    return parse_reflection_output(await llm_client.complete(request))


# ---------------------------------------------------------------------------
# Response loop
# ---------------------------------------------------------------------------


async def run_response_loop(
    llm_client: LLMClient,
    *,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    temperature: float | None = None,
    on_status: Callable[[str], Awaitable[None]] | None = None,
    textbook_context: TextbookContext | None = None,
) -> str:
    revision_reasons: list[str] = []
    user_message = _get_latest_user_message(conversation_messages)

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if on_status:
            await on_status(status_generating_response(attempt, MAX_GENERATION_ATTEMPTS))

        candidate = await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons or None,
            temperature=temperature,
            textbook_context=textbook_context,
        )

        if on_status:
            await on_status(status_reviewing_response())

        reflection = await reflect_on_response(
            llm_client,
            backend_model=backend_model,
            user_message=user_message,
            candidate_response=candidate,
        )

        if reflection.status == "PASS":
            return candidate

        revision_reasons = reflection.reasons or ["پاسخ نیاز به اصلاح دارد."]

    return SAFE_FALLBACK_RESPONSE


# ---------------------------------------------------------------------------
# OpenWebUI Pipe entry point
# ---------------------------------------------------------------------------


class Pipe:
    """OpenWebUI Pipe Function for the Yar Kids child-friendly assistant."""

    class Valves(BaseModel):
        BACKEND_MODEL: str = Field(
            default="",
            description=(
                "مدل پشتیبان OpenWebUI برای تولید پاسخ. "
                "اگر خالی باشد از مدل پیش‌فرض سیستم استفاده می‌شود."
            ),
        )
        TEMPERATURE: float = Field(
            default=0.7,
            ge=0.0,
            le=2.0,
            description="دمای تولید پاسخ اصلی.",
        )
        ENABLE_STATUS_UPDATES: bool = Field(
            default=True,
            description="نمایش وضعیت پردازش در رابط کاربری.",
        )
        ENABLE_TEXTBOOK_CONTEXT: bool = Field(
            default=True,
            description="فعال‌سازی بازیابی کتاب درسی از textbook-service (معلم/کمک‌درسی).",
        )
        TEXTBOOK_API_URL: str = Field(
            default="http://localhost:8080",
            description="آدرس پایهٔ API سرویس textbook-service (بدون / در انتها).",
        )
        TEXTBOOK_API_KEY: str = Field(
            default="",
            description="کلید API اختیاری (Bearer token).",
        )
        TEXTBOOK_REQUEST_TIMEOUT_SEC: float = Field(
            default=DEFAULT_TEXTBOOK_TIMEOUT_SEC,
            ge=1.0,
            le=30.0,
            description="مهلت درخواست به textbook-service (ثانیه).",
        )
        TEXTBOOK_NEIGHBOR_PAGES: int = Field(
            default=1,
            ge=0,
            le=3,
            description="تعداد صفحات همسایه برای بازیابی.",
        )
        TEXTBOOK_INCLUDE_IMAGE: str = Field(
            default="auto",
            description='ارسال تصویر صفحه: never | auto | always',
        )

    class UserValves(BaseModel):
        """
        Persona dropdown — rendered by OpenWebUI in Chat Controls → Valves.

        TODO(frontend/yar-ui): For custom chat UI, render a persona dropdown and send
        the selected value in body.metadata.yarkids_persona on each chat request.
        See README → «اتصال UI سفارشی».
        """

        PERSONA: str = Field(
            default="auto",
            title="شخصیت یار کودک",
            description="از این منو شخصیت دوستت رو انتخاب کن! 😊",
            json_schema_extra={
                "input": {
                    "type": "select",
                    "options": PERSONA_DROPDOWN_OPTIONS,
                }
            },
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [
            {
                "id": MODEL_ID,
                "name": MODEL_NAME,
                "description": "همراه هوشمند و کودک‌دوست",
            }
        ]

    async def _resolve_backend_model(self, body: dict[str, Any]) -> str:
        if self.valves.BACKEND_MODEL.strip():
            return self.valves.BACKEND_MODEL.strip()
        return ""

    async def _get_user_object(self, __user__: dict[str, Any]) -> Any:
        from open_webui.models.users import Users

        return await _await_if_needed(Users.get_user_by_id(__user__["id"]))

    def _build_status_emitter(
        self,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> Callable[[str], Awaitable[None]] | None:
        if not self.valves.ENABLE_STATUS_UPDATES or not __event_emitter__:
            return None

        async def emit_status(description: str) -> None:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": description, "done": False, "hidden": False},
                }
            )

        return emit_status

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> Union[str, Iterator[str], AsyncIterator[str]]:
        if body.get("stream", False):
            return self._stream_chat(body, __user__, __request__, __event_emitter__)
        return await self._finish_chat(body, __user__, __request__, __event_emitter__)

    async def _stream_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> AsyncIterator[str]:
        """
        Stream response chunks after processing.

        Status events are emitted during _run_chat; we clear them only right
        before the first text chunk so status and streaming do not fight.
        """
        final_response = await self._run_chat(
            body,
            __user__,
            __request__,
            __event_emitter__,
            use_status=self.valves.ENABLE_STATUS_UPDATES,
        )

        if self.valves.ENABLE_STATUS_UPDATES:
            await asyncio.sleep(STATUS_DISPLAY_PAUSE_SEC)
            await clear_status_message(__event_emitter__)

        for chunk in iter_text_chunks(final_response):
            yield chunk
            await asyncio.sleep(0)

    async def _finish_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> str:
        final_response = await self._run_chat(
            body,
            __user__,
            __request__,
            __event_emitter__,
            use_status=self.valves.ENABLE_STATUS_UPDATES,
        )
        if self.valves.ENABLE_STATUS_UPDATES:
            await clear_status_message(__event_emitter__)
        return final_response

    async def _run_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
        *,
        use_status: bool = True,
    ) -> str:
        user = await self._get_user_object(__user__)
        llm_client = OpenWebUILLMClient(__request__, user)
        backend_model = await self._resolve_backend_model(body)

        if not backend_model:
            return "لطفاً در تنظیمات Pipe (Valves) مدل پشتیبان (BACKEND_MODEL) را مشخص کنید."

        raw_messages = body.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []

        conversation_messages = normalize_messages(raw_messages)
        on_status = self._build_status_emitter(__event_emitter__) if use_status else None
        user_persona = get_user_persona_selection(__user__)
        manual_persona = resolve_manual_persona(user_persona=user_persona, body=body)

        async def emit_detecting_persona() -> None:
            if on_status:
                await on_status(status_detecting_persona())

        persona = await resolve_active_persona(
            llm_client,
            backend_model=backend_model,
            messages=conversation_messages,
            user_persona=user_persona,
            body=body,
            on_detecting_status=emit_detecting_persona
            if not manual_persona
            else None,
        )

        if on_status and manual_persona:
            await on_status(status_persona_selected(manual_persona))
        elif on_status and persona != "none":
            await on_status(status_persona_selected(persona))

        textbook_context: TextbookContext | None = None
        user_message = _get_latest_user_message(conversation_messages)
        if (
            self.valves.ENABLE_TEXTBOOK_CONTEXT
            and persona in TEXTBOOK_PERSONAS
            and user_message
            and self.valves.TEXTBOOK_API_URL.strip()
        ):
            if on_status:
                await on_status(status_fetching_textbook())
            include_image = self.valves.TEXTBOOK_INCLUDE_IMAGE.strip().lower()
            if include_image not in {"never", "auto", "always"}:
                include_image = "auto"
            textbook_context = await fetch_textbook_context(
                user_message,
                api_url=self.valves.TEXTBOOK_API_URL,
                api_key=self.valves.TEXTBOOK_API_KEY or None,
                include_neighbors=self.valves.TEXTBOOK_NEIGHBOR_PAGES,
                include_image=include_image,  # type: ignore[arg-type]
                timeout_sec=self.valves.TEXTBOOK_REQUEST_TIMEOUT_SEC,
            )

        return await run_response_loop(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            temperature=self.valves.TEMPERATURE,
            on_status=on_status,
            textbook_context=textbook_context,
        )
