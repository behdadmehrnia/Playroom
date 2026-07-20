"""Textbook query building and context retrieval (embedded or remote)."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import urllib.error
from typing import Any

from .constants import DEFAULT_TEXTBOOK_TIMEOUT_SEC
from .math_tool import _PERSIAN_DIGIT_MAP
from .messages import (
    _get_latest_user_message,
    _http_get_bytes,
    _http_post_json,
    _normalize_api_base_url,
)
from .types import ChatMessage, TextbookContext, TextbookQueryDiag, TextbookScope

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

# Persian ordinal / digit → grade int (grades 3–6 in the index).
_GRADE_TOKEN_TO_INT: dict[str, int] = {
    "سوم": 3,
    "سه": 3,
    "۳": 3,
    "3": 3,
    "چهارم": 4,
    "چهار": 4,
    "۴": 4,
    "4": 4,
    "پنجم": 5,
    "پنج": 5,
    "۵": 5,
    "5": 5,
    "ششم": 6,
    "شش": 6,
    "۶": 6,
    "6": 6,
}

# Minimal subject keyword → catalog id (mirrors api.textbook.app.subjects).
_SUBJECT_KEYWORD_TO_ID: dict[str, str] = {
    "ریاضی": "math",
    "ریاضیات": "math",
    "علوم": "science",
    "علوم تجربی": "science",
    "فارسی": "persian",
    "نگارش": "writing",
    "مطالعات": "social",
    "مطالعات اجتماعی": "social",
    "اجتماعی": "social",
    "قرآن": "quran",
    "هدیه": "gifts",
    "تفکر": "thinking",
    "فناوری": "technology",
}

# Follow-up questions that should re-use the current page scope.
_TEXTBOOK_FOLLOWUP_MARKERS: tuple[str, ...] = (
    "چه داستانی",
    "چه داستان",
    "اسم داستان",
    "عنوان داستان",
    "عنوان",
    "معنی",
    "یعنی چی",
    "یعنی چه",
    "یعنی چیه",
    "ادامه",
    "بیشتر توضیح",
    "توضیح بده",
    "این صفحه",
    "همین صفحه",
    "اینجا",
    "چی نوشته",
    "چی گفته",
    "نفهمیدم",
    "سخت بود",
    "می‌خونیم",
    "میخونیم",
    "بخون",
    "بخوان",
    "خلاصه",
    "چی یاد",
    "چی یاد گرفتیم",
)
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


def looks_like_textbook_followup(text: str) -> bool:
    """True when the child is still discussing the current textbook page."""
    if not text.strip():
        return False
    if _textbook_has_topic_intent(text) and not _textbook_has_anchor(text):
        return True
    lowered = text.strip().lower()
    return any(marker in lowered for marker in _TEXTBOOK_FOLLOWUP_MARKERS)


def _grade_token_to_int(token: str) -> int | None:
    cleaned = token.strip()
    for key in ("پایه", "کلاس"):
        if cleaned.startswith(key):
            cleaned = cleaned[len(key) :].strip()
    if cleaned.isdigit():
        value = int(cleaned)
        return value if 3 <= value <= 6 else None
    return _GRADE_TOKEN_TO_INT.get(cleaned)


def _subject_keyword_to_id(keyword: str | None) -> str | None:
    if not keyword:
        return None
    return _SUBJECT_KEYWORD_TO_ID.get(keyword.strip())
def _textbook_has_topic_intent(text: str) -> bool:
    return any(marker in text for marker in _TEXTBOOK_TOPIC_INTENT_MARKERS)


def _textbook_wants_whole_lesson(text: str) -> bool:
    return bool(_TEXTBOOK_WHOLE_LESSON_RE.search(text))
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
    # Avoid confusing «سوم/چهارم/...» that appears as an exercise or lesson number
    # (e.g. «تمرین سوم»، «درس سوم») with the student's grade (e.g. «پایه ششم»).
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
    lesson_context = _textbook_has_lesson(text)

    if (exercise_context or lesson_context) and not has_grade_keyword:
        return None

    match = _TEXTBOOK_GRADE_TOKEN_RE.search(text)
    if match:
        token = match.group(0).strip()
        # Bare ordinals (سوم، چهارم، …) must not follow درس/فصل.
        if re.fullmatch(r"سوم|چهارم|پنجم|ششم", token, flags=re.IGNORECASE):
            if re.search(
                rf"(?:درس|فصل)\s*{token}|{token}\s*(?:درس|فصل)",
                text,
                flags=re.IGNORECASE,
            ):
                return None
        return token
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


def resolve_textbook_scope(
    messages: list[ChatMessage],
    *,
    sticky: dict[str, Any] | None = None,
    window: int = 16,
) -> TextbookScope:
    """
    Walk recent user turns and resolve the current textbook position.

    Unlike a single-turn query parser, this tracks page navigation across turns
    (e.g. «صفحه ۳۳» → «بریم صفحه بعد» → «چه داستانیه؟» stays on page 34).
    """
    user_texts = [
        message.content.strip()
        for message in messages
        if message.role == "user" and message.content.strip()
    ]
    if not user_texts:
        return TextbookScope()

    recent = user_texts[-window:]
    grade: int | None = None
    subject_kw: str | None = None
    subject_id: str | None = None
    current_page: int | None = None

    if sticky:
        raw_grade = sticky.get("grade")
        if isinstance(raw_grade, int) and 3 <= raw_grade <= 6:
            grade = raw_grade
        raw_subject = sticky.get("subject")
        if isinstance(raw_subject, str) and raw_subject.strip():
            subject_id = raw_subject.strip()
            subject_kw = next(
                (k for k, v in _SUBJECT_KEYWORD_TO_ID.items() if v == subject_id),
                None,
            )
        raw_page = sticky.get("page")
        if isinstance(raw_page, int) and raw_page > 0:
            current_page = raw_page

    for text in recent:
        grade_token = _extract_grade_token(text)
        if grade_token:
            parsed_grade = _grade_token_to_int(grade_token)
            if parsed_grade is not None:
                grade = parsed_grade

        subject_token = _extract_subject_token(text)
        if subject_token:
            subject_kw = subject_token
            subject_id = _subject_keyword_to_id(subject_token)

        explicit_page = _extract_page_number(text)
        if explicit_page is not None:
            current_page = explicit_page
            continue

        page_words = _extract_page_word_phrase(text)
        if page_words:
            from api.textbook.app.parser import PAGE_NUMBER_WORDS

            current_page = PAGE_NUMBER_WORDS.get(page_words.split()[0], current_page)
            continue

        delta = _relative_page_delta(text)
        if delta and current_page is not None:
            current_page += delta

    return TextbookScope(
        grade=grade,
        subject=subject_kw,
        subject_id=subject_id,
        page=current_page,
    )


def build_textbook_query(
    messages: list[ChatMessage],
    *,
    sticky: dict[str, Any] | None = None,
    window: int = 12,
) -> str:
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
    latest = recent[-1]
    scope = resolve_textbook_scope(messages, sticky=sticky, window=window)

    # Established page session: navigation, follow-ups, or reaffirming grade.
    if scope.has_page_lookup():
        if (
            _textbook_has_anchor(latest)
            or _relative_page_delta(latest) != 0
            or looks_like_textbook_followup(latest)
            or _textbook_wants_whole_lesson(latest)
            or any(kw in latest for kw in ("پایه", "کلاس", "دبستان"))
        ):
            return scope.compose_query(
                user_message=latest if looks_like_textbook_followup(latest) else None
            )

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
    grade: int | None = None,
    subject: str | None = None,
    page: int | None = None,
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
                    grade=grade,
                    subject=subject,
                    page=page,
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
    grade: int | None = None,
    subject: str | None = None,
    page: int | None = None,
) -> TextbookContext | None:
    """Retrieve textbook context via the embedded package, or optional external HTTP URL."""
    if _use_embedded_textbook(api_url):
        return await _fetch_textbook_context_local(
            query,
            include_neighbors=include_neighbors,
            include_image=include_image,
            grade=grade,
            subject=subject,
            page=page,
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
    if grade is not None:
        payload["grade"] = grade
    if subject:
        payload["subject"] = subject
    if page is not None:
        payload["page"] = page

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
