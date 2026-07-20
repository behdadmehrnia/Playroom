"""Message normalization and utility tests."""

from __future__ import annotations

import pytest

from api.core import (
    ChatMessage,
    append_persona_marker,
    coerce_bool,
    extract_message_content,
    extract_persona_marker,
    iter_text_chunks,
    normalize_messages,
    read_valve_bool,
    strip_persona_markers,
)


def test_coerce_bool() -> None:
    assert coerce_bool("true") is True
    assert coerce_bool("0") is False
    assert coerce_bool("بله") is True
    assert coerce_bool(None, default=True) is True
    assert coerce_bool("maybe", default=False) is False


def test_read_valve_bool() -> None:
    class Valves:
        ENABLE = True

    assert read_valve_bool(Valves(), "ENABLE") is True
    assert read_valve_bool(Valves(), "MISSING", default=False) is False


def test_extract_message_content() -> None:
    assert extract_message_content("hi") == "hi"
    assert extract_message_content([{"type": "text", "text": "سلام"}]) == "سلام"
    assert extract_message_content(
        [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]
    ) == "a\nb"


def test_normalize_messages_multimodal() -> None:
    raw = [
        {"role": "user", "content": "بازی کنیم"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "بازی کلمه‌های زنجیره‌ای!"}],
        },
        {"role": "user", "content": [{"type": "text", "text": "داستان"}]},
    ]
    messages = normalize_messages(raw)
    assert len(messages) == 3
    assert messages[1].content == "بازی کلمه‌های زنجیره‌ای!"
    assert messages[2].content == "داستان"


def test_persona_markers_disabled_for_display() -> None:
    marked = append_persona_marker("سلام!\n\n<!--yarkids:gamer-->", "gamer")
    assert "<!--" not in marked
    legacy = "ادامه بازی\n\n<!--yarkids:gamer-->"
    assert strip_persona_markers(legacy) == "ادامه بازی"
    assert extract_persona_marker(legacy) == "gamer"


def test_iter_text_chunks() -> None:
    text = "abcdefgh"
    chunks = list(iter_text_chunks(text, chunk_size=3))
    assert chunks == ["abc", "def", "gh"]
    assert list(iter_text_chunks("")) == [""]
