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
    assert "مطمئنی؟" in format_persona_switch_confirmation("gamer", "storyteller")


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
async def test_greeting_stays_none() -> None:
    assert _looks_like_greeting_only("سلام")
    assert _looks_like_greeting_only("سلام!")
    assert not _looks_like_greeting_only("سلام بازی کنیم")

    llm = DummyLLM(default='{"persona":"creative","confidence":0.99}')
    messages = [ChatMessage(role="user", content="سلام")]
    res = await resolve_active_persona(llm, backend_model="x", messages=messages, body={})
    assert res.persona == "none"


def test_active_persona_metadata_key() -> None:
    assert ACTIVE_PERSONA_METADATA_KEY == "yarkids_active_persona"
