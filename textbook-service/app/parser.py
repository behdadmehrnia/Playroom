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


@dataclass
class ParsedQuery:
    grade: int | None = None
    subject: str | None = None
    topic: str | None = None
    topic_alias: str | None = None
    page: int | None = None
    confidence: float = 0.0


def normalize_digits(text: str) -> str:
    return text.translate(_DIGIT_MAP)


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

    # 1) Book-level subject
    book_subject, book_alias = _find_longest_match(text, lower, BOOK_SUBJECT_SYNONYMS)

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
    result.confidence = min(score, 1.0)

    return result
