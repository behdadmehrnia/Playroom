"""
title: یار کودک
author: Yar Kids
version: 0.2.2
description: دستیار کودک‌دوست با معماری Persona، Intent Detection و Reflection
required_open_webui_version: 0.5.0
"""

from __future__ import annotations

import inspect
import json
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol

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

SAFE_FALLBACK_RESPONSE = (
    "متأسفم، الان نتوانستم پاسخ مناسبی برایت بدهم. "
    "بیایید با هم یک موضوع دیگر را امتحان کنیم! "
    "می‌توانی دربارهٔ یک داستان، یک سوال درسی، یا یک ایدهٔ خلاقانه از من بپرسی."
)

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
    messages: list[dict[str, str]]
    stream: bool = False
    temperature: float | None = None


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


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_system_prompt(
    persona: PersonaId,
    revision_reasons: list[str] | None = None,
) -> str:
    sections: list[str] = [get_core_prompt()]

    persona_prompt = get_persona_prompt(persona)
    if persona_prompt:
        sections.append(persona_prompt)

    if revision_reasons:
        reasons_text = "\n".join(f"- {reason}" for reason in revision_reasons)
        sections.append(f"{REVISION_INSTRUCTION_HEADER}\n{reasons_text}")

    return "\n\n".join(sections)


def build_prompt_messages(
    *,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
) -> list[dict[str, str]]:
    llm_messages: list[dict[str, str]] = [
        {"role": "system", "content": build_system_prompt(persona, revision_reasons)},
    ]
    for message in conversation_messages:
        if message.role != "system":
            llm_messages.append({"role": message.role, "content": message.content})
    return llm_messages


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
) -> PersonaId:
    manual_persona = resolve_manual_persona(user_persona=user_persona, body=body)
    if manual_persona:
        return manual_persona

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
) -> str:
    request = LLMCompletionRequest(
        model=backend_model,
        messages=build_prompt_messages(
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons,
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
) -> str:
    revision_reasons: list[str] = []
    user_message = _get_latest_user_message(conversation_messages)

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if on_status:
            await on_status(f"در حال تولید پاسخ (تلاش {attempt}/{MAX_GENERATION_ATTEMPTS})...")

        candidate = await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons or None,
            temperature=temperature,
        )

        if on_status:
            await on_status("در حال بازبینی کیفیت پاسخ...")

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

    class UserValves(BaseModel):
        """Per-chat persona selector shown in Chat Controls → Valves."""

        PERSONA: str = Field(
            default="auto",
            description="پرسونای فعال برای این گفتگو",
            json_schema_extra={
                "input": {
                    "type": "select",
                    "options": [
                        {"value": "auto", "label": "خودکار (تشخیص نیت)"},
                        {"value": "creative", "label": "خلاق"},
                        {"value": "storyteller", "label": "داستان‌گو"},
                        {"value": "teacher", "label": "معلم"},
                        {"value": "homework", "label": "کمک‌درس"},
                    ],
                }
            },
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [{"id": MODEL_ID, "name": MODEL_NAME}]

    async def _resolve_backend_model(self, body: dict[str, Any]) -> str:
        if self.valves.BACKEND_MODEL.strip():
            return self.valves.BACKEND_MODEL.strip()

        model_from_body = body.get("model", "")
        if isinstance(model_from_body, str) and "." in model_from_body:
            return model_from_body.split(".", 1)[1]

        return str(model_from_body) if model_from_body else ""

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
                {"type": "status", "data": {"description": description, "done": False}}
            )

        return emit_status

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
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
        on_status = self._build_status_emitter(__event_emitter__)

        if on_status:
            await on_status("در حال انتخاب پرسونا...")

        persona = await resolve_active_persona(
            llm_client,
            backend_model=backend_model,
            messages=conversation_messages,
            user_persona=get_user_persona_selection(__user__),
            body=body,
        )

        final_response = await run_response_loop(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            temperature=self.valves.TEMPERATURE,
            on_status=on_status,
        )

        if __event_emitter__ and self.valves.ENABLE_STATUS_UPDATES:
            await __event_emitter__(
                {"type": "status", "data": {"description": "پاسخ آماده است.", "done": True}}
            )

        return final_response
