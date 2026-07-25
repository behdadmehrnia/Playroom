"""Parse textbook فهرست pages via LLM and cache chapter/lesson start pages."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any

from api.textbook.app.store import (
    PageRecord,
    TocEntry,
    clear_toc_entries,
    find_toc_candidate_pages,
    resolve_image_path,
    resolve_page_from_toc,
    save_toc_entries,
    set_toc_job_status,
    toc_map_ready,
)

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"
_TOC_PROMPT_PATH = _PROMPTS_DIR / "toc_extract.md"

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _load_toc_system_prompt() -> str:
    if _TOC_PROMPT_PATH.is_file():
        return _TOC_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "Extract textbook table-of-contents as JSON with chapters, lessons, "
        "and sections. Invent nothing. Reply with JSON only."
    )


def _page_image_b64(page: PageRecord) -> str | None:
    path = resolve_image_path(page.image_path)
    if not path or not path.is_file():
        return None
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fence = _JSON_FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("TOC agent response had no JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("TOC agent JSON root must be an object")
    return payload


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip().translate(
        str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    )
    match = re.search(r"\d{1,3}", text)
    if not match:
        return None
    number = int(match.group(0))
    return number if number > 0 else None


def parse_toc_payload(
    payload: dict[str, Any],
    *,
    grade: int,
    subject: str,
    source_pages: list[int],
) -> list[TocEntry]:
    """Normalize LLM JSON into TocEntry rows."""
    entries: list[TocEntry] = []

    for item in payload.get("chapters") or []:
        if not isinstance(item, dict):
            continue
        number = _as_int(item.get("number"))
        start = _as_int(item.get("start_page"))
        if number is None or start is None:
            continue
        entries.append(
            TocEntry(
                grade=grade,
                subject=subject,
                kind="chapter",
                number=number,
                title=str(item.get("title") or "").strip(),
                start_page=start,
                source_pages=source_pages,
            )
        )

    for item in payload.get("lessons") or []:
        if not isinstance(item, dict):
            continue
        number = _as_int(item.get("number"))
        start = _as_int(item.get("start_page"))
        if number is None or start is None:
            continue
        title = str(item.get("title") or "").strip()
        entries.append(
            TocEntry(
                grade=grade,
                subject=subject,
                kind="lesson",
                number=number,
                title=title,
                start_page=start,
                source_pages=source_pages,
            )
        )

    for item in payload.get("sections") or []:
        if not isinstance(item, dict):
            continue
        start = _as_int(item.get("start_page"))
        title = str(item.get("title") or "").strip()
        if start is None or not title:
            continue
        kind_label = str(item.get("kind") or "section").strip() or "section"
        entries.append(
            TocEntry(
                grade=grade,
                subject=subject,
                kind="section",
                number=None,
                title=f"{kind_label}: {title}" if kind_label != "section" else title,
                start_page=start,
                source_pages=source_pages,
            )
        )

    return entries


def _build_user_content(pages: list[PageRecord]) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    text_blocks: list[str] = []
    for page in pages:
        usable = (page.text or "").strip()
        if usable and page.text_usable:
            snippet = usable[:2500]
            text_blocks.append(f"--- صفحه چاپی {page.printed_page} (متن OCR) ---\n{snippet}")
        else:
            text_blocks.append(
                f"--- صفحه چاپی {page.printed_page} (متن OCR ضعیف/خالی؛ به تصویر تکیه کن) ---"
            )
    parts.append(
        {
            "type": "text",
            "text": (
                "صفحات فهرست این کتاب را ببین و JSON ساختار فصل/درس را برگردان.\n\n"
                + "\n\n".join(text_blocks)
            ),
        }
    )
    for page in pages:
        encoded = _page_image_b64(page)
        if not encoded:
            continue
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    return parts


async def build_toc_map(
    grade: int,
    subject: str,
    *,
    llm_client: Any,
    model: str,
    force: bool = False,
) -> bool:
    """Parse فهرست for one book and persist toc_entries. Returns True on success."""
    if not force and toc_map_ready(grade, subject):
        return True

    pages = find_toc_candidate_pages(grade, subject)
    if not pages:
        set_toc_job_status(grade, subject, "error", "no TOC candidate pages")
        return False

    set_toc_job_status(grade, subject, "running")
    source_pages = [p.printed_page for p in pages]
    try:
        from api.core.types import LLMCompletionRequest

        request = LLMCompletionRequest(
            model=model,
            temperature=0.0,
            messages=[
                {"role": "system", "content": _load_toc_system_prompt()},
                {"role": "user", "content": _build_user_content(pages)},
            ],
        )
        raw = await llm_client.complete(request)
        payload = _extract_json_object(raw)
        entries = parse_toc_payload(
            payload, grade=grade, subject=subject, source_pages=source_pages
        )
        if not entries:
            set_toc_job_status(grade, subject, "error", "empty TOC parse")
            return False
        clear_toc_entries(grade, subject)
        save_toc_entries(grade, subject, entries)
        set_toc_job_status(grade, subject, "ok")
        return True
    except Exception as exc:  # noqa: BLE001 — cache failure must not crash chat
        logger.warning("TOC build failed for g%s %s: %s", grade, subject, exc)
        set_toc_job_status(grade, subject, "error", f"{type(exc).__name__}: {exc}")
        return False


async def ensure_toc_map(
    grade: int,
    subject: str,
    *,
    llm_client: Any | None,
    model: str | None,
    force: bool = False,
) -> bool:
    """Ensure toc cache exists; no-op without an LLM client."""
    if toc_map_ready(grade, subject) and not force:
        return True
    if llm_client is None or not model:
        return toc_map_ready(grade, subject)
    return await build_toc_map(
        grade, subject, llm_client=llm_client, model=model, force=force
    )


def lookup_toc_start_page(
    grade: int,
    subject: str,
    *,
    chapter: int | None = None,
    lesson: int | None = None,
) -> int | None:
    return resolve_page_from_toc(
        grade, subject, chapter=chapter, lesson=lesson
    )
