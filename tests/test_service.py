"""Service-layer orchestration tests."""

from __future__ import annotations

import pytest

from api.config import Settings
from api.core import ChatMessage
from api.core.messages import strip_persona_markers
from api.service import detect_intent_for, run_chat

from tests.conftest import DummyLLM


@pytest.fixture
def service_settings() -> Settings:
    return Settings(
        backend_model="test-model",
        llm_api_key="key",
        enable_reflection=False,
        enable_textbook_context=False,
        enable_web_search=False,
        enable_status_updates=False,
    )


@pytest.mark.asyncio
async def test_detect_intent_for(service_settings: Settings) -> None:
    llm = DummyLLM(responses=['{"persona":"storyteller","confidence":0.92}'])
    messages = [ChatMessage(role="user", content="قصه بگو")]
    intent, user_text = await detect_intent_for(
        llm_client=llm,
        backend_model=service_settings.backend_model,
        messages=messages,
    )
    assert intent.persona == "storyteller"
    assert user_text == "قصه بگو"


@pytest.mark.asyncio
async def test_run_chat_manual_persona(service_settings: Settings) -> None:
    llm = DummyLLM(responses=["پاسخ معلم"])
    messages = [ChatMessage(role="user", content="کسر یعنی چی؟")]
    result = await run_chat(
        settings=service_settings,
        llm_client=llm,
        backend_model=service_settings.backend_model,
        messages=messages,
        persona="teacher",
        body=None,
        enable_reflection=False,
        enable_textbook_context=False,
        enable_web_search=False,
        on_status=None,
    )
    assert strip_persona_markers(result.response) == "پاسخ معلم"
    assert result.persona == "teacher"
    assert result.persona_source == "manual"


@pytest.mark.asyncio
async def test_run_chat_word_chain_confirmation(service_settings: Settings, word_chain_messages: list[ChatMessage]) -> None:
    llm = DummyLLM(default='{"persona":"storyteller","confidence":0.95}')
    messages = word_chain_messages[:-1] + [
        ChatMessage(role="user", content="قصه بگو")
    ]
    body: dict = {}
    result = await run_chat(
        settings=service_settings,
        llm_client=llm,
        backend_model=service_settings.backend_model,
        messages=messages,
        persona=None,
        body=body,
        enable_reflection=False,
        enable_textbook_context=False,
        enable_web_search=False,
        on_status=None,
    )
    assert result.persona == "gamer"
    assert result.persona_source == "confirm"
    assert "مطمئنی" in result.response
