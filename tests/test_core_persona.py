"""Persona resolution and activity detection tests."""

from __future__ import annotations

import pytest

from api.core import (
    ACTIVE_PERSONA_METADATA_KEY,
    ChatMessage,
    _detect_explicit_persona_request,
    _detect_ongoing_activity,
    _infer_persona_from_history,
    _is_activity_continuation,
    _looks_like_greeting_only,
    _looks_like_word_chain_awaiting_answer,
    _should_keep_current_persona,
    format_persona_switch_confirmation,
    resolve_active_persona,
    resolve_manual_persona,
)

from tests.conftest import DummyLLM


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("باش معلم", "teacher"),
        ("معلم باش", "teacher"),
        ("قصه بگو", "storyteller"),
        ("باش داستان‌گو", "storyteller"),
        ("کمک درس باش", "homework"),
        ("بازی کنیم", "gamer"),
        ("خلاق باش", "creative"),
        ("باش معلم، نه باش داستان‌گو، در واقع بازی کنیم", "gamer"),
        ("سلام!", None),
        ("کمک", None),
    ],
)
def test_explicit_persona_triggers(text: str, expected: str | None) -> None:
    assert _detect_explicit_persona_request(text) == expected


def test_manual_persona_sources() -> None:
    assert resolve_manual_persona(user_persona="teacher") == "teacher"
    assert (
        resolve_manual_persona(body={"metadata": {"yarkids_persona": "gamer"}})
        == "gamer"
    )
    assert resolve_manual_persona(body={"persona": "creative"}) == "creative"
    assert resolve_manual_persona(user_persona="auto") is None
    assert resolve_manual_persona(body={"params": {"persona": "teacher"}}) == "teacher"


@pytest.mark.parametrize(
    ("persona", "text"),
    [
        ("homework", "سوال بعد"),
        ("storyteller", "ادامه بده"),
        ("teacher", "مثال دیگر"),
        ("creative", "ایده دیگر"),
    ],
)
def test_activity_continuation_phrases(persona: str, text: str) -> None:
    assert _is_activity_continuation(text, persona) is True  # type: ignore[arg-type]


def test_word_chain_keeps_gamer(word_chain_messages: list[ChatMessage]) -> None:
    assert _detect_ongoing_activity(word_chain_messages, "gamer") is not None
    assert _is_activity_continuation("داستان", "gamer") is False
    assert _looks_like_word_chain_awaiting_answer(word_chain_messages) is True
    assert _should_keep_current_persona("داستان", "gamer", word_chain_messages) is True
    assert _infer_persona_from_history(word_chain_messages) == "gamer"


@pytest.mark.asyncio
async def test_word_chain_stays_gamer_despite_llm_intent(word_chain_messages: list[ChatMessage]) -> None:
    llm = DummyLLM(default='{"persona":"storyteller","confidence":0.95}')
    res = await resolve_active_persona(
        llm, backend_model="x", messages=word_chain_messages, body={}
    )
    assert res.persona == "gamer"
    assert res.ask_confirmation is False


@pytest.mark.asyncio
async def test_explicit_story_switch_asks_confirmation(word_chain_messages: list[ChatMessage]) -> None:
    llm = DummyLLM()
    messages = word_chain_messages[:-1] + [
        ChatMessage(role="user", content="قصه بگو")
    ]
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body={})
    assert res.persona == "gamer"
    assert res.ask_confirmation is True
    assert res.pending_switch_to == "storyteller"
    assert "مطمئنی" in format_persona_switch_confirmation("gamer", "storyteller")


@pytest.mark.asyncio
async def test_welcome_menu_bazi_selects_gamer(welcome_menu_message: str) -> None:
    assert _infer_persona_from_history(
        [ChatMessage(role="assistant", content=welcome_menu_message)]
    ) is None

    llm = DummyLLM(default='{"persona":"teacher","confidence":0.99}')
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content=welcome_menu_message),
        ChatMessage(role="user", content="بازی"),
    ]
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body={})
    assert res.persona == "gamer"
    assert res.ask_confirmation is False


@pytest.mark.asyncio
async def test_soft_switch_creative_to_storyteller_no_confirmation() -> None:
    llm = DummyLLM(default='{"persona":"storyteller","confidence":0.93}')
    messages = [
        ChatMessage(role="user", content="یه ایده خلاق بده"),
        ChatMessage(role="assistant", content="ایده قشنگ: <!-- yarkids:creative -->"),
        ChatMessage(role="user", content="قصه بگو"),
    ]
    body = {"metadata": {ACTIVE_PERSONA_METADATA_KEY: "creative"}}
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body=body)
    assert res.persona == "storyteller"
    assert res.ask_confirmation is False


@pytest.mark.asyncio
async def test_soft_switch_teacher_to_homework_no_confirmation() -> None:
    llm = DummyLLM(default='{"persona":"homework","confidence":0.91}')
    messages = [
        ChatMessage(role="user", content="کسر یعنی چی؟"),
        ChatMessage(role="assistant", content="کسر یعنی... <!-- yarkids:teacher -->"),
        ChatMessage(role="user", content="کمک درس باش"),
    ]
    body = {"metadata": {ACTIVE_PERSONA_METADATA_KEY: "teacher"}}
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body=body)
    assert res.persona == "homework"
    assert res.ask_confirmation is False


@pytest.mark.asyncio
async def test_cross_family_weak_intent_stays_put() -> None:
    llm = DummyLLM(default='{"persona":"teacher","confidence":0.75}')
    messages = [
        ChatMessage(role="user", content="بازی کنیم"),
        ChatMessage(role="assistant", content="باشه بازی! <!-- yarkids:gamer -->"),
        ChatMessage(role="user", content="یه کم درباره کسر بگو"),
    ]
    body = {"metadata": {ACTIVE_PERSONA_METADATA_KEY: "gamer"}}
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body=body)
    assert res.persona == "gamer"
    assert res.ask_confirmation is False


@pytest.mark.asyncio
async def test_cross_family_explicit_asks_confirmation() -> None:
    llm = DummyLLM(default='{"persona":"teacher","confidence":0.98}')
    messages = [
        ChatMessage(role="user", content="بازی کنیم"),
        ChatMessage(role="assistant", content="باشه بازی! <!-- yarkids:gamer -->"),
        ChatMessage(role="user", content="باش معلم"),
    ]
    body = {"metadata": {ACTIVE_PERSONA_METADATA_KEY: "gamer"}}
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body=body)
    assert res.persona == "gamer"
    assert res.ask_confirmation is True
    assert res.pending_switch_to == "teacher"
    assert "بله برو" in format_persona_switch_confirmation("gamer", "teacher")


@pytest.mark.asyncio
async def test_textbook_list_overrides_manual_creative() -> None:
    """Lesson-list asks must use homework tools even if Valves say creative."""
    llm = DummyLLM(default='{"persona":"creative","confidence":0.99}')
    welcome = (
        "سلام! من یار کودک هستم. خلاق، داستان‌گو، معلم، کمک‌درسی، بازی. "
        "کدومش رو دوست داری؟"
    )
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content=welcome),
        ChatMessage(
            role="user",
            content="لیست دروس فارسی چهارم دبستان رو میگی ؟",
        ),
    ]
    res = await resolve_active_persona(
        llm,
        backend_model="x",
        messages=messages,
        user_persona="creative",
        body={},
    )
    assert res.persona == "homework"
    assert res.ask_confirmation is False

    follow = await resolve_active_persona(
        llm,
        backend_model="x",
        messages=messages
        + [
            ChatMessage(role="assistant", content="کدوم کتاب؟"),
            ChatMessage(role="user", content="خود کتاب فارسی"),
        ],
        user_persona="creative",
        body={},
    )
    assert follow.persona == "homework"

