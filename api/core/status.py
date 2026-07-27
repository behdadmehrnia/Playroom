"""UI status message helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from .constants import PERSONA_UI_LABELS, PersonaId
from .messages import _await_if_needed

def get_persona_ui_label(persona: PersonaId | str) -> str:
    """Return a child-friendly persona label for UI status messages."""
    return PERSONA_UI_LABELS.get(str(persona), PERSONA_UI_LABELS["none"])


def status_detecting_persona() -> str:
    return "😊 دارم شخصیت مناسب رو پیدا می‌کنم..."


def status_persona_selected(persona: PersonaId) -> str:
    label = get_persona_ui_label(persona)
    return f"🎭 شخصیت {label} انتخاب شد! بزن بریم..."


def status_generating_response(
    attempt: int = 1,
    max_attempts: int = 1,
    *,
    debug: bool = False,
) -> str:
    """Progress status while writing a reply.

    Attempt counters like «(۱ از ۳)» only appear when ``debug`` is on.
    """
    if debug:
        return f"✨ دارم جوابت رو مینویسم... ({attempt} از {max_attempts})"
    return "✨ دارم جوابت رو مینویسم..."


def status_reviewing_response() -> str:
    return "🔍 یه لحظه! دارم چک می‌کنم همه‌چیز عالی باشه..."


def status_reflection_disabled() -> str:
    return "⚡ بازبینی پاسخ خاموش است — مستقیم جواب می‌دم..."


def status_fetching_textbook() -> str:
    return "📖 دارم صفحهٔ کتاب درسی رو پیدا می‌کنم..."


def status_textbook_unavailable() -> str:
    return "⚠️ نتونستم به سرویس کتاب درسی وصل بشم..."


def status_fetching_web_search() -> str:
    return "🔎 دارم توی اینترنت دنبال اطلاعات می‌گردم..."


def status_web_search_unavailable() -> str:
    return "⚠️ جستجوی اینترنت الان در دسترس نبود..."


def status_calculating_math() -> str:
    return "🔢 دارم حساب می‌کنم..."
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
