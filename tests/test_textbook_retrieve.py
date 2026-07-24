"""Textbook retrieve: page bounds, canonical titles, lesson span (mocked index)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from api.core.generation import build_system_prompt, format_page_out_of_range_instruction
from api.core.types import TextbookContext
from api.textbook.app.models import RetrieveRequest
from api.textbook.app.parser import parse_persian_query
from api.textbook.app.retrieve_service import retrieve_context
from api.textbook.app.store import PageRecord
from api.textbook.app.subjects import (
    BOOK_SUBJECT_SYNONYMS,
    SUBJECT_TITLES,
    canonical_subject_title,
)


def _page(
    *,
    grade: int = 3,
    subject: str = "gifts",
    printed_page: int = 10,
    text: str = "متن نمونه درس",
    title: str | None = None,
) -> PageRecord:
    return PageRecord(
        grade=grade,
        subject=subject,
        subject_title=title or SUBJECT_TITLES.get(subject, subject),
        printed_page=printed_page,
        text=text,
        image_path=None,
        is_scanned=False,
        text_usable=True,
    )


def test_canonical_gifts_title_and_misspelling_synonyms() -> None:
    assert SUBJECT_TITLES["gifts"] == "هدیه های آسمان"
    assert canonical_subject_title("gifts") == "هدیه های آسمان"
    for alias in (
        "هدیه های آسمان",
        "هدیه‌های آسمان",
        "هدایای آسمان",
        "هدیههای آسمان",
        "هدیه",
    ):
        assert BOOK_SUBJECT_SYNONYMS[alias] == "gifts"


@pytest.mark.parametrize(
    "query",
    [
        "صفحه ۱۰ هدیه های آسمان پایه سوم",
        "صفحه ۱۰ هدایای آسمان پایه سوم",
        "صفحه ۱۰ هدیه‌های آسمان پایه سوم",
    ],
)
def test_parser_resolves_gifts_aliases(query: str) -> None:
    parsed = parse_persian_query(query)
    assert parsed.subject == "gifts"
    assert parsed.page == 10
    assert parsed.grade == 3


def test_page_out_of_range_for_gifts() -> None:
    """Page 251 must fail with bounds from printed_page — no reindex needed."""
    with (
        patch("api.textbook.app.retrieve_service.get_printed_page_bounds", return_value=(1, 120)),
        patch("api.textbook.app.retrieve_service.get_page") as get_page_mock,
    ):
        response = retrieve_context(
            RetrieveRequest(query="صفحه ۲۵۱ هدیه های آسمان پایه سوم", include_image="never")
        )
        get_page_mock.assert_not_called()

    assert response.matched is False
    assert response.failure_reason == "page_out_of_range"
    assert response.page == 251
    assert response.max_page == 120
    assert response.min_page == 1
    assert response.subject == "gifts"
    assert response.subject_title == "هدیه های آسمان"


def test_page_out_of_range_without_grade_uses_subject_bounds() -> None:
    with patch(
        "api.textbook.app.retrieve_service.get_printed_page_bounds",
        return_value=(1, 118),
    ) as bounds_mock:
        response = retrieve_context(
            RetrieveRequest(query="صفحه ۲۵۱ هدیه های آسمان", include_image="never")
        )
        bounds_mock.assert_called()
        # First call should be subject-wide (grade=None).
        assert bounds_mock.call_args_list[0].args[0] is None
        assert bounds_mock.call_args_list[0].args[1] == "gifts"

    assert response.matched is False
    assert response.failure_reason == "page_out_of_range"
    assert response.max_page == 118
    assert response.subject_title == "هدیه های آسمان"


def test_page_missing_inside_range_is_not_out_of_range() -> None:
    with (
        patch("api.textbook.app.retrieve_service.get_printed_page_bounds", return_value=(1, 120)),
        patch("api.textbook.app.retrieve_service.get_page", return_value=None),
    ):
        response = retrieve_context(
            RetrieveRequest(query="صفحه ۵۵ هدیه های آسمان پایه سوم", include_image="never")
        )

    assert response.matched is False
    assert response.failure_reason == "page_missing"
    assert response.max_page == 120
    assert response.subject_title == "هدیه های آسمان"


def test_exact_page_expands_to_lesson_span() -> None:
    center = _page(grade=4, subject="persian", printed_page=33, text="شروع درس")
    lesson_pages = [
        _page(grade=4, subject="persian", printed_page=33, text="صفحه اول درس"),
        _page(grade=4, subject="persian", printed_page=34, text="صفحه دوم درس"),
        _page(grade=4, subject="persian", printed_page=35, text="صفحه سوم درس"),
    ]
    with (
        patch("api.textbook.app.retrieve_service.get_printed_page_bounds", return_value=(1, 150)),
        patch("api.textbook.app.retrieve_service.get_page", return_value=center),
        patch(
            "api.textbook.app.retrieve_service.get_lesson_pages",
            return_value=(lesson_pages, 3, 33, 35),
        ),
    ):
        response = retrieve_context(
            RetrieveRequest(query="صفحه ۳۳ فارسی پایه چهارم", include_image="never")
        )

    assert response.matched is True
    assert response.match_type == "lesson_span"
    assert response.page == 33
    assert response.subject_title == "فارسی"
    assert response.context_text is not None
    assert "صفحه اول درس" in response.context_text
    assert "صفحه سوم درس" in response.context_text
    assert response.detected_topic_label is not None
    assert "درس 3" in response.detected_topic_label
    assert "33" in response.detected_topic_label and "35" in response.detected_topic_label


def test_lesson_number_returns_full_span() -> None:
    lesson_pages = [
        _page(grade=4, subject="math", printed_page=40, text="ریاضی درس سوم الف"),
        _page(grade=4, subject="math", printed_page=41, text="ریاضی درس سوم ب"),
    ]
    with patch(
        "api.textbook.app.retrieve_service.get_lesson_pages",
        return_value=(lesson_pages, 3, 40, 41),
    ):
        response = retrieve_context(
            RetrieveRequest(query="درس سوم ریاضی پایه چهارم", include_image="never")
        )

    assert response.matched is True
    assert response.match_type == "lesson_span"
    assert response.subject == "math"
    assert response.subject_title == "ریاضی"
    assert response.context_text is not None
    assert "ریاضی درس سوم الف" in response.context_text
    assert "ریاضی درس سوم ب" in response.context_text


def test_extract_lesson_si_o_yekom() -> None:
    from api.core.textbook import _extract_lesson_number

    assert _extract_lesson_number("درس سی و یکم") == 31
    assert _extract_lesson_number("درس سی‌ویکم چی") == 31


def test_book_unavailable_for_technology_grade_four() -> None:
    """کار و فناوری is not offered in grade 4 — do not fall back to another book."""
    with (
        patch(
            "api.textbook.app.retrieve_service.book_exists_for_grade",
            return_value=False,
        ),
        patch(
            "api.textbook.app.retrieve_service.grades_for_subject",
            return_value=[6],
        ),
        patch("api.textbook.app.retrieve_service.topic_search") as topic_mock,
        patch("api.textbook.app.retrieve_service.get_page") as page_mock,
    ):
        response = retrieve_context(
            RetrieveRequest(
                query="تمرین کتاب کار و فناوری کلاس چهارم",
                include_image="never",
            )
        )
        topic_mock.assert_not_called()
        page_mock.assert_not_called()

    assert response.matched is False
    assert response.failure_reason == "book_unavailable"
    assert response.subject == "technology"
    assert response.grade == 4
    assert response.available_grades == [6]
    assert response.subject_title == "کار و فناوری"

    ctx = TextbookContext(
        matched=False,
        failure_reason="book_unavailable",
        subject="technology",
        subject_title="کار و فناوری",
        grade=4,
        available_grades=[6],
        page_query_failed=True,
    )
    from api.core.generation import format_book_unavailable_instruction

    note = format_book_unavailable_instruction(ctx)
    assert "کار و فناوری" in note
    assert "4" in note
    assert "6" in note
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "کتاب: کار و فناوری" in prompt
    assert "پایهٔ درخواستی: 4" in prompt
    assert "متن کتاب ریاضی" not in prompt


def test_out_of_range_instruction_uses_canonical_title() -> None:
    ctx = TextbookContext(
        matched=False,
        page_out_of_range=True,
        failure_reason="page_out_of_range",
        subject="gifts",
        subject_title="هدیه های آسمان",
        page=251,
        min_page=1,
        max_page=120,
        grade=3,
    )
    note = format_page_out_of_range_instruction(ctx)
    assert "هدیه های آسمان" in note
    assert "هدایای آسمان" in note  # as forbidden example in instruction
    assert "251" in note or "۲۵۱" in note or "صفحهٔ درخواستی: 251" in note
    assert "120" in note

    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "هدیه های آسمان" in prompt
    assert "خارج از محدوده" in prompt or "وجود ندارد" in prompt


def test_lesson_out_of_range_when_beyond_book_lesson_count() -> None:
    with (
        patch(
            "api.textbook.app.retrieve_service.get_lesson_bounds",
            return_value=(1, 17),
        ),
        patch("api.textbook.app.retrieve_service.get_lesson_pages") as pages_mock,
        patch("api.textbook.app.retrieve_service.lesson_search") as search_mock,
    ):
        response = retrieve_context(
            RetrieveRequest(
                query="",
                grade=4,
                subject="persian",
                lesson=31,
                include_image="never",
            )
        )
        pages_mock.assert_not_called()
        search_mock.assert_not_called()

    assert response.matched is False
    assert response.failure_reason == "lesson_out_of_range"
    assert response.lesson == 31
    assert response.min_lesson == 1
    assert response.max_lesson == 17
    assert response.subject_title == "فارسی"


def test_get_lesson_bounds_ignores_sparse_ocr_map() -> None:
    """Single/stray chapter hits must not drive lesson_out_of_range."""
    from api.textbook.app import store as store_mod

    with patch.object(store_mod, "list_lesson_starts", return_value=[(7, 90)]):
        assert store_mod.get_lesson_bounds(4, "math") is None

    with patch.object(
        store_mod, "list_lesson_starts", return_value=[(2, 10), (3, 20), (4, 30)]
    ):
        # Missing درس ۱ → incomplete map
        assert store_mod.get_lesson_bounds(3, "math") is None

    with patch.object(
        store_mod,
        "list_lesson_starts",
        return_value=[(1, 5), (2, 15), (3, 25), (4, 40), (5, 55)],
    ):
        assert store_mod.get_lesson_bounds(4, "persian") == (1, 5)


def test_sparse_lesson_map_yields_lesson_missing_not_oor() -> None:
    with (
        patch(
            "api.textbook.app.retrieve_service.get_lesson_bounds",
            return_value=None,
        ),
        patch(
            "api.textbook.app.retrieve_service.get_lesson_pages",
            return_value=([], None, None, None),
        ),
        patch(
            "api.textbook.app.retrieve_service.lesson_search",
            return_value=None,
        ),
    ):
        response = retrieve_context(
            RetrieveRequest(
                query="",
                grade=4,
                subject="math",
                lesson=3,
                include_image="never",
            )
        )

    assert response.matched is False
    assert response.failure_reason == "lesson_missing"
    assert response.max_lesson is None


def test_lesson_out_of_range_system_prompt_mentions_max() -> None:
    from api.core.generation import format_lesson_out_of_range_instruction

    ctx = TextbookContext(
        matched=False,
        failure_reason="lesson_out_of_range",
        subject="persian",
        subject_title="فارسی",
        grade=4,
        lesson=31,
        min_lesson=1,
        max_lesson=17,
        page_query_failed=True,
    )
    note = format_lesson_out_of_range_instruction(ctx)
    assert "فارسی" in note
    assert "31" in note
    assert "17" in note
    assert "تا درس/فصل 17" in note or "تا درس ۱۷" in note or "17 دارد" in note
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "وجود ندارد" in prompt or "خارج از محدوده" in prompt
    assert "صفحهٔ همان درس ناموجود" in note or "درس ناموجود" in note
