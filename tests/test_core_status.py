"""Status message helper tests."""

from __future__ import annotations

from api.core import (
    MAX_GENERATION_ATTEMPTS,
    get_persona_ui_label,
    status_calculating_math,
    status_detecting_persona,
    status_fetching_textbook,
    status_fetching_web_search,
    status_generating_response,
    status_persona_selected,
    status_reflection_disabled,
    status_reviewing_response,
    status_textbook_unavailable,
    status_web_search_unavailable,
)


def test_get_persona_ui_label() -> None:
    assert get_persona_ui_label("teacher") != "teacher"
    assert "معلم" in get_persona_ui_label("teacher") or "📚" in get_persona_ui_label("teacher")


def test_status_messages_non_empty() -> None:
    assert status_detecting_persona()
    assert status_persona_selected("gamer")
    generating = status_generating_response(1, MAX_GENERATION_ATTEMPTS)
    assert generating
    assert "قشنگت" not in generating
    assert "جوابت رو مینویسم" in generating
    assert status_reviewing_response()
    assert status_reflection_disabled()
    assert status_fetching_textbook()
    assert status_textbook_unavailable()
    assert status_fetching_web_search()
    assert status_web_search_unavailable()
    assert status_calculating_math()
