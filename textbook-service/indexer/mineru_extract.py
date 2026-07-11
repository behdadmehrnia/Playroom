"""
Run MinerU on textbook PDFs and map content_list → per-page plain text.

MinerU is invoked via the `mineru` CLI (install: `pip install 'mineru[pipeline]'`).
For Persian schoolbooks use backend=pipeline and lang=arabic (covers Persian script).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

_HTML_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+\n")


def mineru_available() -> bool:
    return shutil.which("mineru") is not None


def _strip_html(html: str) -> str:
    text = _HTML_TAG.sub(" ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", text).strip()


def _join_caption(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                parts.append(_span_text(item))
        return "\n".join(p for p in parts if p)
    return str(value).strip()


def _span_text(node: object) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, list):
        return " ".join(t for t in (_span_text(x) for x in node) if t)
    if isinstance(node, dict):
        if "content" in node and not isinstance(node["content"], dict):
            inner = node["content"]
            if isinstance(inner, str):
                return inner.strip()
            if isinstance(inner, list):
                return _span_text(inner)
        for key in (
            "text",
            "title_content",
            "paragraph_content",
            "math_content",
            "code_content",
            "algorithm_content",
            "page_footnote_content",
            "list_items",
        ):
            if key in node:
                return _span_text(node[key])
        if "children" in node:
            return _span_text(node["children"])
    return ""


def _block_text_v1(block: dict) -> str:
    """Flatten a legacy content_list.json block."""
    btype = (block.get("type") or "").lower()
    parts: list[str] = []

    if btype in {"text", "title", "index", "equation", "phonetic", "ref_text"}:
        text = block.get("text")
        if text:
            parts.append(str(text).strip())
    elif btype == "table":
        cap = _join_caption(block.get("table_caption"))
        if cap:
            parts.append(cap)
        body = block.get("table_body") or block.get("table_html") or ""
        if body:
            parts.append(_strip_html(str(body)))
        foot = _join_caption(block.get("table_footnote"))
        if foot:
            parts.append(foot)
    elif btype in {"image", "chart"}:
        for key in ("image_caption", "chart_caption", "image_footnote", "chart_footnote"):
            cap = _join_caption(block.get(key))
            if cap:
                parts.append(cap)
        # Some versions put OCR of the figure in `text` / `content`
        extra = block.get("text") or block.get("content")
        if isinstance(extra, str) and extra.strip():
            parts.append(extra.strip())
    elif btype == "list":
        items = block.get("list_items") or block.get("text")
        if items:
            parts.append(_span_text(items) if not isinstance(items, str) else items.strip())
    elif btype == "code":
        for key in ("code_caption", "code_body", "text"):
            val = block.get(key)
            if val:
                parts.append(str(val).strip())
    elif btype in {"header", "footer", "page_number", "aside_text", "page_footnote", "page_aside_text", "page_header", "page_footer"}:
        # Skip chrome — matches MinerU's own markdown cleanup intent.
        return ""
    else:
        text = block.get("text")
        if text:
            parts.append(str(text).strip())

    return "\n".join(p for p in parts if p)


def _block_text_v2(block: dict) -> str:
    """Flatten a content_list_v2.json block (type + content)."""
    btype = (block.get("type") or "").lower()
    if btype in {
        "page_header",
        "page_footer",
        "page_number",
        "page_aside_text",
        "page_footnote",
        "header",
        "footer",
    }:
        return ""

    content = block.get("content")
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, dict):
        return _block_text_v1(block)

    parts: list[str] = []
    for key in (
        "title_content",
        "paragraph_content",
        "math_content",
        "code_content",
        "algorithm_content",
        "list_items",
        "table_caption",
        "table_footnote",
        "image_caption",
        "image_footnote",
        "chart_caption",
        "chart_footnote",
        "code_caption",
        "algorithm_caption",
    ):
        if key in content:
            text = _span_text(content[key])
            if text:
                parts.append(text)

    table_body = content.get("table_body") or content.get("html") or content.get("table_html")
    if table_body:
        parts.append(_strip_html(str(table_body)))

    if not parts and "text" in content:
        parts.append(_span_text(content["text"]))

    return "\n".join(p for p in parts if p)


def _normalize_page_text(chunks: list[str]) -> str:
    text = "\n".join(c for c in chunks if c and c.strip())
    text = _WS.sub("\n", text)
    return text.strip()


def pages_from_content_list(data: object) -> dict[int, str]:
    """
    Build {pdf_page_index: text} from content_list or content_list_v2 payloads.
    """
    pages: dict[int, list[str]] = defaultdict(list)

    # v2: list[list[block]] — outer index is page
    if isinstance(data, list) and data and isinstance(data[0], list):
        for page_idx, blocks in enumerate(data):
            for block in blocks:
                if isinstance(block, dict):
                    text = _block_text_v2(block)
                    if text:
                        pages[page_idx].append(text)
        return {i: _normalize_page_text(chunks) for i, chunks in pages.items()}

    # v1: flat list of blocks with page_idx
    if isinstance(data, list):
        for block in data:
            if not isinstance(block, dict):
                continue
            try:
                page_idx = int(block.get("page_idx", 0))
            except (TypeError, ValueError):
                page_idx = 0
            text = _block_text_v1(block)
            if text:
                pages[page_idx].append(text)
        return {i: _normalize_page_text(chunks) for i, chunks in pages.items()}

    return {}


def find_content_list_file(output_root: Path, pdf_stem: str) -> Path | None:
    """Locate MinerU content_list JSON under output_root (layout varies by version)."""
    if not output_root.is_dir():
        return None

    preferred = (
        f"{pdf_stem}_content_list_v2.json",
        f"{pdf_stem}_content_list.json",
    )
    candidates: list[Path] = []
    for path in output_root.rglob("*.json"):
        name = path.name
        if name in preferred or name.endswith("_content_list_v2.json") or name.endswith("_content_list.json"):
            candidates.append(path)

    if not candidates:
        return None

    def score(p: Path) -> tuple[int, int]:
        name = p.name
        # Prefer v2, then exact stem match, then shallower paths
        v2 = 0 if name.endswith("_content_list_v2.json") else 1
        stem_hit = 0 if pdf_stem in name else 1
        depth = len(p.relative_to(output_root).parts)
        return (v2, stem_hit, depth)

    candidates.sort(key=score)
    return candidates[0]


def load_page_texts(content_list_path: Path) -> dict[int, str]:
    data = json.loads(content_list_path.read_text(encoding="utf-8"))
    return pages_from_content_list(data)


def run_mineru(
    pdf_path: Path,
    output_dir: Path,
    *,
    backend: str = "pipeline",
    method: str = "auto",
    lang: str = "arabic",
    formula: bool = True,
    table: bool = True,
    force: bool = False,
    timeout_sec: int | None = None,
) -> dict[int, str]:
    """
    Parse one PDF with MinerU and return {pdf_page_index: text}.

    Reuses an existing content_list under output_dir unless force=True.
    """
    if not mineru_available():
        raise RuntimeError(
            "mineru CLI not found. Install with: pip install 'mineru[pipeline]' "
            "(and ensure the `mineru` command is on PATH)."
        )

    pdf_path = pdf_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    existing = None if force else find_content_list_file(output_dir, stem)
    if existing is not None:
        return load_page_texts(existing)

    cmd = [
        "mineru",
        "-p", str(pdf_path),
        "-o", str(output_dir),
        "-b", backend,
        "-m", method,
        "-l", lang,
        "-f", "true" if formula else "false",
        "-t", "true" if table else "false",
    ]

    env = os.environ.copy()
    # HuggingFace can be unreachable from some networks; ModelScope is a common fallback.
    env.setdefault("MINERU_MODEL_SOURCE", "modelscope")
    # Keep cross-page table merge off so page_idx stays meaningful for textbooks.
    env.setdefault("MINERU_TABLE_MERGE_ENABLE", "false")

    print(f"  mineru: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"mineru timed out on {pdf_path.name}") from exc

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"mineru failed on {pdf_path.name} (exit {proc.returncode}): {err[:2000]}")

    content_path = find_content_list_file(output_dir, stem)
    if content_path is None:
        raise RuntimeError(
            f"mineru finished but no content_list JSON found under {output_dir} for {stem}"
        )
    return load_page_texts(content_path)
