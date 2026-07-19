# Textbook (embedded in Yar Kids API)

Page-addressable retrieval for Iranian elementary textbooks (grades 3–6).
This package lives under `api/textbook` and is mounted by the standalone API
at `/v1/retrieve`, `/v1/upload-pdf`, etc. Chat flows call it **in-process**
(no separate HTTP service required).

## Data layout

```
api/textbook/data/
  catalog.json
  subject_topics.json
  pdfs/          # place PDFs here
  pages/         # generated page PNGs
  index.sqlite   # generated SQLite index
```

Optional: set `TEXTBOOK_DATA_DIR` to point at another data root.

## Build the index

MinerU needs **Python 3.10–3.12** (not 3.14). Use a dedicated venv:

```powershell
# one-time setup (Windows)
py -3.12 -m venv .venv-indexer
.\.venv-indexer\Scripts\python.exe -m pip install -U pip
.\.venv-indexer\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.\.venv-indexer\Scripts\python.exe -m pip install -r api/requirements.txt
.\.venv-indexer\Scripts\python.exe -m pip install "mineru[pipeline]" ultralytics "doclayout_yolo==0.0.4"
```

Place PDFs in `api/textbook/data/pdfs/` (names must match `catalog.json`), then:

```powershell
$env:MINERU_MODEL_SOURCE = "modelscope"
$env:PYTHONPATH = (Get-Location).Path
# Book-by-book (recommended — survives crashes, commits each book):
.\.venv-indexer\Scripts\python.exe -m api.textbook.indexer.run_parse_all
# Or full rebuild:
.\.venv-indexer\Scripts\python.exe -m api.textbook.indexer.build_index
```

This writes `data/index.sqlite`, `data/pages/*.png`, and caches MinerU JSON under `data/mineru/`.
First run downloads OCR models (~several hundred MB). Expect a long wall-clock time for all books
(8-page MinerU windows on CPU — often many hours for ~30 textbooks).

Monitor progress:

```powershell
Get-Content api\textbook\data\build_index.log -Wait -Tail 20
```

Resume after interruption (skip books that already have pages):

```powershell
.\.venv-indexer\Scripts\python.exe -m api.textbook.indexer.run_parse_all --skip-done
```

If HuggingFace is unreachable, keep `MINERU_MODEL_SOURCE=modelscope` (already the indexer default).

## HTTP endpoints (via main API)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/health` | Index / catalog status |
| POST | `/v1/retrieve` | Persian query → page context |
| GET | `/v1/page-image` | PNG for a page |
| POST | `/v1/upload-pdf` | Upload + optional catalog register |
| POST | `/v1/parse-pdfs` | Build / refresh index |
| GET | `/v1/parse-status/{job_id}` | Async build job status |
| POST | `/v1/upload-index` | Upload a prebuilt `index.sqlite` |
| POST | `/v1/upload-pages` | Upload a ZIP of page PNGs |

Optional auth: set `TEXTBOOK_API_KEY` and send `Authorization: Bearer …`.
