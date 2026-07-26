"""End-to-end coverage: user textbook prompts vs live catalog.json.

Keeps iterating intents the agent must answer from catalog maps + page images:
list chapters/lessons, lesson/chapter by number or title, page lookup, OOR.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from api.core.generation import (
    compose_textbook_failure_reply,
    compose_textbook_outline_reply,
)
from api.core.textbook import resolve_textbook_scope
from api.core.types import ChatMessage, TextbookContext
from api.textbook.app.models import RetrieveRequest
from api.textbook.app.retrieve_service import retrieve_context
from api.textbook.app.store import (
    get_catalog_book,
    lookup_catalog_entry_by_title,
    lookup_catalog_start_page,
)

CATALOG_PATH = Path(__file__).resolve().parents[1] / "api" / "textbook" / "data" / "catalog.json"
PAGES_DIR = Path(__file__).resolve().parents[1] / "api" / "textbook" / "data" / "pages"

GRADE_WORDS = {3: "سوم", 4: "چهارم", 5: "پنجم", 6: "ششم"}
SUBJECT_WORDS = {
    "math": "ریاضی",
    "science": "علوم",
    "persian": "فارسی",
    "writing": "نگارش",
    "social": "مطالعات اجتماعی",
    "quran": "قرآن",
    "gifts": "هدیه های آسمان",
    "thinking": "تفکر",
    "technology": "کار و فناوری",
}


def _load_books() -> list[dict]:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return list(raw.get("books") or [])


def _page_image_exists(grade: int, subject: str, page: int) -> bool:
    return (PAGES_DIR / f"g{grade}_{subject}_p{page}.png").is_file()


def _ask(text: str):
    scope = resolve_textbook_scope([ChatMessage(role="user", content=text)])
    # Only skip chapter when the child named a real lesson title — not book
    # fragments left in topic_query (e.g. leftover «آسمان» from هدیه های آسمان).
    prefer_named = bool(scope.topic_query and scope.topic_query.strip()) and (
        scope.chapter is None or len(scope.topic_query.split()) >= 2
    )
    resp = retrieve_context(
        RetrieveRequest(
            query=scope.topic_query or text,
            grade=scope.grade,
            subject=scope.subject_id,
            page=scope.page,
            lesson=scope.lesson if scope.page is None else None,
            chapter=scope.chapter if scope.page is None and not prefer_named else None,
            kind=scope.kind if scope.page is None else None,
            wants_outline=scope.wants_outline,
            include_image="never",
        )
    )
    return scope, resp


@pytest.fixture(scope="module")
def books() -> list[dict]:
    return _load_books()


# ---------------------------------------------------------------------------
# 1) List lessons / chapters for every catalog book
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt_tmpl",
    [
        "لیست درس‌های {subject} پایه {grade} رو بده",
        "فصول {subject} {grade_word} چیه؟",
        "فهرست مطالب کتاب {subject} {grade_word}",
    ],
)
def test_outline_prompts_match_catalog(books: list[dict], prompt_tmpl: str) -> None:
    # Representative books across naming schemes
    samples = [
        next(b for b in books if b["subject"] == "persian" and b["grade"] == 4),
        next(b for b in books if b["subject"] == "math" and b["grade"] == 5),
        next(b for b in books if b["subject"] == "technology" and b["grade"] == 6),
        next(b for b in books if b["subject"] == "gifts" and b["grade"] == 3),
        next(b for b in books if b["subject"] == "quran" and b["grade"] == 3),
    ]
    for book in samples:
        grade = int(book["grade"])
        subject = book["subject"]
        prompt = prompt_tmpl.format(
            subject=SUBJECT_WORDS[subject],
            grade=grade,
            grade_word=GRADE_WORDS[grade],
        )
        scope, resp = _ask(prompt)
        assert scope.grade == grade, prompt
        assert scope.subject_id == subject, prompt
        assert scope.wants_outline is True, prompt
        assert resp.matched is True, (prompt, resp.failure_reason)
        assert resp.match_type == "catalog_outline", prompt
        text = resp.context_text or ""
        # Catalog titles must appear in the outline body.
        lessons = book.get("lessons") or []
        titled = [L for L in lessons if L.get("title")]
        assert titled, book["title"]
        assert titled[0]["title"] in text, (prompt, titled[0]["title"])
        canned = compose_textbook_outline_reply(
            TextbookContext(
                matched=True,
                match_type="catalog_outline",
                grade=grade,
                subject=subject,
                subject_title=resp.subject_title,
                context_text=resp.context_text,
            )
        )
        assert canned is not None
        assert "نتونستم" not in canned
        assert "«این کتاب»" not in canned
        assert titled[0]["title"] in canned


def test_every_catalog_book_has_retrievable_outline(books: list[dict]) -> None:
    for book in books:
        grade = int(book["grade"])
        subject = book["subject"]
        resp = retrieve_context(
            RetrieveRequest(
                grade=grade,
                subject=subject,
                wants_outline=True,
                include_image="never",
            )
        )
        assert resp.matched is True, book["title"]
        assert resp.match_type == "catalog_outline", book["title"]
        assert book["title"].split(" پایه")[0] in (resp.context_text or "") or book[
            "title"
        ] in (resp.context_text or "")


# ---------------------------------------------------------------------------
# 2) Lesson by number → span matching catalog start_page
# ---------------------------------------------------------------------------


def test_lesson_number_prompts_open_catalog_span(books: list[dict]) -> None:
    cases = [
        ("persian", 4, 4, "ارزش علم"),
        ("math", 5, 1, None),
        ("persian", 6, 5, "هفت خان رستم"),
        ("technology", 6, 1, None),
    ]
    for subject, grade, lesson, expect_title in cases:
        book = get_catalog_book(grade, subject)
        assert book is not None
        start = lookup_catalog_start_page(grade, subject, lesson=lesson)
        assert start is not None
        prompt = f"بریم سراغ حل تمرین‌های درس {lesson} {SUBJECT_WORDS[subject]} پایه {GRADE_WORDS[grade]}"
        scope, resp = _ask(prompt)
        assert scope.lesson == lesson, prompt
        assert scope.grade == grade
        assert scope.subject_id == subject
        assert resp.matched is True, (prompt, resp.failure_reason)
        assert resp.match_type == "lesson_span"
        assert resp.lesson == lesson
        assert resp.page == start
        if expect_title:
            hit = lookup_catalog_entry_by_title(grade, subject, expect_title)
            assert hit is not None and hit.number == lesson


# ---------------------------------------------------------------------------
# 3) Named lesson title → span
# ---------------------------------------------------------------------------


def test_named_lesson_titles_from_catalog(books: list[dict]) -> None:
    named_cases = [
        (4, "persian", "ارزش علم", 4),
        (6, "persian", "هفت خان رستم", 5),
        (6, "persian", "دریاقلی", 8),
        (3, "gifts", "آستین‌های خالی", 1),
        (4, "persian", "آرش کمان‌گیر", 6),
    ]
    for grade, subject, title, lesson_no in named_cases:
        for prompt in (
            f"درس {title} {SUBJECT_WORDS[subject]} پایه {GRADE_WORDS[grade]}",
            f"بریم سراغ حل تمرین‌های درس {title} کتاب {SUBJECT_WORDS[subject]} {GRADE_WORDS[grade]}",
            f"تمرین درس {title} {SUBJECT_WORDS[subject]} {grade}",
        ):
            scope, resp = _ask(prompt)
            assert scope.grade == grade, prompt
            assert scope.subject_id == subject, prompt
            assert resp.matched is True, (prompt, resp.failure_reason, scope)
            assert resp.match_type in {"lesson_span", "topic_search"}, prompt
            assert resp.lesson == lesson_no, (prompt, resp.lesson, resp.page)
            start = lookup_catalog_start_page(grade, subject, lesson=lesson_no)
            assert resp.page == start, prompt


def test_haft_khan_not_confused_with_lesson_seven() -> None:
    prompt = "بریم سراغ حل تمرین‌های درس هفت خان رستم فارسی ششم"
    scope, resp = _ask(prompt)
    assert scope.lesson is None
    assert scope.topic_query and "هفت خان رستم" in scope.topic_query
    assert resp.matched is True
    assert resp.lesson == 5


# ---------------------------------------------------------------------------
# 4) Chapter by number + chapter by title
# ---------------------------------------------------------------------------


def test_chapter_number_prompts(books: list[dict]) -> None:
    cases = [
        ("persian", 4, 2),
        ("math", 5, 1),
        ("technology", 6, 1),  # بخش
    ]
    for subject, grade, chapter in cases:
        start = lookup_catalog_start_page(grade, subject, chapter=chapter)
        assert start is not None
        label = "بخش" if subject == "technology" else "فصل"
        prompt = f"{label} {chapter} {SUBJECT_WORDS[subject]} پایه {GRADE_WORDS[grade]}"
        scope, resp = _ask(prompt)
        assert scope.chapter == chapter, prompt
        assert resp.matched is True, (prompt, resp.failure_reason)
        assert resp.match_type == "lesson_span"
        assert resp.chapter == chapter
        assert resp.page == start


def test_chapter_title_prompts(books: list[dict]) -> None:
    # فارسی چهارم فصل «دانایی و هوشیاری»
    prompt = "فصل دانایی و هوشیاری فارسی پایه چهارم"
    scope, resp = _ask(prompt)
    assert scope.grade == 4 and scope.subject_id == "persian"
    assert resp.matched is True, (resp.failure_reason, scope)
    # Title may resolve as chapter span or topic→lesson inside chapter
    assert resp.match_type in {"lesson_span", "topic_search", "exact_page"}
    assert resp.page is not None
    book = get_catalog_book(4, "persian")
    assert book is not None
    ch = next(c for c in book.chapters if "دانایی" in c.title)
    assert resp.page >= ch.start_page


# ---------------------------------------------------------------------------
# 5) Exact page prompts
# ---------------------------------------------------------------------------


def test_exact_page_prompts_use_catalog_pages(books: list[dict]) -> None:
    cases = [
        (4, "persian", 36),
        (5, "math", 15),
        (6, "persian", 37),
        (3, "gifts", 8),
    ]
    for grade, subject, page in cases:
        if not _page_image_exists(grade, subject, page):
            pytest.skip(f"missing page image g{grade}_{subject}_p{page}")
        prompt = f"صفحه {page} کتاب {SUBJECT_WORDS[subject]} پایه {GRADE_WORDS[grade]} رو توضیح بده"
        scope, resp = _ask(prompt)
        assert scope.page == page
        assert scope.grade == grade
        assert scope.subject_id == subject
        assert resp.matched is True, (prompt, resp.failure_reason)
        assert resp.match_type == "exact_page"
        assert resp.page == page


def test_page_followup_after_outline_keeps_book() -> None:
    messages = [
        ChatMessage(role="user", content="فصول ریاضی پنجم چیه؟"),
        ChatMessage(role="assistant", content="این فصل‌های ریاضی پنجم هستن."),
        ChatMessage(role="user", content="صفحه ۱۵ کتاب رو توضیح میدی؟"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 5
    assert scope.subject_id == "math"
    assert scope.page == 15
    resp = retrieve_context(
        RetrieveRequest(
            grade=5,
            subject="math",
            page=15,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.page == 15


# ---------------------------------------------------------------------------
# 6) Out-of-range honesty
# ---------------------------------------------------------------------------


def test_oor_lesson_and_chapter_match_catalog_bounds(books: list[dict]) -> None:
    # فارسی پنجم: 6 فصل، 17 درس
    scope, resp = _ask("درس ۳۰ فارسی پایه پنجم")
    assert resp.matched is False
    assert resp.failure_reason == "lesson_out_of_range"
    assert resp.max_lesson == 17
    canned = compose_textbook_failure_reply(
        TextbookContext(
            matched=False,
            failure_reason="lesson_out_of_range",
            subject="persian",
            subject_title="فارسی",
            grade=5,
            lesson=30,
            max_lesson=17,
            max_chapter=6,
        )
    )
    assert canned is not None
    assert "۱۷" in canned or "17" in canned

    scope, resp = _ask("فصل ۳۰ فارسی پایه پنجم")
    assert resp.matched is False
    assert resp.failure_reason == "chapter_out_of_range"
    assert resp.max_chapter == 6
    assert resp.max_lesson == 17


def test_no_fake_een_ketab_canned_without_subject() -> None:
    miss = TextbookContext(
        matched=False,
        failure_reason="lesson_missing",
        page_query_failed=True,
    )
    assert compose_textbook_failure_reply(miss) is None
    miss2 = TextbookContext(
        matched=False,
        failure_reason="need_grade_or_subject",
        page_query_failed=True,
        page=15,
    )
    assert compose_textbook_failure_reply(miss2) is None


# ---------------------------------------------------------------------------
# 7) Multi-turn: list → pick lesson → exercises
# ---------------------------------------------------------------------------


def test_list_then_lesson_five_exercises() -> None:
    messages = [
        ChatMessage(role="user", content="لیست دروس فارسی پایه ششم رو بده"),
        ChatMessage(role="assistant", content="این درس‌های فارسی ششم هستن."),
        ChatMessage(role="user", content="بریم سراغ حل تمرین‌های درس ۵"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.wants_outline is False
    assert scope.grade == 6
    assert scope.subject_id == "persian"
    assert scope.lesson == 5
    resp = retrieve_context(
        RetrieveRequest(
            grade=6,
            subject="persian",
            lesson=5,
            include_image="never",
        )
    )
    assert resp.matched is True
    assert resp.lesson == 5
    assert resp.page == lookup_catalog_start_page(6, "persian", lesson=5)


# ---------------------------------------------------------------------------
# 8) Kind namespaces (قرآن جلسه، فناوری مهارت)
# ---------------------------------------------------------------------------


def test_quran_session_and_technology_skill() -> None:
    scope, resp = _ask("جلسه ۳ قرآن پایه سوم")
    assert scope.kind == "session"
    assert scope.lesson == 3
    assert resp.matched is True
    assert resp.match_type == "lesson_span"

    scope, resp = _ask("مهارت ۳ کار و فناوری پایه ششم")
    assert scope.kind == "skill"
    assert scope.lesson == 3
    assert resp.matched is True
    # skill 3 start is distinct from lesson 3
    skill_start = lookup_catalog_start_page(6, "technology", lesson=3, kind="skill")
    lesson_start = lookup_catalog_start_page(6, "technology", lesson=3, kind="lesson")
    assert skill_start != lesson_start
    assert resp.page == skill_start


# ---------------------------------------------------------------------------
# 9) Catalog title lookup consistency for all titled lessons (sample sweep)
# ---------------------------------------------------------------------------


def test_catalog_title_lookup_roundtrip_sample(books: list[dict]) -> None:
    checked = 0
    for book in books:
        grade = int(book["grade"])
        subject = book["subject"]
        for lesson in book.get("lessons") or []:
            title = (lesson.get("title") or "").strip()
            if not title or len(title) < 3:
                continue
            # Skip very generic free-lesson titles that collide.
            if title in {"درس آزاد", "آزاد"}:
                continue
            hit = lookup_catalog_entry_by_title(grade, subject, title)
            assert hit is not None, (book["title"], title)
            assert hit.start_page == int(lesson["start_page"])
            checked += 1
            if checked >= 40:
                return
    assert checked >= 20


def test_named_title_retrieve_for_all_persian_lessons(books: list[dict]) -> None:
    """Every titled فارسی lesson must open via natural-language title prompt."""
    failures: list[str] = []
    for book in books:
        if book["subject"] != "persian":
            continue
        grade = int(book["grade"])
        for lesson in book.get("lessons") or []:
            title = (lesson.get("title") or "").strip()
            if not title or title == "درس آزاد":
                continue
            prompt = (
                f"تمرین درس {title} فارسی پایه {GRADE_WORDS[grade]}"
            )
            scope, resp = _ask(prompt)
            if not resp.matched or resp.lesson != int(lesson["number"]):
                failures.append(
                    f"{prompt} → matched={resp.matched} lesson={resp.lesson} "
                    f"want={lesson['number']} reason={resp.failure_reason} scope={scope}"
                )
    assert not failures, "\n".join(failures[:20])


def test_chapter_titles_retrieve_for_persian_and_math(books: list[dict]) -> None:
    failures: list[str] = []
    for book in books:
        if book["subject"] not in {"persian", "math"}:
            continue
        if not book.get("chapters"):
            continue
        grade = int(book["grade"])
        subject = book["subject"]
        for ch in book["chapters"][:3]:
            title = (ch.get("title") or "").strip()
            if not title:
                continue
            prompt = (
                f"فصل {title} {SUBJECT_WORDS[subject]} پایه {GRADE_WORDS[grade]}"
            )
            scope, resp = _ask(prompt)
            if not resp.matched:
                failures.append(f"{prompt} → {resp.failure_reason} scope={scope}")
                continue
            if resp.page is None or resp.page < int(ch["start_page"]):
                failures.append(
                    f"{prompt} → page={resp.page} want>={ch['start_page']}"
                )
    assert not failures, "\n".join(failures[:20])


def test_user_prompt_matrix_smoke() -> None:
    """Exact prompts the product must answer from catalog."""
    prompts = [
        ("لیست درس‌های کتاب فارسی پایه چهارم رو میگی", "catalog_outline", None),
        ("فصول ریاضی پنجم چیه ؟", "catalog_outline", None),
        ("بریم سراغ حل تمرین‌های درس ۵ فارسی پایه ششم", "lesson_span", 5),
        ("بریم سراغ حل تمرین‌های درس ارزش علم فارسی چهارم", "lesson_span", 4),
        ("بریم سراغ حل تمرین‌های درس هفت خان رستم فارسی ششم", "lesson_span", 5),
        ("تمرین درس دوستی / مشاوره فارسی پایه ششم", "lesson_span", 12),
        ("فصل اخلاق فردی ـ اجتماعی فارسی پایه سوم", {"chapter_span", "lesson_span"}, None),
        ("فصل کسر ریاضی پایه پنجم", {"chapter_span", "lesson_span"}, None),
        ("صفحه ۳۶ فارسی پایه چهارم رو توضیح بده", "exact_page", None),
        ("فصل ۲ فارسی پایه چهارم", "lesson_span", None),
        ("بریم سراغ حل تمرین‌های درس 25 قرآن پایه سوم", "lesson_span", 25),
        ("درس ۳۰ فارسی پایه پنجم", None, None),  # OOR
        ("فصل ۳۰ فارسی پایه پنجم", None, None),  # OOR
    ]
    for prompt, expect_type, expect_lesson in prompts:
        scope, resp = _ask(prompt)
        if expect_type is None:
            assert resp.matched is False, prompt
            assert resp.failure_reason in {
                "lesson_out_of_range",
                "chapter_out_of_range",
            }, (prompt, resp.failure_reason)
            continue
        assert resp.matched is True, (prompt, resp.failure_reason, scope)
        allowed = expect_type if isinstance(expect_type, set) else {expect_type}
        assert resp.match_type in allowed, (prompt, resp.match_type)
        if expect_lesson is not None:
            assert resp.lesson == expect_lesson, prompt


def test_lesson_number_digit_does_not_steal_grade() -> None:
    """«درس 25 قرآن پایه سوم» must stay grade 3, not pick ones-digit ۵."""
    scope, resp = _ask("بریم سراغ حل تمرین‌های درس 25 قرآن پایه سوم")
    assert scope.grade == 3
    assert scope.subject_id == "quran"
    assert scope.lesson == 25
    assert resp.matched is True
    assert resp.lesson == 25

    scope, resp = _ask("بریم سراغ حل تمرین‌های درس 14 علوم پایه سوم")
    assert scope.grade == 3
    assert scope.subject_id == "science"
    assert scope.lesson == 14
    assert resp.matched is True


def test_flat_gifts_chapter_word_maps_to_lesson_or_oor() -> None:
    # هدیه has no chapters — «فصل ۲» should open lesson 2
    scope, resp = _ask("فصل ۲ هدیه های آسمان پایه سوم")
    assert scope.grade == 3 and scope.subject_id == "gifts"
    assert resp.matched is True
    assert resp.lesson == 2 or resp.page == lookup_catalog_start_page(
        3, "gifts", lesson=2
    )

    scope, resp = _ask("فصل ۳۰ هدیه های آسمان پایه سوم")
    assert resp.matched is False
    assert resp.failure_reason == "lesson_out_of_range"


def test_fusul_ketab_persian_grade4_outline() -> None:
    """Exact failing production prompt must return catalog outline."""
    scope, resp = _ask("فصول کتاب فارسی پایه چهارم چیه ؟")
    assert scope.wants_outline is True
    assert scope.grade == 4
    assert scope.subject_id == "persian"
    assert resp.matched is True
    assert resp.match_type == "catalog_outline"
    text = resp.context_text or ""
    assert "فصل" in text
    assert "آفرینش" in text
    assert "دانایی" in text
    assert "بستان" not in text
    canned = compose_textbook_outline_reply(
        TextbookContext(
            matched=True,
            match_type="catalog_outline",
            grade=4,
            subject="persian",
            subject_title="فارسی",
            context_text=text,
        )
    )
    assert canned
    assert "فصل" in canned
    assert "آفرینش" in canned
    assert "بستان" not in canned


def test_short_fusul_farsi_chaharom_outline() -> None:
    """«فصول فارسی چهارم» must not invent بستان — catalog فصل/درس only."""
    scope, resp = _ask("فصول فارسی چهارم")
    assert scope.wants_outline and scope.grade == 4 and scope.subject_id == "persian"
    assert resp.matched and resp.match_type == "catalog_outline"
    text = resp.context_text or ""
    assert "آفرینش" in text and "بستان" not in text


def test_catalog_health_stats_see_lesson_maps() -> None:
    from api.textbook.app.store import catalog_health_stats

    stats = catalog_health_stats()
    assert int(stats["catalog_books"]) >= 20
    assert int(stats["catalog_books_with_lessons"]) >= 20
    assert int(stats["catalog_lesson_entries"]) >= 100
