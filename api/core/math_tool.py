"""Safe arithmetic evaluation tool for homework / teacher personas."""

from __future__ import annotations

import math
import re

from pydantic import BaseModel

_SAFE_MATH_NAMES = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "pow": pow,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "sinh": math.sinh,
    "cosh": math.cosh,
    "tanh": math.tanh,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "ceil": math.ceil,
    "floor": math.floor,
    "degrees": math.degrees,
    "radians": math.radians,
    "factorial": math.factorial,
    "gcd": math.gcd,
    "lcm": math.lcm,
    "hypot": math.hypot,
}

_PERSIAN_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_MATH_OP_MAP = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-", "—": "-"})
_MATH_EXPR_RE = re.compile(
    r"(?:"
    r"(?:(?:sqrt|sin|cos|tan|log|log10|log2|exp|abs|ceil|floor|factorial|gcd|lcm|pow|hypot)\s*)?\("
    r"[^()]{0,80}\)"
    r"|"
    r"\d+(?:\.\d+)?(?:\s*(?:\*\*|[\+\-\*/%^])\s*\d+(?:\.\d+)?)+"
    r")",
    re.IGNORECASE,
)
_MATH_PERSONAS: frozenset[str] = frozenset({"teacher", "homework"})

MATH_TOOL_CONTEXT_HEADER = "نتایج ابزار محاسبه ریاضی (مرجع دقیق — برای بررسی، نه جای آموزش):"
MATH_TOOL_CONTEXT_INSTRUCTION = (
    "مهم: سیستم چند عبارت ریاضی را با ابزار محاسبهٔ امن ارزیابی کرده و نتایج را "
    "در ادامه گذاشته است. از نتایج درست برای بررسی جواب یا قدم‌های میانی استفاده کن. "
    "در حالت کمک‌درسی جواب نهایی را یک‌جا لو نده مگر کودک فقط بررسی بخواهد. "
    "اگر خطای دوستانه (مثل تقسیم بر صفر) آمده، همان را مهربان به کودک بگو و عدد دیگری پیشنهاد بده. "
    "دربارهٔ سیستم یا ابزار محاسبه به‌صورت فنی حرف نزن."
)
MATH_FRIENDLY_ERROR_MESSAGES: dict[str, str] = {
    "تقسیم بر صفر": "تقسیم بر صفر نمیشه! بیای عدد دیگه‌ای امتحان کنیم.",
}


class _MathError(Exception):
    """Raised when math evaluation fails."""


class MathToolUsage(BaseModel):
    """One evaluated expression from the math tool."""

    expression: str
    result: str
    ok: bool = True


def normalize_math_expression(expr: str) -> str:
    """Normalize Persian/Arabic digits and common math symbols for eval."""
    text = expr.strip().translate(_PERSIAN_DIGIT_MAP).translate(_MATH_OP_MAP)
    text = text.replace("^", "**")
    text = text.replace(",", "")
    text = re.sub(r"\s+", "", text)
    return text


def preprocess_math_natural_language(text: str) -> str:
    """Convert common Persian math phrases into evaluable expressions."""
    if not text:
        return text
    t = text.translate(_PERSIAN_DIGIT_MAP).translate(_MATH_OP_MAP)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*به\s*توان\s*(\d+(?:\.\d+)?)", r"\1**\2", t)
    t = re.sub(r"جذر\s*(?:عدد\s*)?(\d+(?:\.\d+)?)", r"sqrt(\1)", t)
    t = re.sub(r"ریشه\s*(?:دوم\s*)?(?:عدد\s*)?(\d+(?:\.\d+)?)", r"sqrt(\1)", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*تقسیم\s*بر\s*(\d+(?:\.\d+)?)", r"\1/\2", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*ضرب(?:\s*در)?\s*(\d+(?:\.\d+)?)", r"\1*\2", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*به\s*علاوه\s*(\d+(?:\.\d+)?)", r"\1+\2", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*منهای\s*(\d+(?:\.\d+)?)", r"\1-\2", t)
    return t


def _safe_math_eval(expr: str) -> float:
    """Safely evaluate a mathematical expression."""
    if not expr or not expr.strip():
        raise _MathError("عبارت خالی است")

    expr = normalize_math_expression(expr)
    if not expr:
        raise _MathError("عبارت خالی است")

    allowed_pattern = re.compile(r"^[\d\s\+\-\*\/\%\(\)\.\,\_\w]+$")
    if not allowed_pattern.match(expr):
        raise _MathError("عبارت شامل نویسهٔ غیرمجاز است")

    forbidden_patterns = [
        r"\bimport\b",
        r"__",
        r"\beval\b",
        r"\bexec\b",
        r"\bcompile\b",
        r"\bopen\b",
        r"\bread\b",
        r"\bwrite\b",
        r"\bos\b",
        r"\bsys\b",
        r"\bsubprocess\b",
        r"\blambda\b",
        r"\bdef\s",
        r"\bclass\s",
        r"\byield\b",
    ]
    for pattern in forbidden_patterns:
        if re.search(pattern, expr):
            raise _MathError("الگوی غیرمجاز در عبارت")

    if len(expr) > 200:
        raise _MathError("عبارت خیلی بلند است")

    try:
        code = compile(expr, "<math>", "eval")
        for name in code.co_names:
            if name not in _SAFE_MATH_NAMES:
                raise _MathError(f"نام ناشناخته: {name}")

        result = eval(code, {"__builtins__": {}}, _SAFE_MATH_NAMES)

        if not isinstance(result, (int, float)):
            raise _MathError("نتیجه عدد نیست")

        if isinstance(result, float) and (math.isnan(result) or math.isinf(result)):
            raise _MathError("نتیجه نامعتبر است")

        return float(result)

    except _MathError:
        raise
    except ZeroDivisionError:
        raise _MathError("تقسیم بر صفر")
    except OverflowError:
        raise _MathError("عدد خیلی بزرگ است")
    except SyntaxError:
        raise _MathError("نحو عبارت نامعتبر است")
    except Exception as e:
        raise _MathError(f"خطای محاسبه: {e}")


def _format_math_result(value: float) -> str:
    """Format a float result nicely for display."""
    if isinstance(value, float) and value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.10g}"


def calculate_math(expr: str) -> str:
    """Evaluate an expression; return formatted result or a Persian error string."""
    try:
        result = _safe_math_eval(expr)
        return _format_math_result(result)
    except _MathError as e:
        return f"خطا: {e}"


def _friendly_math_error(message: str) -> str:
    cleaned = message.removeprefix("خطا:").strip()
    for key, friendly in MATH_FRIENDLY_ERROR_MESSAGES.items():
        if key in cleaned:
            return friendly
    return f"این محاسبه درست انجام نشد ({cleaned}). بیای جور دیگه‌ای بنویسیم."


def extract_math_expressions(text: str, *, limit: int = 5) -> list[str]:
    """Pull candidate arithmetic expressions out of free-form user text."""
    if not text or not text.strip():
        return []
    normalized = preprocess_math_natural_language(text)
    found: list[str] = []
    seen: set[str] = set()
    for match in _MATH_EXPR_RE.finditer(normalized):
        raw = match.group(0).strip()
        cleaned = normalize_math_expression(raw)
        if not cleaned or cleaned in seen:
            continue
        # Skip bare numbers without an operator / function call
        if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
            continue
        if not any(op in cleaned for op in ("+", "-", "*", "/", "%", "(")):
            continue
        seen.add(cleaned)
        found.append(cleaned)
        if len(found) >= limit:
            break
    return found


def run_math_tool_for_message(
    text: str, *, persona: str | None = None, limit: int = 5
) -> list[MathToolUsage]:
    """Extract and evaluate math expressions when persona is teacher/homework."""
    if persona is not None and persona not in _MATH_PERSONAS:
        return []
    usages: list[MathToolUsage] = []
    for expr in extract_math_expressions(text, limit=limit):
        try:
            value = _safe_math_eval(expr)
            usages.append(
                MathToolUsage(
                    expression=expr,
                    result=_format_math_result(value),
                    ok=True,
                )
            )
        except _MathError as exc:
            usages.append(
                MathToolUsage(
                    expression=expr,
                    result=_friendly_math_error(str(exc)),
                    ok=False,
                )
            )
    return usages


def format_math_tool_context(usages: list[MathToolUsage]) -> str | None:
    """Build the system-prompt block for math tool results (ok + friendly errors)."""
    if not usages:
        return None
    lines = [
        MATH_TOOL_CONTEXT_INSTRUCTION,
        "",
        MATH_TOOL_CONTEXT_HEADER,
    ]
    for item in usages:
        if item.ok:
            lines.append(f"- `{item.expression}` = {item.result}")
        else:
            lines.append(f"- `{item.expression}` → {item.result}")
    return "\n".join(lines)
