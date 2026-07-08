from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.config import CATALOG_PATH, INDEX_PATH, PAGES_DIR


@dataclass
class PageRecord:
    grade: int
    subject: str
    subject_title: str
    printed_page: int
    text: str
    image_path: str | None
    is_scanned: bool


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
            SELECT grade, subject, subject_title, printed_page, text, image_path, is_scanned
            FROM pages
            WHERE grade = ? AND subject = ? AND printed_page = ?
            """,
            (grade, subject, printed_page),
        ).fetchone()
    if not row:
        return None
    return PageRecord(
        grade=int(row["grade"]),
        subject=str(row["subject"]),
        subject_title=str(row["subject_title"]),
        printed_page=int(row["printed_page"]),
        text=str(row["text"] or ""),
        image_path=str(row["image_path"]) if row["image_path"] else None,
        is_scanned=bool(row["is_scanned"]),
    )


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
               p.image_path, p.is_scanned
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

    return [
        PageRecord(
            grade=int(row["grade"]),
            subject=str(row["subject"]),
            subject_title=str(row["subject_title"]),
            printed_page=int(row["printed_page"]),
            text=str(row["text"] or ""),
            image_path=str(row["image_path"]) if row["image_path"] else None,
            is_scanned=bool(row["is_scanned"]),
        )
        for row in rows
    ]


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
