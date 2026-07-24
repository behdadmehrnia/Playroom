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
    looks_like_textbook_followup,
    resolve_textbook_scope,
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


def test_extract_grade_ignores_lesson_number() -> None:
    assert _extract_grade_token("درس سوم") is None
    assert _extract_grade_token("فصل چهارم") is None
    assert _extract_grade_token("کلاس چهارم") == "چهارم"
    assert _extract_grade_token("پایه ششم") is not None


def test_extract_grade_prefers_class_over_chapter_ordinal() -> None:
    """«فصل سوم ریاضی کلاس چهارم» must yield grade 4, not get stuck on فصل سوم."""
    assert _extract_grade_token("فصل سوم ریاضی کلاس چهارم رو توضیح بده") == "چهارم"
    from api.core.types import ChatMessage
    from api.core.textbook import resolve_textbook_scope

    scope = resolve_textbook_scope(
        [
            ChatMessage(
                role="user",
                content="فصل سوم ریاضی کلاس چهارم رو توضیح بده",
            )
        ]
    )
    assert scope.grade == 4
    assert scope.subject_id == "math"
    assert scope.lesson == 3
    assert scope.can_retrieve() is True


def test_build_textbook_query_carries_grade_past_lesson_number() -> None:
    """«درس سوم» is lesson 3, not grade 3 — grade comes from earlier «کلاس چهارم»."""
    messages = [
        ChatMessage(role="user", content="کمک درسی"),
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="user", content="فارسی"),
        ChatMessage(role="user", content="درس سوم"),
        ChatMessage(role="user", content="صفحه ۳۳"),
    ]
    query = build_textbook_query(messages)
    assert query
    assert "33" in query or "۳۳" in query
    assert "فارسی" in query
    assert "چهارم" in query
    assert "سوم" not in query.split()[-1:]  # grade slot must not be lesson ordinal


def test_resolve_textbook_scope_tracks_relative_navigation() -> None:
    messages = [
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="user", content="فارسی"),
        ChatMessage(role="user", content="صفحه ۳۳"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="بریم صفحه بعد"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.page == 34


def test_build_textbook_query_followup_after_next_page() -> None:
    """«چه داستانیه؟» after «بریم صفحه بعد» must stay on page 34, not regress to 33."""
    messages = [
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="user", content="فارسی"),
        ChatMessage(role="user", content="درس سوم"),
        ChatMessage(role="user", content="صفحه ۳۳"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="من پایه چهارمم ها"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="بریم صفحه بعد"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="چه داستانیه ؟"),
    ]
    query = build_textbook_query(messages)
    assert query
    assert "34" in query or "۳۴" in query
    assert "33" not in query and "۳۳" not in query
    assert looks_like_textbook_followup("چه داستانیه ؟")


def test_resolve_textbook_scope_uses_sticky_metadata() -> None:
    scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="چه داستانیه؟")],
        sticky={"grade": 4, "subject": "persian", "page": 34},
    )
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.page == 34
    assert scope.has_page_lookup()


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


def test_build_textbook_query_lesson_reference() -> None:
    messages = [
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="user", content="درس سوم ریاضی"),
    ]
    query = build_textbook_query(messages)
    assert query
    assert "درس سوم" in query
    assert "ریاضی" in query
    assert "چهارم" in query


def test_looks_like_page_query_gifts_out_of_range_style() -> None:
    assert looks_like_textbook_page_query("صفحه ۲۵۱ هدیه های آسمان") is True
    assert looks_like_textbook_page_query("صفحه 251 هدایای آسمان پایه سوم") is True
