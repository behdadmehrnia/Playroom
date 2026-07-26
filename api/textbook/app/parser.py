from __future__ import annotations

import re
from dataclasses import dataclass

from api.textbook.app.subjects import (
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
    "یک": 1,
    "دوم": 2,
    "دو": 2,
    "سوم": 3,
    "سه": 3,
    "چهارم": 4,
    "چهار": 4,
    "پنجم": 5,
    "پنج": 5,
    "ششم": 6,
    "شش": 6,
    "هفتم": 7,
    "هفت": 7,
    "هشتم": 8,
    "هشت": 8,
    "نهم": 9,
    "نه": 9,
    "دهم": 10,
    "ده": 10,
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
    "بیست‌وسوم": 23,
    "بیست و سوم": 23,
    "بیست‌وچهارم": 24,
    "بیست و چهارم": 24,
    "بیست‌وپنجم": 25,
    "بیست و پنجم": 25,
    "بیست‌وششم": 26,
    "بیست و ششم": 26,
    "بیست‌وهفتم": 27,
    "بیست و هفتم": 27,
    "بیست‌وهشتم": 28,
    "بیست و هشتم": 28,
    "بیست‌ونهم": 29,
    "بیست و نهم": 29,
    "سی‌ام": 30,
    "سیام": 30,
    "سی ام": 30,
    "سی‌ویکم": 31,
    "سی و یکم": 31,
    "سی‌ودوم": 32,
    "سی و دوم": 32,
    "سی‌وسوم": 33,
    "سی و سوم": 33,
    "سی‌وچهارم": 34,
    "سی و چهارم": 34,
    "سی‌وپنجم": 35,
    "سی و پنجم": 35,
    "سی‌وششم": 36,
    "سی و ششم": 36,
    "سی‌وهفتم": 37,
    "سی و هفتم": 37,
    "سی‌وهشتم": 38,
    "سی و هشتم": 38,
    "سی‌ونهم": 39,
    "سی و نهم": 39,
    "چهلم": 40,
}

_LESSON_ORDINAL_ALT = (
    "اول|یکم|یک|دوم|دو|سوم|سه|چهارم|چهار|پنجم|پنج|ششم|شش|"
    "هفتم|هفت|هشتم|هشت|نهم|نه|دهم|ده|"
    "یازدهم|دوازدهم|سیزدهم|چهاردهم|پانزدهم|شانزدهم|هفدهم|هجدهم|نوزدهم|بیستم|"
    "بیست‌ویکم|بیست و یکم|بیست‌ودوم|بیست و دوم|"
    "بیست‌وسوم|بیست و سوم|بیست‌وچهارم|بیست و چهارم|"
    "بیست‌وپنجم|بیست و پنجم|بیست‌وششم|بیست و ششم|"
    "بیست‌وهفتم|بیست و هفتم|بیست‌وهشتم|بیست و هشتم|"
    "بیست‌ونهم|بیست و نهم|سی‌ام|سیام|سی ام|"
    "سی‌ویکم|سی و یکم|سی‌ودوم|سی و دوم|"
    "سی‌وسوم|سی و سوم|سی‌وچهارم|سی و چهارم|"
    "سی‌وپنجم|سی و پنجم|سی‌وششم|سی و ششم|"
    "سی‌وهفتم|سی و هفتم|سی‌وهشتم|سی و هشتم|"
    "سی‌ونهم|سی و نهم|چهلم"
)


@dataclass
class ParsedQuery:
    grade: int | None = None
    subject: str | None = None
    topic: str | None = None
    topic_alias: str | None = None
    page: int | None = None
    lesson: int | None = None
    chapter: int | None = None
    kind: str | None = None  # lesson|session|project|skill|topic
    search_text: str | None = None
    wants_topic_search: bool = False
    wants_whole_lesson: bool = False
    wants_outline: bool = False
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
        r"(?:صفحه[\s\u200c]*[ٔةهی]?|ص\.?)\s*(\d{1,4})",
        normalized,
        flags=re.IGNORECASE,
    )
    if page_match:
        result.page = int(page_match.group(1))
    else:
        page_words_match = re.search(
            r"(?:صفحه[\s\u200c]*[ٔةهی]?|ص\.?)\s+([^\n.!؟?,،]{1,40})",
            text,
            flags=re.IGNORECASE,
        )
        if page_words_match:
            phrase = page_words_match.group(1).strip()
            phrase = re.split(r"(?:\s+(?:کتاب|درس|ریاضی|فارسی|علوم|نگارش|مطالعات|اجتماعی|قرآن|هدیه|تفکر|فناوری)\b)", phrase, maxsplit=1)[0].strip()
            parsed_page = _parse_persian_number_phrase(phrase)
            if parsed_page is not None:
                result.page = parsed_page

    # Child units (درس/جلسه/مهارت/پروژه) — more specific labels win over درس.
    child_kind, child_no = _extract_child_unit(normalized, text)
    if child_no is not None:
        result.lesson = child_no
        result.kind = child_kind

    # Parent units (فصل / بخش)
    parent_no = _extract_parent_unit(normalized, text)
    if parent_no is not None:
        result.chapter = parent_no

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

    # Standalone / informal grade («فارسی پنجم»، «ریاضی 4»، «ششم» with a book).
    # Prefer subject-anchored forms so «فصل سوم … فارسی چهارم» keeps grade 4.
    if result.grade is None:
        subject_phrases = {
            key
            for key in BOOK_SUBJECT_SYNONYMS
            if key and not key.isascii() and key not in {"کتاب"}
        } | {title for title in SUBJECT_TITLES.values() if title}
        for phrase in sorted(subject_phrases, key=len, reverse=True):
            escaped = re.escape(phrase)
            match = re.search(
                rf"{escaped}(?:[\u200c]*ا?م)?\s*"
                rf"([3-6۳-۶]|سوم|سه|چهارم|چهار|پنجم|پنج|ششم|شش)[هة]?م?"
                rf"(?!\s*(?:درس|فصل|بخش|جلسه|مهارت|پروژه))",
                text,
                flags=re.IGNORECASE,
            )
            if not match:
                match = re.search(
                    rf"([3-6۳-۶]|سوم|سه|چهارم|چهار|پنجم|پنج|ششم|شش)[هة]?م?"
                    rf"\s*{escaped}",
                    text,
                    flags=re.IGNORECASE,
                )
                if match:
                    # Reject «درس ششم فارسی» / «مهارت سوم …» as grade.
                    prefix = text[max(0, match.start() - 12) : match.start()]
                    if re.search(
                        r"(?:درس|فصل|بخش|جلسه|مهارت|پروژه)\s*$",
                        prefix,
                    ):
                        match = None
            if match:
                token = match.group(1)
                digit = normalize_digits(token)
                if digit.isdigit():
                    value = int(digit)
                    if 3 <= value <= 6:
                        result.grade = value
                        break
                grade = GRADE_WORDS.get(token)
                if grade is not None:
                    result.grade = grade
                    break

    if result.grade is None and (
        result.subject or result.page or result.lesson or result.chapter
    ):
        for word in ("ششم", "پنجم", "چهارم", "سوم"):
            # Skip when the ordinal is actually a lesson/chapter reference
            # («درس ششم» / «فصل سوم»)، not the student's grade.
            if word in text and not re.search(
                rf"(?:درس|فصل|بخش|جلسه|مهارت|پروژه)\s*{word}|{word}\s*(?:درس|فصل|بخش|جلسه|مهارت|پروژه)",
                text,
            ):
                result.grade = GRADE_WORDS[word]
                break

    # Free-text topic / named-content search («میرزا کوچک خان»، «شعر ستایش»)
    result.wants_outline = _wants_outline(text)
    if result.wants_outline and result.kind is None:
        outline_kind = _outline_kind_hint(text)
        if outline_kind:
            result.kind = outline_kind
    result.search_text = _extract_search_text(normalized, result)
    result.wants_topic_search = _wants_topic_search(text, result)
    result.wants_whole_lesson = _wants_whole_lesson(text)

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
    elif result.lesson or result.chapter:
        score += 0.25
    elif result.search_text:
        score += 0.2
    if result.wants_whole_lesson:
        score = min(score + 0.1, 1.0)
    if result.wants_outline:
        score = min(score + 0.15, 1.0)
    result.confidence = min(score, 1.0)

    return result


_TOPIC_INTENT_MARKERS = (
    "مربوط",
    "کجای کتاب",
    "کجاى کتاب",
    "کجا در کتاب",
    "درباره",
    "معنی",
    "شعر",
    "داستان",
    "متن",
    "فعالیت",
    "کار در کلاس",
    "تمرین",
)

_WHOLE_LESSON_RE = re.compile(
    r"(?:"
    r"کل\s*درس|تمام\s*درس|همهٔ?\s*(?:ی\s*)?درس|کلّ?\s*درس|"
    r"بقیهٔ?\s*(?:ی\s*)?درس|ادامهٔ?\s*(?:ی\s*)?درس|"
    r"صفحه\s*های\s*(?:این\s+)?درس|کل\s*صفحه\s*های\s*درس|"
    r"کلم(?:ه|ات)\s*(?:سخت\s*)?(?:ی\s*)?(?:داخل\s+|توی\s+|در\s+)?(?:کل\s+|تمام\s+)?درس|"
    r"همهٔ?\s*(?:ی\s*)?صفحه\s*های\s*درس"
    r")",
    flags=re.IGNORECASE,
)


def _wants_whole_lesson(text: str) -> bool:
    return bool(_WHOLE_LESSON_RE.search(text))


_OUTLINE_RE = re.compile(
    r"(?:"
    # «لیست فصل‌ها» / «فهرست دروس»
    r"(?:لیست|فهرست)\s*(?:کن\s*)?(?:همهٔ?\s*)?(?:ی\s*)?"
    r"(?:فصل|فصول|بخش|درس|دروس|جلسه|جلسات|مهارت|پروژه|موضوع)"
    r"(?:[\u200c\s]*ها[یي]?)?"
    # Plural forms: فصول، دروس، فصل‌ها، درس‌ها، …
    r"|(?:فصول|دروس|جلسات)\b"
    r"|(?:فصل|بخش|درس|جلسه|مهارت|پروژه)(?:[\u200c\s]*ها[یي]?)\b"
    r"|ساختار\s*کتاب"
    r"|فهرست\s*مطالب"
    # «فصول ریاضی چیه؟» / «فصل‌هاش چی بود»
    r"|(?:فصول|دروس|فصل|درس|بخش)(?:[\u200c\s]*ها[یي]?)?(?:[\u200c\s]*[ایش]+)?\s*"
    r"(?:چیه|چیه\؟|چی\b|چیست|کدامند|کدومن|کدامن)"
    r")",
    flags=re.IGNORECASE,
)


def _wants_outline(text: str) -> bool:
    return bool(_OUTLINE_RE.search(text))


def _outline_kind_hint(text: str) -> str | None:
    if re.search(r"مهارت", text):
        return "skill"
    if re.search(r"پروژه", text):
        return "project"
    if re.search(r"جلسه|جلسات", text):
        return "session"
    if re.search(r"درس|دروس", text):
        return "lesson"
    return None


def _extract_labeled_number(
    normalized: str,
    original: str,
    labels: tuple[str, ...],
) -> int | None:
    """Parse «برچسب N» / «N برچسب» / «برچسب سوم» for any of the given labels.

    Bare cardinals that start a title («درس هفت خان رستم») are ignored.
    Morphological ordinals («هفتم»، «سی و یکم») and digits always count as numbers
    even when a title follows («درس چهارم ارزش علم»).
    """
    alt = "|".join(re.escape(label) for label in labels)

    def _is_bare_cardinal(token: str) -> bool:
        """True for هفت/چهار/سه — False for هفتم/چهارم/سی‌ویکم."""
        cleaned = (token or "").strip()
        if not cleaned or cleaned.isdigit() or cleaned not in LESSON_ORDINAL_WORDS:
            return False
        if re.search(r"(?:‌|\s)?و(?:‌|\s)?", cleaned):
            return False
        if cleaned.endswith(("م", "ین", "ام")):
            return False
        return True

    def _ordinal_is_word_prefix(match: re.Match[str], source: str) -> bool:
        """True when «درس دو» is only the start of «درس دوستی»."""
        end = match.end()
        if end >= len(source):
            return False
        nxt = source[end]
        return ("\u0600" <= nxt <= "\u06FF") or nxt.isalpha()

    def _followed_by_title(match: re.Match[str], source: str, token: str) -> bool:
        if not _is_bare_cardinal(token):
            return False
        rest = source[match.end() :].strip()
        if not rest:
            return False
        if re.match(
            r"^(?:"
            r"کتاب|فارسی|ریاضی|علوم|نگارش|قرآن|هدیه|مطالعات|اجتماعی|تفکر|فناوری|کار|"
            r"پایه|کلاس|صفحه|فصل|بخش|جلسه|مهارت|پروژه|دبستان|"
            r"چی|چیه|یعنی|باشه|دیگه|دیگر|"
            r"را\b|رو\b|و\b|،|,|\.|!|\?|؟"
            r")",
            rest,
            flags=re.IGNORECASE,
        ):
            return False
        next_token = re.split(r"[\s\u200c]+", rest, maxsplit=1)[0]
        next_token = next_token.strip("،,.!?؟«»\"'")
        if len(next_token) < 2:
            return False
        return any("\u0600" <= ch <= "\u06FF" for ch in next_token)

    digit_match = re.search(
        rf"(?:{alt})\s*(\d{{1,2}})",
        normalized,
        flags=re.IGNORECASE,
    )
    if not digit_match:
        digit_match = re.search(
            rf"(?<!\d)(\d{{1,2}})\s*(?:{alt})",
            normalized,
            flags=re.IGNORECASE,
        )
    if digit_match:
        # Digits are always unit numbers («مهارت ۳ کار و فناوری»).
        return int(digit_match.group(1))

    word_match = re.search(
        rf"(?:{alt})\s+({_LESSON_ORDINAL_ALT})",
        original,
        flags=re.IGNORECASE,
    )
    if not word_match:
        word_match = re.search(
            rf"({_LESSON_ORDINAL_ALT})\s*(?:{alt})",
            original,
            flags=re.IGNORECASE,
        )
    if word_match:
        token = word_match.group(1)
        if _ordinal_is_word_prefix(word_match, original):
            return None
        if _followed_by_title(word_match, original, token):
            return None
        return LESSON_ORDINAL_WORDS.get(token)
    return None


def _extract_child_unit(
    normalized: str, original: str
) -> tuple[str | None, int | None]:
    """Return (kind, number) for درس/جلسه/مهارت/پروژه — first match wins by priority."""
    for kind, labels in (
        ("skill", ("مهارت",)),
        ("project", ("پروژه", "پروژه‌ی", "پروژهٔ")),
        ("session", ("جلسه", "جلسه‌ی", "جلسهٔ")),
        ("lesson", ("درس",)),
    ):
        number = _extract_labeled_number(normalized, original, labels)
        if number is not None:
            return kind, number
    return None, None


def _extract_parent_unit(normalized: str, original: str) -> int | None:
    for labels in (("بخش",), ("فصل",)):
        number = _extract_labeled_number(normalized, original, labels)
        if number is not None:
            return number
    return None


def _wants_topic_search(text: str, parsed: ParsedQuery) -> bool:
    if parsed.page or parsed.lesson or parsed.wants_outline:
        return False
    if parsed.topic:
        return True
    if any(marker in text for marker in _TOPIC_INTENT_MARKERS):
        return True
    # Named content with grade/subject but no page (e.g. «میرزا کوچک خان فارسی ششم»)
    if parsed.search_text and (parsed.grade or parsed.subject):
        # Ignore tiny leftover phrases; allow single tokens like «ستایش».
        if len(parsed.search_text.split()) >= 2 or len(parsed.search_text) >= 5:
            return True
    return False


def _extract_search_text(normalized: str, parsed: ParsedQuery) -> str | None:
    """Strip structural tokens; keep distinctive content words for FTS."""
    cleaned = normalized
    # Remove page / lesson / grade / subject scaffolding.
    cleaned = re.sub(
        r"(?:صفحه[\s\u200c]*[ٔةهی]?|ص\.?)\s*\d{1,4}",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )

    def _strip_unit_number(match: re.Match[str]) -> str:
        """Keep «درس هفت خان رستم»; strip only real «درس هفت» / «درس ۷» locators."""
        token = match.group(0)
        # «درس دوستی» — ordinal is glued to the title word; keep the whole match.
        end = match.end()
        if end < len(cleaned):
            nxt = cleaned[end]
            if ("\u0600" <= nxt <= "\u06FF") or nxt.isalpha():
                return token
        # Digits and morphological ordinals are always locators.
        if re.search(r"\d", token):
            return " "
        # Bare cardinal + title word → keep the whole phrase for search_text.
        parts = re.split(r"\s+", token.strip(), maxsplit=1)
        cardinal = parts[1] if len(parts) > 1 else ""
        is_bare = bool(cardinal) and cardinal in LESSON_ORDINAL_WORDS and not (
            cardinal.endswith(("م", "ین", "ام"))
            or re.search(r"(?:‌|\s)?و(?:‌|\s)?", cardinal)
        )
        rest = cleaned[end:]
        rest_stripped = rest.lstrip()
        if is_bare and rest_stripped and not re.match(
            r"^(?:"
            r"کتاب|فارسی|ریاضی|علوم|نگارش|قرآن|هدیه|مطالعات|اجتماعی|تفکر|فناوری|کار|"
            r"پایه|کلاس|صفحه|فصل|بخش|جلسه|مهارت|پروژه|دبستان|"
            r"چی|چیه|یعنی|باشه|دیگه|دیگر|"
            r"را\b|رو\b|و\b|،|,|\.|!|\?|؟|$"
            r")",
            rest_stripped,
            flags=re.IGNORECASE,
        ):
            next_token = re.split(r"[\s\u200c]+", rest_stripped, maxsplit=1)[0]
            next_token = next_token.strip("،,.!?؟«»\"'")
            if len(next_token) >= 2 and any(
                "\u0600" <= ch <= "\u06FF" for ch in next_token
            ):
                # Keep ordinal as part of the title; drop only the unit label.
                return f" {cardinal} "
        return " "

    cleaned = re.sub(
        rf"(?:درس|فصل|بخش|جلسه|مهارت|پروژه)\s*(?:\d{{1,2}}|{_LESSON_ORDINAL_ALT})",
        _strip_unit_number,
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:لیست|فهرست)\s*(?:کن\s*)?(?:همهٔ?\s*)?(?:ی\s*)?"
        r"(?:فصل|فصول|بخش|درس|دروس|جلسه|جلسات|مهارت|پروژه|موضوع)"
        r"(?:[\u200c\s]*ها[یي]?)?",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"(?:پایه|کلاس)\s*(?:\d|سوم|چهارم|پنجم|ششم|سه|چهار|پنج|شش)",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    # Strip multi-word book names before tokenizing («هدیه های آسمان» → nothing,
    # not leftover «آسمان» which falsely matches «سخن آسمانی»).
    for phrase in sorted(BOOK_SUBJECT_SYNONYMS.keys(), key=len, reverse=True):
        if " " in phrase or "\u200c" in phrase:
            cleaned = cleaned.replace(phrase, " ")
    drop_words = {
        "کتاب",
        "کجا",
        "کجای",
        "مربوط",
        "به",
        "درباره",
        "درباره‌ی",
        "برام",
        "برایم",
        "لطفا",
        "لطفاً",
        "میشه",
        "می‌شه",
        "میخوای",
        "می‌خوای",
        "میخوام",
        "می‌خوام",
        "حل",
        "کنی",
        "کنید",
        "رو",
        "را",
        "از",
        "در",
        # Keep «با» / «و» — titles like «تقسیم با باقی‌مانده» / «… و محاسبات …»
        "که",
        "این",
        "اون",
        "آن",
        "های",
        "ها",
        "تموم",
        "تمام",
        "شد",
        "بریم",
        "سراغ",
        "بعد",
        "قبل",
        "لیست",
        "فهرست",
        "تمرین",
        "تمرینات",
        "تمرین‌ها",
        "تمرینهای",
        "سوال",
        "سؤال",
        "سوالات",
        "سؤالات",
        "درس",
        "فصل",
        "بخش",
        "جلسه",
        "مهارت",
        "پروژه",
        "آسمان",  # fragment of «هدیه های آسمان»
        *GRADE_WORDS.keys(),
        *BOOK_SUBJECT_SYNONYMS.keys(),
    }
    tokens = [
        t
        for t in re.split(r"\s+", cleaned.strip())
        if t and t not in drop_words and len(t) >= 2
    ]
    if not tokens:
        return None
    # Keep enough tokens for long Quran / multi-clause lesson titles.
    return " ".join(tokens[:16])
