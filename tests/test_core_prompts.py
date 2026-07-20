"""Prompt loading tests."""

from __future__ import annotations

import pytest

from api.core import (
    SUPPORTED_PERSONAS,
    get_core_prompt,
    get_intent_detection_prompt,
    get_persona_prompt,
    get_reflection_prompt,
)


def test_core_prompt_loads() -> None:
    prompt = get_core_prompt()
    assert len(prompt) > 100
    assert "یار" in prompt or "کودک" in prompt


def test_intent_detection_prompt_loads() -> None:
    assert "persona" in get_intent_detection_prompt().lower()


@pytest.mark.parametrize("persona", list(SUPPORTED_PERSONAS))
def test_persona_prompts_load(persona: str) -> None:
    prompt = get_persona_prompt(persona)  # type: ignore[arg-type]
    assert prompt is not None
    assert len(prompt) > 20


def test_persona_none_returns_none() -> None:
    assert get_persona_prompt("none") is None


def test_reflection_prompt_includes_core() -> None:
    reflection = get_reflection_prompt()
    core = get_core_prompt()
    assert "{{CORE_PROMPT}}" not in reflection
    assert core[:80] in reflection
