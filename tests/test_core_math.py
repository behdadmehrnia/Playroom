"""Math tool tests."""

from __future__ import annotations

import pytest

from api.core import (
    calculate_math,
    extract_math_expressions,
    format_math_tool_context,
    normalize_math_expression,
    preprocess_math_natural_language,
    run_math_tool_for_message,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("۲ + ۳", "2+3"),
        ("۱۲ × ۵", "12*5"),
        ("sqrt(144)", "sqrt(144)"),
    ],
)
def test_normalize_math_expression(raw: str, expected: str) -> None:
    assert normalize_math_expression(raw) == expected


@pytest.mark.parametrize(
    ("text", "expected_exprs"),
    [
        ("۲ به توان ۱۰", ["2**10"]),
        ("جذر ۱۴۴", ["sqrt(144)"]),
        ("۱۲ × ۵", ["12*5"]),
        ("۱۲ + ۱۷", ["12+17"]),
        ("سلام!", []),
    ],
)
def test_extract_math_expressions(text: str, expected_exprs: list[str]) -> None:
    assert extract_math_expressions(text) == expected_exprs


def test_preprocess_math_natural_language() -> None:
    assert "2**10" in preprocess_math_natural_language("۲ به توان ۱۰")


def test_calculate_math_success() -> None:
    assert calculate_math("2+3") == "5"


def test_calculate_math_division_by_zero() -> None:
    usages = run_math_tool_for_message("۱۰ تقسیم بر ۰", persona="teacher")
    assert len(usages) == 1
    assert usages[0].ok is False
    assert "تقسیم بر صفر نمیشه" in usages[0].result


def test_math_tool_persona_gate() -> None:
    assert run_math_tool_for_message("۱۲ + ۱۷", persona="gamer") == []
    assert run_math_tool_for_message("۱۲ + ۱۷", persona="creative") == []
    usages = run_math_tool_for_message("۱۲ + ۱۷", persona="homework")
    assert len(usages) == 1
    assert usages[0].ok is True
    assert usages[0].result == "29"


def test_format_math_tool_context() -> None:
    usages = run_math_tool_for_message("۲ + ۲", persona="teacher")
    ctx = format_math_tool_context(usages)
    assert ctx is not None
    assert "2+2" in ctx
    assert "4" in ctx
    assert format_math_tool_context([]) is None
