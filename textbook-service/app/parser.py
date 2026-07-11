from __future__ import annotations

import re
from dataclasses import dataclass

from app.subjects import (
    BOOK_SUBJECT_SYNONYMS,
    SUBJECT_TITLES,
    TOPIC_ALIASES,
    resolve_topic_id,
)

# Persian/Arabic digit mapping
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

GRADE_WORDS: dict[str, int] = {
    "سوم": 3,
    "سه": 3,
    "چهارم": 4,
    "چهار": 4,
    "پنجم": 5,
    "پنج": 5,
    "ششم": 6,
    "شش": 6,
}

PAGE_NUMBER_WORDS: dict[str, int] = {
    "اول": 1,
    "یک": 1,
    "یکم": 1,
    "دو": 2,
    "دوم": 2,
    "سه": 3,
    "سوم": 3,
    "چهار": 4,
    "چهارم": 4,
    "پنج": 5,
    "پنجم": 5,
    "شش": 6,
    "ششم": 6,
    "هفت": 7,
    "هفتم": 7,
    "هشت": 8,
    "هشتم": 8,
    "نه": 9,
    "نهم": 9,
    "ده": 10,
    "دهم": 10,
    "یازده": 11,
    "یازدهم": 11,
    "دوازده": 12,
    "دوازدهم": 12,
    "سیزده": 13,
    "سیزدهم": 13,
    "چهارده": 14,
    "چهاردهم": 14,
    "پانزده": 15,
    "پانزدهم": 15,
    "شانزده": 16,
    "شانزدهم": 16,
    "هفده": 17,
    "هفدهم": 17,
    "هجده": 18,
    "هجدهم": 18,
    "نوزده": 19,
    "نوزدهم": 19,
    "بیست": 20,
    "بیستم": 20,
    "سی": 30,
    "سیم": 30,
    "چهل": 40,
    "چهلم": 40,
    "پنجاه": 50,
    "پنجاهم": 50,
    "شصت": 60,
    "شصتم": 60,
    "هفتاد": 70,
    "هفتادم": 70,
    "هشتاد": 80,
    "هشتادم": 80,
    "نود": 90,
    "نودم": 90,
    "صد": 100,
    "صدم": 100,
}


# Ordinal word → integer, used to resolve «درس دوازدهم» / «فصل سوم» references.
LESSON_ORDINAL_WORDS: dict[str, int] = {
    "اول": 1,
    "یکم": 1,
    "دوم": 2,
    "سوم": 3,
    "چهارم": 4,
    "پنجم": 5,
    "ششم": 6,
    "هفتم": 7,
    "هشتم": 8,
    "نهم": 9,
    "دهم": 10,
    "یازدهم": 11,
    "دوازدهم": 12,
    "سیزدهم": 13,
    "چهاردهم": 14,
    "پانزدهم": 15,
    "شانزدهم": 16,
    "هفدهم": 17,
    "هجدهم": 18,
    "نوزدهم": 19,
    "بیستم": 20,
    "بیست‌ویکم": 21,
    "بیست و یکم": 21,
    "بیست‌ودوم": 22,
    "بیست و دوم": 22,
}


@dataclass
class ParsedQuery:
    grade: int | None = None
    subject: str | None = None
    topic: str | None = None
    topic_alias: str | None = None
    page: int | None = None
    lesson: int | None = None
    confidence: float = 0.0


def normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


def _parse_persian_number_phrase(text: str) -> int | None:
    cleaned = re.sub(r"[‌\-,،/]", " ", text.strip())
    # Split on whitespace only; drop a standalone «و» conjunction. Splitting on
    # the bare letter «و» would wrongly break words that contain it (اول، دو، نود).
    tokens = [token for token in re.split(r"\s+", cleaned) if token and token != "و"]
    if not tokens:
        return None
    total = 0
    matched = False
    for token in tokens:
        value = PAGE_NUMBER_WORDS.get(token)
        if value is None:
            return None
        total += value
        matched = True
    if not matched or total <= 0:
        return None
    return total


def _find_longest_match(text: str, lower: str, mapping: dict[str, str]) -> tuple[str | None, str | None]:
    """Return (canonical_id, matched_alias) for longest synonym found."""
    found_id: str | None = None
    matched_alias: str | None = None
    best_len = 0
    for synonym, canonical in sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True):
        if synonym in text or synonym in lower:
            if len(synonym) > best_len:
                found_id = canonical
                matched_alias = synonym
                best_len = len(synonym)
    return found_id, matched_alias


def _find_subject_near_page(
    text: str,
    lower: str,
    mapping: dict[str, str],
) -> tuple[str | None, str | None]:
    """
    Resolve book subject when several may appear in one sentence.

    Prefers the synonym closest to a page marker («صفحه …»); otherwise the
    last synonym in the text — so «ریاضی تموم شد بریم سراغ فارسی صفحه ۴۱»
    resolves to فارسی, not ریاضی.
    """
    hits: list[tuple[int, int, str, str]] = []  # start, length, canonical, alias
    for synonym, canonical in mapping.items():
        if not synonym:
            continue
        haystacks = ((text, synonym), (lower, synonym.lower()))
        for haystack, needle in haystacks:
            start = 0
            while True:
                idx = haystack.find(needle, start)
                if idx < 0:
                    break
                hits.append((idx, len(needle), canonical, synonym))
                start = idx + len(needle)
    if not hits:
        return None, None

    # Deduplicate identical spans (same start from text/lower double scan).
    unique: dict[tuple[int, int, str], tuple[int, int, str, str]] = {}
    for hit in hits:
        key = (hit[0], hit[1], hit[2])
        unique[key] = hit
    hits = list(unique.values())

    page_match = re.search(r"(?:صفحه|صفحهٔ|ص\.?)", text, flags=re.IGNORECASE)
    if page_match:
        page_pos = page_match.start()
        hits.sort(key=lambda item: (abs(item[0] - page_pos), -item[1], -item[0]))
        best = hits[0]
        return best[2], best[3]

    hits.sort(key=lambda item: (item[0], item[1]))
    best = hits[-1]
    return best[2], best[3]


def parse_persian_query(text: str) -> ParsedQuery:
    """
    Extract grade, book subject, optional topic, and page from a Persian query.

    Resolution order:
    1. Book subject (ریاضی، مطالعات اجتماعی، ...)
    2. Topic alias → parent subject (تاریخ → social، مدنی → social، ...)
    """
    normalized = normalize_digits(text)
    lower = text.lower()
    result = ParsedQuery()

    # Grade
    grade_match = re.search(
        r"(?:پایه|کلاس)\s*(\d|[۳۴۵۶]|سوم|چهارم|پنجم|ششم|سه|چهار|پنج|شش)",
        normalized,
        flags=re.IGNORECASE,
    )
    if grade_match:
        token = grade_match.group(1)
        if token.isdigit():
            result.grade = int(token)
        else:
            result.grade = GRADE_WORDS.get(token)

    if result.grade is None:
        for word, grade in GRADE_WORDS.items():
            if word in text and ("پایه" in text or "کلاس" in text or "دبستان" in text):
                result.grade = grade
                break

    # Page
    page_match = re.search(
        r"(?:صفحه|صفحهٔ|ص\.?)\s*(\d{1,4})",
        normalized,
        flags=re.IGNORECASE,
    )
    if page_match:
        result.page = int(page_match.group(1))
    else:
        page_words_match = re.search(
            r"(?:صفحه|صفحهٔ|ص\.?)\s+([^\n.!؟?,،]{1,40})",
            text,
            flags=re.IGNORECASE,
        )
        if page_words_match:
            phrase = page_words_match.group(1).strip()
            phrase = re.split(r"(?:\s+(?:کتاب|درس|ریاضی|فارسی|علوم|نگارش|مطالعات|اجتماعی|قرآن|هدیه|تفکر|فناوری)\b)", phrase, maxsplit=1)[0].strip()
            parsed_page = _parse_persian_number_phrase(phrase)
            if parsed_page is not None:
                result.page = parsed_page

    # Lesson / chapter (درس دوازدهم، فصل سوم، درس ۱۲)
    lesson_match = re.search(
        r"(?:درس|فصل)\s*(\d{1,2})",
        normalized,
        flags=re.IGNORECASE,
    )
    if lesson_match:
        result.lesson = int(lesson_match.group(1))
    else:
        lesson_word_match = re.search(
            r"(?:درس|فصل)\s+(اول|یکم|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|"
            r"یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|هفدهم|هجدهم|نوزدهم|بیستم)",
            text,
            flags=re.IGNORECASE,
        )
        if lesson_word_match:
            result.lesson = LESSON_ORDINAL_WORDS.get(lesson_word_match.group(1))

    # 1) Book-level subject (prefer subject nearest to «صفحه», else last mention)
    book_subject, book_alias = _find_subject_near_page(text, lower, BOOK_SUBJECT_SYNONYMS)

    # 2) Topic → parent subject (only if no book subject, or topic is more specific)
    topic_subject, topic_alias = _find_longest_match(text, lower, TOPIC_ALIASES)

    if book_subject and topic_subject:
        # e.g. "مطالعات اجتماعی تاریخ صفحه ۵۰" — book wins, topic is extra context
        result.subject = book_subject
        if topic_alias and TOPIC_ALIASES.get(topic_alias) == book_subject:
            result.topic_alias = topic_alias
            result.topic = resolve_topic_id(book_subject, topic_alias)
    elif book_subject:
        result.subject = book_subject
    elif topic_subject:
        result.subject = topic_subject
        result.topic_alias = topic_alias
        result.topic = resolve_topic_id(topic_subject, topic_alias or "")

    # Standalone grade ordinal fallback (e.g. "ششم" without پایه/کلاس).
    # Only applied when a subject or page is present, to avoid confusing
    # lesson ordinals ("درس سوم") with grade in generic chat.
    if result.grade is None and (result.subject or result.page):
        for word in ("ششم", "پنجم", "چهارم", "سوم"):
            # Skip when the ordinal is actually a lesson/chapter reference
            # («درس ششم»)، not the student's grade.
            if word in text and not re.search(rf"(?:درس|فصل)\s*{word}", text):
                result.grade = GRADE_WORDS[word]
                break

    # Confidence
    score = 0.0
    if result.grade:
        score += 0.3
    if result.subject:
        score += 0.3
    if result.topic:
        score += 0.05
    if result.page:
        score += 0.35
    elif result.lesson:
        score += 0.25
    result.confidence = min(score, 1.0)

    return result
