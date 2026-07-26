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


def test_exact_page_stays_exact_not_full_lesson_span() -> None:
    """Page asks must not dump a whole (often wrong) lesson span into context."""
    center = _page(grade=4, subject="persian", printed_page=34, text="روباه و زاغ")
    neighbor = _page(grade=4, subject="persian", printed_page=35, text="ادامه")
    lesson_pages = [
        _page(grade=4, subject="persian", printed_page=30, text="درس سوم"),
        center,
        _page(grade=4, subject="persian", printed_page=36, text="ارزش علم — نباید به صفحه ۳۴ بچسبد"),
    ]
    with (
        patch("api.textbook.app.retrieve_service.get_printed_page_bounds", return_value=(1, 150)),
        patch("api.textbook.app.retrieve_service.get_page", return_value=center),
        patch(
            "api.textbook.app.retrieve_service.get_neighbor_pages",
            return_value=[center, neighbor],
        ),
        patch(
            "api.textbook.app.retrieve_service.get_lesson_pages",
            return_value=(lesson_pages, 3, 30, 43),
        ),
        patch(
            "api.textbook.app.retrieve_service.find_lesson_containing_page",
            return_value=(3, 30, 43),
        ),
    ):
        response = retrieve_context(
            RetrieveRequest(query="صفحه ۳۴ فارسی پایه چهارم", include_image="never")
        )

    assert response.matched is True
    assert response.match_type == "exact_page"
    assert response.page == 34
    assert response.context_text is not None
    assert "روباه و زاغ" in response.context_text
    assert "ارزش علم — نباید به صفحه ۳۴ بچسبد" not in response.context_text
    assert "صفحه 34" in response.context_text or "۳۴" in (response.context_text or "")


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

    assert response.matched is False
    assert response.failure_reason == "lesson_out_of_range"
    assert response.lesson == 31
    assert response.min_lesson == 1
    assert response.max_lesson == 17
    assert response.subject_title == "فارسی"


def test_get_lesson_bounds_uses_catalog_kind_namespaces() -> None:
    """مهارت and درس share numbers but stay in separate kind namespaces."""
    from api.textbook.app.store import (
        CatalogBook,
        CatalogLesson,
        get_lesson_bounds,
        lookup_catalog_start_page,
    )

    book = CatalogBook(
        file="C617.pdf",
        grade=6,
        subject="technology",
        title="کار و فناوری",
        parent_label="بخش",
        lessons=[
            CatalogLesson(number=3, start_page=40, kind="lesson", chapter=1),
            CatalogLesson(number=3, start_page=106, kind="skill", chapter=3),
        ],
    )
    with patch(
        "api.textbook.app.store.get_catalog_book",
        lambda grade, subject: book if grade == 6 and subject == "technology" else None,
    ):
        assert get_lesson_bounds(6, "technology", kind="lesson") == (3, 3)
        assert get_lesson_bounds(6, "technology", kind="skill") == (3, 3)
        assert lookup_catalog_start_page(6, "technology", lesson=3, kind="lesson") == 40
        assert lookup_catalog_start_page(6, "technology", lesson=3, kind="skill") == 106


def test_missing_catalog_unit_yields_lesson_missing_not_oor() -> None:
    with (
        patch(
            "api.textbook.app.retrieve_service.get_lesson_bounds",
            return_value=None,
        ),
        patch(
            "api.textbook.app.retrieve_service.get_lesson_pages",
            return_value=([], None, None, None),
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


def test_book_unavailable_system_prompt_mentions_available_grades() -> None:
    from api.core.generation import (
        compose_textbook_failure_reply,
        format_book_unavailable_instruction,
    )

    ctx = TextbookContext(
        matched=False,
        failure_reason="book_unavailable",
        subject="technology",
        subject_title="کار و فناوری",
        grade=4,
        available_grades=[6],
        page_query_failed=False,
    )
    note = format_book_unavailable_instruction(ctx)
    assert "کار و فناوری" in note
    assert "4" in note
    assert "6" in note
    canned = compose_textbook_failure_reply(ctx)
    assert canned is not None
    assert "کار و فناوری" in canned
    assert "4" in canned
    assert "6" in canned
    assert "عکس صفحه ۱۰" not in canned
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "برای پایه 4 نیست" in prompt or "پایهٔ درخواستی: 4" in prompt


def test_page_missing_gets_canned_honest_reply() -> None:
    from api.core.generation import compose_textbook_failure_reply

    ctx = TextbookContext(
        matched=False,
        failure_reason="page_missing",
        subject="persian",
        subject_title="فارسی",
        grade=4,
        page=40,
        page_query_failed=True,
    )
    canned = compose_textbook_failure_reply(ctx)
    assert canned is not None
    assert "۴۰" in canned or "40" in canned
    assert "فارسی" in canned
    assert "باز می‌کنم" not in canned
    assert "عکس" in canned or "متن" in canned


def test_matched_textbook_prompt_demands_immediate_help() -> None:
    ctx = TextbookContext(
        matched=True,
        subject="persian",
        subject_title="فارسی",
        grade=4,
        page=40,
        context_text="متن نمونه درک مطلب صفحه ۴۰",
        text_usable=True,
        needs_image=True,
        image_base64="fakeimg",
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "متن نمونه درک مطلب" in prompt
    assert "دستور کار فوری" in prompt
    assert "تصویر" in prompt
    assert "متن را خواندی" in prompt or "خوندی" in prompt or "مرور" in prompt
    assert "صفحه را باز می‌کنم" in prompt or "باز می‌کنم" in prompt


def test_matched_without_image_asks_for_photo() -> None:
    ctx = TextbookContext(
        matched=True,
        subject="persian",
        subject_title="فارسی",
        grade=4,
        page=40,
        context_text="متن OCR مشکوک",
        text_usable=True,
        needs_image=True,
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "عکس" in prompt
    assert "دستور کار فوری" not in prompt


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
    assert "صفحهٔ همان واحد ناموجود" in note or "واحد ناموجود" in note or "درس ناموجود" in note


def test_catalog_map_parses_persian_digits_and_titles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.textbook.app.store import (
        CatalogBook,
        CatalogChapter,
        CatalogLesson,
        _parse_catalog_chapters,
        _parse_catalog_lessons,
        lookup_catalog_by_title,
        lookup_catalog_start_page,
    )

    chapters = _parse_catalog_chapters(
        [{"number": "۴", "title": "فرهنگ بومی", "start_page": "۷۳"}]
    )
    lessons = _parse_catalog_lessons(
        [
            {
                "number": 4,
                "title": "ارزش علم",
                "start_page": 36,
                "chapter": 2,
            }
        ]
    )
    assert chapters == [CatalogChapter(number=4, start_page=73, title="فرهنگ بومی")]
    assert lessons == [
        CatalogLesson(number=4, start_page=36, title="ارزش علم", chapter=2)
    ]

    book = CatalogBook(
        file="C403.pdf",
        grade=4,
        subject="persian",
        title="فارسی پایه چهارم",
        chapters=chapters,
        lessons=lessons,
    )
    monkeypatch.setattr(
        "api.textbook.app.store.get_catalog_book",
        lambda grade, subject: book if grade == 4 and subject == "persian" else None,
    )
    assert lookup_catalog_start_page(4, "persian", chapter=4) == 73
    assert lookup_catalog_start_page(4, "persian", lesson=4) == 36
    assert lookup_catalog_by_title(4, "persian", "ارزش علم") == 36


def test_catalog_resolve_and_retrieve_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.textbook.app.store import CatalogBook, CatalogChapter, CatalogLesson

    book = CatalogBook(
        file="C403.pdf",
        grade=4,
        subject="persian",
        title="فارسی پایه چهارم",
        chapters=[CatalogChapter(number=4, start_page=73, title="فرهنگ بومی")],
        lessons=[
            CatalogLesson(number=4, start_page=36, title="ارزش علم", chapter=2)
        ],
    )
    monkeypatch.setattr(
        "api.textbook.app.store.get_catalog_book",
        lambda grade, subject: book if grade == 4 and subject == "persian" else None,
    )

    from api.textbook.app.store import lookup_catalog_start_page

    assert lookup_catalog_start_page(4, "persian", chapter=4) == 73
    assert lookup_catalog_start_page(4, "persian", lesson=4) == 36

    page36 = _page(
        grade=4,
        subject="persian",
        printed_page=36,
        text="ارزش علم — متن درس چهارم",
        title="فارسی",
    )
    page73 = _page(
        grade=4,
        subject="persian",
        printed_page=73,
        text="فصل چهارم فرهنگ بومی",
        title="فارسی",
    )
    page74 = _page(
        grade=4,
        subject="persian",
        printed_page=74,
        text="ادامه فصل چهارم",
        title="فارسی",
    )

    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.book_exists_for_grade", lambda g, s: True
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_chapter_pages",
        lambda grade, subject, chapter_number, max_pages=40: (
            [page73, page74],
            4,
            73,
            74,
        ),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.format_catalog_outline",
        lambda grade, subject, chapter=None: "بخش فهرست آزمایشی",
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_lesson_bounds",
        lambda *a, **k: (1, 10),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_lesson_pages",
        lambda grade, subject, lesson_number=None, page=None, kind=None, max_pages=40: (
            [page36],
            4,
            36,
            36,
        ),
    )

    chapter_resp = retrieve_context(
        RetrieveRequest(grade=4, subject="persian", chapter=4, include_image="never")
    )
    assert chapter_resp.matched is True
    assert chapter_resp.page == 73
    assert chapter_resp.chapter == 4
    assert chapter_resp.match_type == "lesson_span"
    assert "فهرست" in (chapter_resp.context_text or "")

    lesson_resp = retrieve_context(
        RetrieveRequest(grade=4, subject="persian", lesson=4, include_image="never")
    )
    assert lesson_resp.matched is True
    assert lesson_resp.page == 36
    assert lesson_resp.lesson == 4
    assert lesson_resp.match_type == "lesson_span"


def test_catalog_outline_and_skill_not_lesson(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.textbook.app.store import CatalogBook, CatalogChapter, CatalogLesson

    book = CatalogBook(
        file="C617.pdf",
        grade=6,
        subject="technology",
        title="کار و فناوری",
        parent_label="بخش",
        chapters=[CatalogChapter(number=3, start_page=101, title="مهارت‌ها")],
        lessons=[
            CatalogLesson(number=3, start_page=40, kind="lesson", title="درس سه", chapter=1),
            CatalogLesson(
                number=3, start_page=106, kind="skill", title="گل‌سازی", chapter=3
            ),
        ],
    )
    monkeypatch.setattr(
        "api.textbook.app.store.get_catalog_book",
        lambda grade, subject: book if grade == 6 and subject == "technology" else None,
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.book_exists_for_grade",
        lambda g, s: True,
    )
    skill_page = _page(
        grade=6,
        subject="technology",
        printed_page=106,
        text="مهارت ۳ گل‌سازی",
        title="کار و فناوری",
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_lesson_bounds",
        lambda grade, subject, kind=None: (1, 13) if kind == "skill" else (1, 5),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_lesson_pages",
        lambda grade, subject, lesson_number=None, page=None, kind=None, max_pages=40: (
            ([skill_page], 3, 106, 106)
            if kind == "skill" and lesson_number == 3
            else ([], None, None, None)
        ),
    )

    outline = retrieve_context(
        RetrieveRequest(
            grade=6,
            subject="technology",
            wants_outline=True,
            include_image="never",
        )
    )
    assert outline.matched is True
    assert outline.match_type == "catalog_outline"
    assert "بخش" in (outline.context_text or "")
    assert "مهارت 3" in (outline.context_text or "") or "مهارت ۳" in (
        outline.context_text or ""
    )

    skill = retrieve_context(
        RetrieveRequest(
            grade=6,
            subject="technology",
            lesson=3,
            kind="skill",
            include_image="never",
        )
    )
    assert skill.matched is True
    assert skill.page == 106
    assert "مهارت" in (skill.detected_topic_label or "")


def test_retrieve_by_lesson_title_via_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Named title in query should open the lesson page, not chapter start."""
    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context
    from api.textbook.app.store import CatalogBook, CatalogChapter, CatalogLesson

    book = CatalogBook(
        file="C603.pdf",
        grade=6,
        subject="persian",
        title="فارسی پایه ششم",
        chapters=[CatalogChapter(number=3, start_page=40, title="فصل سه")],
        lessons=[
            CatalogLesson(number=5, start_page=52, title="ارزش علم", chapter=3)
        ],
    )
    monkeypatch.setattr(
        "api.textbook.app.store.get_catalog_book",
        lambda grade, subject: book if grade == 6 and subject == "persian" else None,
    )
    page52 = _page(
        grade=6,
        subject="persian",
        printed_page=52,
        text="ارزش علم — متن درس برای توضیح",
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_page",
        lambda grade, subject, printed_page: (
            page52 if printed_page == 52 else None
        ),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_neighbor_pages",
        lambda *a, **k: [],
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.book_exists_for_grade",
        lambda grade, subject: True,
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service._resolve_page_bounds",
        lambda *a, **k: (1, 200),
    )

    resp = retrieve_context(
        RetrieveRequest(
            query="ارزش علم",
            grade=6,
            subject="persian",
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.page == 52
    assert "ارزش علم" in (resp.context_text or "")


def test_agent_page_and_catalog_flows_side_by_side(monkeypatch: pytest.MonkeyPatch) -> None:
    """Page path stays exact; catalog intents use span/outline — as chat service wires them."""
    from api.core.textbook import resolve_textbook_scope
    from api.core.types import ChatMessage

    page34 = _page(grade=4, subject="persian", printed_page=34, text="روباه و زاغ")
    skill106 = _page(
        grade=6, subject="technology", printed_page=106, text="مهارت گل‌سازی"
    )

    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.book_exists_for_grade",
        lambda g, s: True,
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service._resolve_page_bounds",
        lambda *a, **k: (1, 200),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_page",
        lambda g, s, p: page34 if (g, s, p) == (4, "persian", 34) else None,
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_neighbor_pages",
        lambda *a, **k: [page34],
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.find_lesson_containing_page",
        lambda *a, **k: (3, 30, 40),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_lesson_pages",
        lambda grade, subject, lesson_number=None, page=None, kind=None, max_pages=40: (
            ([skill106], 3, 106, 106)
            if kind == "skill" and lesson_number == 3
            else (
                (
                    [
                        _page(grade=4, subject="persian", printed_page=30, text="کل درس"),
                        page34,
                    ],
                    3,
                    30,
                    40,
                )
                if page == 34
                else ([], None, None, None)
            )
        ),
    )
    monkeypatch.setattr(
        "api.textbook.app.retrieve_service.get_lesson_bounds",
        lambda grade, subject, kind=None: (1, 13) if kind == "skill" else (1, 17),
    )

    # 1) Explicit page → exact_page even if a lesson span exists around it.
    page_scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="صفحه ۳۴ فارسی پایه چهارم")]
    )
    page_resp = retrieve_context(
        RetrieveRequest(
            query="",
            grade=page_scope.grade,
            subject=page_scope.subject_id,
            page=page_scope.page,
            # Service drops lesson when page is known:
            lesson=page_scope.lesson if page_scope.page is None else None,
            chapter=page_scope.chapter if page_scope.page is None else None,
            kind=page_scope.kind if page_scope.page is None else None,
            wants_outline=page_scope.wants_outline,
            include_image="never",
        )
    )
    assert page_resp.matched is True
    assert page_resp.match_type == "exact_page"
    assert page_resp.page == 34
    assert "روباه و زاغ" in (page_resp.context_text or "")
    assert "کل درس" not in (page_resp.context_text or "")

    # 2) Skill intent → catalog span on skill page, not lesson 3.
    skill_scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="مهارت ۳ کار و فناوری ششم")]
    )
    skill_resp = retrieve_context(
        RetrieveRequest(
            query="",
            grade=skill_scope.grade,
            subject=skill_scope.subject_id,
            page=skill_scope.page,
            lesson=skill_scope.lesson,
            kind=skill_scope.kind,
            include_image="never",
        )
    )
    assert skill_resp.matched is True
    assert skill_resp.match_type == "lesson_span"
    assert skill_resp.page == 106
    assert "مهارت" in (skill_resp.detected_topic_label or "")

    # 3) Outline intent → structure only.
    outline_scope = resolve_textbook_scope(
        [ChatMessage(role="user", content="لیست فصل‌های فارسی چهارم")]
    )
    monkeypatch.setattr(
        "api.textbook.app.store.get_catalog_book",
        lambda grade, subject: __import__(
            "api.textbook.app.store", fromlist=["CatalogBook", "CatalogChapter"]
        ).CatalogBook(
            file="C403.pdf",
            grade=4,
            subject="persian",
            title="فارسی پایه چهارم",
            chapters=[
                __import__(
                    "api.textbook.app.store", fromlist=["CatalogChapter"]
                ).CatalogChapter(number=1, start_page=5, title="آفرینش"),
                __import__(
                    "api.textbook.app.store", fromlist=["CatalogChapter"]
                ).CatalogChapter(number=2, start_page=20, title="دانایی"),
            ],
        )
        if grade == 4 and subject == "persian"
        else None,
    )
    outline_resp = retrieve_context(
        RetrieveRequest(
            query="",
            grade=outline_scope.grade,
            subject=outline_scope.subject_id,
            wants_outline=outline_scope.wants_outline,
            include_image="never",
        )
    )
    assert outline_resp.matched is True
    assert outline_resp.match_type == "catalog_outline"
    assert "فصل" in (outline_resp.context_text or "")


def test_chapter_out_of_range_reports_max_chapter_and_lessons() -> None:
    """«فصل ۳۰» when book has 6–7 chapters must not silently become lesson_missing."""
    response = retrieve_context(
        RetrieveRequest(
            query="",
            grade=5,
            subject="persian",
            chapter=30,
            include_image="never",
        )
    )
    assert response.matched is False
    assert response.failure_reason == "chapter_out_of_range"
    assert response.chapter == 30
    assert response.max_chapter == 6
    assert response.max_lesson == 17

    from api.core.generation import (
        compose_textbook_failure_reply,
        format_chapter_out_of_range_instruction,
    )
    from api.core.types import TextbookContext

    ctx = TextbookContext(
        matched=False,
        failure_reason="chapter_out_of_range",
        subject="persian",
        subject_title="فارسی",
        grade=5,
        chapter=30,
        max_chapter=6,
        max_lesson=17,
        page_query_failed=True,
    )
    note = format_chapter_out_of_range_instruction(ctx)
    assert "30" in note or "فصل" in note
    assert "6" in note
    assert "17" in note
    canned = compose_textbook_failure_reply(ctx)
    assert canned is not None
    assert "فصل" in canned
    assert "6" in canned
    assert "17" in canned


def test_named_lesson_title_expands_to_lesson_span() -> None:
    """«ارزش علم» must open the full درس span, not just the start page."""
    response = retrieve_context(
        RetrieveRequest(
            query="تمرین های درس ارزش علم فارسی پایه چهارم",
            grade=4,
            subject="persian",
            include_image="never",
        )
    )
    assert response.matched is True
    assert response.match_type == "lesson_span"
    assert response.lesson == 4
    assert response.page == 36
    assert "صفحات" in (response.context_text or "") or "درس 4" in (
        response.context_text or ""
    )


def test_glued_named_title_matches_catalog() -> None:
    from api.textbook.app.store import lookup_catalog_by_title, lookup_catalog_entry_by_title

    assert lookup_catalog_by_title(4, "persian", "ارزشعلم") == 36
    hit = lookup_catalog_entry_by_title(4, "persian", "ارزش علم")
    assert hit is not None
    assert hit.unit == "lesson"
    assert hit.number == 4
    assert hit.start_page == 36


def test_catalog_outline_includes_page_ranges() -> None:
    response = retrieve_context(
        RetrieveRequest(
            grade=4,
            subject="persian",
            wants_outline=True,
            include_image="never",
        )
    )
    assert response.matched is True
    assert response.match_type == "catalog_outline"
    text = response.context_text or ""
    assert "۱۷" in text or "17" in text or "واحد" in text
    assert "صفحات" in text or "صفحه" in text
    assert "ارزش علم" in text


def test_disk_page_bounds_without_index() -> None:
    """When SQLite is absent, printed-page bounds come from on-disk PNGs."""
    from api.textbook.app.store import get_printed_page_bounds

    bounds = get_printed_page_bounds(4, "persian")
    assert bounds is not None
    min_p, max_p = bounds
    assert min_p >= 1
    assert max_p >= 100


def test_page_lookup_works_with_images_only() -> None:
    response = retrieve_context(
        RetrieveRequest(
            grade=4,
            subject="persian",
            page=36,
            include_image="never",
        )
    )
    assert response.matched is True
    assert response.match_type == "exact_page"
    assert response.page == 36


def test_lesson_exercises_by_number_returns_span() -> None:
    response = retrieve_context(
        RetrieveRequest(
            query="بریم سراغ حل تمرین های درس ۵ فارسی پایه ششم",
            grade=6,
            subject="persian",
            lesson=5,
            include_image="never",
        )
    )
    assert response.matched is True
    assert response.match_type == "lesson_span"
    assert response.lesson == 5
    assert response.page == 37  # هفت خان رستم


def test_chapter_si_am_parses_as_30() -> None:
    from api.textbook.app.parser import parse_persian_query

    parsed = parse_persian_query("فصل سی ام فارسی پایه پنجم")
    assert parsed.chapter == 30
    assert parsed.grade == 5
    assert parsed.subject == "persian"
