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
