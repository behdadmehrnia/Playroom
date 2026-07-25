"""Parse textbook فهرست pages via LLM and cache chapter/lesson start pages."""

from __future__ import annotations

import base64
import json
import logging
import re
import asyncio
from pathlib import Path
from typing import Any

from api.textbook.app.store import (
    PageRecord,
    TocEntry,
    clear_toc_entries,
    find_toc_candidate_pages,
    get_toc_job_status,
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

# Keep TOC vision payloads small — raw MinerU PNGs can OOM the chat worker.
_TOC_MAX_IMAGES = 2
_TOC_IMAGE_MAX_SIDE = 896
_TOC_IMAGE_JPEG_QUALITY = 45
_TOC_IMAGE_MAX_BYTES = 220_000
# Skip opening huge source files entirely (PIL still decompresses full PNG in RAM).
_TOC_SOURCE_MAX_FILE_BYTES = 1_200_000


def _load_toc_system_prompt() -> str:
    if _TOC_PROMPT_PATH.is_file():
        return _TOC_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "Extract textbook table-of-contents as JSON with chapters, lessons, "
        "and sections. Invent nothing. Reply with JSON only."
    )


def _page_image_b64(page: PageRecord) -> str | None:
    """Encode a page image for TOC vision — resized JPEG to avoid OOM on chat."""
    path = resolve_image_path(page.image_path)
    if not path or not path.is_file():
        return None
    try:
        # MinerU page PNGs are often multi-MB; opening them in PIL alone can OOM.
        if path.stat().st_size > _TOC_SOURCE_MAX_FILE_BYTES:
            logger.info(
                "TOC skip large image page=%s size=%s",
                page.printed_page,
                path.stat().st_size,
            )
            return None
        from io import BytesIO

        from PIL import Image

        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((_TOC_IMAGE_MAX_SIDE, _TOC_IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=_TOC_IMAGE_JPEG_QUALITY, optimize=True)
            raw = buf.getvalue()
        if len(raw) > _TOC_IMAGE_MAX_BYTES:
            return None
        return base64.b64encode(raw).decode("ascii")
    except Exception:  # noqa: BLE001 — vision is optional; text-only TOC still works
        logger.warning("TOC image encode failed for page %s", page.printed_page)
        return None


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


def _build_user_content(
    pages: list[PageRecord],
    *,
    include_images: bool = False,
) -> list[dict[str, Any]]:
    """Build multimodal user content. Images off by default — prod OOM risk."""
    parts: list[dict[str, Any]] = []
    text_blocks: list[str] = []
    for page in pages:
        usable = (page.text or "").strip()
        if usable and page.text_usable:
            snippet = usable[:2500]
            text_blocks.append(f"--- صفحه چاپی {page.printed_page} (متن OCR) ---\n{snippet}")
        else:
            text_blocks.append(
                f"--- صفحه چاپی {page.printed_page} (متن OCR ضعیف/خالی) ---"
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
    if not include_images:
        return parts
    # Optional compressed images — full-resolution PNGs OOM the chat worker.
    attached = 0
    for page in pages:
        if attached >= _TOC_MAX_IMAGES:
            break
        encoded = _page_image_b64(page)
        if not encoded:
            continue
        parts.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            }
        )
        attached += 1
    return parts


async def build_toc_map(
    grade: int,
    subject: str,
    *,
    llm_client: Any,
    model: str,
    force: bool = False,
    llm_timeout_sec: float = 8.0,
) -> bool:
    """Parse فهرست for one book and persist toc_entries. Returns True on success."""
    if not force and toc_map_ready(grade, subject):
        return True

    # Avoid stacking parallel TOC builds.
    if not force and get_toc_job_status(grade, subject) == "running":
        return False

    pages = await asyncio.to_thread(
        lambda: find_toc_candidate_pages(grade, subject, max_pages=_TOC_MAX_IMAGES)
    )
    if not pages:
        set_toc_job_status(grade, subject, "error", "no TOC candidate pages")
        return False

    # Require at least some OCR text — empty vision-only TOC hangs/crashes easily.
    usable_chars = sum(
        len((p.text or "").strip()) for p in pages if p.text_usable and (p.text or "").strip()
    )
    if usable_chars < 40:
        set_toc_job_status(grade, subject, "error", "TOC pages have no usable OCR text")
        return False

    set_toc_job_status(grade, subject, "running")
    source_pages = [p.printed_page for p in pages]
    try:
        from api.core.types import LLMCompletionRequest

        request = LLMCompletionRequest(
            model=model,
            temperature=0.0,
            timeout_sec=llm_timeout_sec,
            messages=[
                {"role": "system", "content": _load_toc_system_prompt()},
                {
                    "role": "user",
                    "content": _build_user_content(pages, include_images=False),
                },
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
    except asyncio.CancelledError:
        set_toc_job_status(grade, subject, "error", "cancelled")
        raise
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
    llm_timeout_sec: float = 8.0,
) -> bool:
    """Ensure toc cache exists; no-op without an LLM client."""
    if toc_map_ready(grade, subject) and not force:
        return True
    if llm_client is None or not model:
        return toc_map_ready(grade, subject)
    return await build_toc_map(
        grade,
        subject,
        llm_client=llm_client,
        model=model,
        force=force,
        llm_timeout_sec=llm_timeout_sec,
    )


def schedule_toc_map_build(
    grade: int,
    subject: str,
    *,
    llm_client: Any | None,
    model: str | None,
    force: bool = False,
) -> None:
    """Start TOC build in the background — never blocks the HTTP request."""
    if llm_client is None or not model:
        return
    if toc_map_ready(grade, subject) and not force:
        return
    if get_toc_job_status(grade, subject) == "running":
        return

    async def _run() -> None:
        try:
            await build_toc_map(
                grade,
                subject,
                llm_client=llm_client,
                model=model,
                force=force,
                llm_timeout_sec=8.0,
            )
        except Exception:  # noqa: BLE001
            logger.exception("background TOC build failed g%s %s", grade, subject)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        logger.warning("no running loop for background TOC build")


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


def lookup_toc_by_title(grade: int, subject: str, title: str) -> int | None:
    from api.textbook.app.store import resolve_page_from_toc_title

    return resolve_page_from_toc_title(grade, subject, title)
