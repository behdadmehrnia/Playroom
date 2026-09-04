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
    return "😊 Finding the right mode for you..."


def status_persona_selected(persona: PersonaId) -> str:
    label = get_persona_ui_label(persona)
    return f"🎭 {label} mode it is! Here we go..."


def status_generating_response(
    attempt: int = 1,
    max_attempts: int = 1,
    *,
    debug: bool = False,
) -> str:
    """Progress status while writing a reply.

    Attempt counters like "(1 of 3)" only appear when ``debug`` is on.
    """
    if debug:
        return f"✨ Writing your answer... ({attempt} of {max_attempts})"
    return "✨ Writing your answer..."


def status_reviewing_response() -> str:
    return "🔍 One moment! Checking everything looks great..."


def status_reflection_disabled() -> str:
    return "⚡ Review is off — answering straight away..."


def status_fetching_textbook() -> str:
    return "📖 Finding the textbook page..."


def status_textbook_unavailable() -> str:
    return "⚠️ Couldn't reach the textbook service..."


def status_fetching_web_search() -> str:
    return "🔎 Searching the web for information..."


def status_web_search_unavailable() -> str:
    return "⚠️ Web search wasn't available just now..."


def status_calculating_math() -> str:
    return "🔢 Working out the maths..."
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
