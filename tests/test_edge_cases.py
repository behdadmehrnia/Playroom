"""Cross-cutting edge-case tests for Yar Kids subsystems."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.core import ChatMessage, build_textbook_query
from api.core.generation import build_system_prompt
from api.core.math_tool import calculate_math, extract_math_expressions, normalize_math_expression
from api.core.persona import (
    _is_activity_continuation,
    _should_keep_current_persona,
    resolve_active_persona,
)
from api.core.textbook import (
    _extract_subject_token,
    _subject_query_label,
    resolve_textbook_scope,
)
from api.core.types import TextbookContext
from api.core.web_search import looks_like_web_search_request
from api.textbook.app.store import _lesson_target_patterns, get_neighbor_pages


def test_lesson_patterns_accept_ocr_punctuation() -> None:
    """MinerU/RTL often yields «فصل :3» instead of «فصل 3»."""
    patterns = _lesson_target_patterns(3)
    samples = (
        "فصل 3 ضرب و تقسیم",
        "فصل :3 ضرب و تقسیم",
        "فصل:۳ ضرب",
        "فصل-3",
        "3 فصل",
        "فصل سوم",
        "سوم فصل",
    )
    for sample in samples:
        assert any(p.search(sample) for p in patterns), sample


def test_lesson_patterns_do_not_match_wrong_number() -> None:
    patterns = _lesson_target_patterns(3)
    assert not any(p.search("فصل 2 کسر") for p in patterns)
    assert not any(p.search("فصل :4 اندازهگیری") for p in patterns)


def test_compose_query_keeps_full_gifts_title() -> None:
    messages = [ChatMessage(role="user", content="صفحه ۲۵۱ هدیه های آسمان پایه سوم")]
    query = build_textbook_query(messages)
    assert "هدیه های آسمان" in query
    assert "251" in query or "۲۵۱" in query


def test_build_textbook_query_preserves_gifts_misspelling() -> None:
    messages = [
        ChatMessage(role="user", content="صفحه ۱۰ هدایای آسمان پایه سوم"),
    ]
    query = build_textbook_query(messages)
    assert query
    assert "هدیه های آسمان" in query
    assert "10" in query or "۱۰" in query


def test_extract_subject_prefers_full_gifts_phrase() -> None:
    assert _extract_subject_token("صفحه ۱۰ هدیه های آسمان") == "هدیه های آسمان"
    assert _extract_subject_token("صفحه ۱۰ هدایای آسمان") == "هدایای آسمان"
    assert _subject_query_label("هدایای آسمان") == "هدیه های آسمان"
    assert _subject_query_label("هدیه") == "هدیه های آسمان"
    assert _extract_subject_token("املا صفحه ۱۰ پایه ششم") == "املا"
    assert _subject_query_label("املا") == "فارسی"


def test_resolve_scope_bare_page_after_page_ask() -> None:
    """«۳۷» after asking for page must become page=37, not keep lesson-only retrieve."""
    messages = [
        ChatMessage(
            role="user",
            content="میخوام تمرین های فصل سه کتاب ریاضی رو با هم حل کنیم",
        ),
        ChatMessage(
            role="assistant",
            content="کلاس چندمی؟ اگر شماره صفحه رو هم بدونی بهم بگو.",
        ),
        ChatMessage(role="user", content="ششم"),
        ChatMessage(
            role="assistant",
            content="می‌شه شماره صفحه رو بهم بگی؟ (چون شماره صفحه خیلی دقیق‌تره)",
        ),
        ChatMessage(role="user", content="۳۷"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.subject_id == "math"
    assert scope.grade == 6
    assert scope.page == 37
    assert scope.lesson == 3
    assert scope.has_page_lookup() is True
    query = build_textbook_query(messages)
    assert "37" in query or "۳۷" in query
    assert "صفحه" in query


def test_bare_digit_after_grade_ask_is_grade_not_page() -> None:
    messages = [
        ChatMessage(role="user", content="تمرین ریاضی فصل دو"),
        ChatMessage(role="assistant", content="کلاس چندمی هستی؟"),
        ChatMessage(role="user", content="۶"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.grade == 6
    assert scope.page is None


def test_resolve_scope_keeps_math_chapter_across_grade_followup() -> None:
    """«فصل سوم ریاضی» سپس «پایه ششم» → structured scope with lesson retrieve."""
    messages = [
        ChatMessage(
            role="user",
            content="میخوام تمرین های فصل سوم کتاب ریاضی رو حل کنیم",
        ),
        ChatMessage(role="assistant", content="کلاس چندمی؟"),
        ChatMessage(role="user", content="پایه ششم"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.subject_id == "math"
    assert scope.lesson == 3
    assert scope.grade == 6
    # Chapter is enough to retrieve; page remains the preferred locator.
    assert scope.can_retrieve() is True
    assert scope.has_lesson_lookup() is True
    assert "ریاضی" in scope.debug_label()
    assert "3" in scope.debug_label()
    assert scope.compose_query()
    assert "ریاضی" in scope.compose_query()


def test_resolve_scope_lesson_correction_clears_bad_page() -> None:
    """Wrong page then «درس پنجم منظورم بود» → lesson lookup, not stuck out-of-range page."""
    messages = [
        ChatMessage(
            role="user",
            content="صفحه ۲۵۰ کتاب هدیه های آسمان رو حل میکنی",
        ),
        ChatMessage(role="assistant", content="کلاس چندمی؟"),
        ChatMessage(role="user", content="کلاس ششم"),
        ChatMessage(role="assistant", content="این کتاب صفحه ۲۵۰ ندارد."),
        ChatMessage(role="user", content="حالا درس پنجم منظورم بود"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.subject_id == "gifts"
    assert scope.grade == 6
    assert scope.lesson == 5
    assert scope.page is None
    assert scope.has_lesson_lookup() is True
    assert scope.has_page_lookup() is False


def test_resolve_scope_page_words_compound() -> None:
    """«بیست و یکم» must resolve to 21, not first-token 20."""
    messages = [
        ChatMessage(role="user", content="صفحه بیست و یکم فارسی پایه ششم"),
    ]
    scope = resolve_textbook_scope(messages)
    assert scope.page == 21
    assert scope.can_retrieve() is True
    query = build_textbook_query(messages)
    assert "21" in query or "۲۱" in query
    assert "20" not in query.replace("21", "")


def test_neighbor_pages_skip_nonpositive(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_get_page(grade: int, subject: str, printed_page: int):
        calls.append(printed_page)
        return None

    monkeypatch.setattr("api.textbook.app.store.index_exists", lambda: True)
    monkeypatch.setattr("api.textbook.app.store.get_page", fake_get_page)
    get_neighbor_pages(4, "math", 1, radius=2)
    assert all(p > 0 for p in calls)
    assert 0 not in calls
    assert -1 not in calls


def test_lesson_missing_system_prompt_is_specific() -> None:
    ctx = TextbookContext(
        matched=False,
        failure_reason="lesson_missing",
        subject="math",
        subject_title="ریاضی",
        grade=4,
        page_query_failed=True,
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "درس" in prompt or "فصل" in prompt
    assert "ریاضی" in prompt
    assert "از خودت نساز" in prompt or "حدس نزن" in prompt
    assert "عکس" in prompt
    assert "صفحه" in prompt


def test_need_info_asks_only_missing_grade_when_chapter_known() -> None:
    ctx = TextbookContext(
        matched=False,
        need_info=True,
        failure_reason="need_grade_or_subject",
        subject="math",
        subject_title="ریاضی",
        lesson=3,
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "کلاس چندمی" in prompt or "کلاس چندم" in prompt
    assert "ریاضی" in prompt
    assert "درس/فصل: 3" in prompt or "فصل: 3" in prompt
    assert "هنوز لازم است بپرسی" in prompt
    # Chapter already known — only ask for missing grade, not page/chapter again.
    assert "شمارهٔ صفحه؟ (ترجیح) یا شمارهٔ فصل/درس؟" not in prompt


def test_need_info_prefers_page_but_accepts_chapter() -> None:
    ctx = TextbookContext(
        matched=False,
        need_info=True,
        subject="math",
        subject_title="ریاضی",
        grade=6,
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "هنوز لازم است بپرسی: شمارهٔ صفحه؟ (ترجیح) یا شمارهٔ فصل/درس؟" in prompt
    assert "هنوز لازم است بپرسی: کلاس چندمی؟" not in prompt
    assert "هنوز لازم است بپرسی: کدام کتاب" not in prompt


def test_need_info_does_not_reask_locator_when_lesson_known() -> None:
    ctx = TextbookContext(
        matched=False,
        need_info=True,
        subject="math",
        subject_title="ریاضی",
        grade=6,
        lesson=3,
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "درس/فصل: 3" in prompt or "فصل: 3" in prompt
    assert "شمارهٔ صفحه؟ (ترجیح) یا شمارهٔ فصل/درس؟" not in prompt


def test_lookup_failed_asks_for_photo_or_question_text() -> None:
    ctx = TextbookContext(
        matched=False,
        page_query_failed=True,
        subject="math",
        subject_title="ریاضی",
        grade=6,
        page=42,
    )
    prompt = build_system_prompt("homework", textbook_context=ctx)
    assert "پیدا" in prompt
    assert "عکس" in prompt
    assert "سوال" in prompt


def test_math_tool_rejects_dunder_and_handles_div_zero() -> None:
    bad = calculate_math("__import__('os')")
    assert bad.startswith("خطا:")
    zero = calculate_math("10/0")
    assert "صفر" in zero
    assert normalize_math_expression("۱۲×۵") == "12*5"
    exprs = extract_math_expressions("۱۲ × ۵ چنده؟")
    assert exprs == ["12*5"]


def test_web_search_skips_pure_story_request() -> None:
    assert looks_like_web_search_request("داستان یه ربات فضایی بگو", persona="gamer") is False
    assert looks_like_web_search_request("ماینکرفت چطور الماس پیدا کنم؟", persona="gamer") is True
    assert looks_like_web_search_request("بازی minecraft", persona="teacher") is False


def test_sticky_gamer_does_not_block_textbook_page_request() -> None:
    text = "صفحه ۱۲ ریاضی پایه پنجم"
    messages = [
        ChatMessage(role="user", content="بازی کنیم"),
        ChatMessage(
            role="assistant",
            content="بیا بازی کلمه‌های زنجیره‌ای کنیم! نوبت توئه، با حرف «س» بگو.",
        ),
        ChatMessage(role="user", content=text),
    ]
    assert _should_keep_current_persona(text, "gamer", messages) is False


@pytest.mark.asyncio
async def test_resolve_persona_breaks_word_chain_for_textbook() -> None:
    messages = [
        ChatMessage(role="user", content="بازی کنیم"),
        ChatMessage(
            role="assistant",
            content="بازی کلمات زنجیره‌ای! نوبت توئه با حرف ب.",
        ),
        ChatMessage(role="user", content="صفحه ۱۲ ریاضی پایه پنجم"),
    ]
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value='{"persona":"homework","confidence":0.95}'
    )
    resolution = await resolve_active_persona(
        llm_client=llm,
        backend_model="test",
        messages=messages,
        body={"metadata": {"yarkids_active_persona": "gamer"}},
    )
    assert resolution.persona == "homework"
    assert resolution.ask_confirmation is False
    llm.complete.assert_not_awaited()


def test_help_marker_ignores_activity_continuation() -> None:
    assert _is_activity_continuation("سوال بعد", "homework") is True
    assert _is_activity_continuation("صفحه ۱۲ ریاضی پایه پنجم", "homework") is False
