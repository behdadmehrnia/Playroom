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


def test_persona_markers_roundtrip_invisible() -> None:
    marked = append_persona_marker("سلام دوست من!", "teacher")
    assert "سلام دوست من!" in marked
    assert "<!--" not in marked
    assert "\u2060" not in marked  # no Word Joiner tofu
    assert extract_persona_marker(marked) == "teacher"
    assert strip_persona_markers(marked) == "سلام دوست من!"

    # Re-append replaces previous marker.
    remaked = append_persona_marker(marked, "homework")
    assert extract_persona_marker(remaked) == "homework"
    assert strip_persona_markers(remaked) == "سلام دوست من!"


def test_persona_markers_legacy_html_and_word_joiner() -> None:
    legacy_html = "ادامه بازی\n\n<!--playroom:gamer-->"
    assert strip_persona_markers(legacy_html) == "ادامه بازی"
    assert extract_persona_marker(legacy_html) == "gamer"

    # Old Word-Joiner fence still decodes.
    from api.core.constants import _ZW_DIGIT, _ZW_LEGACY_MARK

    code = _ZW_DIGIT["1"] + _ZW_DIGIT["1"]  # gamer
    legacy_zw = f"سلام{_ZW_LEGACY_MARK}{code}{_ZW_LEGACY_MARK}"
    assert extract_persona_marker(legacy_zw) == "gamer"
    assert strip_persona_markers(legacy_zw) == "سلام"


def test_iter_text_chunks() -> None:
    text = "abcdefgh"
    chunks = list(iter_text_chunks(text, chunk_size=3))
    assert chunks == ["abc", "def", "gh"]
    assert list(iter_text_chunks("")) == [""]
