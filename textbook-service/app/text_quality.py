"""Detect garbled / unusable text from Persian textbook PDF extraction."""

from __future__ import annotations

import re

# Persian + Arabic letters, digits, common punctuation
_PERSIAN_CHAR = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
# Latin letters outside normal ASCII (common in broken CMap extraction)
_GARBAGE_CHAR = re.compile(r"[\u00C0-\u024F\u0370-\u03FF\u1E00-\u1EFFƀ-ʿ]")


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
    if ratio < 0.55:
        return True

    garbage_hits = len(_GARBAGE_CHAR.findall(cleaned))
    if garbage_hits >= 3:
        return True

    return False
