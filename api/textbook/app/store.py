from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from api.textbook.app.config import CATALOG_PATH, DATA_DIR, INDEX_PATH, PAGES_DIR
from api.textbook.app.subjects import SUBJECT_TITLES
from api.textbook.app.text_quality import is_text_garbled


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
class CatalogChapter:
    number: int
    start_page: int
    title: str = ""


CHILD_KINDS = ("lesson", "session", "project", "skill", "topic")
KIND_LABELS: dict[str, str] = {
    "lesson": "درس",
    "session": "جلسه",
    "project": "پروژه",
    "skill": "مهارت",
    "topic": "زیربخش",
}
# Aliases kids say → kind
KIND_ALIASES: dict[str, str] = {
    "درس": "lesson",
    "جلسه": "session",
    "جلسه‌ی": "session",
    "جلسهٔ": "session",
    "پروژه": "project",
    "پروژه‌ی": "project",
    "پروژهٔ": "project",
    "مهارت": "skill",
}


@dataclass
class CatalogLesson:
    number: int
    start_page: int
    title: str = ""
    chapter: int | None = None
    kind: str = "lesson"
    aliases: list[str] = field(default_factory=list)

    @property
    def kind_label(self) -> str:
        return KIND_LABELS.get(self.kind, "درس")

    def all_titles(self) -> list[str]:
        titles = [self.title] if self.title else []
        titles.extend(a for a in self.aliases if a)
        return titles


@dataclass
class CatalogTitleHit:
    """Result of matching a free-text title against the manual catalog."""

    start_page: int
    unit: Literal["lesson", "chapter"] = "lesson"
    number: int | None = None
    kind: str = "lesson"
    title: str = ""
    chapter: int | None = None
    score: int = 0


@dataclass
class CatalogBook:
    file: str
    grade: int
    subject: str
    title: str
    page_offset: int = 0
    parent_label: str = "فصل"
    chapters: list[CatalogChapter] = field(default_factory=list)
    lessons: list[CatalogLesson] = field(default_factory=list)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(INDEX_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def index_exists() -> bool:
    if not INDEX_PATH.is_file():
        return False
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
            ).fetchone()
            return row is not None
    except sqlite3.DatabaseError:
        return False


def page_count() -> int:
    if not index_exists():
        return 0
    try:
        with _connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM pages").fetchone()
            return int(row["c"]) if row else 0
    except sqlite3.OperationalError:
        return 0


def _parse_catalog_int(value: object) -> int | None:
    """Accept int or digit strings (Latin / Persian / Arabic-Indic)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        from api.textbook.app.parser import normalize_digits

        cleaned = normalize_digits(value).strip()
        if cleaned.isdigit():
            return int(cleaned)
    return None


def _parse_catalog_chapters(raw: object) -> list[CatalogChapter]:
    if not isinstance(raw, list):
        return []
    out: list[CatalogChapter] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        number = _parse_catalog_int(item.get("number"))
        start_page = _parse_catalog_int(item.get("start_page"))
        if number is None or start_page is None:
            continue
        if number < 1 or start_page < 1:
            continue
        out.append(
            CatalogChapter(
                number=number,
                start_page=start_page,
                title=str(item.get("title") or "").strip(),
            )
        )
    return out


def _parse_catalog_kind(raw: object) -> str:
    kind = str(raw or "lesson").strip().lower()
    if kind in CHILD_KINDS:
        return kind
    # Persian label in JSON → kind id
    for alias, canonical in KIND_ALIASES.items():
        if kind == alias or kind == canonical:
            return canonical
    return "lesson"


def _parse_catalog_lessons(raw: object) -> list[CatalogLesson]:
    if not isinstance(raw, list):
        return []
    out: list[CatalogLesson] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        number = _parse_catalog_int(item.get("number"))
        start_page = _parse_catalog_int(item.get("start_page"))
        if number is None or start_page is None:
            continue
        if number < 1 or start_page < 1:
            continue
        chapter_no = _parse_catalog_int(item.get("chapter"))
        aliases_raw = item.get("aliases")
        aliases: list[str] = []
        if isinstance(aliases_raw, list):
            aliases = [str(a).strip() for a in aliases_raw if str(a).strip()]
        elif isinstance(aliases_raw, str) and aliases_raw.strip():
            aliases = [aliases_raw.strip()]
        out.append(
            CatalogLesson(
                number=number,
                start_page=start_page,
                title=str(item.get("title") or "").strip(),
                chapter=chapter_no if chapter_no and chapter_no >= 1 else None,
                kind=_parse_catalog_kind(item.get("kind")),
                aliases=aliases,
            )
        )
    return out


def load_catalog() -> list[CatalogBook]:
    if not CATALOG_PATH.is_file():
        return []
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    books: list[CatalogBook] = []
    for item in raw.get("books", []):
        if not isinstance(item, dict):
            continue
        parent_label = str(item.get("parent_label") or "فصل").strip() or "فصل"
        books.append(
            CatalogBook(
                file=item["file"],
                grade=int(item["grade"]),
                subject=item["subject"],
                title=item.get("title", item["subject"]),
                page_offset=int(item.get("page_offset", 0)),
                parent_label=parent_label,
                chapters=_parse_catalog_chapters(item.get("chapters")),
                lessons=_parse_catalog_lessons(item.get("lessons")),
            )
        )
    return books


def get_catalog_book(grade: int, subject: str) -> CatalogBook | None:
    subject_id = (subject or "").strip()
    for book in load_catalog():
        if book.grade == grade and book.subject == subject_id:
            return book
    return None


def catalog_health_stats() -> dict[str, int | str]:
    """Counts for /health — empty lesson maps mean the volume catalog is stale."""
    books = load_catalog()
    with_lessons = sum(1 for book in books if book.lessons)
    lesson_entries = sum(len(book.lessons) for book in books)
    return {
        "catalog_books": len(books),
        "catalog_books_with_lessons": with_lessons,
        "catalog_lesson_entries": lesson_entries,
        "catalog_path": str(CATALOG_PATH),
    }


def lookup_catalog_start_page(
    grade: int,
    subject: str,
    *,
    chapter: int | None = None,
    lesson: int | None = None,
    kind: str | None = None,
) -> int | None:
    """Resolve printed start page from manual catalog chapter/child maps."""
    book = get_catalog_book(grade, subject)
    if book is None:
        return None
    if chapter is not None:
        for entry in book.chapters:
            if entry.number == chapter:
                return entry.start_page
    if lesson is not None:
        want_kind = _parse_catalog_kind(kind) if kind else None
        for entry in book.lessons:
            if entry.number != lesson:
                continue
            if want_kind is None:
                # Prefer exact lesson kind; else first matching number.
                if entry.kind == "lesson":
                    return entry.start_page
                continue
            if entry.kind == want_kind:
                return entry.start_page
        if want_kind is None:
            for entry in book.lessons:
                if entry.number == lesson:
                    return entry.start_page
        # Session requested but only lessons exist (or vice versa).
        if want_kind == "session":
            for entry in book.lessons:
                if entry.number == lesson and entry.kind == "lesson":
                    return entry.start_page
        if want_kind == "lesson":
            for entry in book.lessons:
                if entry.number == lesson and entry.kind == "session":
                    return entry.start_page
    return None


_CATALOG_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _normalize_catalog_title(text: str) -> str:
    cleaned = (text or "").replace("\u200c", " ").strip().lower()
    cleaned = cleaned.translate(_CATALOG_DIGIT_MAP)
    cleaned = re.sub(r"[«»\"'`]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _compact_catalog_title(text: str) -> str:
    return _normalize_catalog_title(text).replace(" ", "")


def _connectorless_compact(text: str) -> str:
    """Compact title with optional Persian connectors removed for fuzzy match."""
    cleaned = _normalize_catalog_title(text)
    cleaned = re.sub(r"\b(?:و|با|در|از|به)\b", " ", cleaned)
    return re.sub(r"\s+", "", cleaned)


def _score_title_match(needle: str, title: str) -> int:
    """Score a catalog title against a free-text needle (0 = no match)."""
    etitle = _normalize_catalog_title(title)
    if not etitle or not needle:
        return 0
    if needle == etitle:
        return 100
    n_compact = _compact_catalog_title(needle)
    e_compact = _compact_catalog_title(etitle)
    if n_compact and e_compact and (n_compact == e_compact):
        return 98
    n_fuzzy = _connectorless_compact(needle)
    e_fuzzy = _connectorless_compact(etitle)
    if n_fuzzy and e_fuzzy and n_fuzzy == e_fuzzy:
        return 96
    # Parenthetical / digit disambiguation: «فرهنگ بومی ۲» vs «۱»
    n_digits = re.findall(r"\d+", needle)
    e_digits = re.findall(r"\d+", etitle)
    digit_bonus = 0
    if n_digits and e_digits:
        if n_digits[-1] == e_digits[-1]:
            digit_bonus = 15
        else:
            # Wrong edition number — heavily penalize bare shared stem.
            digit_bonus = -40
    # Containment must stay below exact (100) so «حروف ناخوانا (۱)» beats
    # «تمرین حروف ناخوانا (۱)» and nearer lengths win ties.
    if needle in etitle or etitle in needle:
        length_gap = abs(len(etitle) - len(needle))
        return max(0, 72 + digit_bonus - length_gap)
    if n_compact and e_compact and (
        n_compact in e_compact or e_compact in n_compact
    ):
        length_gap = abs(len(e_compact) - len(n_compact))
        return max(0, 65 + digit_bonus - length_gap // 2)
    if n_fuzzy and e_fuzzy and (n_fuzzy in e_fuzzy or e_fuzzy in n_fuzzy):
        length_gap = abs(len(e_fuzzy) - len(n_fuzzy))
        return max(0, 62 + digit_bonus - length_gap // 2)
    n_tokens = {t for t in needle.split() if len(t) >= 2}
    e_tokens = {t for t in etitle.split() if len(t) >= 2}
    # Ignore light connectors for token comparison.
    connectors = {"با", "در", "از", "به"}
    n_tokens -= connectors
    e_tokens -= connectors
    if n_tokens and n_tokens <= e_tokens:
        return max(0, 55 + digit_bonus)
    if n_tokens and e_tokens and len(n_tokens & e_tokens) >= max(2, len(n_tokens) - 1):
        return max(0, 50 + digit_bonus)
    return 0


def lookup_catalog_entry_by_title(
    grade: int, subject: str, title: str
) -> CatalogTitleHit | None:
    """Match a lesson/chapter title from the manual catalog (rich result)."""
    needle = _normalize_catalog_title(title)
    if not needle or len(needle) < 2:
        return None
    # Drop «تمرین» only when it is scaffolding before a unit label
    # («تمرین درس ارزش علم»). Keep real titles like «تمرین حروف ناخوانا (۱)».
    needle = re.sub(
        r"^تمرین(?:‌ها|ات|های)?\s+(?=(?:درس|فصل|بخش|جلسه|مهارت|پروژه)\b)",
        "",
        needle,
    ).strip()
    for _ in range(3):
        stripped = re.sub(
            r"^(?:درس|فصل|بخش|جلسه|مهارت|پروژه)\s+",
            "",
            needle,
        ).strip()
        if stripped == needle:
            break
        needle = stripped
    if not needle:
        return None
    book = get_catalog_book(grade, subject)
    if book is None:
        return None

    candidates: list[CatalogTitleHit] = []
    for entry in book.lessons:
        best = 0
        best_title = entry.title
        for candidate_title in entry.all_titles():
            score = _score_title_match(needle, candidate_title)
            if score > best:
                best = score
                best_title = candidate_title
        if best:
            candidates.append(
                CatalogTitleHit(
                    start_page=entry.start_page,
                    unit="lesson",
                    number=entry.number,
                    kind=entry.kind,
                    title=best_title or entry.title,
                    chapter=entry.chapter,
                    score=best,
                )
            )
    for entry in book.chapters:
        score = _score_title_match(needle, entry.title)
        if score:
            candidates.append(
                CatalogTitleHit(
                    start_page=entry.start_page,
                    unit="chapter",
                    number=entry.number,
                    kind="chapter",
                    title=entry.title,
                    chapter=entry.number,
                    score=score,
                )
            )
    if not candidates:
        return None
    # Prefer higher score, then nearer title length, then earlier unit number,
    # then lessons over chapters. Duplicate exact titles («حل مسئله») resolve
    # to the first occurrence in the book.
    needle_len = len(needle)
    candidates.sort(
        key=lambda item: (
            item.score,
            -abs(len(_normalize_catalog_title(item.title or "")) - needle_len),
            3 if item.unit == "lesson" else 1,
            -(item.number or 10**6),
        ),
        reverse=True,
    )
    best = candidates[0]
    return best if best.score >= 50 else None


def lookup_catalog_by_title(grade: int, subject: str, title: str) -> int | None:
    """Match a lesson/chapter title from the manual catalog (e.g. «ارزش علم»)."""
    hit = lookup_catalog_entry_by_title(grade, subject, title)
    return hit.start_page if hit is not None else None


def grades_for_subject(subject: str) -> list[int]:
    """Grades that have this subject in catalog.json (sorted)."""
    grades = sorted(
        {
            book.grade
            for book in load_catalog()
            if book.subject == subject
        }
    )
    return grades


def index_has_book(grade: int, subject: str) -> bool:
    """True when the SQLite index has at least one page for this book."""
    if not index_exists():
        return False
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM pages
            WHERE grade = ? AND subject = ? AND printed_page > 0
            LIMIT 1
            """,
            (grade, subject),
        ).fetchone()
    return row is not None


def book_exists_for_grade(grade: int, subject: str) -> bool:
    """True if catalog or index lists this grade+subject textbook."""
    if any(b.grade == grade and b.subject == subject for b in load_catalog()):
        return True
    return index_has_book(grade, subject)


def find_book_by_file(filename: str) -> CatalogBook | None:
    for book in load_catalog():
        if book.file == filename:
            return book
    return None


def upsert_book(book: CatalogBook) -> bool:
    """
    Add or update a book entry in catalog.json, matched by ``file``.

    Returns True if the catalog file was modified (new entry added or an
    existing one changed). Preserves the top-level ``_instructions`` block
    and any other non-``books`` keys.
    """
    if not CATALOG_PATH.is_file():
        raw: dict[str, object] = {"books": []}
    else:
        raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    books = raw.get("books", [])
    if not isinstance(books, list):
        books = []
        raw["books"] = books

    entry = {
        "file": book.file,
        "grade": book.grade,
        "subject": book.subject,
        "title": book.title,
        "page_offset": book.page_offset,
    }
    if book.parent_label and book.parent_label != "فصل":
        entry["parent_label"] = book.parent_label
    if book.chapters:
        entry["chapters"] = [
            {
                "number": ch.number,
                "start_page": ch.start_page,
                **({"title": ch.title} if ch.title else {}),
            }
            for ch in book.chapters
        ]
    if book.lessons:
        entry["lessons"] = [
            {
                "number": les.number,
                "start_page": les.start_page,
                **({"title": les.title} if les.title else {}),
                **({"chapter": les.chapter} if les.chapter is not None else {}),
                **({"kind": les.kind} if les.kind and les.kind != "lesson" else {}),
            }
            for les in book.lessons
        ]

    for i, existing in enumerate(books):
        if isinstance(existing, dict) and existing.get("file") == book.file:
            # Preserve manually curated chapter/lesson maps unless caller provided new ones.
            merged = {**existing, **entry}
            if "chapters" not in entry and "chapters" in existing:
                merged["chapters"] = existing["chapters"]
            if "lessons" not in entry and "lessons" in existing:
                merged["lessons"] = existing["lessons"]
            if "parent_label" not in entry and "parent_label" in existing:
                merged["parent_label"] = existing["parent_label"]
            if merged == existing:
                return False
            books[i] = merged
            _write_catalog(raw)
            return True

    books.append(entry)
    raw["books"] = books
    _write_catalog(raw)
    return True


def _write_catalog(raw: dict[str, object]) -> None:
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _page_image_relpath(grade: int, subject: str, printed_page: int) -> str:
    return f"pages/g{grade}_{subject}_p{printed_page}.png"


def _image_only_page(
    grade: int,
    subject: str,
    printed_page: int,
) -> PageRecord | None:
    """Build a vision-only page record when SQLite index is missing/incomplete."""
    rel = _page_image_relpath(grade, subject, printed_page)
    path = resolve_image_path(rel)
    if path is None or not path.is_file():
        return None
    book = get_catalog_book(grade, subject)
    title = book.title if book else SUBJECT_TITLES.get(subject, subject)
    return PageRecord(
        grade=grade,
        subject=subject,
        subject_title=title,
        printed_page=printed_page,
        text="",
        image_path=rel,
        is_scanned=True,
        text_usable=False,
    )


def get_page(grade: int, subject: str, printed_page: int) -> PageRecord | None:
    if index_exists():
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
        if row:
            return _row_to_page(row)
    return _image_only_page(grade, subject, printed_page)


def get_printed_page_bounds(
    grade: int | None,
    subject: str,
) -> tuple[int, int] | None:
    """
    Return (min_printed_page, max_printed_page) for a book in the existing index.

    Uses only ``printed_page`` values already stored by the MinerU/indexer pipeline
    (offset already applied at index time). Does not read raw PDF page counts.
    When ``grade`` is None, aggregates across all grades for that subject.
    Falls back to on-disk page images when the SQLite index is missing.
    """
    if not subject:
        return None
    if index_exists():
        sql = """
            SELECT MIN(printed_page) AS min_p, MAX(printed_page) AS max_p
            FROM pages
            WHERE subject = ? AND printed_page > 0
        """
        params: list[object] = [subject]
        if grade is not None:
            sql += " AND grade = ?"
            params.append(grade)
        with _connect() as conn:
            row = conn.execute(sql, params).fetchone()
        if row and row["min_p"] is not None and row["max_p"] is not None:
            return int(row["min_p"]), int(row["max_p"])
    return _disk_page_bounds(grade, subject)


def _disk_page_bounds(
    grade: int | None,
    subject: str,
) -> tuple[int, int] | None:
    """Infer printed-page range from ``pages/g{grade}_{subject}_pN.png`` files."""
    if not PAGES_DIR.is_dir():
        return None
    numbers: list[int] = []
    if grade is not None:
        pattern = f"g{grade}_{subject}_p*.png"
        for path in PAGES_DIR.glob(pattern):
            match = re.search(r"_p(\d+)\.png$", path.name)
            if match:
                numbers.append(int(match.group(1)))
    else:
        pattern = f"g*_{subject}_p*.png"
        for path in PAGES_DIR.glob(pattern):
            match = re.search(rf"^g\d+_{re.escape(subject)}_p(\d+)\.png$", path.name)
            if match:
                numbers.append(int(match.group(1)))
    if not numbers:
        return None
    return min(numbers), max(numbers)


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
        neighbor_page = center_page + offset
        # Front-matter / offset leftovers (printed_page <= 0) must not leak into
        # LLM context as if they were real student pages.
        if neighbor_page <= 0:
            continue
        neighbor = get_page(grade, subject, neighbor_page)
        if neighbor:
            pages.append(neighbor)
    return sorted(pages, key=lambda p: p.printed_page)


_MAX_UNIT_PAGES = 40


def list_lesson_starts(
    grade: int,
    subject: str,
    *,
    kind: str | None = None,
) -> list[tuple[int, int]]:
    """Return [(number, start_page), ...] from catalog, sorted by start page."""
    book = get_catalog_book(grade, subject)
    if book is None:
        return []
    want = _parse_catalog_kind(kind) if kind else None
    starts: list[tuple[int, int]] = []
    for entry in book.lessons:
        if want is not None and entry.kind != want:
            # Allow lesson↔session soft match when filtering for either.
            if not (
                want in {"lesson", "session"}
                and entry.kind in {"lesson", "session"}
            ):
                continue
        starts.append((entry.number, entry.start_page))
    starts.sort(key=lambda item: (item[1], item[0]))
    return starts


def list_chapter_starts(grade: int, subject: str) -> list[tuple[int, int]]:
    book = get_catalog_book(grade, subject)
    if book is None:
        return []
    starts = [(ch.number, ch.start_page) for ch in book.chapters]
    starts.sort(key=lambda item: (item[1], item[0]))
    return starts


def get_lesson_bounds(
    grade: int | None,
    subject: str | None,
    *,
    kind: str | None = None,
) -> tuple[int, int] | None:
    """Return (min_number, max_number) for catalog children of the given kind."""
    if grade is None or not subject:
        return None
    book = get_catalog_book(grade, subject)
    if book is None or not book.lessons:
        return None
    want = _parse_catalog_kind(kind) if kind else "lesson"
    numbers = sorted(
        {
            e.number
            for e in book.lessons
            if e.kind == want
            or (
                want in {"lesson", "session"}
                and e.kind in {"lesson", "session"}
            )
        }
    )
    if not numbers:
        # Fall back to all child numbers when kind filter empty (topic-only books).
        if kind is None:
            numbers = sorted({e.number for e in book.lessons})
        if not numbers:
            return None
    return numbers[0], numbers[-1]


def get_chapter_bounds(grade: int | None, subject: str | None) -> tuple[int, int] | None:
    if grade is None or not subject:
        return None
    starts = list_chapter_starts(grade, subject)
    if not starts:
        return None
    numbers = sorted({n for n, _ in starts})
    return numbers[0], numbers[-1]


def _span_end_from_starts(
    start_page: int,
    starts: list[tuple[int, int]],
    *,
    max_pages: int,
    book_max_page: int | None,
) -> int:
    end = start_page + max_pages - 1
    for _number, other_start in starts:
        if other_start > start_page:
            end = min(end, other_start - 1)
            break
    else:
        if book_max_page is not None and book_max_page >= start_page:
            end = min(end, book_max_page)
    if end < start_page:
        end = start_page
    return end


def _book_max_printed_page(grade: int, subject: str) -> int | None:
    bounds = get_printed_page_bounds(grade, subject)
    return bounds[1] if bounds else None


def _collect_pages(grade: int, subject: str, start: int, end: int) -> list[PageRecord]:
    pages: list[PageRecord] = []
    for printed in range(start, end + 1):
        record = get_page(grade, subject, printed)
        if record:
            pages.append(record)
    return pages


def lesson_search(
    grade: int,
    subject: str,
    lesson_number: int,
    *,
    kind: str | None = None,
) -> PageRecord | None:
    """Locate the catalog start page of a child unit and load it from the index."""
    start = lookup_catalog_start_page(
        grade, subject, lesson=lesson_number, kind=kind
    )
    if start is None:
        return None
    return get_page(grade, subject, start)


def find_chapter_containing_page(
    grade: int,
    subject: str,
    page: int,
) -> int | None:
    """Return the catalog parent-unit number that contains ``page``."""
    book = get_catalog_book(grade, subject)
    if book is None or not book.chapters:
        return None
    chapters = sorted(book.chapters, key=lambda ch: ch.start_page)
    chosen: int | None = None
    for ch in chapters:
        if ch.start_page <= page:
            chosen = ch.number
        else:
            break
    return chosen


def find_chapter_for_lesson(
    grade: int,
    subject: str,
    lesson_number: int,
    *,
    kind: str | None = None,
) -> int | None:
    """Return the parent chapter number for a catalog child unit."""
    book = get_catalog_book(grade, subject)
    if book is None:
        return None
    want = _parse_catalog_kind(kind) if kind else None
    for entry in book.lessons:
        if entry.number != lesson_number:
            continue
        if want is not None and entry.kind != want:
            if not (
                want in {"lesson", "session"}
                and entry.kind in {"lesson", "session"}
            ):
                continue
        if entry.chapter is not None:
            return entry.chapter
    return None


def find_lesson_containing_page(
    grade: int,
    subject: str,
    page: int,
) -> tuple[int, int, int] | None:
    """Return (lesson_number, start_page, end_page) for the catalog unit containing page."""
    book = get_catalog_book(grade, subject)
    if book is None or not book.lessons:
        return None
    # All child starts sorted by page (any kind) for contiguous spans.
    starts = sorted(
        [(e.number, e.start_page) for e in book.lessons],
        key=lambda item: item[1],
    )
    chosen: tuple[int, int] | None = None
    for number, start in starts:
        if start <= page:
            chosen = (number, start)
        else:
            break
    if chosen is None:
        return None
    number, start = chosen
    book_max = _book_max_printed_page(grade, subject)
    end = _span_end_from_starts(
        start, starts, max_pages=_MAX_UNIT_PAGES, book_max_page=book_max
    )
    if page < start or page > end:
        return None
    return number, start, end


def get_lesson_pages(
    grade: int,
    subject: str,
    *,
    lesson_number: int | None = None,
    page: int | None = None,
    kind: str | None = None,
    max_pages: int = _MAX_UNIT_PAGES,
) -> tuple[list[PageRecord], int | None, int | None, int | None]:
    """Return (pages, lesson_number, start_page, end_page) from catalog maps.

    Works with SQLite index when present; otherwise falls back to on-disk page images.
    """
    book = get_catalog_book(grade, subject)
    all_starts = (
        sorted([(e.number, e.start_page) for e in book.lessons], key=lambda i: i[1])
        if book
        else []
    )
    book_max = _book_max_printed_page(grade, subject)

    start: int | None = None
    end: int | None = None
    resolved = lesson_number

    if lesson_number is not None:
        start = lookup_catalog_start_page(
            grade, subject, lesson=lesson_number, kind=kind
        )
        if start is None:
            return [], None, None, None
        end = _span_end_from_starts(
            start, all_starts, max_pages=max_pages, book_max_page=book_max
        )
    elif page is not None:
        found = find_lesson_containing_page(grade, subject, page)
        if not found:
            single = get_page(grade, subject, page)
            return ([single] if single else []), None, page, page
        resolved, start, end = found
    else:
        return [], None, None, None

    if start is None or end is None:
        return [], None, None, None
    pages = _collect_pages(grade, subject, start, end)
    return pages, resolved, start, end


def get_chapter_pages(
    grade: int,
    subject: str,
    *,
    chapter_number: int,
    max_pages: int = _MAX_UNIT_PAGES,
) -> tuple[list[PageRecord], int | None, int | None, int | None]:
    """Return (pages, chapter_number, start_page, end_page) for a catalog parent unit."""
    start = lookup_catalog_start_page(grade, subject, chapter=chapter_number)
    if start is None:
        return [], None, None, None
    starts = list_chapter_starts(grade, subject)
    book_max = _book_max_printed_page(grade, subject)
    end = _span_end_from_starts(
        start, starts, max_pages=max_pages, book_max_page=book_max
    )
    pages = _collect_pages(grade, subject, start, end)
    return pages, chapter_number, start, end


def format_catalog_outline(
    grade: int,
    subject: str,
    *,
    chapter: int | None = None,
) -> str | None:
    """Human-readable structure block for the LLM (labels from catalog)."""
    book = get_catalog_book(grade, subject)
    if book is None:
        return None
    parent_label = book.parent_label or "فصل"
    lines: list[str] = [
        f"ساختار کتاب «{book.title}» (پایه {book.grade}) — فقط از همین فهرست استفاده کن:"
    ]
    chapters = book.chapters
    if chapter is not None:
        chapters = [c for c in book.chapters if c.number == chapter]
        if not chapters and book.chapters:
            return None

    book_max = _book_max_printed_page(grade, subject)
    chapter_starts = list_chapter_starts(grade, subject)
    lesson_starts = sorted(
        [(e.number, e.start_page) for e in book.lessons],
        key=lambda item: item[1],
    )

    def _end_for(start: int, starts: list[tuple[int, int]]) -> int:
        return _span_end_from_starts(
            start, starts, max_pages=_MAX_UNIT_PAGES, book_max_page=book_max
        )

    if chapters:
        lines.append(
            f"این کتاب {len(book.chapters)} {parent_label} و "
            f"{len(book.lessons)} واحد فرزند دارد."
        )
        for ch in sorted(chapters, key=lambda c: c.number):
            title = f" — {ch.title}" if ch.title else ""
            ch_end = _end_for(ch.start_page, chapter_starts)
            page_bit = (
                f"صفحات {ch.start_page} تا {ch_end}"
                if ch_end > ch.start_page
                else f"از صفحه {ch.start_page}"
            )
            lines.append(f"{parent_label} {ch.number}{title} ({page_bit})")
            children = [
                e
                for e in book.lessons
                if e.chapter == ch.number
            ]
            children.sort(key=lambda e: (e.start_page, e.number))
            for e in children:
                et = f" — {e.title}" if e.title else ""
                end = _end_for(e.start_page, lesson_starts)
                page_bit = (
                    f"صفحات {e.start_page} تا {end}"
                    if end > e.start_page
                    else f"صفحه {e.start_page}"
                )
                lines.append(
                    f"  - {e.kind_label} {e.number}{et} ({page_bit})"
                )
    else:
        # Flat book (gifts/science): list children only.
        children = sorted(book.lessons, key=lambda e: (e.start_page, e.number))
        if not children:
            return None
        lines.append(f"این کتاب {len(children)} واحد دارد.")
        for e in children:
            et = f" — {e.title}" if e.title else ""
            end = _end_for(e.start_page, lesson_starts)
            page_bit = (
                f"صفحات {e.start_page} تا {end}"
                if end > e.start_page
                else f"صفحه {e.start_page}"
            )
            lines.append(
                f"{e.kind_label} {e.number}{et} ({page_bit})"
            )
    return "\n".join(lines)



def _tokenize_for_fts(text: str) -> list[str]:
    cleaned = "".join(
        ch if ch.isalnum() or "\u0600" <= ch <= "\u06FF" else " " for ch in text
    )
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) >= 2]
    # Drop ultra-common query filler words so FTS focuses on content names.
    stop = {
        "کجا",
        "کجای",
        "کتاب",
        "مربوط",
        "درباره",
        "درباره‌ی",
        "صفحه",
        "پایه",
        "کلاس",
        "درس",
        "فصل",
        "تمرین",
        "تمرینات",
        "تمرین‌ها",
        "سوال",
        "سؤال",
        "برام",
        "برایم",
        "کنی",
        "کنید",
        "میخوای",
        "میخوام",
        "می‌خوام",
        "می‌خوای",
        "حل",
        "رو",
        "را",
        "به",
        "از",
        "در",
        "با",
        "که",
        "این",
        "اون",
        "آن",
    }
    kept = [t for t in tokens if t not in stop and t not in SUBJECT_STOPWORDS]
    if not kept:
        kept = tokens
    # FTS5: quote tokens to avoid syntax errors
    quoted = [f'"{t}"' for t in kept[:10]]
    # Also try concatenating adjacent tokens (میرزا کوچک → میرزاکوچک) for
    # names that appear without spaces in the PDF text.
    if len(kept) >= 2:
        joined = "".join(kept[:3])
        if len(joined) >= 4:
            quoted.append(f'"{joined}"')
        if len(kept) >= 2:
            quoted.append(f'"{kept[0]}{kept[1]}"')
    return quoted


# Subject title words that should not dominate FTS topic queries.
SUBJECT_STOPWORDS = {
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
    "سوم",
    "چهارم",
    "پنجم",
    "ششم",
}


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
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            rows = []

    hits = [_row_to_page(row) for row in rows]
    if hits:
        return hits

    # Fallback: LIKE search for sticky Persian names (میرزاکوچک) when FTS misses.
    like_terms = [
        t.strip('"') for t in terms if len(t.strip('"')) >= 3
    ][:4]
    if not like_terms:
        return []
    like_sql = """
        SELECT grade, subject, subject_title, printed_page, text,
               image_path, is_scanned, text_usable
        FROM pages
        WHERE printed_page > 0
    """
    like_params: list[object] = []
    for term in like_terms:
        like_sql += " AND text LIKE ?"
        like_params.append(f"%{term}%")
    if grade is not None:
        like_sql += " AND grade = ?"
        like_params.append(grade)
    if subject is not None:
        like_sql += " AND subject = ?"
        like_params.append(subject)
    like_sql += " ORDER BY printed_page LIMIT ?"
    like_params.append(limit)
    with _connect() as conn:
        rows = conn.execute(like_sql, like_params).fetchall()
    return [_row_to_page(row) for row in rows]


def resolve_image_path(image_path: str | None) -> Path | None:
    if not image_path:
        return None
    # Indexes built on Windows may store ``pages\foo.png``; normalize separators
    # so Linux deployments resolve the same relative paths.
    normalized = image_path.replace("\\", "/").strip()
    path = Path(normalized)
    if path.is_file():
        return path
    candidate = PAGES_DIR / path.name
    if candidate.is_file():
        return candidate
    # Also try relative to the textbook data root (e.g. pages/foo.png).
    candidate = Path(DATA_DIR) / normalized
    if candidate.is_file():
        return candidate
    return None


