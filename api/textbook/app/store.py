from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from api.textbook.app.config import CATALOG_PATH, DATA_DIR, INDEX_PATH, PAGES_DIR
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

    for i, existing in enumerate(books):
        if isinstance(existing, dict) and existing.get("file") == book.file:
            if {k: existing.get(k) for k in entry} == entry:
                return False
            books[i] = {**existing, **entry}
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


def get_printed_page_bounds(
    grade: int | None,
    subject: str,
) -> tuple[int, int] | None:
    """
    Return (min_printed_page, max_printed_page) for a book in the existing index.

    Uses only ``printed_page`` values already stored by the MinerU/indexer pipeline
    (offset already applied at index time). Does not read raw PDF page counts.
    When ``grade`` is None, aggregates across all grades for that subject.
    """
    if not subject or not index_exists():
        return None
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
    if not row or row["min_p"] is None or row["max_p"] is None:
        return None
    return int(row["min_p"]), int(row["max_p"])


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
    21: "بیست و یکم",
    22: "بیست و دوم",
    23: "بیست و سوم",
    24: "بیست و چهارم",
    25: "بیست و پنجم",
    26: "بیست و ششم",
    27: "بیست و هفتم",
    28: "بیست و هشتم",
    29: "بیست و نهم",
    30: "سی‌ام",
    31: "سی و یکم",
    32: "سی و دوم",
    33: "سی و سوم",
    34: "سی و چهارم",
    35: "سی و پنجم",
    36: "سی و ششم",
    37: "سی و هفتم",
    38: "سی و هشتم",
    39: "سی و نهم",
    40: "چهلم",
}
_LESSON_UNIT_WORDS = ("درس", "فصل")
# Pages containing this many distinct lesson markers are treated as tables of
# contents / unit dividers and skipped when locating a lesson's real start page.
_LESSON_TOC_THRESHOLD = 3
_MAX_DETECTABLE_LESSONS = 40


def _lesson_target_patterns(lesson_number: int):
    """Patterns that mark the start of a specific lesson/chapter.

    PDF/OCR for RTL books often yields «3 فصل», «فصل :3», or «فصل-۳» instead of
    a clean «فصل 3», so we accept both orders, optional punctuation, and
    digit/ordinal forms.
    """
    import re as _re

    ordinal = _LESSON_ORDINALS.get(lesson_number)
    digit = str(lesson_number)
    persian_digit = digit.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
    # Optional OCR junk between unit word and number (colon, dash, Persian colon).
    sep = r"[\s:：\-–—٫.\u200c]{0,4}"
    patterns: list = []
    for unit in _LESSON_UNIT_WORDS:
        if ordinal:
            patterns.append(_re.compile(rf"{unit}{sep}{ordinal}"))
            patterns.append(_re.compile(rf"{ordinal}{sep}{unit}"))
        for num in {digit, persian_digit}:
            patterns.append(_re.compile(rf"{unit}{sep}{num}\b"))
            patterns.append(_re.compile(rf"(?<!\d){num}{sep}{unit}"))
            # OCR often drops the word boundary after Persian digits.
            patterns.append(_re.compile(rf"{unit}{sep}{num}(?!\d)"))
    return patterns


def lesson_search(grade: int, subject: str, lesson_number: int) -> PageRecord | None:
    """Locate the start page of a lesson/chapter (درس/فصل) within a book.

    Lesson headers appear both on the table-of-contents pages (which list many
    lessons) and on the real lesson page (which references only its own). We
    pick the candidate page with the fewest distinct lesson markers.
    """
    if lesson_number < 1 or not index_exists():
        return None

    target_patterns = _lesson_target_patterns(lesson_number)
    patterns_by_number = {
        n: _lesson_target_patterns(n) for n in range(1, _MAX_DETECTABLE_LESSONS + 1)
    }

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

    candidates: list[tuple[int, int, int, sqlite3.Row]] = []
    for row in rows:
        text = str(row["text"] or "")
        if not any(p.search(text) for p in target_patterns):
            continue
        distinct = sum(
            1
            for n, patterns in patterns_by_number.items()
            if any(p.search(text) for p in patterns)
        )
        head = text[:_LESSON_HEADER_CHARS]
        not_in_header = 0 if any(p.search(head) for p in target_patterns) else 1
        candidates.append((distinct, not_in_header, int(row["printed_page"]), row))

    if not candidates:
        return None

    filtered = [c for c in candidates if c[0] < _LESSON_TOC_THRESHOLD]
    pool = filtered or candidates
    # Prefer real chapter openers (header + few markers) over TOC-like pages.
    pool.sort(key=lambda c: (c[0], c[1], c[2]))
    return _row_to_page(pool[0][3])


_MAX_LESSON_PAGES = 14


def list_lesson_starts(grade: int, subject: str) -> list[tuple[int, int]]:
    """Return [(lesson_number, start_page), ...] sorted by start page.

    Single pass over the book pages (avoids N full scans).
    Prefers chapter-opener pages (header-zone match, few distinct markers).
    """
    if not index_exists():
        return []

    patterns_by_number = {
        n: _lesson_target_patterns(n) for n in range(1, _MAX_DETECTABLE_LESSONS + 1)
    }
    # lesson_number -> best (distinct_count, not_in_header, printed_page)
    best: dict[int, tuple[int, int, int]] = {}

    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT printed_page, text
            FROM pages
            WHERE grade = ? AND subject = ? AND printed_page > 0
            ORDER BY printed_page
            """,
            (grade, subject),
        ).fetchall()

    for row in rows:
        text = str(row["text"] or "")
        if not text.strip():
            continue
        present = [
            n
            for n, patterns in patterns_by_number.items()
            if any(p.search(text) for p in patterns)
        ]
        if not present:
            continue
        distinct = len(present)
        page = int(row["printed_page"])
        head = text[:_LESSON_HEADER_CHARS]
        for number in present:
            patterns = patterns_by_number[number]
            not_in_header = 0 if any(p.search(head) for p in patterns) else 1
            prev = best.get(number)
            # Prefer non-TOC, header-zone hits, then earlier pages.
            score = (distinct, not_in_header, page)
            if prev is None or score < prev:
                best[number] = score

    starts = [
        (number, page)
        for number, (distinct, _h, page) in best.items()
        if distinct < _LESSON_TOC_THRESHOLD
    ]
    if not starts:
        # Fall back to whatever we saw (including TOC-heavy pages).
        starts = [(number, page) for number, (_d, _h, page) in best.items()]
    starts.sort(key=lambda item: item[1])
    deduped: list[tuple[int, int]] = []
    seen_pages: set[int] = set()
    for number, page in starts:
        if page in seen_pages:
            continue
        seen_pages.add(page)
        deduped.append((number, page))
    return deduped


# Minimum distinct lesson/chapter headers before we trust max/min for
# lesson_out_of_range. Sparse OCR (e.g. only «فصل 7» found) must not reject
# legitimate requests for درس ۳ as out-of-range — fall through to lesson_missing.
_MIN_TRUSTED_LESSON_MARKERS = 3
# Detected lessons must cover at least this fraction of 1..max to count as a
# real chapter map (avoids {1, 17} from TOC noise looking contiguous).
_MIN_LESSON_COVERAGE_RATIO = 0.55
# Prefer درس/فصل markers near the top of the page (real chapter openers).
_LESSON_HEADER_CHARS = 320


def get_lesson_bounds(
    grade: int | None, subject: str | None
) -> tuple[int, int] | None:
    """Return trustworthy (min_lesson, max_lesson), or None if the map is weak.

    Books without a reliable درس/فصل map must return None so retrieve falls
    through to lesson_missing (ask for page/photo) instead of a false
    lesson_out_of_range when only one stray header was OCR'd.
    """
    if grade is None or not subject:
        return None
    starts = list_lesson_starts(grade, subject)
    if not starts:
        return None
    numbers = sorted({n for n, _ in starts})
    if len(numbers) < _MIN_TRUSTED_LESSON_MARKERS:
        return None
    # Incomplete maps that skip درس/فصل ۱ (e.g. only {2,3,4}) are not trusted
    # for out-of-range — otherwise «درس اول» is wrongly rejected.
    if numbers[0] != 1:
        return None
    max_n = numbers[-1]
    if max_n < 1:
        return None
    coverage = len(numbers) / max_n
    if coverage < _MIN_LESSON_COVERAGE_RATIO:
        return None
    return 1, max_n


def find_lesson_containing_page(
    grade: int,
    subject: str,
    page: int,
) -> tuple[int, int, int] | None:
    """Return (lesson_number, start_page, end_page) for the lesson containing page."""
    starts = list_lesson_starts(grade, subject)
    if not starts:
        return None
    chosen: tuple[int, int] | None = None
    for number, start in starts:
        if start <= page:
            chosen = (number, start)
        else:
            break
    if chosen is None:
        return None
    number, start = chosen
    end = start
    for other_number, other_start in starts:
        if other_start > start:
            end = other_start - 1
            break
    else:
        # Last lesson: extend a reasonable window, capped later by get_lesson_pages.
        end = start + _MAX_LESSON_PAGES - 1
    if page < start or page > end:
        # Page before first lesson header — treat as single-page span.
        return None
    return number, start, end


def _lesson_marker_count(text: str) -> int:
    """How many distinct درس/فصل numbers appear on a page (TOC pages score high)."""
    if not text.strip():
        return 0
    patterns_by_number = {
        n: _lesson_target_patterns(n) for n in range(1, _MAX_DETECTABLE_LESSONS + 1)
    }
    return sum(
        1
        for patterns in patterns_by_number.values()
        if any(p.search(text) for p in patterns)
    )


def _refine_lesson_start_past_toc(
    grade: int,
    subject: str,
    lesson_number: int,
    *,
    after_page: int,
    scan_ahead: int = 40,
) -> int | None:
    """Find a non-TOC page for this lesson after a contents-list hit."""
    target_patterns = _lesson_target_patterns(lesson_number)
    for printed in range(after_page + 1, after_page + scan_ahead + 1):
        record = get_page(grade, subject, printed)
        if not record:
            continue
        text = record.text or ""
        if not any(p.search(text) for p in target_patterns):
            continue
        if _lesson_marker_count(text) < _LESSON_TOC_THRESHOLD:
            return printed
    return None


def get_lesson_pages(
    grade: int,
    subject: str,
    *,
    lesson_number: int | None = None,
    page: int | None = None,
    max_pages: int = _MAX_LESSON_PAGES,
) -> tuple[list[PageRecord], int | None, int | None, int | None]:
    """
    Return (pages, lesson_number, start_page, end_page) for a whole lesson.

    Identify the lesson either by explicit lesson_number or by a page inside it.
    """
    if not index_exists():
        return [], None, None, None

    start: int | None = None
    end: int | None = None
    resolved_lesson = lesson_number

    if lesson_number is not None:
        center = lesson_search(grade, subject, lesson_number)
        if not center:
            return [], None, None, None
        start = center.printed_page
        # TOC pages list many دروس (e.g. page 29: درس چهارم + درس پنجم). Prefer a
        # later page that opens this lesson alone; otherwise treat as missing so
        # we ask for a real page instead of inventing from the contents list.
        if _lesson_marker_count(center.text or "") >= _LESSON_TOC_THRESHOLD:
            refined = _refine_lesson_start_past_toc(
                grade, subject, lesson_number, after_page=start
            )
            if refined is None:
                return [], None, None, None
            start = refined
        starts = list_lesson_starts(grade, subject)
        end = start + max_pages - 1
        for _number, other_start in starts:
            if other_start > start:
                end = min(end, other_start - 1)
                break
    elif page is not None:
        found = find_lesson_containing_page(grade, subject, page)
        if not found:
            # Fallback: current page ± a small window when headers are missing.
            single = get_page(grade, subject, page)
            return ([single] if single else []), None, page, page
        resolved_lesson, start, end = found
    else:
        return [], None, None, None

    if start is None or end is None:
        return [], None, None, None

    if end < start:
        end = start
    if end - start + 1 > max_pages:
        # Prefer keeping pages from the start of the lesson.
        end = start + max_pages - 1

    pages: list[PageRecord] = []
    for printed in range(start, end + 1):
        record = get_page(grade, subject, printed)
        if record:
            pages.append(record)
    return pages, resolved_lesson, start, end


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
