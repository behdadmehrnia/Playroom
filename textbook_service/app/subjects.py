"""
Subject and topic resolution for Iranian elementary textbooks (grades 3–6).

Books use a canonical `subject` id (matches catalog.json).
Topics are sub-units inside a book (e.g. history inside social studies).
"""

from __future__ import annotations

import json
from pathlib import Path

from textbook_service.app.config import DATA_DIR

SUBJECT_TITLES: dict[str, str] = {
    "math": "ریاضی",
    "science": "علوم تجربی",
    "persian": "فارسی",
    "writing": "نگارش",
    "social": "مطالعات اجتماعی",
    "quran": "قرآن",
    "gifts": "هدیه‌های آسمان",
    "thinking": "تفکر و پژوهش",
    "technology": "کار و فناوری",
}

BOOK_SUBJECT_SYNONYMS: dict[str, str] = {
    "math": "math",
    "ریاضی": "math",
    "ریاضیات": "math",
    "science": "science",
    "علوم": "science",
    "علوم تجربی": "science",
    "تجربی": "science",
    "persian": "persian",
    "فارسی": "persian",
    "بخوانیم": "persian",
    "املا": "persian",
    "writing": "writing",
    "نگارش": "writing",
    "social": "social",
    "social_studies": "social",
    "مطالعات": "social",
    "مطالعات اجتماعی": "social",
    "اجتماعی": "social",
    "quran": "quran",
    "قرآن": "quran",
    "قران": "quran",
    # gifts / hadiye
    "gifts": "gifts",
    "hadiye": "gifts",
    "هدیه": "gifts",
    "هدیه های آسمان": "gifts",
    "هدیه‌های آسمان": "gifts",
    "هدیه‌های": "gifts",
    # grade 6 extras
    "thinking": "thinking",
    "تفکر": "thinking",
    "تفکر و پژوهش": "thinking",
    "پژوهش": "thinking",
    "technology": "technology",
    "کار و فناوری": "technology",
    "فناوری": "technology",
    "کارفناوری": "technology",
}

# Default topic → parent subject (overridable via data/subject_topics.json)
DEFAULT_TOPIC_ALIASES: dict[str, str] = {
    # inside social studies
    "تاریخ": "social",
    "تاریخ ایران": "social",
    "تاریخ جهان": "social",
    "جغرافیا": "social",
    "جغرافی": "social",
    "مدنی": "social",
    "نهادهای اجتماعی": "social",
    "شهروندی": "social",
    "اقتصاد": "social",
    "مکان": "social",
    "محیط": "social",
    "درس تاریخ": "social",
    "درس جغرافیا": "social",
    "درس مدنی": "social",
}

TOPIC_LABELS: dict[str, str] = {
    "history": "تاریخ",
    "geography": "جغرافیا",
    "civics": "مدنی / نهادهای اجتماعی",
    "economics": "اقتصاد",
}


def _load_topic_config() -> tuple[dict[str, str], dict[str, dict[str, list[str]]]]:
    """
    Load optional data/subject_topics.json.

    Format:
    {
      "social": {
        "topics": [
          {"id": "history", "aliases": ["تاریخ", "تاریخ ایران"]},
          {"id": "geography", "aliases": ["جغرافیا"]}
        ]
      }
    }
    """
    path = DATA_DIR / "subject_topics.json"
    if not path.is_file():
        return dict(DEFAULT_TOPIC_ALIASES), {}

    raw = json.loads(path.read_text(encoding="utf-8"))
    aliases: dict[str, str] = dict(DEFAULT_TOPIC_ALIASES)
    by_subject: dict[str, dict[str, list[str]]] = {}

    for subject_id, config in raw.items():
        if not isinstance(config, dict):
            continue
        topic_map: dict[str, list[str]] = {}
        for topic in config.get("topics", []):
            if not isinstance(topic, dict):
                continue
            topic_id = str(topic.get("id", "")).strip()
            topic_aliases = topic.get("aliases", [])
            if not topic_id or not isinstance(topic_aliases, list):
                continue
            normalized_aliases = [str(a).strip() for a in topic_aliases if str(a).strip()]
            topic_map[topic_id] = normalized_aliases
            for alias in normalized_aliases:
                aliases[alias] = subject_id
        if topic_map:
            by_subject[subject_id] = topic_map

    return aliases, by_subject


TOPIC_ALIASES, TOPICS_BY_SUBJECT = _load_topic_config()


def all_book_synonyms() -> dict[str, str]:
    return BOOK_SUBJECT_SYNONYMS


def all_topic_aliases() -> dict[str, str]:
    return TOPIC_ALIASES


def topic_label(topic_id: str | None) -> str | None:
    if not topic_id:
        return None
    return TOPIC_LABELS.get(topic_id)


def resolve_topic_id(subject: str, matched_alias: str) -> str | None:
    """Return topic id (e.g. history) when alias came from topic map."""
    if not matched_alias:
        return None
    subject_topics = TOPICS_BY_SUBJECT.get(subject, {})
    for topic_id, aliases in subject_topics.items():
        if matched_alias in aliases:
            return topic_id
    return None
