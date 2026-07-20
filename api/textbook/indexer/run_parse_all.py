#!/usr/bin/env python3
"""
Parse every catalog PDF with MinerU and update index.sqlite book-by-book.

Safer than a single full rebuild for long runs: each book is committed, and
already-indexed books (with matching page counts) can be skipped via --skip-done.

Usage (from repo root, Python 3.12 indexer venv)::

    .\\.venv-indexer\\Scripts\\python.exe -m api.textbook.indexer.run_parse_all
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys

os.environ.setdefault("MINERU_MODEL_SOURCE", "modelscope")
os.environ.setdefault("MINERU_TABLE_MERGE_ENABLE", "false")

from api.textbook.app.config import INDEX_PATH, PDFS_DIR
from api.textbook.app.store import load_catalog
from api.textbook.indexer.build_index import index_book
from api.textbook.indexer.mineru_extract import mineru_available


def _indexed_page_count(grade: int, subject: str) -> int:
    if not INDEX_PATH.is_file():
        return 0
    try:
        with sqlite3.connect(INDEX_PATH) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM pages WHERE grade = ? AND subject = ?",
                (grade, subject),
            ).fetchone()
            return int(row[0]) if row else 0
    except sqlite3.Error:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse all textbook PDFs with MinerU")
    parser.add_argument("--skip-done", action="store_true", help="Skip books that already have pages")
    parser.add_argument("--mineru-force", action="store_true")
    parser.add_argument("--ocr-engine", choices=("mineru", "tesseract"), default="mineru")
    args = parser.parse_args()

    if args.ocr_engine == "mineru" and not mineru_available():
        print("error: mineru CLI not found in this Python environment", file=sys.stderr)
        return 1

    books = load_catalog()
    if not books:
        print("error: empty catalog", file=sys.stderr)
        return 1

    total = 0
    for book in books:
        pdf_path = PDFS_DIR / book.file
        if not pdf_path.is_file():
            print(f"skip (missing pdf): {book.file}")
            continue
        existing = _indexed_page_count(book.grade, book.subject)
        if args.skip_done and existing > 0:
            print(f"skip (already indexed {existing} pages): {book.file}")
            continue
        print(f"=== {book.file} (grade={book.grade}, subject={book.subject}) ===")
        try:
            count = index_book(
                book,
                use_ocr=True,
                ocr_engine=args.ocr_engine,
                mineru_force=args.mineru_force,
            )
            total += count
        except Exception as exc:  # noqa: BLE001 — continue remaining books
            print(f"FAILED {book.file}: {exc}", file=sys.stderr)
            continue

    print(f"All done. Pages touched this run: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
