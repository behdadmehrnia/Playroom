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
    looks_like_textbook_session_switch,
    resolve_textbook_scope,
)

from api.textbook.app.models import RetrieveRequest
from api.textbook.app.retrieve_service import retrieve_context


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


def test_resolve_textbook_scope_tracks_relative_chapter_navigation() -> None:
    messages = [
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="user", content="فارسی"),
        ChatMessage(role="user", content="فصل ۳"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="بریم فصل بعدی"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.chapter == 4


def test_relative_chapter_from_sticky_page_without_explicit_chapter() -> None:
    """«فصل بعدی» after page navigation must infer parent unit from catalog."""
    messages = [
        ChatMessage(role="user", content="خب بریم فصل بعدی"),
    ]
    scope = resolve_textbook_scope(
        messages,
        sticky={"grade": 4, "subject": "persian", "page": 34, "lesson": 3},
    )
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    # Page 34 is in فصل ۲ → next is فصل ۳
    assert scope.chapter == 3
    assert scope.page is None


def test_sticky_page_next_page_uses_latest_not_history() -> None:
    """Sticky page 34 + «صفحه بعد» must become 35, not regress via old «صفحه ۳۳»."""
    messages = [
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="فارسی"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="صفحه ۳۳"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="خب بریم صفحه ی بعدی"),
    ]
    scope = resolve_textbook_scope(
        messages,
        sticky={"grade": 4, "subject": "persian", "page": 34, "lesson": 3},
    )
    assert scope.page == 35


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


def test_subject_switch_with_chapter_after_other_math() -> None:
    """«ریاضی بسه، تمرین فصل ۳ فارسی» باید فصل ۳ کتاب فارسی را بگیرد."""
    scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="خب ریاضی بسه، بریم تمرین های فصل ۳ فارسی رو حل کنیم")],
        sticky={"grade": 4, "subject": "math"},
    )
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.chapter == 3

    resp = retrieve_context(
        RetrieveRequest(
            query="",
            grade=scope.grade,
            subject=scope.subject_id,
            chapter=scope.chapter,
            include_image="never",
        )
    )
    assert resp.matched is True


def test_retrieve_next_chapter_via_relative_navigation() -> None:
    """«فصل ۳» → «فصل بعدی» باید فصل ۴ را retrieve کند."""
    messages = [
        ChatMessage(role="user", content="کلاس چهارم"),
        ChatMessage(role="user", content="فارسی"),
        ChatMessage(role="user", content="فصل ۳"),
        ChatMessage(role="assistant", content="..."),
        ChatMessage(role="user", content="بریم فصل بعدی"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.chapter == 4

    resp = retrieve_context(
        RetrieveRequest(
            query="",
            grade=scope.grade,
            subject=scope.subject_id,
            chapter=scope.chapter,
            include_image="never",
        )
    )
    assert resp.matched is True


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


def test_page_flow_still_preferred_over_lesson_and_outline() -> None:
    """Classic page locator must remain first-class and sticky across turns."""
    messages = [
        ChatMessage(role="user", content="سلام میخوام کمک درسی"),
        ChatMessage(role="assistant", content="کلاس چندمی؟ کدوم کتاب؟ صفحه چند؟"),
        ChatMessage(role="user", content="صفحه ۳۴ فارسی پایه چهارم"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.page == 34
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.has_page_lookup() is True
    assert scope.wants_outline is False

    # Relative navigation still works after an explicit page.
    follow = resolve_textbook_scope(
        messages
        + [
            ChatMessage(role="assistant", content="این صفحه درباره روباهه."),
            ChatMessage(role="user", content="بریم صفحه بعد"),
        ]
    )
    assert follow.page == 35
    assert follow.grade == 4
    assert follow.subject_id == "persian"


def test_expected_unit_intents_resolve_for_agent() -> None:
    """Agent-facing intents: outline / skill / session / section."""
    outline = resolve_textbook_scope(
        [ChatMessage(role="user", content="لیست فصل‌های فارسی چهارم")]
    )
    assert outline.wants_outline is True
    assert outline.grade == 4
    assert outline.subject_id == "persian"
    assert outline.can_retrieve() is True
    assert looks_like_textbook_page_query("لیست فصل‌های فارسی چهارم") is True

    skill = resolve_textbook_scope(
        [ChatMessage(role="user", content="مهارت ۳ کار و فناوری ششم")]
    )
    assert skill.kind == "skill"
    assert skill.lesson == 3
    assert skill.page is None

    session = resolve_textbook_scope(
        [ChatMessage(role="user", content="جلسه ۵ قرآن سوم")]
    )
    assert session.kind == "session"
    assert session.lesson == 5
    assert session.subject_id == "quran"

    section = resolve_textbook_scope(
        [ChatMessage(role="user", content="بخش ۲ فناوری ششم")]
    )
    assert section.chapter == 2
    assert section.subject_id == "technology"

    # Outline after a sticky chapter should open the full book list.
    cleared = resolve_textbook_scope(
        [
            ChatMessage(role="user", content="فصل سوم فارسی چهارم"),
            ChatMessage(role="assistant", content="باشه"),
            ChatMessage(role="user", content="لیست فصل‌ها رو بگو"),
        ]
    )
    assert cleared.wants_outline is True
    assert cleared.chapter is None


def test_page_beats_sticky_lesson_when_child_gives_page() -> None:
    scope = resolve_textbook_scope(
        [
            ChatMessage(role="user", content="درس چهارم فارسی چهارم"),
            ChatMessage(role="assistant", content="اگر صفحه رو هم بدونی دقیق‌تره"),
            ChatMessage(role="user", content="صفحه ۳۶"),
        ]
    )
    assert scope.page == 36
    assert scope.lesson == 4
    assert scope.has_page_lookup() is True


def test_list_dorous_outline_intent() -> None:
    """Colloquial «لیست دروس» must open catalog outline (not a vague refusal)."""
    text = "لیست دروس فارسی پایه چهارم رو میگی ؟"
    assert looks_like_textbook_page_query(text) is True
    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.wants_outline is True
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.can_retrieve() is True

    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    resp = retrieve_context(
        RetrieveRequest(
            grade=scope.grade,
            subject=scope.subject_id,
            wants_outline=True,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.match_type == "catalog_outline"
    assert "درس" in (resp.context_text or "")
    assert "آفریدگار" in (resp.context_text or "") or "فصل" in (resp.context_text or "")


def test_list_then_chapter_clears_outline_sticky() -> None:
    """After «لیست دروس», bare «فصل چهارم» must open chapter pages — not stay on outline."""
    list_text = "سلام، لیست درس های کتاب فارسی چهارم دبستان رو میگی ؟"
    assert looks_like_textbook_session_switch(list_text) is True
    assert looks_like_textbook_page_query(list_text) is True

    messages = [
        ChatMessage(role="user", content=list_text),
        ChatMessage(
            role="assistant",
            content="این‌ها درس‌های کتاب فارسی پایه‌ی چهارمه…",
        ),
        ChatMessage(role="user", content="فصل چهارم"),
    ]
    assert looks_like_textbook_session_switch("فصل چهارم") is True
    scope = resolve_textbook_scope(messages)
    assert scope.wants_outline is False
    assert scope.chapter == 4
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.has_chapter_lookup() is True
    assert scope.can_retrieve() is True

    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    resp = retrieve_context(
        RetrieveRequest(
            grade=scope.grade,
            subject=scope.subject_id,
            chapter=scope.chapter,
            wants_outline=False,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.match_type == "lesson_span"
    assert resp.chapter == 4


def test_chapter_without_grade_asks_not_guesses() -> None:
    """«فصل سوم ریاضی» without پایه must not retrieve / invent a grade."""
    text = "میتونی فعالیت های فصل سوم کتاب ریاضی رو حل کنی برام"
    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.subject_id == "math"
    assert scope.chapter == 3
    assert scope.grade is None
    assert scope.can_retrieve() is False
    # Conversational leftovers are not a lesson title.
    assert not scope.topic_query or "میتونی" not in (scope.topic_query or "")

    from api.core.generation import compose_textbook_need_info_reply
    from api.core.types import TextbookContext

    canned = compose_textbook_need_info_reply(
        TextbookContext(
            need_info=True,
            failure_reason="need_grade_or_subject",
            subject="math",
            subject_title="ریاضی",
            chapter=3,
        )
    )
    assert canned is not None
    assert "کلاس" in canned or "پایه" in canned
    assert "ریاضی" in canned


def test_named_lesson_title_with_book_grade_sets_topic() -> None:
    scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="درس ارزش علم فارسی پایه چهارم")]
    )
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.topic_query == "ارزش علم"
    assert scope.can_retrieve() is True


def test_exercise_named_lesson_end_to_end() -> None:
    """«تمرین درس ارزش علم» → scope topic + catalog lesson span."""
    text = "بریم سراغ حل تمرین های درس ارزش علم کتاب فارسی پایه چهارم"
    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.topic_query is not None
    assert "ارزش علم" in scope.topic_query
    assert scope.can_retrieve() is True

    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    resp = retrieve_context(
        RetrieveRequest(
            query=scope.topic_query or text,
            grade=scope.grade,
            subject=scope.subject_id,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.match_type == "lesson_span"
    assert resp.lesson == 4


def test_chapter_thirty_out_of_range_via_scope() -> None:
    text = "فصل سی ام فارسی پایه پنجم"
    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.chapter == 30
    assert scope.grade == 5
    assert scope.subject_id == "persian"

    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    resp = retrieve_context(
        RetrieveRequest(
            grade=scope.grade,
            subject=scope.subject_id,
            chapter=scope.chapter,
            include_image="never",
        )
    )
    assert resp.matched is False
    assert resp.failure_reason == "chapter_out_of_range"
    assert resp.max_chapter == 6
    assert resp.max_lesson == 17


def test_list_lessons_then_solve_lesson_five() -> None:
    messages = [
        ChatMessage(
            role="user",
            content="لیست دروس فارسی پایه ششم رو بده",
        ),
        ChatMessage(role="assistant", content="این‌ها درس‌های فارسی ششم هستن."),
        ChatMessage(
            role="user",
            content="بریم سراغ حل تمرین های درس ۵",
        ),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.wants_outline is False
    assert scope.grade == 6
    assert scope.subject_id == "persian"
    assert scope.lesson == 5

    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    resp = retrieve_context(
        RetrieveRequest(
            grade=scope.grade,
            subject=scope.subject_id,
            lesson=scope.lesson,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.lesson == 5
    assert resp.match_type == "lesson_span"


def test_haft_khan_rostam_is_title_not_lesson_seven() -> None:
    """«درس هفت خان رستم» must not resolve as درس ۷."""
    from api.core.textbook import _extract_lesson_number
    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.parser import parse_persian_query
    from api.textbook.app.retrieve_service import retrieve_context

    text = "بریم سراغ حل تمرین های درس هفت خان رستم فارسی ششم"
    assert _extract_lesson_number(text) is None
    parsed = parse_persian_query(text)
    assert parsed.lesson is None
    assert parsed.search_text is not None
    assert "هفت خان رستم" in parsed.search_text

    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.lesson is None
    assert scope.topic_query is not None
    assert "هفت خان رستم" in scope.topic_query

    resp = retrieve_context(
        RetrieveRequest(
            query=scope.topic_query,
            grade=6,
            subject="persian",
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.lesson == 5
    assert resp.match_type == "lesson_span"


def test_list_persian_grade4_canned_outline_no_doreh_ask() -> None:
    """«لیست درس‌های فارسی پایه چهارم» must return the catalog list immediately."""
    from api.core.generation import (
        build_system_prompt,
        compose_textbook_outline_reply,
    )
    from api.core.textbook import build_textbook_query
    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    text = "لیست درس های کتاب فارسی پایه چهارم رو میگی"
    assert looks_like_textbook_page_query(text) is True
    assert looks_like_textbook_session_switch(text) is True
    assert build_textbook_query([ChatMessage(role="user", content=text)])

    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.wants_outline is True
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert scope.has_outline_lookup() is True

    resp = retrieve_context(
        RetrieveRequest(
            grade=4,
            subject="persian",
            wants_outline=True,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.match_type == "catalog_outline"
    assert "ارزش علم" in (resp.context_text or "")

    from api.core.types import TextbookContext

    ctx = TextbookContext(
        matched=True,
        match_type="catalog_outline",
        grade=4,
        subject="persian",
        subject_title="فارسی",
        context_text=resp.context_text,
        text_usable=True,
    )
    canned = compose_textbook_outline_reply(ctx)
    assert canned is not None
    assert "ارزش علم" in canned
    assert "دوره" not in canned
    assert "جلوی چشمم" not in canned
    assert "کلاس چندم" not in canned

    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "فهرست رسمی" in prompt or "فهرست / لیست" in prompt
    assert "دوره اول / دوره دوم" in prompt  # forbidden explicitly in outline instruction
    # Outline must NOT use the page-action header that tells the model to read images.
    assert "اول تصویر صفحه را بخوان" not in prompt



def test_fusul_math_grade5_returns_outline_not_fake_missing() -> None:
    """«فصول ریاضی پنجم چیه» must list chapters — never «این کتاب» canned miss."""
    from api.core.generation import (
        compose_textbook_failure_reply,
        compose_textbook_outline_reply,
    )
    from api.core.types import TextbookContext
    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    text = "فصول ریاضی پنجم چیه ؟"
    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    assert scope.wants_outline is True
    assert scope.grade == 5
    assert scope.subject_id == "math"

    resp = retrieve_context(
        RetrieveRequest(
            grade=5,
            subject="math",
            wants_outline=True,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.match_type == "catalog_outline"

    ctx = TextbookContext(
        matched=True,
        match_type="catalog_outline",
        grade=5,
        subject="math",
        subject_title=resp.subject_title,
        context_text=resp.context_text,
    )
    canned = compose_textbook_outline_reply(ctx)
    assert canned is not None
    assert "فصل" in canned
    assert "نتونستم" not in canned
    assert "«این کتاب»" not in canned

    # Generic miss without a book must NOT produce the canned «این کتاب» reply.
    miss = TextbookContext(
        matched=False,
        failure_reason="lesson_missing",
        page_query_failed=True,
    )
    assert compose_textbook_failure_reply(miss) is None


def test_page_followup_keeps_math_after_fusul_ask() -> None:
    messages = [
        ChatMessage(role="user", content="فصول ریاضی پنجم چیه ؟"),
        ChatMessage(role="assistant", content="این‌ها فصل‌های ریاضی پنجم هستن."),
        ChatMessage(role="user", content="صفحه ۱۵ کتاب رو توضیح میدی؟"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 5
    assert scope.subject_id == "math"
    assert scope.page == 15

    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    resp = retrieve_context(
        RetrieveRequest(
            grade=scope.grade,
            subject=scope.subject_id,
            page=scope.page,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.page == 15
