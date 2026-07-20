"""
title: یار کودک (DEPRECATED)
author: Yar Kids
version: 0.6.5
description: [DEPRECATED] منطق محلی Pipe — از api/pipe/pipe.py (کلاینت API) و سرویس api/ استفاده کنید
required_open_webui_version: 0.5.0

DEPRECATED: This monolithic OpenWebUI Pipe runs all Yar Kids logic in-process.
Prefer the standalone FastAPI service under ``api/`` plus the thin OpenWebUI
client at ``api/pipe/pipe.py``. Kept only for generating a single-file embedded
artifact via ``api/pipe/generate-logic-pipe.py`` and for historical reference.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import AsyncIterator
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Protocol, Union

from pydantic import BaseModel, Field

warnings.warn(
    "api.pipe.pipe_logic is deprecated. Use the Yar Kids API (api/) with "
    "api/pipe/pipe.py as the OpenWebUI client instead.",
    DeprecationWarning,
    stacklevel=2,
)

# ---------------------------------------------------------------------------
# Math tool for safe evaluation of arithmetic expressions
# Used by homework and teacher personas to verify calculations
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_ID = "yarkids"
MODEL_NAME = "یار کودک"
MAX_GENERATION_ATTEMPTS = 3
INTENT_CONFIDENCE_THRESHOLD = 0.7
MANUAL_PERSONA_METADATA_KEY = "yarkids_persona"
ACTIVE_PERSONA_METADATA_KEY = "yarkids_active_persona"
PENDING_PERSONA_METADATA_KEY = "yarkids_pending_persona"
# Legacy HTML marker (may still appear in older chat history).
_PERSONA_MARKER_RE = re.compile(r"<!--\s*yarkids:([a-z_]+)\s*-->", re.IGNORECASE)
# Invisible sticky marker: Word Joiner + 2 zero-width chars + Word Joiner.
# Zero-width space/non-joiner/joiner encode the persona without showing in the UI.
_ZW_MARK = "\u2060"
_ZW_DIGIT = {"0": "\u200b", "1": "\u200c", "2": "\u200d"}
_ZW_DIGIT_INV = {v: k for k, v in _ZW_DIGIT.items()}
_PERSONA_ZW_CODE: dict[str, str] = {
    "creative": "00",
    "storyteller": "01",
    "teacher": "02",
    "homework": "10",
    "gamer": "11",
}
_ZW_CODE_PERSONA: dict[str, str] = {v: k for k, v in _PERSONA_ZW_CODE.items()}
_ZW_PERSONA_MARKER_RE = re.compile(
    f"{_ZW_MARK}([{_ZW_DIGIT['0']}{_ZW_DIGIT['1']}{_ZW_DIGIT['2']}]{{2}}){_ZW_MARK}"
)
PERSONA_AUTO_VALUE = "auto"
SUPPORTED_PERSONAS = ("creative", "storyteller", "teacher", "homework", "gamer")
REVISION_INSTRUCTION_HEADER = "بازبینی لازم است. پاسخ قبلی مناسب نبود. دلایل:"
TEXTBOOK_CONTEXT_HEADER = (
    "متن کتاب درسی بازیابی‌شده (مرجع — برای راهنمایی آموزشی؛ جواب نهایی را بدون آموزش روش نده):"
)
TEXTBOOK_CONTEXT_INSTRUCTION = (
    "مهم: متن واقعی صفحهٔ کتاب درسی در ادامه آمده است. "
    "فقط و فقط از همین متن برای کمک به کودک استفاده کن. "
    "چیزی از خودت به متن اضافه نکن و محتوای صفحه را حدس نزن. "
    "**همین حالا همین صفحه را در اختیار داری.** "
    "مستقیم و مهربان با محتوای همین صفحه کمک را شروع کن "
    "(مثلاً بگو در این صفحه چه تمرینی هست و از کجا شروع کنیم). "
    "اگر کودک خواست متن را بنویسی یا کلمات سخت را مشخص کنی، از همین متن استفاده کن. "
    "اگر چند صفحه از یک درس آمده، برای «کل درس / بقیهٔ درس / کلمات سخت درس» از همهٔ صفحات استفاده کن "
    "و از کودک نخواه صفحهٔ بعد را خودش باز کند. "
    "ممنوع: پرسیدن دوبارهٔ پایه/کتاب/صفحه؛ گفتن «صبر کن صفحه را باز کنم»؛ "
    "خواستنِ «یک خط از صفحه را بنویس» وقتی متن صفحه را داری؛ "
    "نوشتن پرانتز یا توضیح دربارهٔ سیستم/پرامپت/کانتکست؛ "
    "وانمود کردن که هنوز صفحه نرسیده. "
    "اگر تصویر صفحه هم ضمیمه شد، آن را «صفحهٔ کتاب» بنام — نه تصویر ارسالی کودک "
    "(مگر واقعاً در تاریخچهٔ کاربر تصویر آمده باشد)."
)
TEXTBOOK_IMAGE_ONLY_INSTRUCTION = (
    "مهم: متن این صفحه از فایل کتاب به‌درستی استخراج نشد و متنِ زیر ناخواناست، "
    "اما تصویر صفحه پیوست شده است. "
    "فقط و فقط محتوای صفحه را از روی «تصویر پیوست‌شده» بخوان و به کودک کمک کن. "
    "به متن ناخوانای زیر استناد نکن و محتوای صفحه را از خودت حدس نزن. "
    "این تصویر، ضمیمهٔ مرجع از پایگاه کتاب است و تصویر ارسالیِ کاربر نیست؛ "
    "پس هرگز نگو «تصویری که فرستادی» مگر اینکه واقعاً کاربر تصویری فرستاده باشد. "
    "دربارهٔ سیستم یا فرستادن تصویر حرف نزن؛ مستقیم از روی صفحه کمک کن. "
    "**ممنوع:** گفتن «کتاب‌ها ممکن است تغییر کنند» یا خواستنِ یک خط از صفحه وقتی تصویر صفحه را داری."
)
TEXTBOOK_UNREADABLE_INSTRUCTION = (
    "توجه مهم: صفحهٔ درخواستی پیدا شد، اما متن آن از فایل کتاب ناخوانا استخراج شد "
    "و تصویری هم برای نمایش در دسترس نیست. "
    "به‌هیچ‌وجه محتوای صفحه، شعر، متن یا تمرین را از خودت نساز و حدس نزن. "
    "صادقانه و مهربان به کودک بگو الان نتوانستی متن این صفحه را درست بخوانی، "
    "و از او بخواه بخشی از متن یا سوالش را خودش بنویسد تا با هم کار کنید. "
    "دربارهٔ سیستم یا پرامپت حرف نزن."
)
TEXTBOOK_LOOKUP_FAILED_INSTRUCTION = (
    "توجه مهم: کودک صفحه/درس مشخصی خواسته، اما متن آن صفحه الان در پرامپت نیست "
    "(پیدا نشد یا سرویس در دسترس نبود). "
    "به‌هیچ‌وجه محتوای آن صفحه/درس را از خودت نساز و حدس نزن "
    "(حتی نام یا موضوع درس را هم از خودت نگو). "
    "**هرگز نگو «به کتابت دسترسی ندارم» و هرگز دربارهٔ سیستم/پرامپت/صبر برای باز شدن صفحه حرف نزن.** "
    "اگر پایه و کتاب و شمارهٔ صفحه را قبلاً گفته: مهربان بگو الان نتوانستی همان صفحه را پیدا کنی "
    "و بخواه یک خط از تمرین یا صورت سوال را خودش بنویسد. "
    "اگر یکی از این سه تا را نگفته: فقط همان موردِ گم‌شده را بپرس "
    "(صفحه؟ پایه؟ کدام کتاب؟). "
    "هرگز وانمود نکن که متن یا تصویری را می‌بینی که نداری."
)
TEXTBOOK_NEED_INFO_INSTRUCTION = (
    "توجه: کودک دربارهٔ تمرین/درس/صفحهٔ کتاب صحبت می‌کند، اما هنوز اطلاعات کافی برای "
    "پیدا کردن دقیق صفحه نداری. "
    "**هرگز نگو «به کتابت دسترسی ندارم» و دربارهٔ سیستم حرف نزن.** "
    "مهربان و کوتاه فقط مواردی را که هنوز نمی‌دانی بپرس: "
    "۱) شمارهٔ صفحه؟ ۲) کلاس چندم؟ ۳) کدام کتاب/درس؟ "
    "محتوای صفحه را از خودت نساز؛ فقط اطلاعات لازم را بپرس."
)
DEFAULT_TEXTBOOK_TIMEOUT_SEC = 5.0

WEB_SEARCH_CONTEXT_HEADER = (
    "نتایج جستجوی اینترنت (مرجع به‌روز — فقط برای حقایق؛ چیز ساختگی اضافه نکن):"
)
WEB_SEARCH_CONTEXT_INSTRUCTION = (
    "مهم: نتایج واقعی جستجوی وب در ادامه آمده است. "
    "اگر سؤال کودک به اطلاعات واقعی/به‌روز نیاز دارد (بازی، واقعیت، راهنما)، "
    "فقط از همین نتایج استفاده کن و چیزی از خودت اختراع نکن. "
    "**ممنوع بدون استناد به همین نتایج:** گفتن «این بازی وجود ندارد»، "
    "«هنوز ساخته/منتشر نشده»، یا تصحیح نام بازی به نسخهٔ دیگر. "
    "اگر نتایج می‌گویند بازی اعلام/منتشر شده، همان را ملایم و مناسب سن بگو؛ "
    "اگر نتایج مبهم‌اند، بگو مطمئن نیستی — حدس نزن. "
    "محتوای نامناسب سن، خشن یا بزرگسال را از نتایج نادیده بگیر. "
    "لینک خام یا آدرس سایت را برای کودک نخوان مگر خیلی لازم باشد؛ "
    "به‌جایش خلاصهٔ ساده و ایمن بگو. "
    "دربارهٔ سیستم، سرچ، یا «اینترنت» به‌صورت فنی حرف نزن — "
    "مثل دوستی که چیزها را می‌داند جواب بده. "
    "اگر نتایج کافی نبودند، صادقانه بگو مطمئن نیستی و حدس نزن."
)
WEB_SEARCH_NO_RESULTS_INSTRUCTION = (
    "توجه: کودک دربارهٔ یک بازی یا واقعیت صحبت می‌کند، اما الان نتایج جستجوی وب "
    "در پرامپت نیست (پیدا نشد یا سرویس در دسترس نبود). "
    "**هرگز نگو این بازی وجود ندارد / هنوز ساخته نشده / منتشر نشده** مگر کاملاً مطمئن باشی. "
    "اگر مطمئن نیستی: هیجان‌زده با علاقه‌اش همراهی کن، بگو جزئیات دقیق را الان مطمئن نیستی، "
    "و بپرس دوست دارد دربارهٔ چه چیز بازی حرف بزنید یا بازی کلامی کنید. "
    "دربارهٔ سیستم یا جستجو حرف نزن."
)
DEFAULT_WEB_SEARCH_TIMEOUT_SEC = 8.0
DEFAULT_WEB_SEARCH_MAX_RESULTS = 5

# Lightweight heuristic (pipe-side) — mirrors textbook-service page queries
_TEXTBOOK_PAGE_QUERY_RE = re.compile(
    r"(?:صفحه|صفحهٔ|ص\.?)\s*[\d۰-۹٠-٩]+",
    re.IGNORECASE,
)
# Anchor detection for Persian number-words like «بیست و یکم»:
# we only need to detect the presence of the page marker keyword.
_TEXTBOOK_PAGE_MARKER_RE = re.compile(r"(?:صفحه|صفحهٔ|ص\.?)", re.IGNORECASE)
# Lesson / chapter reference (درس دوازدهم، فصل سوم، فصل یک، درس ۱۲).
_TEXTBOOK_LESSON_RE = re.compile(
    r"(?:درس|فصل)\s*(?:[\d۰-۹٠-٩]+|اول|یکم|یک|دوم|دو|سوم|سه|چهارم|چهار|پنجم|پنج|ششم|شش|"
    r"هفتم|هفت|هشتم|هشت|نهم|نه|دهم|ده|"
    r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|هفدهم|هجدهم|نوزدهم|بیستم)",
    re.IGNORECASE,
)
# Explicit page number after a page marker (Persian or ASCII digits).
_TEXTBOOK_PAGE_NUMBER_RE = re.compile(
    r"(?:صفحه|صفحهٔ|صفحه‌ی|ص\.?)\s*([\d۰-۹٠-٩]+)",
    re.IGNORECASE,
)
# Relative page references: «صفحه بعد/بعدی»، «بعدش»، «صفحه قبل/قبلی»، «قبلش»،
# «بریم صفحه بعد»، «صفحه بعدی».
_TEXTBOOK_NEXT_PAGE_RE = re.compile(
    r"(?:صفحه[\s\u200cٔی]*بعد(?:ی|ش)?|بعدش|صفحه‌ی?\s*بعد|بریم\s+(?:به\s+)?صفحه\s*بعد)",
    re.IGNORECASE,
)
_TEXTBOOK_PREV_PAGE_RE = re.compile(
    r"(?:صفحه[\s\u200cٔی]*قبل(?:ی|ش)?|قبلش|صفحه‌ی?\s*قبل|بریم\s+(?:به\s+)?صفحه\s*قبل)",
    re.IGNORECASE,
)
_PERSIAN_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# Persian number words that can follow «صفحه» to form a page reference.
_TEXTBOOK_PAGE_NUMBER_WORDS: frozenset[str] = frozenset({
    "اول", "یکم", "یک", "دوم", "دو", "سوم", "سه", "چهارم", "چهار", "پنجم", "پنج",
    "ششم", "شش", "هفتم", "هفت", "هشتم", "هشت", "نهم", "نه", "دهم", "ده",
    "یازدهم", "یازده", "دوازدهم", "دوازده", "سیزدهم", "سیزده", "چهاردهم", "چهارده",
    "پانزدهم", "پانزده", "شانزدهم", "شانزده", "هفدهم", "هفده", "هجدهم", "هجده",
    "نوزدهم", "نوزده", "بیست", "بیستم", "سی", "چهل", "پنجاه", "شصت", "هفتاد",
    "هشتاد", "نود", "صد",
})
_TEXTBOOK_PAGE_WORD_AFTER_RE = re.compile(
    r"(?:صفحه|صفحهٔ|صفحه‌ی|ص\.?)\s+(\S+)",
    re.IGNORECASE,
)
_TEXTBOOK_GRADE_QUERY_RE = re.compile(
    r"(?:پایه|کلاس)\s*[\d۳۴۵۶سومچهارمپنجمشش]+|پایه\s*(?:سوم|چهارم|پنجم|ششم)",
    re.IGNORECASE,
)
# Standalone grade token (e.g. bare «ششم») used to carry the grade forward
# across turns without dragging along an old page reference.
_TEXTBOOK_GRADE_TOKEN_RE = re.compile(
    r"(?:پایه|کلاس)\s*[\d۳۴۵۶٣٤٥٦]+|سوم|چهارم|پنجم|ششم",
    re.IGNORECASE,
)
# Also accept «چهارمم / ششمی» spoken forms.
_TEXTBOOK_GRADE_CASUAL_RE = re.compile(
    r"(?:کلاس|پایه)?\s*(سوم|چهارم|پنجم|ششم)م?",
    re.IGNORECASE,
)
_TEXTBOOK_SUBJECT_KEYWORDS: tuple[str, ...] = (
    "ریاضی",
    "فارسی",
    "علوم",
    "نگارش",
    "مطالعات",
    "اجتماعی",
    "قرآن",
    "هدیه",
    "تفکر",
    "فناوری",
    "کتاب",
)
# Real subjects (excludes the generic word «کتاب») for carrying forward.
_TEXTBOOK_SUBJECT_TOKENS: tuple[str, ...] = _TEXTBOOK_SUBJECT_KEYWORDS[:-1]

SAFE_FALLBACK_RESPONSE = (
    "متأسفم، الان نتوانستم پاسخ مناسبی برایت بدهم. "
    "بیایید با هم یک موضوع دیگر را امتحان کنیم! "
    "می‌توانی دربارهٔ یک داستان، یک سوال درسی، یا یک ایدهٔ خلاقانه از من بپرسی."
)

# Child-friendly labels for persona dropdown and status messages.
PERSONA_UI_LABELS: dict[str, str] = {
    "auto": "✨ خودکار",
    "creative": "🎨 خلاق",
    "storyteller": "📖 داستان‌گو",
    "teacher": "📚 معلم",
    "homework": "✏️ کمک‌درس",
    "gamer": "🎮 بازی و سرگرمی",
    "none": "😊 یار کودک",
}

PERSONA_DROPDOWN_OPTIONS: list[dict[str, str]] = [
    {"value": "auto", "label": "✨ خودکار — خودم انتخاب می‌کنم!"},
    {"value": "creative", "label": "🎨 خلاق"},
    {"value": "storyteller", "label": "📖 داستان‌گو"},
    {"value": "teacher", "label": "📚 معلم"},
    {"value": "homework", "label": "✏️ کمک‌درس"},
    {"value": "gamer", "label": "🎮 بازی و سرگرمی"},
]

STREAM_CHUNK_SIZE = 16
# Brief pause so the UI can paint status before it is cleared for streaming.
STATUS_DISPLAY_PAUSE_SEC = 0.12

# Prompts live under api/prompts/ (sibling of this package directory).
PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PersonaId = Literal["creative", "storyteller", "teacher", "homework", "gamer", "none"]
ReflectionStatus = Literal["PASS", "REVISE"]
VALID_PERSONAS: set[PersonaId] = {
    "creative",
    "storyteller",
    "teacher",
    "homework",
    "gamer",
    "none",
}
TEXTBOOK_PERSONAS: frozenset[PersonaId] = frozenset({"teacher", "homework"})
WEB_SEARCH_PERSONAS: frozenset[PersonaId] = frozenset(
    {"creative", "storyteller", "gamer"}
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class IntentDetectionResult(BaseModel):
    persona: PersonaId
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class PersonaResolution(BaseModel):
    """Result of sticky persona resolution (may ask before switching)."""

    persona: PersonaId
    pending_switch_to: PersonaId | None = None
    ask_confirmation: bool = False


class ReflectionResult(BaseModel):
    status: ReflectionStatus
    reasons: list[str] | None = None


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    stream: bool = False
    temperature: float | None = None


class TextbookContext(BaseModel):
    matched: bool = False
    match_type: str | None = None
    grade: int | None = None
    subject: str | None = None
    subject_title: str | None = None
    page: int | None = None
    context_text: str | None = None
    needs_image: bool = False
    image_base64: str | None = None
    images_base64: list[str] = Field(default_factory=list)
    page_query_failed: bool = False
    need_info: bool = False
    text_usable: bool = True
    error: str | None = None


class WebSearchResult(BaseModel):
    title: str = ""
    url: str | None = None
    snippet: str = ""


class WebSearchContext(BaseModel):
    matched: bool = False
    query: str | None = None
    results: list[WebSearchResult] = Field(default_factory=list)
    context_text: str | None = None
    provider: str | None = None
    error: str | None = None



class TextbookQueryDiag(BaseModel):
    """Diagnostics for textbook context lookup."""

    query_sent: str | None = None
    matched: bool = False
    context_preview: str | None = None
    grade: int | None = None
    subject: str | None = None
    subject_title: str | None = None
    page: int | None = None
    error: str | None = None
    need_info: bool = False
    page_query_failed: bool = False


class WebSearchQueryDiag(BaseModel):
    """Diagnostics for web search lookup."""

    query_sent: str | None = None
    provider_used: str | None = None
    matched: bool = False
    results_count: int = 0
    error: str | None = None


class LLMClient(Protocol):
    async def complete(self, request: LLMCompletionRequest) -> str: ...


IntentDetectionResult.model_rebuild()
ReflectionResult.model_rebuild()
ChatMessage.model_rebuild()
MathToolUsage.model_rebuild()
TextbookQueryDiag.model_rebuild()
WebSearchQueryDiag.model_rebuild()


# ---------------------------------------------------------------------------
# Prompt loading (from .md files under api/prompts/)
# ---------------------------------------------------------------------------

_prompt_cache: dict[str, str] = {}


def _load_prompt(relative_path: str) -> str:
    """Load and cache a markdown prompt file from the prompts directory."""
    if relative_path in _prompt_cache:
        return _prompt_cache[relative_path]

    path = PROMPTS_DIR / relative_path
    text = path.read_text(encoding="utf-8").strip()
    _prompt_cache[relative_path] = text
    return text


def get_core_prompt() -> str:
    return _load_prompt("core.md")


def get_persona_prompt(persona: PersonaId) -> str | None:
    if persona == "none":
        return None
    if persona not in SUPPORTED_PERSONAS:
        return None
    return _load_prompt(f"personas/{persona}.md")


def get_intent_detection_prompt() -> str:
    return _load_prompt("intent_detection.md")


def get_reflection_prompt() -> str:
    template = _load_prompt("reflection.md")
    return template.replace("{{CORE_PROMPT}}", get_core_prompt())


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


async def _await_if_needed(value: Any) -> Any:
    """Await coroutines; return plain values unchanged (OpenWebUI version compat)."""
    if inspect.isawaitable(value):
        return await value
    return value


def get_persona_ui_label(persona: PersonaId | str) -> str:
    """Return a child-friendly persona label for UI status messages."""
    return PERSONA_UI_LABELS.get(str(persona), PERSONA_UI_LABELS["none"])


def status_detecting_persona() -> str:
    return "😊 دارم شخصیت مناسب رو پیدا می‌کنم..."


def status_persona_selected(persona: PersonaId) -> str:
    label = get_persona_ui_label(persona)
    return f"🎭 شخصیت {label} انتخاب شد! بزن بریم..."


def status_generating_response(attempt: int, max_attempts: int) -> str:
    return f"✨ دارم جواب قشنگت رو می‌نویسم... ({attempt} از {max_attempts})"


def status_reviewing_response() -> str:
    return "🔍 یه لحظه! دارم چک می‌کنم همه‌چیز عالی باشه..."


def status_reflection_disabled() -> str:
    return "⚡ بازبینی پاسخ خاموش است — مستقیم جواب می‌دم..."


def status_fetching_textbook() -> str:
    return "📖 دارم صفحهٔ کتاب درسی رو پیدا می‌کنم..."


def status_textbook_unavailable() -> str:
    return "⚠️ نتونستم به سرویس کتاب درسی وصل بشم..."


def status_fetching_web_search() -> str:
    return "🔎 دارم توی اینترنت دنبال اطلاعات می‌گردم..."


def status_web_search_unavailable() -> str:
    return "⚠️ جستجوی اینترنت الان در دسترس نبود..."


def status_calculating_math() -> str:
    return "🔢 دارم حساب می‌کنم..."


def coerce_bool(value: Any, *, default: bool = True) -> bool:
    """Robust bool coercion for OpenWebUI valves (bool / 0-1 / 'true'|'false')."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on", "بله"}:
            return True
        if normalized in {"0", "false", "no", "off", "خیر", ""}:
            return False
    return default


def read_valve_bool(valves: Any, name: str, *, default: bool = True) -> bool:
    """Read a boolean valve whether valves is a Pydantic model or a plain dict."""
    if valves is None:
        return default
    if isinstance(valves, dict):
        return coerce_bool(valves.get(name, default), default=default)
    return coerce_bool(getattr(valves, name, default), default=default)


def _format_textbook_debug(*, query: str, api_url: str, context: TextbookContext) -> str:
    short_query = query if len(query) <= 60 else query[:57] + "..."
    if context.error:
        return f"🐞 دیباگ کتاب | خطا: {context.error} | URL: {api_url}"
    if context.matched:
        return (
            f"🐞 دیباگ کتاب | ✅ یافت شد: پایه {context.grade} "
            f"{context.subject_title or context.subject} صفحه {context.page} "
            f"({context.match_type}) | کوئری: «{short_query}»"
        )
    return (
        f"🐞 دیباگ کتاب | ❌ چیزی یافت نشد (matched=false) | "
        f"کوئری: «{short_query}» | URL: {api_url}"
    )


def looks_like_textbook_page_query(text: str) -> bool:
    """True when the user message likely refers to a specific textbook page/lesson/topic."""
    if not text.strip():
        return False
    if _relative_page_delta(text) != 0:
        return True
    if _textbook_wants_whole_lesson(text):
        return True
    if _textbook_has_topic_intent(text):
        return True
    has_page = bool(_TEXTBOOK_PAGE_MARKER_RE.search(text))
    has_lesson = _textbook_has_lesson(text)
    has_grade = bool(_TEXTBOOK_GRADE_QUERY_RE.search(text)) or bool(
        _TEXTBOOK_GRADE_TOKEN_RE.search(text)
    )
    has_subject = any(kw in text for kw in _TEXTBOOK_SUBJECT_KEYWORDS)
    if has_lesson:
        return True
    return has_page and (has_grade or has_subject)


# Words that signal the child is talking about their schoolbook / homework
# exercise but may not yet have given enough detail (grade + book + page) to
# run a lookup. Used to ask for the missing info instead of guessing.
_TEXTBOOK_HELP_MARKERS: tuple[str, ...] = (
    "کتاب",
    "تمرین",
    "صفحه",
    "درس",
    "فصل",
    "مسئله",
    "مسأله",
    "سوال",
    "سؤال",
    "تکلیف",
    "فعالیت",
    "مربوط",
)

_TEXTBOOK_TOPIC_INTENT_MARKERS: tuple[str, ...] = (
    "مربوط",
    "کجای کتاب",
    "کجاى کتاب",
    "کجا در کتاب",
    "درباره",
    "معنی",
    "شعر",
    "داستان",
    "فعالیت",
    "کار در کلاس",
)

_TEXTBOOK_WHOLE_LESSON_RE = re.compile(
    r"(?:"
    r"کل\s*درس|تمام\s*درس|همهٔ?\s*(?:ی\s*)?درس|کلّ?\s*درس|"
    r"بقیهٔ?\s*(?:ی\s*)?درس|ادامهٔ?\s*(?:ی\s*)?درس|"
    r"صفحه\s*های\s*(?:این\s+)?درس|کل\s*صفحه\s*های\s*درس|"
    r"کلم(?:ه|ات)\s*(?:سخت\s*)?(?:ی\s*)?(?:داخل\s+|توی\s+|در\s+)?(?:کل\s+|تمام\s+)?درس|"
    r"همهٔ?\s*(?:ی\s*)?صفحه\s*های\s*درس"
    r")",
    re.IGNORECASE,
)


def looks_like_textbook_help_request(text: str) -> bool:
    """True when the child references their schoolbook/homework in some way."""
    if not text.strip():
        return False
    return any(marker in text for marker in _TEXTBOOK_HELP_MARKERS)


# Factual / info-seeking cues — decide WHEN to search (not what the answer is).
_WEB_SEARCH_NEED_RE = re.compile(
    r"(?:"
    r"چطور|چگونه|چیه|چیست|چی\s*هست|چی\s*شده|کجاست|کجا\s*(?:پیدا|میس?شه)|"
    r"کی\s*(?:هست|بود|ساخته)|چرا\s*(?:این|اون)|آپدیت|نسخه|ورژن|"
    r"منتشر|اومده|وجود\s*داره|واقعیه|"
    r"تحقیق|جستجو|سرچ|اینترنت|نصب(?:ش|ش؟\s*کن)?"
    r"|درباره(?:\s*ی|\s*ٔ)?"
    r"|اسم\s*(?:بازی|شخصیت)|قهرمان|آیتم|مود|اسکین|"
    r"how\s+to|what\s+is|where\s+(?:is|can)|who\s+is|"
    r"\?|؟"
    r")",
    re.IGNORECASE,
)

# Named title + version (e.g. «فورزا هورایزن ۶»، «Horizon 5»).
_WEB_SEARCH_GAME_VERSION_RE = re.compile(
    r"(?:"
    r"[A-Za-z][A-Za-z0-9:'-]{1,}(?:\s+[A-Za-z][A-Za-z0-9:'-]{1,}){0,4}\s*[\d۰-۹]{1,2}"
    r"|"
    r"[\u0600-\u06FF]{2,}(?:\s+[\u0600-\u06FF]{2,}){0,4}\s*[\d۰-۹]{1,2}"
    r")",
)

# Talking about a specific game even without a question mark.
_WEB_SEARCH_GAME_TALK_RE = re.compile(
    r"(?:"
    r"بازی\s+(?!کنیم|کنیم!|کلم|فکری|عددی)"
    r"[\w\u0600-\u06FF]"
    r"|"
    r"(?:دوست\s*دارم|بازی\s*می‌?کنم|بازی\s*کردم|بلدی|شناختی)\b"
    r")",
    re.IGNORECASE,
)

# Latest turn refers to an earlier topic («دربارش تحقیق کن»).
_WEB_SEARCH_REFERRING_RE = re.compile(
    r"(?:"
    r"دربار(?:هٔ?|ه‌ی?|ش)|همین|اون(?:و)?|همان|"
    r"تحقیق\s*کن|سرچ\s*کن|جستجو\s*کن|بیشتر\s*بگو|"
    r"پیداش?\s*کن|بگرد|اینترنت"
    r")",
    re.IGNORECASE,
)

# Pure creative/play turns where search is usually noise.
_WEB_SEARCH_SKIP_RE = re.compile(
    r"(?:"
    r"داستان\s*(?:بگو|کوتاه)|قصه\s*بگو|ادامه\s*بده|"
    r"بازی\s*کنیم|یه\s*بازی\s*(?:کلم|فکری|عددی|سریع)?|"
    r"یه\s*ایده|ایده\s*بده|"
    r"حوصله.?م\s*سر|چی\s*کار\s*کنم|نقاشی\s*کن|"
    r"بسازیم|بیا\s*بازی"
    r")",
    re.IGNORECASE,
)

_WEB_SEARCH_LIKE_TAIL_RE = re.compile(
    r"(?:"
    r"(?:\s+من)?\s+خیلی\s+دوست\s+دارم\.?\s*$"
    r"|\s+دوست\s+دارم\.?\s*$"
    r"|\s+بازی\s+می‌?کنم\.?\s*$"
    r"|\s+بازی\s+کردم\.?\s*$"
    r"|\s+رو\s+بلدی\??\s*$"
    r"|\s+رو\s+می‌?شناسی\??\s*$"
    r")",
    re.IGNORECASE,
)

# Strip chat fluff so the search box gets the topic, not «میتونی تحقیق کنی».
_WEB_SEARCH_CHAT_FILLERS: frozenset[str] = frozenset(
    {
        "درباره",
        "درباره‌ی",
        "دربارهٔ",
        "دربارش",
        "ی",
        "یه",
        "یک",
        "من",
        "تو",
        "این",
        "اون",
        "هم",
        "همون",
        "همین",
        "میتونی",
        "می‌تونی",
        "میشه",
        "می‌شه",
        "تحقیق",
        "کنی",
        "کن",
        "ببینی",
        "ببین",
        "چیه",
        "چیست",
        "چی",
        "میخوام",
        "می‌خوام",
        "نصبش",
        "نصب",
        "کنم",
        "برام",
        "بهم",
        "لطفا",
        "لطفاً",
        "بازیه",
        "انگار",
        "مثل",
        "شبیه",
        "خب",
        "مگه",
        "به",
        "از",
        "با",
        "رو",
        "را",
        "و",
        "یا",
        "که",
        "اینترنت",
        "دسترسی",
        "نداری",
        "داری",
        "سرچ",
        "جستجو",
        "بگو",
        "بده",
        "بگرد",
        "پیدا",
    }
)


def looks_like_web_search_request(
    text: str, *, persona: PersonaId | str | None = None
) -> bool:
    """True when the latest user turn likely needs a real web lookup."""
    cleaned = text.strip()
    if not cleaned:
        return False
    if _WEB_SEARCH_NEED_RE.search(cleaned):
        return True
    if _WEB_SEARCH_GAME_VERSION_RE.search(cleaned):
        return True
    if _WEB_SEARCH_SKIP_RE.search(cleaned):
        return False
    if persona == "gamer" and _WEB_SEARCH_GAME_TALK_RE.search(cleaned):
        if re.search(r"[A-Za-z]{3,}", cleaned) or re.search(
            r"[\u0600-\u06FF]{3,}", cleaned
        ):
            return True
    if len(cleaned) < 12:
        return False
    return False


def _strip_web_search_chat_fillers(text: str) -> str:
    tokens = re.split(r"[\s،,.?؟!؛:]+", text)
    kept = [
        tok
        for tok in tokens
        if tok
        and tok not in _WEB_SEARCH_CHAT_FILLERS
        and tok.lower() not in _WEB_SEARCH_CHAT_FILLERS
    ]
    return " ".join(kept).strip()


def _topic_from_user_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip())
    tightened = _WEB_SEARCH_LIKE_TAIL_RE.sub("", collapsed)
    tightened = re.sub(r"^\s*من\s+", "", tightened)
    tightened = re.sub(r"\s+", " ", tightened).strip(" .،!")
    return _strip_web_search_chat_fillers(tightened) or tightened


def build_web_search_query(messages: list[ChatMessage], *, max_len: int = 200) -> str:
    """Build a search query the way a person would type it into Google.

    Uses the child's own words (minus chat fluff). If they say «تحقیق کن دربارش»,
    pulls the topic from earlier turns — no name dictionaries / aliases.
    """
    user_texts = [
        message.content.strip()
        for message in messages
        if message.role == "user" and message.content.strip()
    ]
    if not user_texts:
        return ""

    latest = user_texts[-1]
    window = user_texts[-8:]

    topic_source = latest
    if _WEB_SEARCH_REFERRING_RE.search(latest) and len(window) >= 2:
        for text in reversed(window[:-1]):
            topic = _topic_from_user_text(text)
            if topic and len(topic) >= 2:
                topic_source = text
                break

    core = _topic_from_user_text(topic_source)
    if not core:
        core = re.sub(r"\s+", " ", latest).strip()
    if len(core) <= max_len:
        return core
    return core[: max_len - 1].rstrip() + "…"


def _web_search_query_variants(query: str) -> list[str]:
    """Light natural refinements only (same words + optional «بازی»)."""
    cleaned = query.strip()
    if not cleaned:
        return []
    variants = [cleaned]
    if "بازی" not in cleaned and "game" not in cleaned.lower():
        variants.append(f"{cleaned} بازی")
    return variants


def _format_web_search_debug(
    *, query: str, provider: str, context: WebSearchContext
) -> str:
    short_query = query if len(query) <= 60 else query[:57] + "..."
    if context.error:
        return f"🐞 دیباگ سرچ | خطا: {context.error} | provider={provider}"
    if context.matched:
        n = len(context.results)
        return (
            f"🐞 دیباگ سرچ | ✅ {n} نتیجه | provider={context.provider or provider} "
            f"| کوئری: «{short_query}»"
        )
    return (
        f"🐞 دیباگ سرچ | ❌ چیزی یافت نشد | provider={provider} "
        f"| کوئری: «{short_query}»"
    )


def _textbook_has_topic_intent(text: str) -> bool:
    return any(marker in text for marker in _TEXTBOOK_TOPIC_INTENT_MARKERS)


def _textbook_wants_whole_lesson(text: str) -> bool:
    return bool(_TEXTBOOK_WHOLE_LESSON_RE.search(text))


async def clear_status_message(
    __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
) -> None:
    """Hide the status bar after the response is complete (OpenWebUI events API)."""
    if not __event_emitter__:
        return
    await __event_emitter__(
        {
            "type": "status",
            "data": {"description": "", "done": True, "hidden": True},
        }
    )


def extract_text_from_completion(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    if not isinstance(response, dict):
        return str(response).strip()

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
    return str(response).strip()


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def extract_message_content(content: Any) -> str:
    """Flatten Open WebUI / OpenAI message content (str or multimodal parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                item_type = item.get("type")
                if item_type in {"text", "input_text", "output_text"}:
                    parts.append(str(item.get("text") or ""))
                elif "text" in item:
                    parts.append(str(item.get("text") or ""))
                elif "content" in item:
                    parts.append(extract_message_content(item.get("content")))
        return "\n".join(p for p in parts if p)
    if isinstance(content, dict):
        return extract_message_content(content.get("text") or content.get("content"))
    return str(content)


def normalize_messages(raw_messages: list[dict[str, Any]]) -> list[ChatMessage]:
    normalized: list[ChatMessage] = []
    for item in raw_messages:
        role = item.get("role")
        if role not in {"system", "user", "assistant"}:
            continue
        content = extract_message_content(item.get("content")).strip()
        if not content:
            continue
        normalized.append(ChatMessage(role=role, content=content))
    return normalized


def strip_persona_markers(text: str) -> str:
    """Remove sticky persona markers (invisible + legacy HTML) from text."""
    if not text:
        return text
    cleaned = _PERSONA_MARKER_RE.sub("", text)
    cleaned = _ZW_PERSONA_MARKER_RE.sub("", cleaned)
    # Also drop leftover Word Joiners that some clients render as tofu.
    cleaned = cleaned.replace("\u2060", "").replace("\ufeff", "")
    return cleaned.rstrip()


def append_persona_marker(text: str, persona: PersonaId) -> str:
    """Compatibility shim: never append visible/invisible junk to replies.

    Sticky persona is recovered from activity signals + metadata, not markers.
    """
    del persona  # markers disabled — they render as garbage in Open WebUI
    return strip_persona_markers(text) if text else text


def extract_persona_marker(text: str) -> PersonaId | None:
    """Decode legacy markers from older chats (current replies have none)."""
    if not text:
        return None
    zw_matches = _ZW_PERSONA_MARKER_RE.findall(text)
    if zw_matches:
        code = "".join(_ZW_DIGIT_INV.get(ch, "") for ch in zw_matches[-1])
        persona = _ZW_CODE_PERSONA.get(code)
        if persona:
            return persona  # type: ignore[return-value]
    html_matches = _PERSONA_MARKER_RE.findall(text)
    if html_matches:
        return _normalize_persona(html_matches[-1])
    return None


_GREETING_ONLY_RE = re.compile(
    r"^(?:"
    r"سلام(?:\s*علیکم)?|درود|هی+|hello|hi|hey|"
    r"صبح\s*بخیر|ظهر\s*بخیر|عصر\s*بخیر|شب\s*بخیر|"
    r"خوبی\??|چطوری\??|چه\s*خبر\??"
    r")[\s!.！؟?٫،,~]*$",
    re.IGNORECASE,
)


def _looks_like_greeting_only(text: str) -> bool:
    """True for bare greetings that must stay on persona none."""
    cleaned = text.strip()
    if not cleaned or len(cleaned) > 40:
        return False
    return bool(_GREETING_ONLY_RE.match(cleaned))


def _looks_like_welcome_or_menu(content: str) -> bool:
    """True for the first-turn persona picker / welcome message."""
    if "کدومش رو بیشتر دوست داری" in content:
        return True
    if "با هم آشنا شدیم" in content or "من «یار کودک» هستم" in content:
        # Welcome often lists all personas — do not treat as active session.
        hits = sum(
            1
            for signal in (
                "داستان‌گو",
                "داستان گو",
                "کمک‌درسی",
                "کمک درسی",
                "بازی و سرگرمی",
                "خلاق",
                "معلم",
            )
            if signal in content
        )
        return hits >= 3
    return False


_MENU_PERSONA_PICKS: dict[str, PersonaId] = {
    "بازی": "gamer",
    "سرگرمی": "gamer",
    "گیمر": "gamer",
    "بازی و سرگرمی": "gamer",
    "داستان": "storyteller",
    "قصه": "storyteller",
    "داستان‌گو": "storyteller",
    "داستان گو": "storyteller",
    "معلم": "teacher",
    "خلاق": "creative",
    "کمک‌درسی": "homework",
    "کمک درسی": "homework",
    "کمک‌درس": "homework",
    "کمک درس": "homework",
}


def _detect_menu_persona_pick(text: str) -> PersonaId | None:
    """Map short welcome-menu replies like «بازی» to a persona."""
    cleaned = text.strip()
    cleaned = re.sub(r"^[\s🎮🎨📖📚✏️]+", "", cleaned)
    cleaned = re.sub(r"[!.！؟?٫،,~]+$", "", cleaned).strip()
    if not cleaned or len(cleaned) > 30:
        return None
    if cleaned in _MENU_PERSONA_PICKS:
        return _MENU_PERSONA_PICKS[cleaned]
    lowered = cleaned.lower()
    for key, persona in sorted(_MENU_PERSONA_PICKS.items(), key=lambda item: -len(item[0])):
        if lowered == key.lower():
            return persona
    return None


def _last_assistant_is_welcome(messages: list[ChatMessage]) -> bool:
    for message in reversed(messages):
        if message.role == "assistant":
            return _looks_like_welcome_or_menu(message.content)
    return False


def _get_latest_user_message(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.content.strip():
            return message.content.strip()
    return ""


def _textbook_has_page(text: str) -> bool:
    return bool(_TEXTBOOK_PAGE_MARKER_RE.search(text))


def _textbook_has_lesson(text: str) -> bool:
    return bool(_TEXTBOOK_LESSON_RE.search(text))


def _textbook_has_page_reference(text: str) -> bool:
    """A resolvable page reference: «صفحه ۸» or «صفحه بیست و یکم» (not a bare «صفحه»)."""
    if _extract_page_number(text) is not None:
        return True
    match = _TEXTBOOK_PAGE_WORD_AFTER_RE.search(text)
    if match and match.group(1) in _TEXTBOOK_PAGE_NUMBER_WORDS:
        return True
    return False


def _textbook_has_anchor(text: str) -> bool:
    """A concrete reference the service can resolve: page, lesson, or relative page."""
    if _relative_page_delta(text) != 0:
        return True
    return _textbook_has_page_reference(text) or _textbook_has_lesson(text)


def _textbook_has_grade(text: str) -> bool:
    return bool(_TEXTBOOK_GRADE_TOKEN_RE.search(text))


def _textbook_has_subject(text: str) -> bool:
    return any(kw in text for kw in _TEXTBOOK_SUBJECT_KEYWORDS)


def _extract_grade_token(text: str) -> str | None:
    # Avoid confusing «سوم/چهارم/...» that appears as an exercise number
    # (e.g. «تمرین سوم») with the student's grade (e.g. «پایه ششم»).
    exercise_context = any(
        kw in text
        for kw in (
            "تمرین",
            "سوال",
            "سوالات",
            "شماره",
            "مسئله",
            "آزمایش",
            "صفحه تمرین",
        )
    )
    has_grade_keyword = any(kw in text for kw in ("پایه", "کلاس", "دبستان"))

    if exercise_context and not has_grade_keyword:
        return None

    match = _TEXTBOOK_GRADE_TOKEN_RE.search(text)
    if match:
        return match.group(0).strip()
    casual = _TEXTBOOK_GRADE_CASUAL_RE.search(text)
    if casual and (has_grade_keyword or casual.group(1)):
        # Normalize «چهارمم» → «چهارم»
        return casual.group(1)
    return None


def _extract_subject_token(text: str) -> str | None:
    """Pick the subject the user most likely means right now.

    When several subjects appear (e.g. «ریاضی تموم شد بریم سراغ فارسی صفحه ۴۱»),
    prefer the one closest to the page marker; otherwise the last mentioned.
    """
    hits: list[tuple[int, str]] = []
    for keyword in _TEXTBOOK_SUBJECT_TOKENS:
        start = 0
        while True:
            idx = text.find(keyword, start)
            if idx < 0:
                break
            hits.append((idx, keyword))
            start = idx + len(keyword)
    if not hits:
        return None

    page_match = _TEXTBOOK_PAGE_MARKER_RE.search(text)
    if page_match:
        page_pos = page_match.start()
        hits.sort(key=lambda item: (abs(item[0] - page_pos), -item[0]))
        return hits[0][1]

    hits.sort(key=lambda item: item[0])
    return hits[-1][1]


def _extract_page_number(text: str) -> int | None:
    match = _TEXTBOOK_PAGE_NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1).translate(_PERSIAN_DIGIT_MAP))
    except ValueError:
        return None


def _extract_page_word_phrase(text: str) -> str | None:
    """Return Persian number-word phrase after «صفحه» when digits are absent."""
    if _extract_page_number(text) is not None:
        return None
    match = _TEXTBOOK_PAGE_WORD_AFTER_RE.search(text)
    if not match:
        return None
    first = match.group(1)
    if first not in _TEXTBOOK_PAGE_NUMBER_WORDS:
        return None
    # Keep a short trailing phrase of number words (e.g. «بیست و یکم»).
    tail = text[match.start(1) :]
    tokens = re.split(r"\s+", tail.strip())
    kept: list[str] = []
    for token in tokens[:4]:
        cleaned = token.strip("،,.!?؟")
        if cleaned in _TEXTBOOK_PAGE_NUMBER_WORDS or cleaned == "و":
            kept.append(cleaned)
        else:
            break
    return " ".join(kept) if kept else None


def _extract_lesson_phrase(text: str) -> str | None:
    match = _TEXTBOOK_LESSON_RE.search(text)
    return match.group(0).strip() if match else None


def _compose_textbook_query(
    *,
    page: int | None = None,
    page_words: str | None = None,
    lesson_phrase: str | None = None,
    subject: str | None = None,
    grade: str | None = None,
) -> str:
    """Build a minimal query so old subjects in chat prose cannot leak in."""
    parts: list[str] = []
    if page is not None:
        parts.append(f"صفحه {page}")
    elif page_words:
        parts.append(f"صفحه {page_words}")
    elif lesson_phrase:
        parts.append(lesson_phrase)
    else:
        return ""
    if subject:
        parts.append(subject)
    if grade:
        parts.append(grade)
    return " ".join(parts)


def _relative_page_delta(text: str) -> int:
    """+1 for «صفحه بعد/بعدش»، -1 for «صفحه قبل/قبلش»، 0 otherwise."""
    if _TEXTBOOK_NEXT_PAGE_RE.search(text):
        return 1
    if _TEXTBOOK_PREV_PAGE_RE.search(text):
        return -1
    return 0


def _resolve_relative_page(recent_user_texts: list[str]) -> int | None:
    """Resolve «صفحه بعد/قبل» into a concrete page from earlier explicit pages.

    Walks the recent user turns, tracking the last explicit page number and
    applying +/-1 for each relative reference, so «صفحه ۷۸» → «بعدش» → «بعدش»
    correctly resolves to 80. Returns None when the latest turn is not a
    relative reference or no base page is known.
    """
    if not recent_user_texts:
        return None
    latest = recent_user_texts[-1]
    if _relative_page_delta(latest) == 0 or _extract_page_number(latest) is not None:
        return None
    current: int | None = None
    for text in recent_user_texts:
        explicit = _extract_page_number(text)
        if explicit is not None:
            current = explicit
            continue
        delta = _relative_page_delta(text)
        if delta and current is not None:
            current += delta
    if current is None or current < 1:
        return None
    return current


def build_textbook_query(messages: list[ChatMessage], *, window: int = 12) -> str:
    """
    Build a focused textbook query, scoped to the current page conversation.

    The query is anchored on the MOST RECENT user turn that references a page
    or lesson. Only clean tokens are emitted (صفحه N + subject + grade) so
    conversational leftovers like «ریاضی تموم شد بریم سراغ فارسی» cannot make
    the server pick the wrong book.

    Also supports topic/named-content queries («میرزا کوچک خان»، «کجای کتاب مربوط به …»)
    by combining distinctive words with carried grade/subject.

    Returns "" when the recent conversation has no textbook reference at all.
    """
    user_texts = [
        message.content.strip()
        for message in messages
        if message.role == "user" and message.content.strip()
    ]
    if not user_texts:
        return ""
    recent = user_texts[-window:]

    def _lookup_subject(from_idx: int) -> str | None:
        # Prefer subject in/after the anchor turn; else carry from earlier turns.
        for text in reversed(recent[from_idx:]):
            token = _extract_subject_token(text)
            if token:
                return token
        for text in reversed(recent[:from_idx]):
            token = _extract_subject_token(text)
            if token:
                return token
        return None

    def _lookup_grade(from_idx: int) -> str | None:
        for text in reversed(recent[from_idx:]):
            token = _extract_grade_token(text)
            if token:
                return token
        for text in reversed(recent[:from_idx]):
            token = _extract_grade_token(text)
            if token:
                return token
        return None

    # Relative page reference («صفحه بعد»، «بعدش»، «صفحه قبل») → concrete page.
    relative_page = _resolve_relative_page(recent)
    if relative_page is not None:
        anchor_idx = len(recent) - 1
        return _compose_textbook_query(
            page=relative_page,
            subject=_lookup_subject(anchor_idx),
            grade=_lookup_grade(anchor_idx),
        )

    anchor_idx: int | None = None
    for idx in range(len(recent) - 1, -1, -1):
        if _textbook_has_anchor(recent[idx]):
            anchor_idx = idx
            break

    if anchor_idx is not None:
        anchor = recent[anchor_idx]
        page = _extract_page_number(anchor)
        page_words = _extract_page_word_phrase(anchor) if page is None else None
        lesson_phrase = (
            _extract_lesson_phrase(anchor) if page is None and not page_words else None
        )
        query = _compose_textbook_query(
            page=page,
            page_words=page_words,
            lesson_phrase=lesson_phrase,
            subject=_lookup_subject(anchor_idx),
            grade=_lookup_grade(anchor_idx),
        )
        # If a later turn asks for the whole lesson, keep the page anchor and
        # mark the query so the server expands to all lesson pages.
        if any(_textbook_wants_whole_lesson(t) for t in recent[anchor_idx:]):
            query = f"کل درس {query}".strip()
        return query

    # Whole-lesson follow-up without a new page number («بقیه درس»، «کلمات سخت کل درس»).
    latest_idx = len(recent) - 1
    latest = recent[latest_idx]
    if _textbook_wants_whole_lesson(latest):
        page = None
        for text in reversed(recent):
            page = _extract_page_number(text)
            if page is not None:
                break
        lesson_phrase = None
        if page is None:
            for text in reversed(recent):
                lesson_phrase = _extract_lesson_phrase(text)
                if lesson_phrase:
                    break
        query = _compose_textbook_query(
            page=page,
            lesson_phrase=lesson_phrase,
            subject=_lookup_subject(latest_idx),
            grade=_lookup_grade(latest_idx),
        )
        if query:
            return f"کل درس {query}".strip()

    # Topic / named-content query without an explicit page number.
    if _textbook_has_topic_intent(latest) or (
        _extract_subject_token(latest) and _extract_grade_token(latest)
        and any(m in latest for m in ("تمرین", "شعر", "داستان", "معنی", "متن", "فعالیت"))
    ):
        subject = _lookup_subject(latest_idx)
        grade = _lookup_grade(latest_idx)
        # Keep the child's content words; server strips scaffolding.
        parts = [latest]
        if subject and subject not in latest:
            parts.append(subject)
        if grade and grade not in latest:
            parts.append(grade)
        return " ".join(parts).strip()

    return ""


def _normalize_persona(value: str | None) -> PersonaId | None:
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in {"", "none", "auto", "automatic"}:
        return None
    if normalized in SUPPORTED_PERSONAS:
        return normalized  # type: ignore[return-value]
    return None


def iter_text_chunks(text: str, chunk_size: int = STREAM_CHUNK_SIZE) -> Iterator[str]:
    """Split text into chunks for simulated streaming in OpenWebUI pipes."""
    if not text:
        yield ""
        return
    for index in range(0, len(text), chunk_size):
        yield text[index : index + chunk_size]


# ---------------------------------------------------------------------------
# Textbook context client (calls external textbook-service API)
# ---------------------------------------------------------------------------


def _normalize_api_base_url(api_url: str) -> str:
    return api_url.strip().rstrip("/")


def _http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout_sec: float,
) -> dict[str, Any] | None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None


def _http_get_bytes(
    url: str,
    *,
    headers: dict[str, str],
    timeout_sec: float,
) -> bytes | None:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        return response.read()


def _textbook_context_from_payload(data: dict[str, Any]) -> TextbookContext:
    raw_image = str(data["image_base64"]) if data.get("image_base64") else None
    images: list[str] = []
    if raw_image:
        images = [part.strip() for part in raw_image.split("\n---YK_IMAGE---\n") if part.strip()]

    return TextbookContext(
        matched=True,
        match_type=str(data.get("match_type")) if data.get("match_type") else None,
        grade=int(data["grade"]) if data.get("grade") is not None else None,
        subject=str(data["subject"]) if data.get("subject") else None,
        subject_title=str(data["subject_title"]) if data.get("subject_title") else None,
        page=int(data["page"]) if data.get("page") is not None else None,
        context_text=str(data["context_text"]) if data.get("context_text") else None,
        needs_image=bool(data.get("needs_image")),
        image_base64=images[0] if images else None,
        images_base64=images,
        text_usable=bool(data.get("text_usable", True)),
    )


def _use_embedded_textbook(api_url: str) -> bool:
    """Empty / local / self → use in-process textbook package (no HTTP)."""
    value = api_url.strip().lower()
    return value in {"", "local", "inprocess", "self", "embedded"}


async def _fetch_textbook_context_local(
    query: str,
    *,
    include_neighbors: int = 2,
    include_image: str = "auto",
) -> TextbookContext | None:
    from api.textbook.app.models import RetrieveRequest
    from api.textbook.app.retrieve_service import retrieve_context

    mode = include_image.strip().lower()
    if mode not in {"never", "auto", "always"}:
        mode = "auto"

    def _retrieve() -> TextbookContext:
        try:
            response = retrieve_context(
                RetrieveRequest(
                    query=query,
                    include_neighbors=include_neighbors,
                    include_image=mode,  # type: ignore[arg-type]
                )
            )
        except Exception as exc:  # noqa: BLE001 — graceful degrade
            return TextbookContext(matched=False, error=f"{type(exc).__name__}: {exc}")

        if not response.matched:
            return TextbookContext(matched=False)
        return _textbook_context_from_payload(response.model_dump())

    return await asyncio.to_thread(_retrieve)


async def fetch_textbook_context(
    query: str,
    *,
    api_url: str = "",
    api_key: str | None = None,
    include_neighbors: int = 2,
    include_image: str = "auto",
    timeout_sec: float = DEFAULT_TEXTBOOK_TIMEOUT_SEC,
) -> TextbookContext | None:
    """Retrieve textbook context via embedded package or external HTTP URL."""
    if _use_embedded_textbook(api_url):
        return await _fetch_textbook_context_local(
            query,
            include_neighbors=include_neighbors,
            include_image=include_image,
        )

    base = _normalize_api_base_url(api_url)
    if not base:
        return None

    headers: dict[str, str] = {}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = {
        "query": query,
        "include_neighbors": include_neighbors,
        "include_image": include_image,
    }

    def _retrieve() -> tuple[dict[str, Any] | None, str | None]:
        try:
            result = _http_post_json(
                f"{base}/v1/retrieve",
                payload,
                headers=headers,
                timeout_sec=timeout_sec,
            )
            return result, None
        except urllib.error.HTTPError as exc:
            return None, f"HTTP {exc.code} از {base}"
        except urllib.error.URLError as exc:
            return None, f"اتصال ناموفق به {base}: {exc.reason}"
        except (json.JSONDecodeError, TimeoutError, ValueError) as exc:
            return None, f"{type(exc).__name__}: {exc}"

    data, error = await asyncio.to_thread(_retrieve)
    if error is not None:
        return TextbookContext(matched=False, error=error)
    if not data or not data.get("matched"):
        return TextbookContext(matched=False)

    context = _textbook_context_from_payload(data)

    if context.needs_image and not context.images_base64:
        image_url = data.get("image_url")
        if isinstance(image_url, str) and image_url.strip():

            def _fetch_image() -> bytes | None:
                full_url = image_url if image_url.startswith("http") else f"{base}{image_url}"
                try:
                    return _http_get_bytes(full_url, headers=headers, timeout_sec=timeout_sec)
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                    return None

            image_bytes = await asyncio.to_thread(_fetch_image)
            if image_bytes:
                encoded = base64.b64encode(image_bytes).decode("ascii")
                context.image_base64 = encoded
                context.images_base64 = [encoded]

    return context


def _format_web_search_results(results: list[WebSearchResult]) -> str:
    lines: list[str] = []
    for idx, item in enumerate(results, start=1):
        title = item.title.strip() or f"نتیجه {idx}"
        snippet = item.snippet.strip()
        url = (item.url or "").strip()
        block = f"{idx}. {title}"
        if snippet:
            block = f"{block}\n{snippet}"
        if url:
            block = f"{block}\nمنبع: {url}"
        lines.append(block)
    return "\n\n".join(lines)


def _parse_external_web_search_payload(
    data: dict[str, Any], *, query: str, provider: str
) -> WebSearchContext:
    results: list[WebSearchResult] = []

    def _append_item(
        *,
        title: str = "",
        snippet: str = "",
        url: str | None = None,
    ) -> None:
        title = (title or "").strip()
        snippet = (snippet or "").strip()
        url = (url or "").strip() or None
        if title or snippet:
            results.append(WebSearchResult(title=title, url=url, snippet=snippet))

    raw_results = data.get("results") or data.get("organic") or data.get("items")
    if isinstance(raw_results, list):
        for item in raw_results:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    _append_item(title="نتیجه", snippet=text)
                continue
            if not isinstance(item, dict):
                continue
            title = str(
                item.get("title") or item.get("name") or item.get("source") or ""
            ).strip()
            snippet = str(
                item.get("snippet")
                or item.get("content")
                or item.get("text")
                or item.get("summary")
                or item.get("description")
                or ""
            ).strip()
            url_raw = item.get("url") or item.get("link") or item.get("href")
            url = str(url_raw).strip() if url_raw else None
            _append_item(title=title, snippet=snippet, url=url)

    # Perplexity-style answer + citations
    answer = str(
        data.get("answer")
        or data.get("text")
        or data.get("summary")
        or data.get("content")
        or ""
    ).strip()
    if answer:
        _append_item(title="پاسخ", snippet=answer[:2000])

    citations = data.get("citations") or data.get("sources") or data.get("references")
    if isinstance(citations, list):
        for item in citations:
            if isinstance(item, str):
                _append_item(title="منبع", url=item)
                continue
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "منبع").strip()
            snippet = str(
                item.get("snippet") or item.get("text") or item.get("excerpt") or ""
            ).strip()
            url_raw = item.get("url") or item.get("link") or item.get("href")
            url = str(url_raw).strip() if url_raw else None
            _append_item(title=title, snippet=snippet, url=url)

    # Nested data wrappers
    nested = data.get("data")
    if isinstance(nested, dict) and not results:
        return _parse_external_web_search_payload(
            nested, query=query, provider=provider
        )

    context_text = str(data.get("context_text") or "").strip()
    if not context_text and results:
        context_text = _format_web_search_results(results)

    error = data.get("error")
    error_text = str(error).strip() if error else None
    # Upstream sometimes wraps an HTML error page in {"error": "<html...>"}
    if error_text and error_text.lstrip().startswith("<"):
        error_text = "سرویس جستجو خطا برگرداند"

    matched = bool(data.get("matched", bool(context_text or results)))
    if error_text and not matched:
        return WebSearchContext(
            matched=False,
            query=query,
            provider=provider,
            error=error_text,
        )

    return WebSearchContext(
        matched=matched,
        query=query,
        results=results,
        context_text=context_text or None,
        provider=provider,
        error=error_text,
    )


def _normalize_perplexity_search_url(perplexity_url: str) -> str:
    """Accept a base host or a full ``/api/v1/search`` URL."""
    raw = (perplexity_url or "").strip()
    if not raw:
        return ""
    base = raw.rstrip("/")
    if base.endswith("/api/v1/search"):
        return base
    if base.endswith("/api/v1"):
        return f"{base}/search"
    if base.endswith("/api"):
        return f"{base}/v1/search"
    return f"{base}/api/v1/search"


def _http_get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout_sec: float,
) -> dict[str, Any] | None:
    request = urllib.request.Request(
        url,
        headers=headers
        or {
            "User-Agent": "YarKids/1.0 (child-assistant; web-search)",
            "Accept": "application/json",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None


def _search_via_perplexity(
    query: str,
    *,
    perplexity_url: str,
    max_results: int,
    timeout_sec: float,
) -> WebSearchContext:
    endpoint = _normalize_perplexity_search_url(perplexity_url)
    if not endpoint:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error="no_perplexity_url",
        )

    url = f"{endpoint}?{urllib.parse.urlencode({'query': query})}"
    try:
        data = _http_get_json(url, timeout_sec=timeout_sec)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            if isinstance(payload, dict):
                parsed = _parse_external_web_search_payload(
                    payload, query=query, provider="perplexity"
                )
                if parsed.matched:
                    return parsed
                if parsed.error:
                    return parsed
        except Exception:
            pass
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error=f"HTTP {exc.code} از سرویس Perplexity",
        )
    except urllib.error.URLError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error=f"اتصال ناموفق به Perplexity: {exc.reason}",
        )
    except (json.JSONDecodeError, TimeoutError, ValueError) as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error=f"{type(exc).__name__}: {exc}",
        )

    if not data:
        return WebSearchContext(matched=False, query=query, provider="perplexity")
    ctx = _parse_external_web_search_payload(data, query=query, provider="perplexity")
    if ctx.results and len(ctx.results) > max_results:
        ctx.results = ctx.results[:max_results]
        ctx.context_text = _format_web_search_results(ctx.results)
    return ctx


def _duckduckgo_instant_answer(
    query: str, *, timeout_sec: float
) -> list[WebSearchResult]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "t": "yarkids",
        }
    )
    url = f"https://api.duckduckgo.com/?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "YarKids/1.0 (child-assistant)"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        return []

    results: list[WebSearchResult] = []
    abstract = str(data.get("AbstractText") or "").strip()
    heading = str(data.get("Heading") or "").strip()
    abstract_url = str(data.get("AbstractURL") or "").strip() or None
    if abstract:
        results.append(
            WebSearchResult(
                title=heading or "خلاصه",
                url=abstract_url,
                snippet=abstract,
            )
        )

    answer = str(data.get("Answer") or "").strip()
    if answer and answer != abstract:
        results.append(WebSearchResult(title="پاسخ سریع", snippet=answer))

    related = data.get("RelatedTopics")
    if isinstance(related, list):
        for item in related:
            if not isinstance(item, dict):
                continue
            text = str(item.get("Text") or "").strip()
            first_url = str(item.get("FirstURL") or "").strip() or None
            if text:
                title = text.split(" - ", 1)[0][:80]
                results.append(
                    WebSearchResult(title=title, url=first_url, snippet=text)
                )
            if len(results) >= DEFAULT_WEB_SEARCH_MAX_RESULTS:
                break
    return results[:DEFAULT_WEB_SEARCH_MAX_RESULTS]


def _duckduckgo_html_results(
    query: str, *, max_results: int, timeout_sec: float
) -> list[WebSearchResult]:
    params = urllib.parse.urlencode({"q": query, "kp": "1"})  # kp=1 → safe search
    # html.duckduckgo.com often serves a bot interstitial; lite is more reliable.
    url = f"https://lite.duckduckgo.com/lite/?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; YarKids/1.0; +https://github.com/yarkids)"
            )
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        html = response.read().decode("utf-8", errors="replace")

    # DuckDuckGo lite: result-link (title+url) + result-snippet.
    title_re = re.compile(
        r'class=[\'"]result-link[\'"][^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'|href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_re = re.compile(
        r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</(?:td|div|a|span)>',
        re.IGNORECASE | re.DOTALL,
    )
    raw_titles = title_re.findall(html)
    snippets = snippet_re.findall(html)

    def _strip_tags(value: str) -> str:
        cleaned = re.sub(r"<[^>]+>", " ", value)
        cleaned = cleaned.replace("&amp;", "&").replace("&quot;", '"').replace(
            "&#x27;", "'"
        )
        cleaned = urllib.parse.unquote(cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _unwrap_ddg_link(href: str) -> str:
        link = href.replace("&amp;", "&")
        if "uddg=" in link:
            # May be protocol-relative: //duckduckgo.com/l/?uddg=...
            if link.startswith("//"):
                link = "https:" + link
            parsed = urllib.parse.urlparse(link)
            qs = urllib.parse.parse_qs(parsed.query)
            encoded = qs.get("uddg", [None])[0]
            if encoded:
                return urllib.parse.unquote(encoded)
        return link

    results: list[WebSearchResult] = []
    for idx, groups in enumerate(raw_titles[:max_results]):
        href = groups[0] or groups[2]
        title_html = groups[1] or groups[3]
        title = _strip_tags(title_html)
        snippet = _strip_tags(snippets[idx]) if idx < len(snippets) else ""
        link = _unwrap_ddg_link(href)
        if title or snippet:
            results.append(WebSearchResult(title=title, url=link, snippet=snippet))
    return results


def _search_duckduckgo(
    query: str, *, max_results: int, timeout_sec: float
) -> WebSearchContext:
    results: list[WebSearchResult] = []
    try:
        results = _duckduckgo_instant_answer(query, timeout_sec=timeout_sec)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        results = []

    if len(results) < max_results:
        try:
            html_results = _duckduckgo_html_results(
                query, max_results=max_results, timeout_sec=timeout_sec
            )
            seen = {(r.title, r.url) for r in results}
            for item in html_results:
                key = (item.title, item.url)
                if key in seen:
                    continue
                results.append(item)
                seen.add(key)
                if len(results) >= max_results:
                    break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            pass

    results = results[:max_results]
    if not results:
        return WebSearchContext(matched=False, query=query, provider="duckduckgo")
    return WebSearchContext(
        matched=True,
        query=query,
        results=results,
        context_text=_format_web_search_results(results),
        provider="duckduckgo",
    )


def _wikipedia_opensearch(
    query: str, *, lang: str, limit: int, timeout_sec: float
) -> list[tuple[str, str]]:
    """Return list of (title, page_url) from MediaWiki opensearch."""
    params = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": query,
            "limit": str(limit),
            "namespace": "0",
            "format": "json",
        }
    )
    url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "YarKids/1.0 (child-assistant; web-search)"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list) or len(data) < 4:
        return []
    titles = data[1] if isinstance(data[1], list) else []
    urls = data[3] if isinstance(data[3], list) else []
    pairs: list[tuple[str, str]] = []
    for idx, title in enumerate(titles):
        title_s = str(title).strip()
        if not title_s:
            continue
        page_url = str(urls[idx]).strip() if idx < len(urls) else ""
        pairs.append((title_s, page_url))
    return pairs


def _wikipedia_summary(
    title: str, *, lang: str, timeout_sec: float
) -> str | None:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "YarKids/1.0 (child-assistant; web-search)"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        return None
    extract = str(data.get("extract") or "").strip()
    return extract or None


def _wikipedia_title_relevant(query: str, title: str) -> bool:
    q = re.sub(r"\b(game|video|بازی)\b", "", query, flags=re.IGNORECASE).strip().lower()
    t = title.lower()
    if not q:
        return True
    if q in t or t.startswith(q):
        return True
    token = q.split()[0] if q.split() else q
    return len(token) >= 4 and (token in t or t.startswith(token))


def _search_wikipedia(
    query: str, *, max_results: int, timeout_sec: float
) -> WebSearchContext:
    """Reliable fallback for known games/topics when DuckDuckGo is flaky."""
    results: list[WebSearchResult] = []
    seen_titles: set[str] = set()
    # Prefer English for game titles (Persian transliterations often miss).
    for lang in ("en", "fa"):
        try:
            pairs = _wikipedia_opensearch(
                query, lang=lang, limit=max(max_results, 3), timeout_sec=timeout_sec
            )
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ):
            continue
        for title, page_url in pairs:
            key = title.lower()
            if key in seen_titles:
                continue
            if not _wikipedia_title_relevant(query, title):
                continue
            try:
                extract = _wikipedia_summary(
                    title, lang=lang, timeout_sec=timeout_sec
                )
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                json.JSONDecodeError,
                ValueError,
            ):
                extract = None
            if not extract:
                continue
            seen_titles.add(key)
            results.append(
                WebSearchResult(
                    title=title,
                    url=page_url or None,
                    snippet=extract[:500],
                )
            )
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return WebSearchContext(matched=False, query=query, provider="wikipedia")
    return WebSearchContext(
        matched=True,
        query=query,
        results=results,
        context_text=_format_web_search_results(results),
        provider="wikipedia",
    )


def _merge_web_search_results(
    *contexts: WebSearchContext, query: str, max_results: int
) -> WebSearchContext:
    merged: list[WebSearchResult] = []
    seen: set[tuple[str, str | None]] = set()
    providers: list[str] = []
    for ctx in contexts:
        if not ctx or not ctx.matched:
            continue
        if ctx.provider:
            providers.append(ctx.provider)
        for item in ctx.results:
            key = (item.title.lower(), item.url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= max_results:
                break
        if len(merged) >= max_results:
            break
    if not merged:
        return WebSearchContext(matched=False, query=query, provider="auto")
    provider = "+".join(dict.fromkeys(providers)) or "auto"
    return WebSearchContext(
        matched=True,
        query=query,
        results=merged,
        context_text=_format_web_search_results(merged),
        provider=provider,
    )


def _search_via_api(
    query: str,
    *,
    api_url: str,
    api_key: str | None,
    max_results: int,
    timeout_sec: float,
) -> WebSearchContext:
    base = _normalize_api_base_url(api_url)
    if not base:
        return WebSearchContext(
            matched=False, query=query, provider="api", error="no_api_url"
        )

    headers: dict[str, str] = {}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = {"query": query, "max_results": max_results}
    try:
        data = _http_post_json(
            f"{base}/v1/search",
            payload,
            headers=headers,
            timeout_sec=timeout_sec,
        )
    except urllib.error.HTTPError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="api",
            error=f"HTTP {exc.code} از {base}",
        )
    except urllib.error.URLError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="api",
            error=f"اتصال ناموفق به {base}: {exc.reason}",
        )
    except (json.JSONDecodeError, TimeoutError, ValueError) as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="api",
            error=f"{type(exc).__name__}: {exc}",
        )

    if not data:
        return WebSearchContext(matched=False, query=query, provider="api")
    return _parse_external_web_search_payload(data, query=query, provider="api")


async def fetch_web_search_context(
    query: str,
    *,
    provider: str = "auto",
    api_url: str = "",
    api_key: str | None = None,
    perplexity_url: str = "",
    max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS,
    timeout_sec: float = DEFAULT_WEB_SEARCH_TIMEOUT_SEC,
) -> WebSearchContext | None:
    """
    Fetch web search snippets for creative/storyteller/gamer personas.

    Providers:
      - ``api``: POST ``{WEB_SEARCH_API_URL}/v1/search``
      - ``perplexity``: GET ``{PERPLEXITY_URL}?query=...``
      - ``duckduckgo``: web search (Wikipedia as backup)
      - ``auto``: first available among api → perplexity → duckduckgo → wikipedia
    """
    cleaned = query.strip()
    if not cleaned:
        return None

    max_results = max(1, min(int(max_results), 10))
    normalized = (provider or "auto").strip().lower()
    if normalized not in {"auto", "api", "duckduckgo", "perplexity"}:
        normalized = "auto"

    variants = _web_search_query_variants(cleaned)
    has_api = bool(_normalize_api_base_url(api_url))
    has_perplexity = bool(_normalize_perplexity_search_url(perplexity_url))

    def _try_api() -> WebSearchContext | None:
        if not has_api:
            return None
        last: WebSearchContext | None = None
        for variant in variants:
            ctx = _search_via_api(
                variant,
                api_url=api_url,
                api_key=api_key,
                max_results=max_results,
                timeout_sec=timeout_sec,
            )
            last = ctx
            if ctx.matched:
                ctx.query = cleaned
                return ctx
        return last

    def _try_perplexity() -> WebSearchContext | None:
        if not has_perplexity:
            return None
        last: WebSearchContext | None = None
        for variant in variants:
            ctx = _search_via_perplexity(
                variant,
                perplexity_url=perplexity_url,
                max_results=max_results,
                timeout_sec=timeout_sec,
            )
            last = ctx
            if ctx.matched:
                ctx.query = cleaned
                return ctx
        return last

    def _try_duckduckgo_wiki() -> WebSearchContext:
        ddg_hits: list[WebSearchContext] = []
        for variant in variants[:2]:
            ddg = _search_duckduckgo(
                variant,
                max_results=max_results,
                timeout_sec=min(timeout_sec, 6.0),
            )
            if ddg.matched:
                ddg_hits.append(ddg)
                break

        wiki_hits: list[WebSearchContext] = []
        if not ddg_hits:
            for variant in variants:
                wiki = _search_wikipedia(
                    variant,
                    max_results=max_results,
                    timeout_sec=min(timeout_sec, 8.0),
                )
                if wiki.matched:
                    wiki_hits.append(wiki)
                    break

        return _merge_web_search_results(
            *ddg_hits, *wiki_hits, query=cleaned, max_results=max_results
        )

    def _run() -> WebSearchContext:
        if normalized == "api":
            ctx = _try_api()
            return ctx or WebSearchContext(
                matched=False, query=cleaned, provider="api", error="no_api_url"
            )

        if normalized == "perplexity":
            ctx = _try_perplexity()
            return ctx or WebSearchContext(
                matched=False,
                query=cleaned,
                provider="perplexity",
                error="no_perplexity_url",
            )

        if normalized == "duckduckgo":
            return _try_duckduckgo_wiki()

        # auto: try whatever is configured, then local fallbacks
        for attempt in (_try_api, _try_perplexity):
            ctx = attempt()
            if ctx and ctx.matched:
                return ctx

        return _try_duckduckgo_wiki()

    return await asyncio.to_thread(_run)


async def resolve_web_search_context(
    *,
    messages: list[ChatMessage],
    persona: PersonaId,
    enable_web_search: bool,
    provider: str = "auto",
    api_url: str = "",
    api_key: str | None = None,
    perplexity_url: str = "",
    max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS,
    timeout_sec: float = DEFAULT_WEB_SEARCH_TIMEOUT_SEC,
    debug: bool = False,
    on_status: Callable[[str], Awaitable[None]] | None = None,
) -> WebSearchContext | None:
    """Gate + fetch web search for eligible personas."""
    user_message = _get_latest_user_message(messages)
    query = build_web_search_query(messages)
    should_fetch = bool(
        enable_web_search
        and persona in WEB_SEARCH_PERSONAS
        and query
        and looks_like_web_search_request(user_message, persona=persona)
    )
    if not should_fetch:
        return None

    if on_status:
        await on_status(status_fetching_web_search())

    context = await fetch_web_search_context(
        query,
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        perplexity_url=perplexity_url,
        max_results=max_results,
        timeout_sec=timeout_sec,
    )
    if debug and on_status and context:
        await on_status(
            _format_web_search_debug(
                query=query, provider=provider, context=context
            )
        )
        await asyncio.sleep(1.2)
    if context and not context.matched and on_status and not debug:
        await on_status(status_web_search_unavailable())
    return context


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_system_prompt(
    persona: PersonaId,
    revision_reasons: list[str] | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
) -> str:
    sections: list[str] = [get_core_prompt()]

    persona_prompt = get_persona_prompt(persona)
    if persona_prompt:
        sections.append(persona_prompt)

    if textbook_context and textbook_context.matched and textbook_context.context_text:
        meta_parts: list[str] = []
        if textbook_context.subject_title:
            meta_parts.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_parts.append(f"پایه {textbook_context.grade}")
        if textbook_context.page:
            meta_parts.append(f"صفحه {textbook_context.page}")
        meta = " — ".join(meta_parts)
        if textbook_context.text_usable:
            instruction = TEXTBOOK_CONTEXT_INSTRUCTION
        elif textbook_context.image_base64:
            instruction = TEXTBOOK_IMAGE_ONLY_INSTRUCTION
        else:
            instruction = TEXTBOOK_UNREADABLE_INSTRUCTION
        header = f"{instruction}\n\n{TEXTBOOK_CONTEXT_HEADER}"
        if meta:
            header = f"{header}\n({meta})"
        sections.append(f"{header}\n{textbook_context.context_text}")
    elif textbook_context and textbook_context.page_query_failed:
        sections.append(TEXTBOOK_LOOKUP_FAILED_INSTRUCTION)
    elif textbook_context and textbook_context.need_info:
        sections.append(TEXTBOOK_NEED_INFO_INSTRUCTION)

    if (
        web_search_context
        and web_search_context.matched
        and web_search_context.context_text
    ):
        sections.append(
            f"{WEB_SEARCH_CONTEXT_INSTRUCTION}\n\n"
            f"{WEB_SEARCH_CONTEXT_HEADER}\n"
            f"{web_search_context.context_text}"
        )
    elif web_search_context is not None and not web_search_context.matched:
        # We attempted a search (game/fact talk) but got nothing — block
        # hallucinated «doesn't exist / not released» claims.
        sections.append(WEB_SEARCH_NO_RESULTS_INSTRUCTION)

    math_block = format_math_tool_context(math_tool_usages or [])
    if math_block:
        sections.append(math_block)

    if revision_reasons:
        reasons_text = "\n".join(f"- {reason}" for reason in revision_reasons)
        sections.append(f"{REVISION_INSTRUCTION_HEADER}\n{reasons_text}")

    return "\n\n".join(sections)


def _attach_textbook_image_to_messages(
    messages: list[dict[str, Any]],
    textbook_context: TextbookContext | None,
) -> list[dict[str, Any]]:
    if not textbook_context or not textbook_context.needs_image:
        return messages
    images = textbook_context.images_base64 or (
        [textbook_context.image_base64] if textbook_context.image_base64 else []
    )
    images = [img for img in images if img]
    if not images:
        return messages

    image_note = (
        "[ضمیمهٔ مرجع سیستمی]\n"
        "این تصویر(ها) را سیستم از پایگاه کتاب درسی بازیابی کرده است "
        "(کاربر آن‌ها را نفرستاده است).\n"
        "فقط مرجعِ صفحه(های) کتاب هستند؛ برای خواندن متن/شکل/جدول از آن‌ها استفاده کن."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": image_note}]
    for encoded in images[:4]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )

    updated = list(messages)
    updated.append({"role": "system", "content": content})
    return updated


def build_prompt_messages(
    *,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
) -> list[dict[str, Any]]:
    llm_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                persona,
                revision_reasons,
                textbook_context=textbook_context,
                web_search_context=web_search_context,
                math_tool_usages=math_tool_usages,
            ),
        },
    ]
    for message in conversation_messages:
        if message.role != "system":
            content = (
                strip_persona_markers(message.content)
                if message.role == "assistant"
                else message.content
            )
            llm_messages.append({"role": message.role, "content": content})
    return _attach_textbook_image_to_messages(llm_messages, textbook_context)


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------


def parse_intent_detection_output(raw_output: str) -> IntentDetectionResult:
    payload = _extract_json_object(raw_output)
    if not payload:
        return IntentDetectionResult(persona="none")

    persona_raw = str(payload.get("persona", "none")).strip().lower()
    if persona_raw not in VALID_PERSONAS:
        return IntentDetectionResult(persona="none")

    persona: PersonaId = persona_raw  # type: ignore[assignment]
    if persona == "none":
        return IntentDetectionResult(persona="none")

    confidence_raw = payload.get("confidence")
    if confidence_raw is None:
        return IntentDetectionResult(persona="none")

    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        return IntentDetectionResult(persona="none")

    if confidence < INTENT_CONFIDENCE_THRESHOLD:
        return IntentDetectionResult(persona="none")

    return IntentDetectionResult(persona=persona, confidence=confidence)


async def detect_intent(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    current_persona: PersonaId | None = None,
) -> IntentDetectionResult:
    user_text = _get_latest_user_message(messages)
    if not user_text:
        return IntentDetectionResult(persona="none")

    # Bare greetings must not lock a persona (TC: «سلام» → none).
    if _looks_like_greeting_only(user_text):
        return IntentDetectionResult(persona="none")

    explicit = _detect_explicit_persona_request(user_text)
    if explicit:
        return IntentDetectionResult(persona=explicit, confidence=0.98)

    # Hard stick: during an active persona session, short/continuation turns
    # must NOT go to the LLM (e.g. word-chain answer «داستان»).
    if (
        current_persona
        and current_persona != "none"
        and _should_keep_current_persona(user_text, current_persona, messages)
    ):
        return IntentDetectionResult(persona=current_persona, confidence=0.97)

    activity = _detect_ongoing_activity(messages, current_persona)
    system_prompt = get_intent_detection_prompt()
    if current_persona and current_persona != "none":
        system_prompt += (
            f"\n\n⚠️ چسبندگی پرسونا: کاربر الان در حالت «{current_persona}» است"
            + (f" و فعالیت «{activity}»" if activity else "")
            + ". "
            "فقط اگر درخواست صریح و قاطع برای عوض کردن حالت بود پرسونا را عوض کن. "
            "کلمهٔ تکی مثل «داستان» / «بازی» / «معلم» در وسط فعالیت، درخواست تعویض نیست. "
            "«ادامه بده»، «سوال بعد»، «مثال دیگر»، «ایده دیگر» یعنی ماندن در همان پرسونا."
        )

    history = _format_recent_messages(messages, max_turns=6)
    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": system_prompt},
            *history,
        ],
    )
    return parse_intent_detection_output(await llm_client.complete(request))


# ---------------------------------------------------------------------------
# Context awareness helpers
# ---------------------------------------------------------------------------


_ACTIVITY_PATTERNS: dict[PersonaId, tuple[str, ...]] = {
    "gamer": (
        "بازی کلمات",
        "کلمه‌های زنجیره‌ای",
        "کلمه های زنجیره",
        "زنجیره",
        "آخرین حرف",
        "حرف آخر",
        "کلمه بگو",
        "کلمه اول",
        "نوبت تو",
        "نوبت توئه",
        "نوبت من",
        "چیستان",
        "معما",
        "حدس بزن",
        "بازی کنیم",
        "بریم بازی",
        "شروع می‌کنم",
        "با «",
        "با \"",
    ),
    "storyteller": (
        "ادامه بده",
        "بعدش چی شد",
        "سپس",
        "و بعد",
        "داستان را ادامه",
        "شخصیت داستان",
        "ماجرا ادامه",
        "داستان بگو",
        "قصه بگو",
        "می‌خوام داستان",
    ),
    "teacher": (
        "مثال دیگر",
        "مثال دیگه",
        "مشکل مشابه",
        "بخش دیگر",
        "قدم بعد",
        "مرحله بعد",
        "نمی‌فهمم",
        "معلوم نشد",
        "دوباره توضیح",
        "یعنی چی",
        "توضیح بده",
    ),
    "homework": (
        "سوال بعد",
        "تمرین بعد",
        "بخش ب",
        "قسمتی دیگر",
        "جوابش چیه",
        "مرحله بعد",
        "چطور حل",
        "مراحل",
        "این مسئله",
        "حل کن",
    ),
    "creative": (
        "ایده دیگر",
        "ایده دیگه",
        "پیشنهاد دیگر",
        "چیزی دیگر",
        "نوع دیگر",
        "راه دیگر",
        "ایده بده",
        "حوصله",
    ),
}

_ACTIVITY_CONTINUATION: dict[PersonaId, tuple[str, ...]] = {
    "gamer": ("نوبت من", "ادامه", "یکی دیگه", "چیستان دیگه", "معما دیگه"),
    "storyteller": (
        "ادامه بده",
        "بعدش",
        "بعدش چی شد",
        "و بعد",
        "ادامه داستان",
        "بعدی",
    ),
    "teacher": ("مثال دیگر", "مثال دیگه", "دوباره توضیح", "قدم بعد", "مرحله بعد"),
    "homework": ("سوال بعد", "تمرین بعد", "بعدی", "مرحله بعد", "یکی دیگه"),
    "creative": ("ایده دیگر", "ایده دیگه", "پیشنهاد دیگر", "چیزی دیگر", "یکی دیگه"),
}

_ACTIVITY_DISPLAY_NAMES: dict[PersonaId, str] = {
    "gamer": "بازی کلمات/چیستان",
    "storyteller": "قصه‌گویی تعاملی",
    "teacher": "آموزش مفهومی",
    "homework": "حل تمرین قدم‌به‌قدم",
    "creative": "ایده‌پردازی خلاقانه",
}

PERSONA_FA_LABELS: dict[PersonaId, str] = {
    "creative": "خلاق",
    "storyteller": "داستان‌گو",
    "teacher": "معلم",
    "homework": "کمک‌درس",
    "gamer": "بازی و سرگرمی",
    "none": "یار کودک",
}

_CONFIRM_YES_RE = re.compile(
    r"^(?:بله|آره|باشه|موافقم|باشه برو|بله برو|آره برو|باشه عوض کن|بله عوض کن)"
    r"(?:\s|$|[!.،,])",
    re.IGNORECASE,
)
_CONFIRM_NO_RE = re.compile(
    r"^(?:نه|نخیر|نه همین|نه همون|نمی‌خوام|نمیخوام|ادامه بده|همین‌جا|همینجا)"
    r"(?:\s|$|[!.،,])",
    re.IGNORECASE,
)


def _is_activity_continuation(text: str, persona: PersonaId) -> bool:
    """True when the latest user message continues the current activity."""
    cleaned = text.strip()
    if not cleaned:
        return False
    for phrase in _ACTIVITY_CONTINUATION.get(persona, ()):
        if cleaned == phrase or cleaned.startswith(phrase):
            return True
    return False


_WORD_CHAIN_SIGNALS = (
    "زنجیره",
    "نوبت تو",
    "نوبت توئه",
    "کلمه بگو",
    "با حرف",
    "حرف «",
    'حرف "',
    "آخرین حرف",
    "حرف آخر",
    "کلمه اول",
    "کلمه‌های زنجیر",
    "کلمه های زنجیر",
    "بازی کلمات",
    "بازی کلمه‌",
)


def _looks_like_word_chain_awaiting_answer(messages: list[ChatMessage]) -> bool:
    """True when the latest assistant turn is waiting for a word-chain reply."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        content = message.content
        if "مطمئنی؟" in content or "بریم سراغ «" in content:
            continue
        return any(signal in content for signal in _WORD_CHAIN_SIGNALS)
    return False


def _looks_like_hard_switch_request(text: str) -> bool:
    """True only for clear persona-switch intent (not a single keyword)."""
    if _detect_explicit_persona_request(text):
        return True
    lowered = text.strip().lower()
    switch_phrases = (
        "بریم سراغ",
        "حالم عوض",
        "حالت عوض",
        "دیگه بازی نه",
        "دیگه قصه نه",
        "می‌خوام داستان بشنوم",
        "میخوام داستان بشنوم",
        "می‌خوام قصه",
        "میخوام قصه",
        "بریم درس",
        "بریم بازی",
        "دیگه درس",
    )
    return any(phrase in lowered for phrase in switch_phrases)


def _should_keep_current_persona(
    text: str,
    persona: PersonaId,
    messages: list[ChatMessage],
) -> bool:
    """Sticky rule: keep persona unless a hard switch is clearly requested."""
    if not text.strip():
        return True
    if _looks_like_hard_switch_request(text):
        return False
    if _is_activity_continuation(text, persona):
        return True
    # Word-chain answers like «داستان» must stay on gamer.
    cleaned = text.strip()
    if (
        persona == "gamer"
        and len(cleaned) <= 40
        and "?" not in cleaned
        and "؟" not in cleaned
        and _looks_like_word_chain_awaiting_answer(messages)
    ):
        return True
    if _detect_ongoing_activity(messages, persona):
        # Mid-session message without hard switch → stay.
        return True
    # Even without explicit activity markers, short replies stay sticky
    # when history already confirms the same persona (not the welcome menu).
    if len(cleaned) <= 40 and "?" not in cleaned and "؟" not in cleaned:
        if extract_persona_marker(
            next((m.content for m in reversed(messages) if m.role == "assistant"), "")
        ) == persona:
            return True
    return False


def _detect_ongoing_activity(
    messages: list[ChatMessage], current_persona: PersonaId | None
) -> str | None:
    """Check if user is in the middle of an activity with the current persona."""
    if not current_persona or current_persona == "none":
        return None

    patterns = _ACTIVITY_PATTERNS.get(current_persona, ())
    if not patterns:
        return None

    window = messages[-12:]
    if not window:
        return None

    prior = window[:-1] if len(window) >= 2 else window
    for message in prior:
        if any(pattern in message.content for pattern in patterns):
            return _ACTIVITY_DISPLAY_NAMES.get(current_persona, current_persona)

    latest = window[-1].content if window else ""
    if _is_activity_continuation(latest, current_persona):
        if _infer_persona_from_history(messages) == current_persona or any(
            pattern in message.content
            for message in prior
            for pattern in patterns
        ):
            return _ACTIVITY_DISPLAY_NAMES.get(current_persona, current_persona)
    return None


def _format_recent_messages(messages: list[ChatMessage], max_turns: int = 6) -> list[dict[str, str]]:
    """Format recent conversation for intent detection context."""
    formatted = []
    for m in messages[-max_turns:]:
        if m.role != "system":
            content = (
                strip_persona_markers(m.content)
                if m.role == "assistant"
                else m.content
            )
            formatted.append({"role": m.role, "content": content})
    return formatted


_EXPLICIT_PERSONA_TRIGGERS: dict[str, tuple[str, ...]] = {
    "creative": (
        "خلاق باش",
        "باش خلاق",
        "خلاق شو",
        "حالت خلاق",
        "شخصیت خلاق",
        "mode creative",
    ),
    "storyteller": (
        "داستان بگو",
        "قصه بگو",
        "داستان‌گو باش",
        "داستان گو باش",
        "قصه‌گو باش",
        "قصه گو باش",
        "باش داستان‌گو",
        "باش داستان گو",
        "باش قصه‌گو",
        "باش قصه گو",
        "حالت داستان",
        "شخصیت داستان",
        "mode storyteller",
    ),
    "teacher": (
        "معلم باش",
        "باش معلم",
        "حالت معلم",
        "شخصیت معلم",
        "mode teacher",
    ),
    "homework": (
        "کمک درس باش",
        "کمک‌درس باش",
        "باش کمک درس",
        "باش کمک‌درس",
        "حالت کمک درس",
        "شخصیت کمک درس",
        "mode homework",
    ),
    "gamer": (
        "بازی باش",
        "بازی کن",
        "بازی کنیم",
        "بریم بازی",
        "باش بازی",
        "باش گیمر",
        "گیمر باش",
        "حالت بازی",
        "شخصیت بازی",
        "mode gamer",
    ),
}


def _infer_persona_from_history(messages: list[ChatMessage]) -> PersonaId | None:
    """Infer the current persona from recent assistant responses."""
    assistant_msgs = [m.content for m in messages[-8:] if m.role == "assistant"]
    if not assistant_msgs:
        return None

    # Prefer explicit sticky markers written into prior replies (legacy only).
    for content in reversed(assistant_msgs):
        if _looks_like_welcome_or_menu(content):
            continue
        marked = extract_persona_marker(content)
        if marked:
            return marked

    # Strong mid-activity signals only — never match the welcome menu.
    PERSONA_RESPONSE_PATTERNS: dict[PersonaId, tuple[str, ...]] = {
        "gamer": (
            "نوبت تو",
            "نوبت توئه",
            "کلمه بگو",
            "کلمه اول",
            "زنجیره",
            "بازی کلمات",
            "کلمه‌های زنجیره‌ای",
            "با حرف",
            "حدس بزن",
            "نوبت من",
            "حرف آخر",
            "شروع می‌کنم",
        ),
        "storyteller": (
            "داستان کامل",
            "داستان مشترک",
            "با هم داستان",
            "اول ماجرا",
            "دنیای خیال",
            "ادامه داستان",
            "شخصیت داستان",
            "حالت داستان‌گو",
            "حالت داستان گو",
        ),
        "teacher": (
            "به زبان ساده",
            "قدم اول",
            "قدم بعد",
            "درک کردی",
            "توضیح دهم",
            "حالت معلم",
        ),
        "homework": (
            "حل کنیم",
            "مرحله بعد",
            "سوال بعد",
            "حالت کمک‌درس",
            "حالت کمک درس",
        ),
        "creative": (
            "ایده دیگر",
            "ایده دیگه",
            "حالت خلاق",
            "بیا بسازیم",
        ),
    }

    for content in reversed(assistant_msgs):
        if "مطمئنی؟" in content or "بریم سراغ «" in content:
            continue
        if _looks_like_welcome_or_menu(content):
            continue
        lowered = content.lower()
        for persona, patterns in PERSONA_RESPONSE_PATTERNS.items():
            if any(p in lowered for p in patterns):
                return persona
    return None


def _detect_explicit_persona_request(text: str) -> PersonaId | None:
    """Detect explicit persona switch; last matching trigger in the message wins."""
    lowered = text.strip().lower()
    matches: list[tuple[int, str]] = []
    for persona, triggers in _EXPLICIT_PERSONA_TRIGGERS.items():
        for trigger in triggers:
            start = 0
            needle = trigger.lower()
            while True:
                idx = lowered.find(needle, start)
                if idx < 0:
                    break
                matches.append((idx, persona))
                start = idx + max(len(needle), 1)
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]  # type: ignore[return-value]


def _extract_pending_switch_from_history(
    messages: list[ChatMessage],
) -> PersonaId | None:
    """Read pending switch target from the last confirmation question."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        content = message.content
        if "مطمئنی؟" not in content and "بریم سراغ «" not in content:
            continue
        match = re.search(r"بریم سراغ «([^»]+)»", content)
        if not match:
            match = re.search(r"به «([^»]+)» عوض", content)
        if not match:
            return None
        label = match.group(1).strip()
        for persona_id, fa_label in PERSONA_FA_LABELS.items():
            if fa_label == label and persona_id != "none":
                return persona_id
        return None
    return None


def format_persona_switch_confirmation(
    current: PersonaId, pending: PersonaId
) -> str:
    """Ask the child before leaving the current persona."""
    current_label = PERSONA_FA_LABELS.get(current, current)
    pending_label = PERSONA_FA_LABELS.get(pending, pending)
    return (
        f"الان داریم با هم در حالت «{current_label}» ادامه می‌دیم. "
        f"به نظر می‌رسه می‌خوای بریم سراغ «{pending_label}». "
        f"مطمئنی؟\n\n"
        f"اگر آره، بگو «بله برو».\n"
        f"اگر نه، بگو «نه همین‌جا» تا همون کار قبلی رو ادامه بدیم."
    )


def resolve_manual_persona(
    *,
    user_persona: str | None = None,
    body: dict[str, Any] | None = None,
) -> PersonaId | None:
    """
    Resolve manually selected persona from chat UserValves or request metadata.

    OpenWebUI exposes UserValves in Chat Controls → Valves sidebar.
    When persona is "auto" or empty, returns None so intent detection runs.
    """
    manual = _normalize_persona(user_persona)
    if manual:
        return manual

    if not body:
        return None

    metadata = body.get("metadata") or {}
    if isinstance(metadata, dict):
        metadata_persona = metadata.get(MANUAL_PERSONA_METADATA_KEY)
        if isinstance(metadata_persona, str):
            manual = _normalize_persona(metadata_persona)
            if manual:
                return manual

    # Custom frontend (e.g. Yar UI): send persona directly on the request body.
    for key in ("yarkids_persona", "persona", "PERSONA"):
        direct = body.get(key)
        if isinstance(direct, str):
            manual = _normalize_persona(direct)
            if manual:
                return manual

    params = body.get("params") or {}
    if isinstance(params, dict):
        params_persona = params.get("PERSONA") or params.get("persona")
        if isinstance(params_persona, str):
            manual = _normalize_persona(params_persona)
            if manual:
                return manual

    return None


def get_user_persona_selection(__user__: dict[str, Any] | None) -> str | None:
    """Read persona from OpenWebUI UserValves (Chat Controls sidebar)."""
    if not __user__:
        return None

    valves = __user__.get("valves")
    if valves is None:
        return None

    persona = dict(valves).get("PERSONA")
    if isinstance(persona, str) and persona.strip():
        return persona.strip()

    return None


# ---------------------------------------------------------------------------

async def resolve_active_persona(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    user_persona: str | None = None,
    body: dict[str, Any] | None = None,
    on_detecting_status: Callable[[], Awaitable[None]] | None = None,
) -> PersonaResolution:
    """
    Resolve persona with sticky behaviour.

    - Manual UserValves persona wins immediately (no confirmation).
    - Auto-detected persona sticks across turns (via metadata/history).
    - Switching away from a sticky persona requires confirmation
      («بله برو» / «نه همین‌جا»), except the very first selection.
    - Mid-activity short answers (e.g. word-chain «داستان») never switch.
    """
    manual_persona = resolve_manual_persona(user_persona=user_persona, body=body)
    latest_user_msg = _get_latest_user_message(messages)

    # Manual selection from Chat Controls: honor immediately.
    if manual_persona:
        return PersonaResolution(persona=manual_persona)

    # Hard stay during word-chain even if sticky metadata/history was lost.
    if (
        latest_user_msg
        and _looks_like_word_chain_awaiting_answer(messages)
        and not _looks_like_hard_switch_request(latest_user_msg)
    ):
        return PersonaResolution(persona="gamer")

    # Recover sticky persona (metadata → history).
    current_persona: PersonaId | None = None
    if body:
        metadata = body.get("metadata") or {}
        if isinstance(metadata, dict):
            prev_persona = metadata.get(ACTIVE_PERSONA_METADATA_KEY)
            if isinstance(prev_persona, str):
                normalized = _normalize_persona(prev_persona)
                if normalized:
                    current_persona = normalized
    if current_persona is None:
        current_persona = _infer_persona_from_history(messages)

    # «سلام» alone: stay on none until the child actually picks an activity.
    if (
        latest_user_msg
        and _looks_like_greeting_only(latest_user_msg)
        and (not current_persona or current_persona == "none")
    ):
        return PersonaResolution(persona="none")

    # Welcome-menu short picks («بازی»، «داستان»، …) are first selections, not switches.
    menu_pick = (
        _detect_menu_persona_pick(latest_user_msg) if latest_user_msg else None
    )
    if menu_pick and (
        not current_persona
        or current_persona == "none"
        or _last_assistant_is_welcome(messages)
    ):
        return PersonaResolution(persona=menu_pick)

    # Answer a pending switch confirmation from the previous assistant turn.
    pending = _extract_pending_switch_from_history(messages)
    if pending and latest_user_msg and current_persona and current_persona != "none":
        if _CONFIRM_YES_RE.search(latest_user_msg.strip()):
            return PersonaResolution(persona=pending)
        if _CONFIRM_NO_RE.search(latest_user_msg.strip()):
            return PersonaResolution(persona=current_persona)

    # Sticky keep without calling the LLM when appropriate.
    if (
        current_persona
        and current_persona != "none"
        and latest_user_msg
        and _should_keep_current_persona(latest_user_msg, current_persona, messages)
    ):
        return PersonaResolution(persona=current_persona)

    if on_detecting_status:
        await on_detecting_status()

    intent = await detect_intent(
        llm_client,
        backend_model=backend_model,
        messages=messages,
        current_persona=current_persona,
    )
    desired = intent.persona

    # First selection (no sticky yet): accept immediately.
    if not current_persona or current_persona == "none":
        return PersonaResolution(persona=desired if desired != "none" else "none")

    # Same persona or none → stay.
    if desired in (None, "none", current_persona):
        return PersonaResolution(persona=current_persona)

    # Different persona requested while sticky → ask confirmation first.
    return PersonaResolution(
        persona=current_persona,
        pending_switch_to=desired,
        ask_confirmation=True,
    )


# ---------------------------------------------------------------------------
# LLM client
# ---------------------------------------------------------------------------


class OpenWebUILLMClient:
    def __init__(self, request: Any, user: Any) -> None:
        self._request = request
        self._user = user

    async def complete(self, request: LLMCompletionRequest) -> str:
        from open_webui.utils.chat import generate_chat_completion

        body: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
            "stream": request.stream,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature

        response = await _await_if_needed(
            generate_chat_completion(self._request, body, self._user)
        )
        return extract_text_from_completion(response)


# ---------------------------------------------------------------------------
# Main agent
# ---------------------------------------------------------------------------


async def generate_response(
    llm_client: LLMClient,
    *,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
    temperature: float | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
) -> str:
    request = LLMCompletionRequest(
        model=backend_model,
        messages=build_prompt_messages(
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        ),
        stream=False,
        temperature=temperature,
    )
    return await llm_client.complete(request)


# ---------------------------------------------------------------------------
# Reflection agent
# ---------------------------------------------------------------------------


def parse_reflection_output(raw_output: str) -> ReflectionResult:
    payload = _extract_json_object(raw_output)
    if not payload:
        return ReflectionResult(status="REVISE", reasons=["خروجی بازبین قابل parse نبود."])

    status_raw = str(payload.get("status", "")).strip().upper()
    if status_raw == "PASS":
        return ReflectionResult(status="PASS")

    reasons_raw = payload.get("reasons", [])
    reasons: list[str] = []
    if isinstance(reasons_raw, list):
        reasons = [str(item).strip() for item in reasons_raw if str(item).strip()]

    if not reasons:
        reasons = ["پاسخ برای کودک مناسب تشخیص داده نشد."]

    return ReflectionResult(status="REVISE", reasons=reasons)


async def reflect_on_response(
    llm_client: LLMClient,
    *,
    backend_model: str,
    user_message: str,
    candidate_response: str,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
) -> ReflectionResult:
    textbook_note = ""
    if textbook_context and textbook_context.matched:
        meta_bits: list[str] = []
        if textbook_context.subject_title:
            meta_bits.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_bits.append(f"پایه {textbook_context.grade}")
        if textbook_context.page:
            meta_bits.append(f"صفحه {textbook_context.page}")
        meta = "، ".join(meta_bits) if meta_bits else "صفحهٔ کتاب"
        textbook_note = (
            f"\n\nتوجه بازبین: سیستم متن/تصویر واقعیِ {meta} را به نویسنده داده است. "
            "اگر پاسخ بر اساس همان صفحه صحبت می‌کند، آن را توهم حساب نکن و PASS بده "
            "(مگر اینکه ناامن یا نامناسب باشد)."
        )
    elif textbook_context and (
        textbook_context.page_query_failed or textbook_context.need_info
    ):
        textbook_note = (
            "\n\nتوجه بازبین: نویسنده متن صفحه را نداشته؛ اگر محتوای دقیق صفحه را ساخته، REVISE."
        )

    web_note = ""
    if web_search_context and web_search_context.matched:
        web_note = (
            "\n\nتوجه بازبین: سیستم نتایج واقعی جستجوی وب را به نویسنده داده است. "
            "اگر پاسخ بر اساس همان نتایج است، آن را توهم حساب نکن و PASS بده "
            "(مگر اینکه ناامن یا نامناسب سن باشد)."
        )
    elif web_search_context is not None and not web_search_context.matched:
        web_note = (
            "\n\nتوجه بازبین: نویسنده نتایج جستجو نداشته. "
            "اگر ادعا کرده بازی وجود ندارد / هنوز منتشر نشده بدون شواهد، REVISE."
        )

    review_prompt = (
        f"پیام کودک:\n{user_message}\n\n"
        f"پاسخ پیشنهادی:\n{candidate_response}"
        f"{textbook_note}{web_note}\n\n"
        "فقط JSON خروجی بده."
    )
    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": get_reflection_prompt()},
            {"role": "user", "content": review_prompt},
        ],
    )
    return parse_reflection_output(await llm_client.complete(request))


# ---------------------------------------------------------------------------
# Response loop
# ---------------------------------------------------------------------------


async def run_response_loop(
    llm_client: LLMClient,
    *,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    temperature: float | None = None,
    on_status: Callable[[str], Awaitable[None]] | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
    enable_reflection: bool = True,
) -> str:
    revision_reasons: list[str] = []
    user_message = _get_latest_user_message(conversation_messages)
    # When reflection is off, generate once and return — never SAFE_FALLBACK.
    if not enable_reflection:
        if on_status:
            await on_status(status_reflection_disabled())
            await on_status(status_generating_response(1, 1))
        return await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=None,
            temperature=temperature,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        )

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if on_status:
            await on_status(status_generating_response(attempt, MAX_GENERATION_ATTEMPTS))

        candidate = await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons or None,
            temperature=temperature,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        )

        if on_status:
            await on_status(status_reviewing_response())

        reflection = await reflect_on_response(
            llm_client,
            backend_model=backend_model,
            user_message=user_message,
            candidate_response=candidate,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
        )

        if reflection.status == "PASS":
            return candidate

        revision_reasons = reflection.reasons or ["پاسخ نیاز به اصلاح دارد."]

    return SAFE_FALLBACK_RESPONSE


def build_textbook_diag(
    *,
    query_sent: str | None,
    context: TextbookContext | None,
) -> TextbookQueryDiag | None:
    if not query_sent and context is None:
        return None
    preview = None
    if context and context.context_text:
        preview = context.context_text[:400]
    return TextbookQueryDiag(
        query_sent=query_sent or None,
        matched=bool(context and context.matched),
        context_preview=preview,
        grade=context.grade if context else None,
        subject=context.subject if context else None,
        subject_title=context.subject_title if context else None,
        page=context.page if context else None,
        error=context.error if context else None,
        need_info=bool(context and context.need_info),
        page_query_failed=bool(context and context.page_query_failed),
    )


def build_web_search_diag(
    *,
    query_sent: str | None,
    context: WebSearchContext | None,
) -> WebSearchQueryDiag | None:
    if not query_sent and context is None:
        return None
    return WebSearchQueryDiag(
        query_sent=(context.query if context and context.query else query_sent) or None,
        provider_used=context.provider if context else None,
        matched=bool(context and context.matched),
        results_count=len(context.results) if context else 0,
        error=context.error if context else None,
    )


class Pipe:
    """DEPRECATED local OpenWebUI Pipe — prefer ``api/pipe/pipe.py`` + the API.

    This class still embeds the full Yar Kids pipeline for legacy / embedded
    single-file builds. New deployments should run ``api.main`` and import
    ``api/pipe/pipe.py`` in OpenWebUI instead.
    """

    class Valves(BaseModel):
        BACKEND_MODEL: str = Field(
            default="",
            description=(
                "مدل پشتیبان OpenWebUI برای تولید پاسخ. "
                "اگر خالی باشد از مدل پیش‌فرض سیستم استفاده می‌شود."
            ),
        )
        TEMPERATURE: float = Field(
            default=0.7,
            ge=0.0,
            le=2.0,
            description="دمای تولید پاسخ اصلی.",
        )
        ENABLE_STATUS_UPDATES: bool = Field(
            default=True,
            description="نمایش وضعیت پردازش در رابط کاربری.",
        )
        ENABLE_REFLECTION: bool = Field(
            default=True,
            title="ایجنت بازبینی پاسخ",
            description=(
                "اگر روشن باشد، پاسخ قبل از ارسال توسط ایجنت Reflection بررسی می‌شود. "
                "اگر خاموش باشد، پاسخ بلافاصله بدون بازبینی ارسال می‌شود "
                "(پیام وضعیت: «بازبینی پاسخ خاموش است»)."
            ),
        )
        ENABLE_TEXTBOOK_CONTEXT: bool = Field(
            default=True,
            description="فعال‌سازی بازیابی کتاب درسی از textbook-service (معلم/کمک‌درسی).",
        )
        TEXTBOOK_API_URL: str = Field(
            default="http://localhost:8080",
            description="آدرس پایهٔ API سرویس textbook-service (بدون / در انتها).",
        )
        TEXTBOOK_API_KEY: str = Field(
            default="",
            description="کلید API اختیاری (Bearer token).",
        )
        TEXTBOOK_REQUEST_TIMEOUT_SEC: float = Field(
            default=DEFAULT_TEXTBOOK_TIMEOUT_SEC,
            ge=1.0,
            le=30.0,
            description="مهلت درخواست به textbook-service (ثانیه).",
        )
        TEXTBOOK_NEIGHBOR_PAGES: int = Field(
            default=1,
            ge=0,
            le=3,
            description="تعداد صفحات همسایه برای بازیابی.",
        )
        TEXTBOOK_INCLUDE_IMAGE: str = Field(
            default="auto",
            description='ارسال تصویر صفحه: never | auto | always',
        )
        TEXTBOOK_DEBUG: bool = Field(
            default=False,
            description="نمایش اطلاعات دیباگ بازیابی کتاب در نوار وضعیت (برای عیب‌یابی).",
        )
        ENABLE_WEB_SEARCH: bool = Field(
            default=True,
            description=(
                "فعال‌سازی جستجوی وب برای پرسوناهای خلاق / داستان‌گو / بازی و سرگرمی "
                "(وقتی سؤال واقعی/به‌روز باشد)."
            ),
        )
        WEB_SEARCH_PROVIDER: str = Field(
            default="auto",
            description=(
                "ارائه‌دهنده جستجو: auto | duckduckgo | api | perplexity "
                "(auto = هر منبعی که در دسترس باشد: api → perplexity → DuckDuckGo)."
            ),
        )
        WEB_SEARCH_API_URL: str = Field(
            default="",
            description=(
                "آدرس پایهٔ سرویس جستجوی سفارشی (POST /v1/search). "
                "خالی = غیرفعال برای provider=api."
            ),
        )
        WEB_SEARCH_API_KEY: str = Field(
            default="",
            description="کلید API اختیاری برای سرویس جستجو (Bearer token).",
        )
        WEB_SEARCH_PERPLEXITY_URL: str = Field(
            default="",
            description=(
                "آدرس پایه یا کامل سرویس جستجوی Perplexity "
                "(GET .../api/v1/search?query=...). خالی = غیرفعال."
            ),
        )
        WEB_SEARCH_REQUEST_TIMEOUT_SEC: float = Field(
            default=DEFAULT_WEB_SEARCH_TIMEOUT_SEC,
            ge=1.0,
            le=30.0,
            description="مهلت درخواست جستجوی وب (ثانیه).",
        )
        WEB_SEARCH_MAX_RESULTS: int = Field(
            default=DEFAULT_WEB_SEARCH_MAX_RESULTS,
            ge=1,
            le=10,
            description="حداکثر تعداد نتایج جستجو برای تزریق به پرامپت.",
        )
        WEB_SEARCH_DEBUG: bool = Field(
            default=False,
            description="نمایش اطلاعات دیباگ جستجوی وب در نوار وضعیت.",
        )

    class UserValves(BaseModel):
        """
        Persona dropdown — rendered by OpenWebUI in Chat Controls → Valves.

        TODO(frontend/yar-ui): For custom chat UI, render a persona dropdown and send
        the selected value in body.metadata.yarkids_persona on each chat request.
        See README → «اتصال UI سفارشی».
        """

        PERSONA: str = Field(
            default="auto",
            title="شخصیت یار کودک",
            description="از این منو شخصیت دوستت رو انتخاب کن! 😊",
            json_schema_extra={
                "input": {
                    "type": "select",
                    "options": PERSONA_DROPDOWN_OPTIONS,
                }
            },
        )

    def __init__(self) -> None:
        warnings.warn(
            "Pipe from pipe_logic is deprecated; use api/pipe/pipe.py with the "
            "standalone API instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.valves = self.Valves()

    def pipes(self) -> list[dict[str, str]]:
        return [
            {
                "id": MODEL_ID,
                "name": MODEL_NAME,
                "description": "همراه هوشمند و کودک‌دوست [DEPRECATED — use API client]",
            }
        ]

    async def _resolve_backend_model(self, body: dict[str, Any]) -> str:
        if self.valves.BACKEND_MODEL.strip():
            return self.valves.BACKEND_MODEL.strip()
        return ""

    async def _get_user_object(self, __user__: dict[str, Any]) -> Any:
        from open_webui.models.users import Users

        return await _await_if_needed(Users.get_user_by_id(__user__["id"]))

    def _build_status_emitter(
        self,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> Callable[[str], Awaitable[None]] | None:
        if not self.valves.ENABLE_STATUS_UPDATES or not __event_emitter__:
            return None

        async def emit_status(description: str) -> None:
            await __event_emitter__(
                {
                    "type": "status",
                    "data": {"description": description, "done": False, "hidden": False},
                }
            )

        return emit_status

    async def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> Union[str, Iterator[str], AsyncIterator[str]]:
        if body.get("stream", False):
            return self._stream_chat(body, __user__, __request__, __event_emitter__)
        return await self._finish_chat(body, __user__, __request__, __event_emitter__)

    async def _stream_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> AsyncIterator[str]:
        """
        Stream response chunks after processing.

        Status events are emitted during _run_chat; we clear them only right
        before the first text chunk so status and streaming do not fight.
        """
        final_response = await self._run_chat(
            body,
            __user__,
            __request__,
            __event_emitter__,
            use_status=self.valves.ENABLE_STATUS_UPDATES,
        )

        if self.valves.ENABLE_STATUS_UPDATES:
            await asyncio.sleep(STATUS_DISPLAY_PAUSE_SEC)
            await clear_status_message(__event_emitter__)

        for chunk in iter_text_chunks(final_response):
            yield chunk
            await asyncio.sleep(0)

    async def _finish_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
    ) -> str:
        final_response = await self._run_chat(
            body,
            __user__,
            __request__,
            __event_emitter__,
            use_status=self.valves.ENABLE_STATUS_UPDATES,
        )
        if self.valves.ENABLE_STATUS_UPDATES:
            await clear_status_message(__event_emitter__)
        return final_response

    async def _run_chat(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any],
        __request__: Any,
        __event_emitter__: Callable[[dict[str, Any]], Awaitable[None]] | None,
        *,
        use_status: bool = True,
    ) -> str:
        user = await self._get_user_object(__user__)
        llm_client = OpenWebUILLMClient(__request__, user)
        backend_model = await self._resolve_backend_model(body)

        if not backend_model:
            return "لطفاً در تنظیمات Pipe (Valves) مدل پشتیبان (BACKEND_MODEL) را مشخص کنید."

        raw_messages = body.get("messages", [])
        if not isinstance(raw_messages, list):
            raw_messages = []

        conversation_messages = normalize_messages(raw_messages)
        on_status = self._build_status_emitter(__event_emitter__) if use_status else None
        user_persona = get_user_persona_selection(__user__)
        manual_persona = resolve_manual_persona(user_persona=user_persona, body=body)

        async def emit_detecting_persona() -> None:
            if on_status:
                await on_status(status_detecting_persona())

        resolution = await resolve_active_persona(
            llm_client,
            backend_model=backend_model,
            messages=conversation_messages,
            user_persona=user_persona,
            body=body,
            on_detecting_status=emit_detecting_persona
            if not manual_persona
            else None,
        )

        if resolution.ask_confirmation and resolution.pending_switch_to:
            # Persist sticky + pending via metadata when the host supports it.
            metadata = body.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                body["metadata"] = metadata
            metadata[ACTIVE_PERSONA_METADATA_KEY] = resolution.persona
            metadata[PENDING_PERSONA_METADATA_KEY] = resolution.pending_switch_to
            if on_status:
                await on_status(status_persona_selected(resolution.persona))
            return append_persona_marker(
                format_persona_switch_confirmation(
                    resolution.persona, resolution.pending_switch_to
                ),
                resolution.persona,
            )

        persona = resolution.persona

        # Persist active persona for multi-turn context (TC-79).
        if persona and persona != "none":
            metadata = body.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
                body["metadata"] = metadata
            metadata[ACTIVE_PERSONA_METADATA_KEY] = persona
            metadata.pop(PENDING_PERSONA_METADATA_KEY, None)

        if on_status and manual_persona:
            await on_status(status_persona_selected(manual_persona))
        elif on_status and persona != "none":
            await on_status(status_persona_selected(persona))

        textbook_context: TextbookContext | None = None
        user_message = _get_latest_user_message(conversation_messages)
        textbook_query = build_textbook_query(conversation_messages)
        # Textbook knowledge base is available ONLY for teacher/homework personas.
        should_fetch_textbook = bool(
            self.valves.ENABLE_TEXTBOOK_CONTEXT
            and textbook_query
            and self.valves.TEXTBOOK_API_URL.strip()
            and persona in TEXTBOOK_PERSONAS
        )
        if should_fetch_textbook:
            if on_status:
                await on_status(status_fetching_textbook())
            include_image = self.valves.TEXTBOOK_INCLUDE_IMAGE.strip().lower()
            if include_image not in {"never", "auto", "always"}:
                include_image = "auto"
            textbook_context = await fetch_textbook_context(
                textbook_query,
                api_url=self.valves.TEXTBOOK_API_URL,
                api_key=self.valves.TEXTBOOK_API_KEY or None,
                include_neighbors=self.valves.TEXTBOOK_NEIGHBOR_PAGES,
                include_image=include_image,  # type: ignore[arg-type]
                timeout_sec=self.valves.TEXTBOOK_REQUEST_TIMEOUT_SEC,
            )
            if self.valves.TEXTBOOK_DEBUG and on_status and textbook_context:
                await on_status(
                    _format_textbook_debug(
                        query=textbook_query,
                        api_url=self.valves.TEXTBOOK_API_URL,
                        context=textbook_context,
                    )
                )
                await asyncio.sleep(1.2)
            if textbook_context and not textbook_context.matched:
                if looks_like_textbook_page_query(textbook_query):
                    textbook_context.page_query_failed = True
                else:
                    textbook_context.need_info = True
                if on_status and not self.valves.TEXTBOOK_DEBUG:
                    await on_status(status_textbook_unavailable())
        elif (
            self.valves.ENABLE_TEXTBOOK_CONTEXT
            and persona in TEXTBOOK_PERSONAS
            and looks_like_textbook_help_request(user_message)
        ):
            # Child is clearly asking about their schoolbook/homework but has not
            # yet given enough detail (grade + book + page) to run a lookup.
            # Ask for the missing info instead of guessing or claiming no access.
            textbook_context = TextbookContext(need_info=True)

        web_search_context = await resolve_web_search_context(
            messages=conversation_messages,
            persona=persona,
            enable_web_search=self.valves.ENABLE_WEB_SEARCH,
            provider=self.valves.WEB_SEARCH_PROVIDER,
            api_url=self.valves.WEB_SEARCH_API_URL,
            api_key=self.valves.WEB_SEARCH_API_KEY or None,
            perplexity_url=self.valves.WEB_SEARCH_PERPLEXITY_URL,
            max_results=self.valves.WEB_SEARCH_MAX_RESULTS,
            timeout_sec=self.valves.WEB_SEARCH_REQUEST_TIMEOUT_SEC,
            debug=self.valves.WEB_SEARCH_DEBUG,
            on_status=on_status,
        )

        math_tool_usages = run_math_tool_for_message(
            user_message, persona=persona
        )
        if math_tool_usages and on_status:
            await on_status(status_calculating_math())

        # Persona is already teacher/homework here (gate above); no switch needed.
        enable_reflection = read_valve_bool(
            self.valves, "ENABLE_REFLECTION", default=True
        )
        final_response = await run_response_loop(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            temperature=self.valves.TEMPERATURE,
            on_status=on_status,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
            enable_reflection=enable_reflection,
        )
        if persona and persona != "none":
            final_response = append_persona_marker(final_response, persona)
        else:
            final_response = strip_persona_markers(final_response)
        return final_response
