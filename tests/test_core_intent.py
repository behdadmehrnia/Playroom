"""Intent detection parsing and local shortcuts."""

from __future__ import annotations

import pytest

from api.core import (
    ChatMessage,
    INTENT_CONFIDENCE_THRESHOLD,
    detect_intent,
    parse_intent_detection_output,
)

from tests.conftest import DummyLLM


@pytest.mark.parametrize(
    ("raw", "persona", "confidence"),
    [
        ('{"persona":"teacher","confidence":0.95}', "teacher", 0.95),
        ('{"persona":"none"}', "none", None),
        ('{"persona":"teacher","confidence":0.5}', "none", None),
        ("not json", "none", None),
        ('{"persona":"invalid","confidence":0.99}', "none", None),
    ],
)
def test_parse_intent_detection_output(
    raw: str, persona: str, confidence: float | None
) -> None:
    result = parse_intent_detection_output(raw)
    assert result.persona == persona
    assert result.confidence == confidence


@pytest.mark.asyncio
async def test_detect_intent_explicit_bypasses_llm() -> None:
    llm = DummyLLM(default='{"persona":"creative","confidence":0.99}')
    messages = [ChatMessage(role="user", content="باش معلم")]
    result = await detect_intent(llm, backend_model="x", messages=messages)
    assert result.persona == "teacher"
    assert result.confidence == 0.98
    assert llm.calls == []


@pytest.mark.asyncio
async def test_detect_intent_greeting_returns_none() -> None:
    llm = DummyLLM()
    messages = [ChatMessage(role="user", content="سلام!")]
    result = await detect_intent(llm, backend_model="x", messages=messages)
    assert result.persona == "none"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_detect_intent_calls_llm_when_needed() -> None:
    llm = DummyLLM(responses=['{"persona":"homework","confidence":0.9}'])
    messages = [ChatMessage(role="user", content="۱۲ × ۵ چنده؟")]
    result = await detect_intent(llm, backend_model="x", messages=messages)
    assert result.persona == "homework"
    assert result.confidence == 0.9
    assert len(llm.calls) == 1


def test_intent_confidence_threshold() -> None:
    assert INTENT_CONFIDENCE_THRESHOLD == 0.7
