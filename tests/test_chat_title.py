"""Chat title generation heuristics."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from api.core import ChatMessage, get_chat_title_prompt
from api.core.chat_title import (
    PLACEHOLDER_CHAT_TITLE,
    conversation_ready_for_title,
    generate_chat_title,
    is_generic_chat_title,
    looks_like_title_generation_request,
    sanitize_chat_title,
    should_emit_chat_title,
)


def test_chat_title_prompt_is_persian_and_child_friendly() -> None:
    prompt = get_chat_title_prompt()
    assert "فارسی" in prompt
    assert "کودکانه" in prompt or "کودک" in prompt
    assert "نمونه بد" in prompt


def test_detects_openwebui_title_task() -> None:
    messages = [
        ChatMessage(
            role="user",
            content=(
                "### Task:\nGenerate a concise, 3-5 word title with an emoji "
                "summarizing the chat history.\n### Chat History:\nUser: سلام"
            ),
        )
    ]
    assert looks_like_title_generation_request(messages) is True


def test_normal_homework_message_is_not_title_task() -> None:
    messages = [
        ChatMessage(
            role="user",
            content="میخوام تمرین های فصل سه کتاب ریاضی رو با هم حل کنیم",
        )
    ]
    assert looks_like_title_generation_request(messages) is False


def test_greeting_only_not_ready_for_title() -> None:
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content="سلام! من یار کودک هستم."),
    ]
    assert conversation_ready_for_title(messages) is False


def test_second_user_turn_ready_for_title() -> None:
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content="سلام! کدوم حالت؟"),
        ChatMessage(role="user", content="تمرین ریاضی فصل سه پایه ششم"),
    ]
    assert conversation_ready_for_title(messages) is True


def test_substantive_first_message_ready() -> None:
    messages = [
        ChatMessage(
            role="user",
            content="میخوام تمرین های فصل سه کتاب ریاضی رو با هم حل کنیم",
        )
    ]
    assert conversation_ready_for_title(messages) is True


def test_generic_english_intro_title() -> None:
    assert is_generic_chat_title("👋 Introduction to Yar Koodak") is True
    assert is_generic_chat_title("✏️ تمرین کسر ریاضی") is False


def test_sanitize_strips_prefix_and_quotes() -> None:
    assert sanitize_chat_title('عنوان: «تمرین ریاضی»') == "تمرین ریاضی"


@pytest.mark.asyncio
async def test_generate_placeholder_when_too_early() -> None:
    llm = AsyncMock()
    title = await generate_chat_title(
        llm,
        backend_model="test",
        messages=[ChatMessage(role="user", content="سلام")],
    )
    assert title == PLACEHOLDER_CHAT_TITLE
    llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_generate_uses_llm_when_ready() -> None:
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="✏️ تمرین ریاضی ششم")
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content="سلام!"),
        ChatMessage(role="user", content="تمرین فصل سه ریاضی پایه ششم"),
    ]
    title = await generate_chat_title(llm, backend_model="test", messages=messages)
    assert "ریاضی" in title
    llm.complete.assert_awaited()


def test_should_emit_only_when_generic_current() -> None:
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content="سلام"),
        ChatMessage(role="user", content="داستان روباه بگو"),
    ]
    assert should_emit_chat_title(messages, current_title=None) is True
    assert (
        should_emit_chat_title(messages, current_title="👋 Introduction to Yar Koodak")
        is True
    )
    assert (
        should_emit_chat_title(messages, current_title="📖 قصه روباه") is False
    )
