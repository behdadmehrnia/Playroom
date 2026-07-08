#!/usr/bin/env python3
"""
Build SQLite index and page PNGs from PDF textbooks listed in data/catalog.json.

Usage (from textbook-service/):
    python indexer/build_index.py
    python indexer/build_index.py --pdf-dir /path/to/pdfs
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVICE_ROOT))

from app.config import (  # noqa: E402
    CATALOG_PATH,
    DATA_DIR,
    INDEX_PATH,
    MIN_TEXT_CHARS_FOR_DIGITAL,
    PAGES_DIR,
    PDFS_DIR,
)
from app.subjects import SUBJECT_TITLES  # noqa: E402

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise SystemExit("Install pymupdf: pip install pymupdf") from exc


import io

# OCR is optional. It is loaded lazily and disabled permanently on first failure
# (e.g. a broken pandas/numpy in the environment), so indexing never crashes.
_OCR_STATE: dict[str, object] = {"enabled": True, "checked": False, "fn": None}


def _load_ocr():
    """Return a callable (PIL.Image -> str) or None if OCR is unavailable."""
    if _OCR_STATE["checked"]:
        return _OCR_STATE["fn"]
    _OCR_STATE["checked"] = True
    if not _OCR_STATE["enabled"]:
        return None
    try:
        import pytesseract  # noqa: PLC0415

        def _run(image) -> str:
            return pytesseract.image_to_string(image, lang="fas").strip()

        _OCR_STATE["fn"] = _run
        return _run
    except BaseException as exc:  # noqa: BLE001 - keep indexing alive on any import failure
        print(
            f"warning: OCR disabled (could not load pytesseract: {type(exc).__name__}). "
            "Scanned pages will be indexed without OCR text.",
            file=sys.stderr,
        )
        _OCR_STATE["fn"] = None
        return None


def _try_ocr(image_bytes: bytes) -> str:
    ocr = _load_ocr()
    if ocr is None:
        return ""
    try:
        from PIL import Image  # noqa: PLC0415

        image = Image.open(io.BytesIO(image_bytes))
        return ocr(image)
    except BaseException:  # noqa: BLE001
        return ""


def _printed_page_from_offset(pdf_page_index: int, page_offset: int) -> int:
    """
    Deterministic mapping: printed_page = pdf_page_index + 1 - page_offset.

    Guaranteed unique within a book (strictly increasing with pdf_page_index).
    Front-matter pages (cover/blank) map to <= 0 and stay unique.
    """
    return pdf_page_index + 1 - page_offset


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS pages_fts;
        DROP TABLE IF EXISTS pages;

        CREATE TABLE pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            grade INTEGER NOT NULL,
            subject TEXT NOT NULL,
            subject_title TEXT NOT NULL,
            printed_page INTEGER NOT NULL,
            pdf_page_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            image_path TEXT,
            is_scanned INTEGER NOT NULL DEFAULT 0,
            UNIQUE(grade, subject, printed_page)
        );

        CREATE VIRTUAL TABLE pages_fts USING fts5(
            text,
            subject_title,
            content='pages',
            content_rowid='id'
        );
        """
    )


def _insert_page(
    conn: sqlite3.Connection,
    *,
    grade: int,
    subject: str,
    subject_title: str,
    printed_page: int,
    pdf_page_index: int,
    text: str,
    image_path: str | None,
    is_scanned: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO pages (
            grade, subject, subject_title, printed_page, pdf_page_index,
            text, image_path, is_scanned
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            grade,
            subject,
            subject_title,
            printed_page,
            pdf_page_index,
            text,
            image_path,
            1 if is_scanned else 0,
        ),
    )


def build_index(pdf_dir: Path, *, render_dpi: int = 120, use_ocr: bool = True) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    if not use_ocr:
        _OCR_STATE["enabled"] = False

    if not CATALOG_PATH.is_file():
        raise FileNotFoundError(f"Missing catalog: {CATALOG_PATH}")

    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    books = catalog.get("books", [])
    if not books:
        raise ValueError("catalog.json has no books")

    if INDEX_PATH.is_file():
        INDEX_PATH.unlink()

    total_pages = 0
    with sqlite3.connect(INDEX_PATH) as conn:
        _init_db(conn)

        for book in books:
            pdf_name = book["file"]
            pdf_path = pdf_dir / pdf_name
            if not pdf_path.is_file():
                print(f"skip (missing): {pdf_path}")
                continue

            grade = int(book["grade"])
            subject = book["subject"]
            title = book.get("title", SUBJECT_TITLES.get(subject, subject))
            page_offset = int(book.get("page_offset", 0))

            print(f"indexing: {pdf_path.name} (grade={grade}, subject={subject})")
            doc = fitz.open(pdf_path)

            for pdf_page_index in range(len(doc)):
                page = doc[pdf_page_index]
                raw_text = page.get_text("text").strip()
                is_scanned = len(raw_text) < MIN_TEXT_CHARS_FOR_DIGITAL

                if is_scanned and use_ocr:
                    pix = page.get_pixmap(dpi=render_dpi)
                    ocr_text = _try_ocr(pix.tobytes("png"))
                    text = ocr_text if ocr_text else raw_text
                else:
                    text = raw_text

                printed_page = _printed_page_from_offset(pdf_page_index, page_offset)

                image_name = f"g{grade}_{subject}_p{printed_page}.png"
                image_path = PAGES_DIR / image_name
                if not image_path.is_file():
                    pix = page.get_pixmap(dpi=render_dpi)
                    pix.save(str(image_path))

                _insert_page(
                    conn,
                    grade=grade,
                    subject=subject,
                    subject_title=title,
                    printed_page=printed_page,
                    pdf_page_index=pdf_page_index,
                    text=text,
                    image_path=str(image_path.relative_to(DATA_DIR)),
                    is_scanned=is_scanned and len(text) < MIN_TEXT_CHARS_FOR_DIGITAL,
                )
                total_pages += 1

            doc.close()

        conn.execute(
            """
            INSERT INTO pages_fts(rowid, text, subject_title)
            SELECT id, text, subject_title FROM pages
            """
        )
        conn.commit()

    print(f"Done. Indexed {total_pages} pages → {INDEX_PATH}")
    return total_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Build textbook SQLite index from PDFs")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=PDFS_DIR,
        help=f"Directory containing PDF files (default: {PDFS_DIR})",
    )
    parser.add_argument("--dpi", type=int, default=120, help="PNG render DPI")
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Skip OCR entirely (use when the environment's OCR deps are broken)",
    )
    args = parser.parse_args()

    try:
        build_index(args.pdf_dir, render_dpi=args.dpi, use_ocr=not args.no_ocr)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
