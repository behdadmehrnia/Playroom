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
from app.text_quality import is_text_garbled  # noqa: E402
from indexer.mineru_extract import (  # noqa: E402
    mineru_available,
    run_mineru,
)

try:
    import fitz  # PyMuPDF
except ImportError as exc:
    raise SystemExit("Install pymupdf: pip install pymupdf") from exc


import os
import shutil
import statistics
import subprocess
import tempfile

# Fallback OCR (optional): calls the `tesseract` binary via subprocess.
# Prefer MinerU (`--ocr-engine mineru`, the default) — Tesseract output on
# Iranian schoolbook fonts is often unusable.
_OCR_STATE: dict[str, object] = {"enabled": True, "checked": False, "available": False}

OCR_LANG = "fas"
OCR_PSM = "3"
OCR_TIMEOUT_SEC = 120
# Mean per-word tesseract confidence below which OCR output is considered
# unreliable (calligraphy / decorative fonts). Such pages fall back to image.
MIN_OCR_CONFIDENCE = 65.0

MINERU_OUT_DIR = DATA_DIR / "mineru"
DEFAULT_OCR_ENGINE = "mineru"


def _ocr_available() -> bool:
    """Return True if the tesseract binary with the Persian model is usable."""
    if _OCR_STATE["checked"]:
        return bool(_OCR_STATE["available"])
    _OCR_STATE["checked"] = True
    if not _OCR_STATE["enabled"]:
        _OCR_STATE["available"] = False
        return False
    binary = shutil.which("tesseract")
    if not binary:
        print(
            "warning: OCR disabled — `tesseract` binary not found on PATH. "
            "Install it (e.g. `brew install tesseract tesseract-lang`).",
            file=sys.stderr,
        )
        _OCR_STATE["available"] = False
        return False
    try:
        langs = subprocess.run(
            [binary, "--list-langs"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        available_langs = langs.stdout.decode("utf-8", "ignore")
        if OCR_LANG not in available_langs:
            print(
                f"warning: OCR disabled — tesseract language '{OCR_LANG}' not installed. "
                "Install the Persian model (e.g. `brew install tesseract-lang`).",
                file=sys.stderr,
            )
            _OCR_STATE["available"] = False
            return False
    except (OSError, subprocess.SubprocessError):
        _OCR_STATE["available"] = False
        return False
    _OCR_STATE["available"] = True
    return True


def _try_ocr(image_bytes: bytes) -> tuple[str, float]:
    """Run tesseract on PNG bytes.

    Returns (recognized_text, mean_word_confidence). Confidence is 0.0 on
    failure or when tesseract reports no confident words.
    """
    if not _ocr_available():
        return "", 0.0
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img_path = os.path.join(tmp, "page.png")
            with open(img_path, "wb") as fh:
                fh.write(image_bytes)
            base = os.path.join(tmp, "out")
            subprocess.run(
                [
                    "tesseract", img_path, base,
                    "-l", OCR_LANG, "--psm", OCR_PSM, "txt", "tsv",
                ],
                capture_output=True,
                timeout=OCR_TIMEOUT_SEC,
                check=False,
            )
            text = ""
            txt_file = base + ".txt"
            if os.path.isfile(txt_file):
                with open(txt_file, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read().strip()
            confidence = _mean_confidence(base + ".tsv")
            return text, confidence
    except (OSError, subprocess.SubprocessError):
        return "", 0.0


def _mean_confidence(tsv_path: str) -> float:
    if not os.path.isfile(tsv_path):
        return 0.0
    confidences: list[float] = []
    with open(tsv_path, encoding="utf-8", errors="ignore") as fh:
        lines = fh.read().splitlines()
    for line in lines[1:]:  # skip header
        cols = line.split("\t")
        if len(cols) < 12:
            continue
        word = cols[11].strip()
        if not word:
            continue
        try:
            conf = float(cols[10])
        except ValueError:
            continue
        if conf >= 0:
            confidences.append(conf)
    return statistics.mean(confidences) if confidences else 0.0


def _text_is_usable(text: str) -> bool:
    """Clean digital/OCR text: long enough and not garbled mojibake."""
    return len(text.strip()) >= MIN_TEXT_CHARS_FOR_DIGITAL and not is_text_garbled(text)


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
            text_usable INTEGER NOT NULL DEFAULT 1,
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
    text_usable: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO pages (
            grade, subject, subject_title, printed_page, pdf_page_index,
            text, image_path, is_scanned, text_usable
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            1 if text_usable else 0,
        ),
    )


def _resolve_page_text(
    *,
    raw_text: str,
    mineru_text: str,
    ocr_engine: str,
    use_ocr: bool,
    page: "fitz.Page",
    ocr_dpi: int,
    stats: dict[str, int],
) -> tuple[str, bool]:
    """
    Choose the best text for a page.

    Prefer clean digital text; otherwise MinerU (default) or legacy tesseract.
    """
    digital_ok = _text_is_usable(raw_text)
    if digital_ok:
        return raw_text, True

    if not use_ocr:
        return raw_text, False

    if ocr_engine == "mineru":
        if mineru_text:
            stats["ocr_pages"] += 1
            if _text_is_usable(mineru_text):
                stats["ocr_fixed"] += 1
                return mineru_text, True
            # Keep MinerU text for FTS even when quality heuristics fail;
            # still mark unusable so retrieve can attach the page image.
            if len(mineru_text.strip()) > len(raw_text.strip()):
                return mineru_text, False
        return raw_text, False

    # Legacy tesseract path
    ocr_png = page.get_pixmap(dpi=ocr_dpi).tobytes("png")
    ocr_text, ocr_conf = _try_ocr(ocr_png)
    if not ocr_text:
        return raw_text, False
    stats["ocr_pages"] += 1
    clean = _text_is_usable(ocr_text)
    confident = ocr_conf >= MIN_OCR_CONFIDENCE
    if clean and confident:
        stats["ocr_fixed"] += 1
        return ocr_text, True
    if len(ocr_text) > len(raw_text):
        return ocr_text, False
    return raw_text, False


def build_index(
    pdf_dir: Path,
    *,
    render_dpi: int = 120,
    ocr_dpi: int = 300,
    use_ocr: bool = True,
    ocr_engine: str = DEFAULT_OCR_ENGINE,
    mineru_backend: str = "pipeline",
    mineru_lang: str = "arabic",
    mineru_force: bool = False,
) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PAGES_DIR.mkdir(parents=True, exist_ok=True)

    if not use_ocr:
        _OCR_STATE["enabled"] = False

    if use_ocr and ocr_engine == "mineru" and not mineru_available():
        raise RuntimeError(
            "OCR engine is mineru but the `mineru` CLI was not found. "
            "Install with: pip install -r requirements-indexer.txt "
            "or pass --ocr-engine tesseract / --no-ocr."
        )

    stats = {"ocr_pages": 0, "ocr_fixed": 0}

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

            mineru_pages: dict[int, str] = {}
            if use_ocr and ocr_engine == "mineru":
                book_out = MINERU_OUT_DIR / pdf_path.stem
                try:
                    mineru_pages = run_mineru(
                        pdf_path,
                        book_out,
                        backend=mineru_backend,
                        lang=mineru_lang,
                        force=mineru_force,
                    )
                    print(f"  mineru pages with text: {len(mineru_pages)}")
                except RuntimeError as exc:
                    print(f"  warning: mineru failed — {exc}", file=sys.stderr)
                    mineru_pages = {}

            doc = fitz.open(pdf_path)

            for pdf_page_index in range(len(doc)):
                page = doc[pdf_page_index]
                raw_text = page.get_text("text").strip()
                mineru_text = mineru_pages.get(pdf_page_index, "")

                # Iranian schoolbook PDFs often embed broken font CMaps that
                # produce plenty of text, but it's mojibake — OCR/MinerU then.
                text, text_usable = _resolve_page_text(
                    raw_text=raw_text,
                    mineru_text=mineru_text,
                    ocr_engine=ocr_engine,
                    use_ocr=use_ocr,
                    page=page,
                    ocr_dpi=ocr_dpi,
                    stats=stats,
                )

                # Attach the page image whenever the text isn't reliably usable
                # (e.g. calligraphic poems) so a vision model can read it.
                is_scanned = not text_usable

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
                    is_scanned=is_scanned,
                    text_usable=text_usable,
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

    print(
        f"Done. Indexed {total_pages} pages → {INDEX_PATH} "
        f"(engine={ocr_engine}, OCR/parse on {stats['ocr_pages']} pages, "
        f"clean text for {stats['ocr_fixed']})"
    )
    return total_pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Build textbook SQLite index from PDFs")
    parser.add_argument(
        "--pdf-dir",
        type=Path,
        default=PDFS_DIR,
        help=f"Directory containing PDF files (default: {PDFS_DIR})",
    )
    parser.add_argument("--dpi", type=int, default=120, help="Stored page PNG render DPI")
    parser.add_argument("--ocr-dpi", type=int, default=300, help="Render DPI used for tesseract OCR")
    parser.add_argument(
        "--ocr-engine",
        choices=("mineru", "tesseract"),
        default=DEFAULT_OCR_ENGINE,
        help="Text recovery engine when digital PDF text is missing/garbled (default: mineru)",
    )
    parser.add_argument(
        "--mineru-backend",
        default="pipeline",
        help="MinerU backend (default: pipeline — best for Persian via -l arabic)",
    )
    parser.add_argument(
        "--mineru-lang",
        default="arabic",
        help="MinerU OCR language for pipeline backend (arabic covers Persian)",
    )
    parser.add_argument(
        "--mineru-force",
        action="store_true",
        help="Re-run MinerU even if a cached content_list exists under data/mineru/",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="Skip OCR/MinerU entirely (digital text layer only)",
    )
    args = parser.parse_args()

    try:
        build_index(
            args.pdf_dir,
            render_dpi=args.dpi,
            ocr_dpi=args.ocr_dpi,
            use_ocr=not args.no_ocr,
            ocr_engine=args.ocr_engine,
            mineru_backend=args.mineru_backend,
            mineru_lang=args.mineru_lang,
            mineru_force=args.mineru_force,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
