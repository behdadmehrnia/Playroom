"""Shared fixtures for Yar Kids API tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.core import ChatMessage, LLMCompletionRequest


class DummyLLM:
    """Minimal LLMClient stub with a FIFO response queue."""

    def __init__(
        self,
        *,
        responses: list[str] | None = None,
        default: str = '{"persona":"none","confidence":0.5}',
    ) -> None:
        self._responses = list(responses or [])
        self._default = default
        self.calls: list[LLMCompletionRequest] = []

    async def complete(self, request: LLMCompletionRequest) -> str:
        self.calls.append(request)
        if self._responses:
            return self._responses.pop(0)
        return self._default

    async def aclose(self) -> None:
        return None


@pytest.fixture
def dummy_llm() -> DummyLLM:
    return DummyLLM()


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        backend_model="test-model",
        llm_api_key="test-key",
        llm_base_url="http://llm.test/v1",
        enable_reflection=False,
        enable_textbook_context=False,
        enable_web_search=False,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, test_settings: Settings) -> TestClient:
    """FastAPI TestClient with lifespan and overridden LLM."""
    monkeypatch.setenv("YARKIDS_BACKEND_MODEL", test_settings.backend_model)
    monkeypatch.setenv("YARKIDS_LLM_API_KEY", test_settings.llm_api_key)
    monkeypatch.setenv("YARKIDS_LLM_BASE_URL", test_settings.llm_base_url)
    monkeypatch.setenv("YARKIDS_ENABLE_REFLECTION", "false")
    monkeypatch.setenv("YARKIDS_ENABLE_TEXTBOOK_CONTEXT", "false")
    monkeypatch.setenv("YARKIDS_ENABLE_WEB_SEARCH", "false")

    from api.main import create_app

    with TestClient(create_app()) as test_client:
        test_client.app.state.settings = test_settings
        test_client.app.state.llm_client = DummyLLM(
            responses=["سلام! چطور می‌تونم کمکت کنم؟"]
        )
        yield test_client


@pytest.fixture
def word_chain_messages() -> list[ChatMessage]:
    game_reply = (
        "بیا یه بازی سریع شروع کنیم: «بازی کلمه‌های زنجیره‌ای». "
        "من می‌گم «خورشید» ☀️ — حالا نوبت توئه! باید یه کلمه با حرف «د» بگی."
    )
    return [
        ChatMessage(role="user", content="بازی کنیم"),
        ChatMessage(role="assistant", content=game_reply),
        ChatMessage(role="user", content="داستان"),
    ]


@pytest.fixture
def welcome_menu_message() -> str:
    return (
        "سلام! من «یار کودک» هستم.\n\n"
        "🎨 خلاق: ایده‌های نقاشی\n"
        "📖 داستان‌گو: قصه‌های جذاب\n"
        "📚 معلم: مفاهیم علمی\n"
        "✏️ کمک‌درسی: تمرین مدرسه\n"
        "🎮 بازی و سرگرمی: معما و چیستان\n\n"
        "کدومش رو بیشتر دوست داری؟"
    )
