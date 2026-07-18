"""Deterministic helper tests for persona_system_tests.md (non-textbook)."""

from __future__ import annotations

import pytest

from api.core import (
    ACTIVE_PERSONA_METADATA_KEY,
    ChatMessage,
    _detect_explicit_persona_request,
    _detect_ongoing_activity,
    _infer_persona_from_history,
    _is_activity_continuation,
    extract_math_expressions,
    format_math_tool_context,
    looks_like_web_search_request,
    resolve_manual_persona,
    run_math_tool_for_message,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("باش معلم", "teacher"),
        ("معلم باش", "teacher"),
        ("قصه بگو", "storyteller"),
        ("باش داستان‌گو", "storyteller"),
        ("کمک درس باش", "homework"),
        ("بازی کنیم", "gamer"),
        ("خلاق باش", "creative"),
        ("باش معلم، نه باش داستان‌گو، در واقع بازی کنیم", "gamer"),
        ("سلام!", None),
        ("کمک", None),
    ],
)
def test_explicit_persona_triggers(text: str, expected: str | None) -> None:
    assert _detect_explicit_persona_request(text) == expected


def test_manual_persona_sources() -> None:
    assert resolve_manual_persona(user_persona="teacher") == "teacher"
    assert (
        resolve_manual_persona(body={"metadata": {"yarkids_persona": "gamer"}})
        == "gamer"
    )
    assert resolve_manual_persona(body={"persona": "creative"}) == "creative"
    assert resolve_manual_persona(user_persona="auto") is None


def test_ongoing_activity_word_chain_keeps_gamer() -> None:
    messages = [
        ChatMessage(role="assistant", content="بریم بازی کلمات! نوبت تو، کلمه بگو."),
        ChatMessage(role="user", content="داستان"),
    ]
    assert _detect_ongoing_activity(messages, "gamer") is not None
    assert _is_activity_continuation("داستان", "gamer") is True
    assert _infer_persona_from_history(messages) == "gamer"


@pytest.mark.parametrize(
    ("persona", "text"),
    [
        ("homework", "سوال بعد"),
        ("storyteller", "ادامه بده"),
        ("teacher", "مثال دیگر"),
        ("creative", "ایده دیگر"),
    ],
)
def test_activity_continuation_phrases(persona: str, text: str) -> None:
    assert _is_activity_continuation(text, persona) is True  # type: ignore[arg-type]


def test_math_natural_language_and_errors() -> None:
    assert extract_math_expressions("۲ به توان ۱۰") == ["2**10"]
    assert extract_math_expressions("جذر ۱۴۴") == ["sqrt(144)"]
    assert extract_math_expressions("۱۲ × ۵") == ["12*5"]

    usages = run_math_tool_for_message("۱۰ تقسیم بر ۰", persona="teacher")
    assert len(usages) == 1
    assert usages[0].ok is False
    assert "تقسیم بر صفر نمیشه" in usages[0].result

    ctx = format_math_tool_context(usages)
    assert ctx is not None
    assert "تقسیم بر صفر نمیشه" in ctx

    # Non-math personas must not get the tool.
    assert run_math_tool_for_message("۱۲ + ۱۷", persona="gamer") == []
    assert run_math_tool_for_message("۱۲ + ۱۷", persona="creative") == []


def test_web_search_persona_gate_helpers() -> None:
    assert looks_like_web_search_request("ماینکرفت چطور الماس پیدا کنم؟") is True
    assert looks_like_web_search_request("داستان یه ربات فضایی بگو") is False


def test_active_persona_metadata_key() -> None:
    assert ACTIVE_PERSONA_METADATA_KEY == "yarkids_active_persona"
