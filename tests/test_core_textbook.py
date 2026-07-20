"""Textbook query building and helper tests."""

from __future__ import annotations

import pytest

from api.core import ChatMessage, build_textbook_query, looks_like_textbook_help_request, looks_like_textbook_page_query
from api.core.textbook import (
    _extract_grade_token,
    _extract_page_number,
    _extract_subject_token,
    _textbook_context_from_payload,
    _use_embedded_textbook,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("صفحه ۷ کتاب فارسی پایه ششم", True),
        ("سلام چطوری", False),
    ],
)
def test_looks_like_textbook_page_query(text: str, expected: bool) -> None:
    assert looks_like_textbook_page_query(text) is expected


def test_looks_like_textbook_help_request() -> None:
    assert looks_like_textbook_help_request("کتاب درسی رو باز کن") is True
    assert looks_like_textbook_help_request("سلام") is False


def test_extract_textbook_tokens() -> None:
    text = "صفحه ۷ کتاب فارسی پایه ششم"
    assert _extract_page_number(text) == 7
    assert _extract_grade_token(text) is not None
    assert _extract_subject_token(text) is not None


def test_build_textbook_query_page_reference() -> None:
    messages = [
        ChatMessage(role="user", content="صفحه ۱۲ ریاضی پایه پنجم"),
    ]
    query = build_textbook_query(messages)
    assert query
    assert "12" in query or "۱۲" in query or "صفحه" in query


def test_build_textbook_query_empty_without_reference() -> None:
    messages = [ChatMessage(role="user", content="سلام")]
    assert build_textbook_query(messages) == ""


@pytest.mark.parametrize(
    ("url", "embedded"),
    [
        ("", True),
        ("local", True),
        ("embedded", True),
        ("http://textbook.example", False),
    ],
)
def test_use_embedded_textbook(url: str, embedded: bool) -> None:
    assert _use_embedded_textbook(url) is embedded


def test_textbook_context_from_payload() -> None:
    ctx = _textbook_context_from_payload(
        {
            "matched": True,
            "grade": 6,
            "subject": "math",
            "subject_title": "ریاضی",
            "page": 7,
            "context_text": "متن",
            "text_usable": True,
        }
    )
    assert ctx.matched is True
    assert ctx.page == 7
    assert ctx.context_text == "متن"
