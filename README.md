<div align="center">

# Playroom

**A safe AI companion for children — five modes in one model.**

Creative, storyteller, teacher, homework and games, routed automatically,
grounded in the actual school textbook page, and reviewed for safety
before a child ever sees a reply.

[![Tests](https://github.com/behdadmehrnia/Playroom/actions/workflows/tests.yml/badge.svg)](https://github.com/behdadmehrnia/Playroom/actions/workflows/tests.yml)
[![Python](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

</div>

---

## Table of contents

- [Highlights](#highlights)
- [The five modes](#the-five-modes)
- [How a message is handled](#how-a-message-is-handled)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [HTTP API](#http-api)
- [Textbook retrieval](#textbook-retrieval)
- [Web search](#web-search)
- [Editing the prompts](#editing-the-prompts)
- [Project structure](#project-structure)
- [Tests](#tests)
- [A note on language](#a-note-on-language)
- [License](#license)

---

## Highlights

| | |
|---|---|
| 🛡️ **Safety outranks everything** | A core prompt that no persona or user instruction can override, plus a reflection agent that judges every reply before it is sent. |
| 📚 **Page-addressable textbooks** | Ask for a page, lesson or chapter and the real page — text *and* image — comes back from a local SQLite index. The image wins over OCR. |
| 🧭 **Intent routing** | A classifier picks the mode above a confidence floor and stays put mid-activity instead of flipping on a single word. |
| ✏️ **Method, never the answer** | Homework mode teaches the approach and refuses to hand over a finished result to copy. |
| 🔢 **Checked arithmetic** | Maths in a child's message is evaluated by a sandboxed tool and used to explain the steps. |
| ⚡ **Drop-in OpenAI API** | Point any OpenAI-compatible client at it, or use the built-in playground. |

---

## The five modes

One model, five personas. Tools are gated per mode — the textbook and the calculator
belong to teaching, web search belongs to play.

| Mode | For | Textbook | Web search | Maths |
|---|---|:---:|:---:|:---:|
| 🎨 `creative` | Ideas, drawing, making things | — | ✓ | — |
| 📖 `storyteller` | Short stories, 4–8 sentences | — | ✓ | — |
| 📚 `teacher` | Explaining concepts | ✓ | — | ✓ |
| ✏️ `homework` | Working an exercise, step by step | ✓ | — | ✓ |
| 🎮 `gamer` | Word games, riddles, video game facts | — | ✓ | — |

A mode is chosen in one of three ways, in priority order:

1. `metadata.playroom_persona` on the request (or a top-level `persona` key)
2. Intent detection, when confidence clears `0.7`
3. Otherwise `none` — Playroom introduces itself and offers the modes

---

## How a message is handled

```
message
   │
   ├── 1. Route      persona from metadata, else intent detection (≥ 0.7 confidence)
   ├── 2. Ground     textbook page · web results · maths result   (gated by mode)
   ├── 3. Generate   safety core + persona prompt + retrieved context
   ├── 4. Review     reflection agent judges safety only; can send it back
   └── 5. Stream     SSE chunks with live status, then a conversation title
```

Retrieval failures never turn into invention. When a page is missing, out of range,
or unreadable, the service answers from structured fields instead of trusting the
model to admit it doesn't know.

---

## Getting started

Requires **Python 3.12** and an OpenAI-compatible LLM endpoint.

```bash
pip install -r api/requirements-runtime.txt
cp .env.example .env        # then set PLAYROOM_BACKEND_MODEL and PLAYROOM_LLM_API_KEY
uvicorn api.main:app --reload --port 8000
```

Then open **<http://localhost:8000>** for the landing page, or
**<http://localhost:8000/chat>** for the playground.

### Docker

```bash
docker compose up -d --build
```

The named volume `playroom-textbook-data` keeps `pages/`, `pdfs/` and `index.sqlite`
across rebuilds; `catalog.json` is refreshed from the image on every start.

---

## Configuration

All settings are environment variables prefixed `PLAYROOM_`. See [`.env.example`](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `PLAYROOM_BACKEND_MODEL` | — | Backend LLM model (**required**) |
| `PLAYROOM_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible base URL |
| `PLAYROOM_LLM_API_KEY` | — | Bearer token for the LLM service |
| `PLAYROOM_TEMPERATURE` | `0.7` | Sampling temperature |
| `PLAYROOM_ENABLE_REFLECTION` | `true` | Safety review before sending |
| `PLAYROOM_ENABLE_STATUS_UPDATES` | `true` | Live status events while working |
| `PLAYROOM_ENABLE_CHAT_TITLE` | `true` | Name conversations automatically |
| `PLAYROOM_ENABLE_TEXTBOOK_CONTEXT` | `true` | Textbook retrieval |
| `PLAYROOM_ENABLE_WEB_SEARCH` | `true` | Web search |
| `PLAYROOM_API_HOST` / `_PORT` | `0.0.0.0` / `8000` | Bind address |

---

## HTTP API

Interactive docs are served at `/docs`.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat` | Native chat endpoint, SSE when `stream: true` |
| `POST` | `/v1/chat/completions` | OpenAI Chat Completions (alias: `/v1/chat/completion`) |
| `POST` | `/v1/responses` | OpenAI Responses API |
| `GET` | `/v1/personas` | The persona list and each one's tool access |
| `POST` | `/v1/persona/resolve` | Resolve which persona a conversation would use |
| `POST` | `/v1/intent` | Intent classification only |
| `POST` | `/v1/generate` · `/v1/reflect` | Generation and safety review in isolation |
| `POST` | `/v1/textbook/query` · `/retrieve` | Textbook lookup |
| `POST` | `/v1/web-search/query` · `/retrieve` | Web search, plus a route per provider |
| `GET` | `/health` | Liveness |

The client's `model` field is ignored; `PLAYROOM_BACKEND_MODEL` is used.

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"tell me a story"}]}'
```

Every response (and the final stream chunk) carries a `playroom` object with the active
persona, the textbook query and result, web search, and maths tool usage.

---

## Textbook retrieval

The embedded [`api/textbook/`](api/textbook/) package indexes textbook PDFs into a local
SQLite database plus per-page PNGs, and is called in-process — no separate service.
Pages are addressable by page number, lesson, or chapter.

Indexing uses [MinerU](https://github.com/opendatalab/MinerU) and needs its own
environment; see [`api/textbook/README.md`](api/textbook/README.md). If retrieval is
unavailable, Playroom continues without book context rather than inventing a page.

---

## Web search

Set `PLAYROOM_WEB_SEARCH_PROVIDER` to one provider, `auto`, or a comma-separated
fallback chain tried in order:

| Provider | Endpoint |
|---|---|
| `api` | `POST {WEB_SEARCH_API_URL}/v1/search` |
| `perplexity` | `GET {…}/api/v1/search?query=…` |
| `duckduckgo` | Built-in DuckDuckGo (+ Wikipedia) |
| `gerdoo` | `GET {…}/search?query=…` |

Each provider also has its own test route under `/v1/web-search/providers/…`.
If search fails, the chat continues without results — it does not guess.

---

## Editing the prompts

Behaviour lives in Markdown, not in code. Edit the files under [`api/prompts/`](api/prompts/):

| File | Role |
|---|---|
| `core.md` | Identity and the safety guardrails that outrank everything |
| `personas/*.md` | One file per mode |
| `intent_detection.md` | The routing classifier |
| `reflection.md` | The safety reviewer |
| `chat_title.md` | Conversation titles |
| `web_search_query.md` | Turning a child's phrasing into a search query |

---

## Project structure

```
api/
├── main.py             # entrypoint: uvicorn api.main:app
├── config.py           # env settings
├── llm.py              # OpenAI-compatible client
├── service.py          # chat orchestration
├── models.py           # request/response schemas
├── core/               # domain logic
│   ├── persona.py      #   persona resolution and stickiness
│   ├── intent.py       #   intent classification
│   ├── textbook.py     #   textbook query parsing
│   ├── web_search.py   #   provider chain
│   ├── generation.py   #   prompt building, reflection loop
│   ├── math_tool.py    #   sandboxed arithmetic
│   └── prompts.py      #   loads api/prompts/*.md
├── routes/             # HTTP endpoints
│   ├── openai_compat.py#   /v1/chat/completions, /v1/responses
│   └── landing.py      #   landing page + chat playground
├── prompts/            # all model behaviour, as Markdown
└── textbook/           # embedded page-addressable retrieval
```

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

263 tests covering personas, intent, textbook parsing and retrieval, web search,
the maths tool, generation, and the HTTP routes. A manual QA checklist lives in
[`tests/README.md`](tests/README.md).

---

## A note on language

Playroom's instruction layer — every prompt, all UI copy, and these docs — is English,
and the core prompt tells the model to **reply in whatever language the child writes in**.

The textbook subsystem is a deliberate exception. Its corpus is Persian, so the query
parsers in `api/core/textbook.py` and `api/core/web_search.py` match Persian phrasing
(«صفحه ۴۲», «فصل سوم»), and book titles in `catalog.json` stay in Persian. That is the
recognition layer for the content, not user-facing copy. Swap the corpus and those
matchers are what you would replace.

---

## License

[MIT](LICENSE) © Behdad Mehrnia
