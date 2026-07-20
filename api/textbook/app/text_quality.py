"""Detect garbled / unusable text from Persian textbook PDF extraction."""

from __future__ import annotations

import re

# Persian + Arabic letters, digits, common punctuation
_PERSIAN_CHAR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
# Latin letters outside normal ASCII (common in broken CMap extraction)
_GARBAGE_CHAR = re.compile(r"[\u00C0-\u024F\u0370-\u03FF\u1E00-\u1EFFƀ-ʿ]")

# High-signal Persian tokens used to detect character-reversed OCR lines.
_ORIENTATION_MARKERS = (
    "درس",
    "فصل",
    "صفحه",
    "تمرین",
    "پایه",
    "کلاس",
    "سوم",
    "چهارم",
    "پنجم",
    "ششم",
    "فارسی",
    "ریاضی",
    "علوم",
    "قرآن",
    "نگارش",
    "دبستان",
    "وزارت",
    "آموزش",
    "پرورش",
    "بخوانیم",
    "فعالیت",
    "سوال",
    "سؤال",
    "پاسخ",
    "معنی",
    "شعر",
    "داستان",
    "کتاب",
)


def persian_letter_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    persian = sum(1 for ch in letters if _PERSIAN_CHAR.match(ch))
    return persian / len(letters)


def is_text_garbled(text: str, *, min_chars: int = 40) -> bool:
    """
    True when extracted PDF text is likely unusable (custom font / bad CMap).

  Iranian schoolbook PDFs often produce mojibake like: ðآ موƦخŋتȺ
    """
    cleaned = text.strip()
    if len(cleaned) < min_chars:
        return False

    ratio = persian_letter_ratio(cleaned)
    if ratio < 0.35:
        return True

    garbage_hits = len(_GARBAGE_CHAR.findall(cleaned))
    if garbage_hits >= 2:
        return True

    return False


def _orientation_score(text: str) -> int:
    compact = text.replace("\u200c", "")
    return sum(1 for marker in _ORIENTATION_MARKERS if marker in compact)


def _arabic_letter_count(text: str) -> int:
    return sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")


def fix_rtl_char_reversal(text: str) -> str:
    """
    Fix MinerU/PaddleOCR lines that store Persian in visual (character-reversed) order.

    Example: «ناتسبد موس» → «سوم دبستان».

    When OCR dumps a page in visual order, nearly every Arabic line is reversed.
    We decide orientation at page level (not per line) so unmarked lines still flip.
    """
    if not text or _arabic_letter_count(text) < 4:
        return text

    lines = text.splitlines()
    arabic_idxs = [
        i for i, line in enumerate(lines) if _arabic_letter_count(line) >= 4
    ]
    if not arabic_idxs:
        return text

    flipped = list(lines)
    for i in arabic_idxs:
        flipped[i] = lines[i][::-1]
    flipped_text = "\n".join(flipped)

    original_score = _orientation_score(text)
    flipped_score = _orientation_score(flipped_text)

    # Count how many individual lines clearly prefer the flipped form.
    prefer_flip = 0
    prefer_orig = 0
    for i in arabic_idxs:
        o = _orientation_score(lines[i])
        f = _orientation_score(flipped[i])
        if f > o:
            prefer_flip += 1
        elif o > f:
            prefer_orig += 1

    if flipped_score > original_score or prefer_flip > prefer_orig:
        return flipped_text

    whole_rev = text[::-1]
    if _orientation_score(whole_rev) > original_score:
        return whole_rev
    return text
