"""
title: یار کودک (API Client)
author: Yar Kids
version: 0.6.6
description: Pipe کلاینت OpenWebUI — منطق یار کودک را از طریق API مستقل (api/) اجرا می‌کند
required_open_webui_version: 0.5.0
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import AsyncIterator
from typing import Any, Awaitable, Callable, Union

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_ID = "yarkids_api"
MODEL_NAME = "یار کودک مستقل"
MANUAL_PERSONA_METADATA_KEY = "yarkids_persona"
SUPPORTED_PERSONAS = ("creative", "storyteller", "teacher", "homework", "gamer")
DEFAULT_API_TIMEOUT_SEC = 300.0

PERSONA_DROPDOWN_OPTIONS: list[dict[str, str]] = [
    {"value": "auto", "label": "✨ خودکار — خودم انتخاب می‌کنم!"},
    {"value": "creative", "label": "🎨 خلاق"},
    {"value": "storyteller", "label": "📖 داستان‌گو"},
    {"value": "teacher", "label": "📚 معلم"},
    {"value": "homework", "label": "✏️ کمک‌درس"},
    {"value": "gamer", "label": "🎮 بازی و سرگرمی"},
]

SAFE_FALLBACK_RESPONSE = (
    "متأسفم، الان نتوانستم پاسخ مناسبی برایت بدهم. "
    "بیایید با هم یک موضوع دیگر را امتحان کنیم!"
)

NO_API_URL_MESSAGE = (
    "لطفاً در تنظیمات Pipe مقدار API_BASE_URL را مشخص کنید "
    "(آدرس سرویس api/)."
)

# ---------------------------------------------------------------------------
# Persona resolution (UserValves / metadata — same contract as the API)
# ---------------------------------------------------------------------------


def _normalize_persona(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"", "none", "auto", "automatic"}:
        return None
    if normalized in SUPPORTED_PERSONAS:
        return normalized
    return None


def _get_user_persona_selection(__user__: dict[str, Any] | None) -> str | None:
    if not __user__:
        return None
    valves = __user__.get("valves")
    if valves is None:
        return None
    persona = dict(valves).get("PERSONA")
    if isinstance(persona, str) and persona.strip():
        return persona.strip()
    return None


def resolve_persona_to_forward(
    *,
    __user__: dict[str, Any] | None,
    body: dict[str, Any],
) -> str | None:
    """Resolve the manual persona so the API receives the intended override
    (or None for auto / intent detection)."""
    manual = _normalize_persona(_get_user_persona_selection(__user__))
    if manual:
        return manual

    metadata = body.get("metadata") or {}
    if isinstance(metadata, dict):
        manual = _normalize_persona(metadata.get(MANUAL_PERSONA_METADATA_KEY))
        if manual:
            return manual

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


# ---------------------------------------------------------------------------
# SSE streaming client (stdlib only — zero third-party deps for OpenWebUI)
# ---------------------------------------------------------------------------


def _build_api_headers(api_key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    return headers


def _stream_sse_blocking(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout_sec: float,
    queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Worker thread: POST to the API and stream SSE lines into ``queue``.

    Uses ``loop.call_soon_threadsafe`` because ``asyncio.Queue`` is not
    thread-safe by itself — this is the documented cross-thread pattern.
    """
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=timeout_sec) as response:  # type: ignore[arg-type]
            for raw in response:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                loop.call_soon_threadsafe(queue.put_nowait, ("line", line))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
        except Exception:  # noqa: BLE001
            pass
        loop.call_soon_threadsafe(
            queue.put_nowait, ("error", f"HTTP {exc.code} از API: {detail}")
        )
    except urllib.error.URLError as exc:
        loop.call_soon_threadsafe(
            queue.put_nowait, ("error", f"اتصال به API ناموفق: {exc.reason}")
        )
    except Exception as exc:  # noqa: BLE001
        loop.call_soon_threadsafe(
            queue.put_nowait, ("error", f"{type(exc).__name__}: {exc}")
        )
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, ("done", None))


async def consume_sse_stream(
    url: str,
    payload: dict[str, Any],
    *,
    api_key: str | None,
    timeout_sec: float,
) -> AsyncIterator[tuple[str, str]]:
    """Yield ``(event_type, data)`` tuples parsed from the API's SSE stream."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    task = asyncio.create_task(
        asyncio.to_thread(
            _stream_sse_blocking,
            url,
            payload,
            _build_api_headers(api_key),
            timeout_sec,
            queue,
            loop,
        )
    )
    event_type: str | None = None
    data_lines: list[str] = []
    try:
        while True:
            kind, value = await queue.get()
            if kind == "done":
                break
            if kind == "error":
                raise RuntimeError(str(value))
            line: str = value  # type: ignore[assignment]
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip() or None
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip())
            elif line == "":
                if event_type is not None:
                    yield event_type, "\n".join(data_lines)
                event_type = None
                data_lines = []
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------------------
# Status helpers
# ---------------------------------------------------------------------------


async def clear_status_message(
    __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
) -> None:
    if not __event_emitter__:
        return
    await __event_emitter__(
        {"type": "status", "data": {"description": "", "done": True, "hidden": True}}
    )


# ---------------------------------------------------------------------------
# Pipe
# ---------------------------------------------------------------------------


class Pipe:
    """OpenWebUI Pipe that delegates the full Yar Kids logic to the API.

    Same Valves / UserValves / streaming shape as the deprecated local Pipe
    (``pipe_logic.py``), so it is the drop-in replacement. Every stage —
    persona resolution, intent detection, textbook retrieval, generation,
    reflection — runs inside ``api/``; this client only forwards the request
    and relays SSE (status + text chunks) back to OpenWebUI.
    """

    class Valves(BaseModel):
        API_BASE_URL: str = Field(
            default="http://host.docker.internal:8090",
            description="آدرس پایهٔ API مستقل یار کودک (api/main.py) — بدون / در انتها.",
        )
        API_KEY: str = Field(
            default="",
            description="کلید API اختیاری (Bearer) اگر API پشت دروازهٔ احراز هویت باشد.",
        )
        MODEL: str = Field(
            default="",
            description=(
                "شناسهٔ مدل برای ارسال به API. "
                "خالی = استفاده از مدل پیش‌فرضِ سمت API."
            ),
        )
        TEMPERATURE: float = Field(
            default=0.7,
            ge=0.0,
            le=2.0,
            description="دمای تولید پاسخ.",
        )
        ENABLE_STATUS_UPDATES: bool = Field(
            default=True,
            description="نمایش وضعیت پردازش در رابط کاربری.",
        )
        ENABLE_REFLECTION: bool = Field(
            default=True,
            title="ایجنت بازبینی پاسخ",
            description=(
                "اگر روشن باشد، پاسخ قبل از ارسال توسط ایجنت Reflection بررسی می‌شود."
            ),
        )
        ENABLE_TEXTBOOK_CONTEXT: bool = Field(
            default=True,
            description="بازیابی کتاب درسی از textbook-service (معلم/کمک‌درسی).",
        )
        ENABLE_WEB_SEARCH: bool = Field(
            default=True,
            description=(
                "جستجوی وب برای پرسوناهای خلاق / داستان‌گو / بازی و سرگرمی "
                "(وقتی سؤال واقعی/به‌روز باشد)."
            ),
        )
        REQUEST_TIMEOUT_SEC: float = Field(
            default=DEFAULT_API_TIMEOUT_SEC,
            ge=10.0,
            description="مهلت درخواست به API (ثانیه).",
        )

    class UserValves(BaseModel):
        PERSONA: str = Field(
            default="auto",
            title="شخصیت یار کودک",
            description="از این منو شخصیت دوستت رو انتخاب کن! 😊",
            json_schema_extra={
                "input": {"type": "select", "options": PERSONA_DROPDOWN_OPTIONS}
            },
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [
            {
                "id": MODEL_ID,
                "name": MODEL_NAME,
                "description": "همراه هوشمند و کودک‌دوست (نسخهٔ API)",
            }
        ]

    # -- helpers -----------------------------------------------------------

    def _api_chat_url(self) -> str:
        return self.valves.API_BASE_URL.strip().rstrip("/") + "/v1/chat"

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
                    "data": {
                        "description": description,
                        "done": False,
                        "hidden": False,
                    },
                }
            )

        return emit_status

    def _build_api_payload(
        self, body: dict[str, Any], __user__: dict[str, Any]
    ) -> dict[str, Any]:
        persona = resolve_persona_to_forward(__user__=__user__, body=body)

        raw_messages = body.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []
        messages = [
            {"role": m.get("role"), "content": m.get("content")}
            for m in raw_messages
            if isinstance(m, dict) and isinstance(m.get("content"), str)
        ]

        payload: dict[str, Any] = {
            "messages": messages,
            # Always stream from the API so status events arrive live —
            # we decide whether to yield or accumulate chunks based on the
            # OpenWebUI stream flag (mirrors Pipe._stream_chat / _finish_chat).
            "stream": True,
        }
        if persona:
            payload["persona"] = persona
        if self.valves.MODEL.strip():
            payload["model"] = self.valves.MODEL.strip()
        if self.valves.TEMPERATURE is not None:
            payload["temperature"] = self.valves.TEMPERATURE
        payload["enable_reflection"] = self.valves.ENABLE_REFLECTION
        payload["enable_textbook_context"] = self.valves.ENABLE_TEXTBOOK_CONTEXT
        payload["enable_web_search"] = self.valves.ENABLE_WEB_SEARCH
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            payload["metadata"] = metadata
        return payload

    async def _iter_api_events(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
    ) -> AsyncIterator[tuple[str, str]]:
        """Yield normalized ``(event_kind, text)`` tuples from the API stream.

        event_kind is one of: ``status``, ``status_clear``, ``chunk``,
        ``title``, ``error``, ``done``. The generator ends naturally when the SSE stream
        completes, ensuring clean teardown of the background reader thread.
        """
        payload = self._build_api_payload(body, __user__)
        async for event_type, data in consume_sse_stream(
            self._api_chat_url(),
            payload,
            api_key=self.valves.API_KEY or None,
            timeout_sec=self.valves.REQUEST_TIMEOUT_SEC,
        ):
            if event_type == "status":
                try:
                    description = json.loads(data).get("description", "")
                except json.JSONDecodeError:
                    description = data
                yield "status", description
            elif event_type == "status_clear":
                yield "status_clear", ""
            elif event_type == "chunk":
                try:
                    text = json.loads(data).get("text", "")
                except json.JSONDecodeError:
                    text = data
                if text:
                    yield "chunk", text
            elif event_type == "title":
                try:
                    title = json.loads(data).get("title", "")
                except json.JSONDecodeError:
                    title = data
                if title:
                    yield "title", title
            elif event_type == "error":
                try:
                    message = json.loads(data).get("message", data)
                except json.JSONDecodeError:
                    message = data
                yield "error", message
            elif event_type == "done":
                yield "done", ""

    # -- entry point ------------------------------------------------------

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> Union[str, AsyncIterator[str]]:
        if not self.valves.API_BASE_URL.strip():
            return NO_API_URL_MESSAGE
        if body.get("stream", False):
            return self._stream_chat(body, __user__, __event_emitter__)
        return await self._finish_chat(body, __user__, __event_emitter__)

    # -- streaming --------------------------------------------------------

    async def _stream_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> AsyncIterator[str]:
        emit_status = self._build_status_emitter(__event_emitter__)
        try:
            async for kind, value in self._iter_api_events(body, __user__):
                if kind == "status":
                    if emit_status:
                        await emit_status(value)
                elif kind == "status_clear":
                    await clear_status_message(__event_emitter__)
                elif kind == "chunk":
                    yield value
                    await asyncio.sleep(0)
                elif kind == "title":
                    if __event_emitter__:
                        await __event_emitter__(
                            {"type": "chat:title", "data": value}
                        )
                elif kind == "error":
                    await clear_status_message(__event_emitter__)
                    yield f"\n\n⚠️ {value}"
        except RuntimeError as exc:
            await clear_status_message(__event_emitter__)
            yield f"\n\n⚠️ {exc}"

    # -- non-streaming ----------------------------------------------------

    async def _finish_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> str:
        emit_status = self._build_status_emitter(__event_emitter__)
        chunks: list[str] = []
        error_message: str | None = None
        title: str | None = None
        try:
            async for kind, value in self._iter_api_events(body, __user__):
                if kind == "status":
                    if emit_status:
                        await emit_status(value)
                elif kind == "status_clear":
                    await clear_status_message(__event_emitter__)
                elif kind == "chunk":
                    chunks.append(value)
                elif kind == "title":
                    title = value
                elif kind == "error":
                    error_message = value
        except RuntimeError as exc:
            error_message = str(exc)
        await clear_status_message(__event_emitter__)
        if title and __event_emitter__:
            await __event_emitter__(
                {"type": "chat:title", "data": title}
            )
        if error_message:
            return f"⚠️ {error_message}"
        return "".join(chunks) if chunks else SAFE_FALLBACK_RESPONSE
