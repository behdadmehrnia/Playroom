"""Generation, reflection, and prompt assembly tests."""

from __future__ import annotations

import pytest

from api.core import (
    ChatMessage,
    MathToolUsage,
    TextbookContext,
    WebSearchContext,
    WebSearchResult,
    build_prompt_messages,
    build_system_prompt,
    parse_reflection_output,
    run_response_loop,
)

from tests.conftest import DummyLLM


def test_build_system_prompt_includes_persona_and_core() -> None:
    prompt = build_system_prompt("teacher")
    assert len(prompt) > 200


def test_build_system_prompt_with_textbook_context() -> None:
    ctx = TextbookContext(
        matched=True,
        context_text="متن صفحهٔ کتاب",
        subject_title="ریاضی",
        grade=6,
        page=7,
        text_usable=True,
        needs_image=True,
        image_base64="abc",
    )
    prompt = build_system_prompt("teacher", textbook_context=ctx)
    assert "متن صفحهٔ کتاب" in prompt
    assert "ریاضی" in prompt
    assert "تصویر" in prompt


def test_build_system_prompt_with_web_search_context() -> None:
    ctx = WebSearchContext(
        matched=True,
        query="minecraft diamonds",
        context_text="Use iron pickaxe",
        results=[WebSearchResult(title="Tip", snippet="Use iron pickaxe")],
    )
    prompt = build_system_prompt("gamer", web_search_context=ctx)
    assert "Use iron pickaxe" in prompt


def test_build_system_prompt_with_math_tool() -> None:
    usages = [MathToolUsage(expression="2+2", result="4", ok=True)]
    prompt = build_system_prompt("homework", math_tool_usages=usages)
    assert "2+2" in prompt
    assert "4" in prompt


def test_build_prompt_messages_strips_persona_markers() -> None:
    messages = [
        ChatMessage(role="user", content="سلام"),
        ChatMessage(role="assistant", content="hi\n\n<!--playroom:gamer-->"),
    ]
    built = build_prompt_messages(persona="gamer", conversation_messages=messages)
    assert built[0]["role"] == "system"
    user_msgs = [m for m in built if m["role"] == "user"]
    assert user_msgs
    assert "<!--" not in user_msgs[-1]["content"]


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        ('{"status":"PASS"}', "PASS"),
        ('{"status":"REVISE","reasons":["فحش در پاسخ"]}', "REVISE"),
        ("bad", "PASS"),  # fail-open: broken reviewer must not block replies
    ],
)
def test_parse_reflection_output(raw: str, status: str) -> None:
    result = parse_reflection_output(raw)
    assert result.status == status
    if status == "REVISE":
        assert result.reasons


@pytest.mark.asyncio
async def test_run_response_loop_without_reflection() -> None:
    llm = DummyLLM(responses=["پاسخ نهایی"])
    messages = [ChatMessage(role="user", content="سلام")]
    out = await run_response_loop(
        llm,
        backend_model="x",
        persona="creative",
        conversation_messages=messages,
        enable_reflection=False,
    )
    assert out == "پاسخ نهایی"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_run_response_loop_with_reflection_pass() -> None:
    llm = DummyLLM(
        responses=[
            "پاسخ اول",
            '{"status":"PASS"}',
        ]
    )
    messages = [ChatMessage(role="user", content="سلام")]
    out = await run_response_loop(
        llm,
        backend_model="x",
        persona="creative",
        conversation_messages=messages,
        enable_reflection=True,
    )
    assert out == "پاسخ اول"
    assert len(llm.calls) == 2
