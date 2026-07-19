from __future__ import annotations

import os
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TEXTBOOK_DATA_DIR", SERVICE_ROOT / "data"))
CATALOG_PATH = DATA_DIR / "catalog.json"
INDEX_PATH = DATA_DIR / "index.sqlite"
PAGES_DIR = DATA_DIR / "pages"
PDFS_DIR = DATA_DIR / "pdfs"

API_KEY = os.environ.get("TEXTBOOK_API_KEY", "").strip()
HOST = os.environ.get("TEXTBOOK_HOST", "0.0.0.0")
PORT = int(os.environ.get("TEXTBOOK_PORT", "8080"))

MIN_TEXT_CHARS_FOR_DIGITAL = int(os.environ.get("TEXTBOOK_MIN_TEXT_CHARS", "40"))
DEFAULT_NEIGHBORS = 2
