from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import CATALOG_PATH, INDEX_PATH, PAGES_DIR
from app.text_quality import is_text_garbled


@dataclass
class PageRecord:
    grade: int
    subject: str
    subject_title: str
    printed_page: int
    text: str
    image_path: str | None
    is_scanned: bool
    text_usable: bool = True


def _row_to_page(row: sqlite3.Row) -> PageRecord:
    text = str(row["text"] or "")
    keys = row.keys()
    if "text_usable" in keys and row["text_usable"] is not None:
        text_usable = bool(row["text_usable"])
    else:
        # Fallback for indexes built before the text_usable column existed.
        text_usable = bool(text.strip()) and not is_text_garbled(text)
    return PageRecord(
        grade=int(row["grade"]),
        subject=str(row["subject"]),
        subject_title=str(row["subject_title"]),
        printed_page=int(row["printed_page"]),
        text=text,
        image_path=str(row["image_path"]) if row["image_path"] else None,
        is_scanned=bool(row["is_scanned"]),
        text_usable=text_usable,
    )


@dataclass
class CatalogBook:
    file: str
    grade: int
    subject: str
    title: str
    page_offset: int = 0


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(INDEX_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def index_exists() -> bool:
    return INDEX_PATH.is_file()


def page_count() -> int:
    if not index_exists():
        return 0
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM pages").fetchone()
        return int(row["c"]) if row else 0


def load_catalog() -> list[CatalogBook]:
    if not CATALOG_PATH.is_file():
        return []
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    books: list[CatalogBook] = []
    for item in raw.get("books", []):
        books.append(
            CatalogBook(
                file=item["file"],
                grade=int(item["grade"]),
                subject=item["subject"],
                title=item.get("title", item["subject"]),
                page_offset=int(item.get("page_offset", 0)),
            )
        )
    return books


def get_page(grade: int, subject: str, printed_page: int) -> PageRecord | None:
    if not index_exists():
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT grade, subject, subject_title, printed_page, text, image_path,
                   is_scanned, text_usable
            FROM pages
            WHERE grade = ? AND subject = ? AND printed_page = ?
            """,
            (grade, subject, printed_page),
        ).fetchone()
    if not row:
        return None
    return _row_to_page(row)


def get_neighbor_pages(
    grade: int,
    subject: str,
    center_page: int,
    radius: int,
) -> list[PageRecord]:
    if not index_exists() or radius <= 0:
        return []
    pages: list[PageRecord] = []
    for offset in range(-radius, radius + 1):
        if offset == 0:
            continue
        neighbor = get_page(grade, subject, center_page + offset)
        if neighbor:
            pages.append(neighbor)
    return sorted(pages, key=lambda p: p.printed_page)


def topic_search(
    query: str,
    *,
    grade: int | None = None,
    subject: str | None = None,
    limit: int = 3,
) -> list[PageRecord]:
    if not index_exists():
        return []
    terms = _tokenize_for_fts(query)
    if not terms:
        return []

    match_query = " OR ".join(terms)
    sql = """
        SELECT p.grade, p.subject, p.subject_title, p.printed_page, p.text,
               p.image_path, p.is_scanned, p.text_usable
        FROM pages_fts f
        JOIN pages p ON p.id = f.rowid
        WHERE pages_fts MATCH ?
    """
    params: list[object] = [match_query]
    if grade is not None:
        sql += " AND p.grade = ?"
        params.append(grade)
    if subject is not None:
        sql += " AND p.subject = ?"
        params.append(subject)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    return [_row_to_page(row) for row in rows]


_LESSON_ORDINALS: dict[int, str] = {
    1: "اول",
    2: "دوم",
    3: "سوم",
    4: "چهارم",
    5: "پنجم",
    6: "ششم",
    7: "هفتم",
    8: "هشتم",
    9: "نهم",
    10: "دهم",
    11: "یازدهم",
    12: "دوازدهم",
    13: "سیزدهم",
    14: "چهاردهم",
    15: "پانزدهم",
    16: "شانزدهم",
    17: "هفدهم",
    18: "هجدهم",
    19: "نوزدهم",
    20: "بیستم",
}
_LESSON_UNIT_WORDS = ("درس", "فصل")
# Pages containing this many distinct lesson markers are treated as tables of
# contents / unit dividers and skipped when locating a lesson's real start page.
_LESSON_TOC_THRESHOLD = 3


def lesson_search(grade: int, subject: str, lesson_number: int) -> PageRecord | None:
    """Locate the start page of a lesson/chapter (درس/فصل) within a book.

    Lesson headers appear both on the table-of-contents pages (which list many
    lessons) and on the real lesson page (which references only its own). We
    pick the candidate page with the fewest distinct lesson markers.
    """
    import re as _re

    ordinal = _LESSON_ORDINALS.get(lesson_number)
    if not ordinal or not index_exists():
        return None

    target_patterns = [
        _re.compile(rf"{unit}\s*{ordinal}") for unit in _LESSON_UNIT_WORDS
    ]
    all_patterns = [
        _re.compile(rf"{unit}\s*{word}")
        for unit in _LESSON_UNIT_WORDS
        for word in _LESSON_ORDINALS.values()
    ]

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT grade, subject, subject_title, printed_page, text, image_path,
                   is_scanned, text_usable
            FROM pages
            WHERE grade = ? AND subject = ? AND printed_page > 0
            ORDER BY printed_page
            """,
            (grade, subject),
        ).fetchall()

    candidates: list[tuple[int, int, sqlite3.Row]] = []
    for row in rows:
        text = str(row["text"] or "")
        if not any(p.search(text) for p in target_patterns):
            continue
        distinct = sum(1 for p in all_patterns if p.search(text))
        candidates.append((distinct, int(row["printed_page"]), row))

    if not candidates:
        return None

    filtered = [c for c in candidates if c[0] < _LESSON_TOC_THRESHOLD]
    pool = filtered or candidates
    pool.sort(key=lambda c: (c[0], c[1]))
    return _row_to_page(pool[0][2])


def _tokenize_for_fts(text: str) -> list[str]:
    cleaned = "".join(ch if ch.isalnum() or "\u0600" <= ch <= "\u06FF" else " " for ch in text)
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 2]
    # FTS5: quote tokens to avoid syntax errors
    return [f'"{t}"' for t in tokens[:8]]


def resolve_image_path(image_path: str | None) -> Path | None:
    if not image_path:
        return None
    path = Path(image_path)
    if path.is_file():
        return path
    candidate = PAGES_DIR / path.name
    if candidate.is_file():
        return candidate
    candidate = Path(image_path)
    if candidate.is_file():
        return candidate
    return None
