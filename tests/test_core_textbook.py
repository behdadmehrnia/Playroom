"""Textbook query building and helper tests."""

from __future__ import annotations

import pytest

from api.core import ChatMessage, build_textbook_query, looks_like_textbook_help_request, looks_like_textbook_page_query
from api.core.textbook import (
    _extract_grade_token,
    _extract_page_number,
    _extract_subject_token,
    _grade_token_to_int,
    _subject_keyword_to_id,
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
    assert scope.chapter == 3
    assert scope.lesson is None
    assert scope.can_retrieve() is True


def test_extract_grade_from_subject_plus_ordinal_with_chapter() -> None:
    """«فصل هشتم فارسی چهارم» — چهارم is grade, هشتم is chapter (not درس)."""
    assert _extract_grade_token("فصل هشتم فارسی چهارم") == "چهارم"
    from api.core.types import ChatMessage
    from api.core.textbook import resolve_textbook_scope

    scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="فصل هشتم فارسی چهارم")]
    )
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.chapter == 8
    assert scope.lesson is None
    assert scope.can_retrieve() is True
    assert scope.has_chapter_lookup() is True
    assert scope.has_lesson_lookup() is False

    scoped = resolve_textbook_scope(
        [
            ChatMessage(role="user", content="فصل هشتم فارسی چهارم"),
            ChatMessage(role="assistant", content="صفحه چند؟"),
            ChatMessage(role="user", content="صفحه ۳۴"),
        ]
    )
    assert scoped.grade == 4
    assert scoped.subject_id == "persian"
    assert scoped.page == 34
    assert scoped.has_page_lookup() is True


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


def test_chapter_and_lesson_numbers_are_separate() -> None:
    from api.core.textbook import _extract_chapter_number, _extract_lesson_number
    from api.core.types import ChatMessage
    from api.core.textbook import resolve_textbook_scope
    from api.textbook.app.parser import parse_persian_query

    assert _extract_chapter_number("فصل چهارم فارسی چهارم") == 4
    assert _extract_lesson_number("فصل چهارم فارسی چهارم") is None
    assert _extract_lesson_number("درس چهارم ارزش علم") == 4
    assert _extract_chapter_number("درس چهارم ارزش علم") is None

    chapter_scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="فصل چهارم فارسی چهارم")]
    )
    assert chapter_scope.chapter == 4
    assert chapter_scope.lesson is None
    assert chapter_scope.grade == 4
    assert chapter_scope.subject_id == "persian"

    lesson_scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="درس چهارم فارسی کلاس چهارم")]
    )
    assert lesson_scope.lesson == 4
    assert lesson_scope.chapter is None

    parsed_chapter = parse_persian_query("فصل چهارم فارسی پایه چهارم")
    assert parsed_chapter.chapter == 4
    assert parsed_chapter.lesson is None
    parsed_lesson = parse_persian_query("درس چهارم فارسی پایه چهارم")
    assert parsed_lesson.lesson == 4
    assert parsed_lesson.chapter is None


def test_named_lesson_title_sets_topic_even_with_chapter() -> None:
    """«فصل سوم → کلاس ششم → ارزش علم» must not ignore the lesson title."""
    from api.core.textbook import _extract_named_lesson_title

    assert _extract_named_lesson_title("ارزش علم") == "ارزش علم"
    assert _extract_named_lesson_title("درس ارزش علم") == "ارزش علم"
    assert _extract_named_lesson_title("درس چهارم ارزش علم") == "ارزش علم"
    assert _extract_named_lesson_title("کلاس ششم") is None
    assert _extract_named_lesson_title("کتاب فارسی پایه چهارم") is None
    assert _extract_named_lesson_title("فصل سوم کتاب فارسی رو توضیح بده") is None

    messages = [
        ChatMessage(
            role="user",
            content="نه میخوام بهم فصل سوم کتاب فارسی رو توضیح بدی",
        ),
        ChatMessage(
            role="assistant",
            content="چه عالی! تو کلاس چندمی؟",
        ),
        ChatMessage(role="user", content="کلاس ششم"),
        ChatMessage(
            role="assistant",
            content="می‌شه شماره صفحه یا اسم درس رو در فصل سوم بگی؟",
        ),
        ChatMessage(role="user", content="ارزش علم"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 6
    assert scope.subject_id == "persian"
    assert scope.chapter == 3
    assert scope.topic_query == "ارزش علم"
    assert scope.can_retrieve() is True


def test_followup_about_named_lesson_keeps_topic() -> None:
    messages = [
        ChatMessage(role="user", content="فصل سوم فارسی کلاس ششم"),
        ChatMessage(role="assistant", content="اسم درس رو بگو"),
        ChatMessage(role="user", content="ارزش علم"),
        ChatMessage(role="assistant", content="به نظرت علم چه ارزشی داره؟"),
        ChatMessage(role="user", content="مگه درباره ی درس ارزش علم صحبت نمیکردیم ؟"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 6
    assert scope.subject_id == "persian"
    assert scope.topic_query == "ارزش علم"


def test_page_with_yeh_sticky_across_grade_subject_reply() -> None:
    """«صفحه ی ۴۰» then «کتاب فارسی پایه چهارم» must retrieve that page."""
    assert _extract_page_number("درک مطلب صفحه ی ۴۰ کتاب رو حل کنم") == 40
    assert _extract_page_number("صفحه‌ی ۴۰") == 40
    assert _extract_page_number("صفحهٔ ۴۰") == 40

    messages = [
        ChatMessage(
            role="user",
            content="سلام، میخوام که درک مطلب صفحه ی ۴۰ کتاب رو حل کنم",
        ),
        ChatMessage(
            role="assistant",
            content="کلاس چندمی و این تمرین مربوط به کدوم کتابه؟",
        ),
        ChatMessage(role="user", content="کتاب فارسی پایه چهارم"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.page == 40
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.topic_query is None
    assert scope.can_retrieve() is True
    assert scope.has_page_lookup() is True


@pytest.mark.parametrize(
    ("text", "grade", "subject_id"),
    [
        ("چمدونم ریاضی چهارم", 4, "math"),
        ("کتابم ریاضی چهارم", 4, "math"),
        ("ریاضی چهارم", 4, "math"),
        ("فارسی پنجم", 5, "persian"),
        ("علوم ششم", 6, "science"),
        ("نگارش سوم", 3, "writing"),
        ("چهارم ریاضی", 4, "math"),
        ("ریاضی 4", 4, "math"),
        ("فارسی۴", 4, "persian"),
        ("فارسی۵", 5, "persian"),
        ("ریاضی‌ام چهارمه", 4, "math"),
        ("هدیه های آسمان پنجم", 5, "gifts"),
    ],
)
def test_informal_book_grade_phrases(text: str, grade: int, subject_id: str) -> None:
    """Colloquial «کتاب+پایه» replies must resolve without «پایه/کلاس» keywords."""
    from api.textbook.app.parser import parse_persian_query

    assert _extract_grade_token(text) is not None
    assert _grade_token_to_int(_extract_grade_token(text)) == grade
    assert _subject_keyword_to_id(_extract_subject_token(text)) == subject_id

    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.grade == grade
    assert scope.subject_id == subject_id

    parsed = parse_persian_query(text)
    assert parsed.grade == grade
    assert parsed.subject == subject_id


def test_informal_book_reply_keeps_sticky_page() -> None:
    messages = [
        ChatMessage(role="user", content="درک مطلب صفحه ی ۴۰ رو حل کنیم"),
        ChatMessage(role="assistant", content="کلاس چندمی و کدوم کتاب؟"),
        ChatMessage(role="user", content="چمدونم ریاضی چهارم"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.page == 40
    assert scope.grade == 4
    assert scope.subject_id == "math"
    assert scope.has_page_lookup() is True
