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

From the repo root (with indexer deps installed via `api/requirements.txt`):

```bash
python -m api.textbook.indexer.build_index
# or:
python api/textbook/indexer/build_index.py
```

If HuggingFace is unreachable:

```bash
export MINERU_MODEL_SOURCE=modelscope
```

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
