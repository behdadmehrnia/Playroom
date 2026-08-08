"""Message normalization, persona markers, and shared HTTP helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from typing import Any

from .constants import (
    STREAM_CHUNK_SIZE,
    SUPPORTED_PERSONAS,
    PersonaId,
    _PERSONA_MARKER_RE,
    _PERSONA_ZW_CODE,
    _ZW_CODE_PERSONA,
    _ZW_DIGIT,
    _ZW_DIGIT_INV,
    _ZW_FENCE,
    _ZW_LEGACY_MARK,
    _ZW_LEGACY_PERSONA_MARKER_RE,
    _ZW_PERSONA_MARKER_RE,
)
from .types import ChatMessage

async def _await_if_needed(value: Any) -> Any:
    """Await coroutines; return plain values unchanged (OpenWebUI version compat)."""
    if inspect.isawaitable(value):
        return await value
    return value
def coerce_bool(value: Any, *, default: bool = True) -> bool:
    """Robust bool coercion for OpenWebUI valves (bool / 0-1 / 'true'|'false')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "بله"}:
            return True
        if normalized in {"0", "false", "no", "off", "خیر", ""}:
            return False
    return default


def read_valve_bool(valves: Any, name: str, *, default: bool = True) -> bool:
    """Read a boolean valve whether valves is a Pydantic model or a plain dict."""
    if valves is None:
        return default
    if isinstance(valves, dict):
        return coerce_bool(valves.get(name, default), default=default)
    return coerce_bool(getattr(valves, name, default), default=default)
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


def extract_message_content(content: Any) -> str:
    """Flatten Open WebUI / OpenAI message content (str or multimodal parts)."""
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
                item_type = item.get("type")
                if item_type in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
                elif "content" in item:
                    parts.append(extract_message_content(item.get("content")))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return extract_message_content(content.get("text") or content.get("content"))
    return str(content)


def normalize_messages(raw_messages: list[dict[str, Any]]) -> list[ChatMessage]:
    normalized: list[ChatMessage] = []
    for item in raw_messages:
        role = item.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        content = extract_message_content(item.get("content")).strip()
        if not content:
            continue
        normalized.append(ChatMessage(role=role, content=content))
    return normalized


def strip_persona_markers(text: str) -> str:
    """Remove sticky persona markers (invisible + legacy HTML) from text."""
    if not text:
        return text
    cleaned = _PERSONA_MARKER_RE.sub("", text)
    cleaned = _ZW_PERSONA_MARKER_RE.sub("", cleaned)
    cleaned = _ZW_LEGACY_PERSONA_MARKER_RE.sub("", cleaned)
    # Drop leftover Word Joiners that some clients render as tofu.
    cleaned = cleaned.replace(_ZW_LEGACY_MARK, "").replace("\ufeff", "")
    return cleaned.rstrip()


def append_persona_marker(text: str, persona: PersonaId) -> str:
    """Append an invisible persona tag so history can recover sticky persona.

    The tag uses only zero-width characters (no HTML, no Word Joiner) so it
    should not change Open WebUI / playground / OpenAI-client display. Markers
    are stripped before LLM prompts and can be stripped for UI rendering.
    """
    base = strip_persona_markers(text) if text else ""
    if not persona or persona == "none":
        return base
    code = _PERSONA_ZW_CODE.get(persona)
    if not code or len(code) != 2:
        return base
    encoded = "".join(_ZW_DIGIT[ch] for ch in code)
    marker = f"{_ZW_FENCE}{encoded}{_ZW_FENCE}"
    if not base:
        return marker
    return f"{base}{marker}"


def extract_persona_marker(text: str) -> PersonaId | None:
    """Decode persona tag from assistant history (current + legacy formats)."""
    if not text:
        return None

    def _decode_zw_digits(blob: str) -> PersonaId | None:
        code = "".join(_ZW_DIGIT_INV.get(ch, "") for ch in blob)
        persona = _ZW_CODE_PERSONA.get(code)
        return persona  # type: ignore[return-value]

    zw_matches = _ZW_PERSONA_MARKER_RE.findall(text)
    if zw_matches:
        decoded = _decode_zw_digits(zw_matches[-1])
        if decoded:
            return decoded
    legacy_matches = _ZW_LEGACY_PERSONA_MARKER_RE.findall(text)
    if legacy_matches:
        decoded = _decode_zw_digits(legacy_matches[-1])
        if decoded:
            return decoded
    html_matches = _PERSONA_MARKER_RE.findall(text)
    if html_matches:
        return _normalize_persona(html_matches[-1])
    return None


_GREETING_ONLY_RE = re.compile(
    r"^(?:"
    r"سلام(?:\s*علیکم)?|درود|هی+|hello|hi|hey|"
    r"صبح\s*بخیر|ظهر\s*بخیر|عصر\s*بخیر|شب\s*بخیر|"
    r"خوبی\??|چطوری\??|چه\s*خبر\??"
    r")[\s!.！؟?٫،,~]*$",
    re.IGNORECASE,
)


def _looks_like_greeting_only(text: str) -> bool:
    """True for bare greetings that must stay on persona none."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 40:
        return False
    return bool(_GREETING_ONLY_RE.match(cleaned))


def _looks_like_welcome_or_menu(content: str) -> bool:
    """True for the first-turn persona picker / welcome message."""
    if "کدومش رو بیشتر دوست داری" in content:
        return True
    if "با هم آشنا شدیم" in content or "من «یار کودک» هستم" in content:
        # Welcome often lists all personas — do not treat as active session.
        hits = sum(
            1
            for signal in (
                "داستان‌گو",
                "داستان گو",
                "کمک‌درسی",
                "کمک درسی",
                "بازی و سرگرمی",
                "خلاق",
                "معلم",
            )
            if signal in content
        )
        return hits >= 3
    return False


_MENU_PERSONA_PICKS: dict[str, PersonaId] = {
    "بازی": "gamer",
    "سرگرمی": "gamer",
    "گیمر": "gamer",
    "بازی و سرگرمی": "gamer",
    "داستان": "storyteller",
    "قصه": "storyteller",
    "داستان‌گو": "storyteller",
    "داستان گو": "storyteller",
    "معلم": "teacher",
    "خلاق": "creative",
    "کمک‌درسی": "homework",
    "کمک درسی": "homework",
    "کمک‌درس": "homework",
    "کمک درس": "homework",
}


def _detect_menu_persona_pick(text: str) -> PersonaId | None:
    """Map short welcome-menu replies like «بازی» to a persona."""
    cleaned = text.strip()
    cleaned = re.sub(r"^[\s🎮🎨📖📚✏️]+", "", cleaned)
    cleaned = re.sub(r"[!.！؟?٫،,~]+$", "", cleaned).strip()
    if not cleaned or len(cleaned) > 30:
        return None
    if cleaned in _MENU_PERSONA_PICKS:
        return _MENU_PERSONA_PICKS[cleaned]
    lowered = cleaned.lower()
    for key, persona in sorted(_MENU_PERSONA_PICKS.items(), key=lambda item: -len(item[0])):
        if lowered == key.lower():
            return persona
    return None


def _last_assistant_is_welcome(messages: list[ChatMessage]) -> bool:
    for message in reversed(messages):
        if message.role == "assistant":
            return _looks_like_welcome_or_menu(message.content)
    return False


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
def _http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float,
) -> dict[str, Any] | list[Any] | None:
    request = urllib.request.Request(
        url,
        headers=headers
        or {
            "User-Agent": "YarKids/1.0 (child-assistant; web-search)",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, (dict, list)) else None
