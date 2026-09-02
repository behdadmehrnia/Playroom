"""Web search heuristics, providers, and context resolution."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from typing import Any

from .constants import (
    DEFAULT_WEB_SEARCH_MAX_RESULTS,
    DEFAULT_WEB_SEARCH_TIMEOUT_SEC,
    PersonaId,
    WEB_SEARCH_PERSONAS,
)
from .messages import (
    _get_latest_user_message,
    _http_get_json,
    _http_post_json,
    _normalize_api_base_url,
)
from .prompts import get_web_search_query_prompt
from .status import status_fetching_web_search, status_web_search_unavailable
from .types import (
    ChatMessage,
    LLMClient,
    LLMCompletionRequest,
    WebSearchContext,
    WebSearchQueryDiag,
    WebSearchResult,
)

_WEB_SEARCH_NEED_RE = re.compile(
    r"(?:"
    r"چطور|چگونه|چیه|چیست|چی\s*هست|چی\s*شده|کجاست|کجا\s*(?:پیدا|میس?شه)|"
    r"کی\s*(?:هست|بود|ساخته)|چرا\s*(?:این|اون)|آپدیت|نسخه|ورژن|"
    r"منتشر|اومده|وجود\s*داره|واقعیه|"
    r"تحقیق|جستجو|سرچ|اینترنت|نصب(?:ش|ش؟\s*کن)?"
    r"|درباره(?:\s*ی|\s*ٔ)?"
    r"|اسم\s*(?:بازی|شخصیت)|قهرمان|آیتم|مود|اسکین|"
    r"how\s+to|what\s+is|where\s+(?:is|can)|who\s+is|"
    r"\?|؟"
    r")",
    re.IGNORECASE,
)

# Child (or demo) explicitly asks to look something up online — allow even
# outside the usual creative/gamer/storyteller personas.
_WEB_SEARCH_EXPLICIT_RE = re.compile(
    r"(?:"
    r"از\s*اینترنت|تو\s*اینترنت|روی\s*اینترنت|"
    r"جستجو\s*کن|سرچ\s*کن|تحقیق\s*کن|"
    r"از\s*(?:روی\s*)?نت\b|گوگل\s*کن"
    r")",
    re.IGNORECASE,
)

# Named title + version (e.g. «فورزا هورایزن ۶»، «Horizon 5»).
_WEB_SEARCH_GAME_VERSION_RE = re.compile(
    r"(?:"
    r"[A-Za-z][A-Za-z0-9:'-]{1,}(?:\s+[A-Za-z][A-Za-z0-9:'-]{1,}){0,4}\s*[\d۰-۹]{1,2}"
    r"|"
    r"[\u0600-\u06FF]{2,}(?:\s+[\u0600-\u06FF]{2,}){0,4}\s*[\d۰-۹]{1,2}"
    r")",
)

# Talking about a specific game even without a question mark.
_WEB_SEARCH_GAME_TALK_RE = re.compile(
    r"(?:"
    r"بازی\s+(?!کنیم|کنیم!|کلم|فکری|عددی)"
    r"[\w\u0600-\u06FF]"
    r"|"
    r"(?:دوست\s*دارم|بازی\s*می‌?کنم|بازی\s*کردم|بلدی|شناختی)\b"
    r")",
    re.IGNORECASE,
)

# Latest turn refers to an earlier topic («دربارش تحقیق کن»).
_WEB_SEARCH_REFERRING_RE = re.compile(
    r"(?:"
    r"دربار(?:هٔ?|ه‌ی?|ش)|همین|اون(?:و)?|همان|"
    r"تحقیق\s*کن|سرچ\s*کن|جستجو\s*کن|بیشتر\s*بگو|"
    r"پیداش?\s*کن|بگرد|اینترنت"
    r")",
    re.IGNORECASE,
)

# Pure creative/play turns where search is usually noise.
_WEB_SEARCH_SKIP_RE = re.compile(
    r"(?:"
    r"داستان\s*(?:بگو|کوتاه)|قصه\s*بگو|ادامه\s*بده|"
    r"بازی\s*کنیم|یه\s*بازی\s*(?:کلم|فکری|عددی|سریع)?|"
    r"یه\s*ایده|ایده\s*بده|"
    r"حوصله.?م\s*سر|چی\s*کار\s*کنم|نقاشی\s*کن|"
    r"بسازیم|بیا\s*بازی"
    r")",
    re.IGNORECASE,
)

_WEB_SEARCH_LIKE_TAIL_RE = re.compile(
    r"(?:"
    r"(?:\s+من)?\s+خیلی\s+دوست\s+دارم\.?\s*$"
    r"|\s+دوست\s+دارم\.?\s*$"
    r"|\s+بازی\s+می‌?کنم\.?\s*$"
    r"|\s+بازی\s+کردم\.?\s*$"
    r"|\s+رو\s+بلدی\??\s*$"
    r"|\s+رو\s+می‌?شناسی\??\s*$"
    r")",
    re.IGNORECASE,
)

# Strip chat fluff so the search box gets the topic, not «میتونی تحقیق کنی».
_WEB_SEARCH_CHAT_FILLERS: frozenset[str] = frozenset(
    {
        "درباره",
        "درباره‌ی",
        "دربارهٔ",
        "دربارش",
        "ی",
        "یه",
        "یک",
        "من",
        "تو",
        "این",
        "اون",
        "هم",
        "همون",
        "همین",
        "میتونی",
        "می‌تونی",
        "میشه",
        "می‌شه",
        "تحقیق",
        "کنی",
        "کن",
        "ببینی",
        "ببین",
        "چیه",
        "چیست",
        "چی",
        "میخوام",
        "می‌خوام",
        "نصبش",
        "نصب",
        "کنم",
        "برام",
        "بهم",
        "لطفا",
        "لطفاً",
        "بازیه",
        "انگار",
        "مثل",
        "شبیه",
        "خب",
        "مگه",
        "به",
        "از",
        "با",
        "رو",
        "را",
        "و",
        "یا",
        "که",
        "اینترنت",
        "دسترسی",
        "نداری",
        "داری",
        "سرچ",
        "جستجو",
        "بگو",
        "بده",
        "بگرد",
        "پیدا",
    }
)


def looks_like_web_search_request(
    text: str, *, persona: PersonaId | str | None = None
) -> bool:
    """True when the latest user turn likely needs a real web lookup."""
    cleaned = text.strip()
    if not cleaned:
        return False
    if _WEB_SEARCH_EXPLICIT_RE.search(cleaned):
        return True
    if _WEB_SEARCH_NEED_RE.search(cleaned):
        return True
    if _WEB_SEARCH_GAME_VERSION_RE.search(cleaned):
        return True
    if _WEB_SEARCH_SKIP_RE.search(cleaned):
        return False
    if persona == "gamer" and _WEB_SEARCH_GAME_TALK_RE.search(cleaned):
        if re.search(r"[A-Za-z]{3,}", cleaned) or re.search(
            r"[\u0600-\u06FF]{3,}", cleaned
        ):
            return True
    if len(cleaned) < 12:
        return False
    return False


def looks_like_explicit_web_search_request(text: str) -> bool:
    """True when the user explicitly asks to search the internet."""
    return bool(text and _WEB_SEARCH_EXPLICIT_RE.search(text.strip()))


def _strip_web_search_chat_fillers(text: str) -> str:
    tokens = re.split(r"[\s،,.?؟!؛:]+", text)
    kept = [
        tok
        for tok in tokens
        if tok
        and tok not in _WEB_SEARCH_CHAT_FILLERS
        and tok.lower() not in _WEB_SEARCH_CHAT_FILLERS
    ]
    return " ".join(kept).strip()


def _topic_from_user_text(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.strip())
    tightened = _WEB_SEARCH_LIKE_TAIL_RE.sub("", collapsed)
    tightened = re.sub(r"^\s*من\s+", "", tightened)
    tightened = re.sub(r"\s+", " ", tightened).strip(" .،!")
    return _strip_web_search_chat_fillers(tightened) or tightened


def build_web_search_query(messages: list[ChatMessage], *, max_len: int = 200) -> str:
    """Heuristic draft from the child's words (fallback when LLM rewrite is unavailable).

    Uses the child's own words (minus chat fluff). If they say «تحقیق کن دربارش»,
    pulls the topic from earlier turns — no name dictionaries / aliases.
    """
    user_texts = [
        message.content.strip()
        for message in messages
        if message.role == "user" and message.content.strip()
    ]
    if not user_texts:
        return ""

    latest = user_texts[-1]
    window = user_texts[-8:]

    topic_source = latest
    if _WEB_SEARCH_REFERRING_RE.search(latest) and len(window) >= 2:
        for text in reversed(window[:-1]):
            topic = _topic_from_user_text(text)
            if topic and len(topic) >= 2:
                topic_source = text
                break

    core = _topic_from_user_text(topic_source)
    if not core:
        core = re.sub(r"\s+", " ", latest).strip()
    if len(core) <= max_len:
        return core
    return core[: max_len - 1].rstrip() + "…"


def sanitize_web_search_query(raw: str, *, max_len: int = 120) -> str:
    """Keep a single search-query line from an LLM rewrite."""
    text = (raw or "").strip()
    if not text:
        return ""
    fence = re.search(r"```(?:\w+)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # First non-empty line only.
    for line in text.splitlines():
        line = line.strip().strip("\"'`").strip()
        if line:
            text = line
            break
    text = re.sub(r"\s+", " ", text).strip(" .،!")
    # Drop common wrapper phrases the model might still emit.
    text = re.sub(
        r"^(?:query|search|کوئری|جستجو)\s*[:：\-]\s*",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()
    if not text or len(text) < 2:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def _recent_user_transcript(messages: list[ChatMessage], *, limit: int = 6) -> str:
    lines: list[str] = []
    for message in messages:
        if message.role != "user" or not message.content.strip():
            continue
        lines.append(message.content.strip())
    return "\n".join(lines[-limit:])


async def rewrite_web_search_query(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    draft: str | None = None,
    timeout_sec: float = 6.0,
) -> str:
    """Rewrite the child's ask into a search-engine-friendly query via LLM.

    Falls back to ``draft`` / heuristic ``build_web_search_query`` on any failure.
    """
    fallback = (draft or "").strip() or build_web_search_query(messages)
    if not fallback or not backend_model:
        return fallback

    transcript = _recent_user_transcript(messages)
    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": get_web_search_query_prompt()},
            {
                "role": "user",
                "content": (
                    "از این حرف‌های کودک یک کوئری جستجو بساز.\n\n"
                    f"پیش‌نویس خام (fallback):\n{fallback}\n\n"
                    f"پیام‌های اخیر کاربر:\n{transcript or fallback}"
                ),
            },
        ],
    )
    try:
        raw = await asyncio.wait_for(
            llm_client.complete(request),
            timeout=timeout_sec,
        )
    except Exception:  # noqa: BLE001 — search rewrite must never break chat
        return fallback
    rewritten = sanitize_web_search_query(raw)
    return rewritten or fallback


def _web_search_query_variants(query: str) -> list[str]:
    """Light natural refinements only (same words + optional game cue)."""
    cleaned = query.strip()
    if not cleaned:
        return []
    variants = [cleaned]
    lower = cleaned.lower()
    if "بازی" not in cleaned and "game" not in lower:
        # Prefer Latin cue when the query is already mostly English.
        if re.search(r"[A-Za-z]{3,}", cleaned) and not re.search(
            r"[\u0600-\u06FF]{3,}", cleaned
        ):
            variants.append(f"{cleaned} game")
        else:
            variants.append(f"{cleaned} بازی")
    return variants


def _format_web_search_debug(
    *, query: str, provider: str, context: WebSearchContext
) -> str:
    short_query = query if len(query) <= 60 else query[:57] + "..."
    if context.error:
        return f"🐞 دیباگ سرچ | خطا: {context.error} | provider={provider}"
    if context.matched:
        n = len(context.results)
        return (
            f"🐞 دیباگ سرچ | ✅ {n} نتیجه | provider={context.provider or provider} "
            f"| کوئری: «{short_query}»"
        )
    return (
        f"🐞 دیباگ سرچ | ❌ چیزی یافت نشد | provider={provider} "
        f"| کوئری: «{short_query}»"
    )
def _format_web_search_results(results: list[WebSearchResult]) -> str:
    lines: list[str] = []
    for idx, item in enumerate(results, start=1):
        title = item.title.strip() or f"نتیجه {idx}"
        snippet = item.snippet.strip()
        url = (item.url or "").strip()
        block = f"{idx}. {title}"
        if snippet:
            block = f"{block}\n{snippet}"
        if url:
            block = f"{block}\nمنبع: {url}"
        lines.append(block)
    return "\n\n".join(lines)


def _parse_external_web_search_payload(
    data: dict[str, Any] | list[Any], *, query: str, provider: str
) -> WebSearchContext:
    # Some providers (e.g. Gerdoo GET /search) return a bare results array.
    if isinstance(data, list):
        data = {"results": data}

    results: list[WebSearchResult] = []

    def _append_item(
        *,
        title: str = "",
        snippet: str = "",
        url: str | None = None,
    ) -> None:
        title = (title or "").strip()
        snippet = (snippet or "").strip()
        url = (url or "").strip() or None
        if title or snippet:
            results.append(WebSearchResult(title=title, url=url, snippet=snippet))

    raw_results = data.get("results") or data.get("organic") or data.get("items")
    if isinstance(raw_results, list):
        for item in raw_results:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    _append_item(title="نتیجه", snippet=text)
                continue
            if not isinstance(item, dict):
                continue
            title = str(
                item.get("title") or item.get("name") or item.get("source") or ""
            ).strip()
            snippet = str(
                item.get("snippet")
                or item.get("content")
                or item.get("text")
                or item.get("summary")
                or item.get("description")
                or ""
            ).strip()
            url_raw = item.get("url") or item.get("link") or item.get("href")
            url = str(url_raw).strip() if url_raw else None
            _append_item(title=title, snippet=snippet, url=url)

    # Perplexity-style answer + citations
    answer = str(
        data.get("answer")
        or data.get("text")
        or data.get("summary")
        or data.get("content")
        or ""
    ).strip()
    if answer:
        _append_item(title="پاسخ", snippet=answer[:2000])

    citations = data.get("citations") or data.get("sources") or data.get("references")
    if isinstance(citations, list):
        for item in citations:
            if isinstance(item, str):
                _append_item(title="منبع", url=item)
                continue
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("name") or "منبع").strip()
            snippet = str(
                item.get("snippet") or item.get("text") or item.get("excerpt") or ""
            ).strip()
            url_raw = item.get("url") or item.get("link") or item.get("href")
            url = str(url_raw).strip() if url_raw else None
            _append_item(title=title, snippet=snippet, url=url)

    # Nested data wrappers
    nested = data.get("data")
    if isinstance(nested, dict) and not results:
        return _parse_external_web_search_payload(
            nested, query=query, provider=provider
        )

    context_text = str(data.get("context_text") or "").strip()
    if not context_text and results:
        context_text = _format_web_search_results(results)

    error = data.get("error")
    error_text = str(error).strip() if error else None
    # Upstream sometimes wraps an HTML error page in {"error": "<html...>"}
    if error_text and error_text.lstrip().startswith("<"):
        error_text = "سرویس جستجو خطا برگرداند"

    matched = bool(data.get("matched", bool(context_text or results)))
    if error_text and not matched:
        return WebSearchContext(
            matched=False,
            query=query,
            provider=provider,
            error=error_text,
        )

    return WebSearchContext(
        matched=matched,
        query=query,
        results=results,
        context_text=context_text or None,
        provider=provider,
        error=error_text,
    )


def _normalize_perplexity_search_url(perplexity_url: str) -> str:
    """Accept a base host or a full ``/api/v1/search`` URL."""
    raw = (perplexity_url or "").strip()
    if not raw:
        return ""
    base = raw.rstrip("/")
    if base.endswith("/api/v1/search"):
        return base
    if base.endswith("/api/v1"):
        return f"{base}/search"
    if base.endswith("/api"):
        return f"{base}/v1/search"
    return f"{base}/api/v1/search"


# Named search backends. ``auto`` expands to the default ordered chain.
WEB_SEARCH_PROVIDER_NAMES: frozenset[str] = frozenset(
    {"api", "gerdoo", "perplexity", "duckduckgo"}
)
WEB_SEARCH_PROVIDER_ALIASES: dict[str, str] = {
    "simple": "gerdoo",  # legacy name from early integration
}
# Preferred order when PLAYROOM_WEB_SEARCH_PROVIDER=auto
WEB_SEARCH_AUTO_ORDER: tuple[str, ...] = (
    "api",
    "perplexity",
    "duckduckgo",
    "gerdoo",
)


def parse_web_search_provider_chain(raw: str) -> list[str]:
    """Parse a provider setting into an ordered fallback chain.

    Accepts:
      - ``auto`` / empty → default order (``WEB_SEARCH_AUTO_ORDER``)
      - a single name, e.g. ``gerdoo``
      - a comma/semicolon-separated list, e.g. ``api,perplexity,duckduckgo,gerdoo``
    """
    text = (raw or "").strip().lower()
    if not text or text == "auto":
        return list(WEB_SEARCH_AUTO_ORDER)

    parts = [
        part.strip()
        for part in text.replace(";", ",").split(",")
        if part.strip()
    ]
    chain: list[str] = []
    for part in parts:
        if part == "auto":
            for name in WEB_SEARCH_AUTO_ORDER:
                if name not in chain:
                    chain.append(name)
            continue
        name = WEB_SEARCH_PROVIDER_ALIASES.get(part, part)
        if name in WEB_SEARCH_PROVIDER_NAMES and name not in chain:
            chain.append(name)
    return chain or list(WEB_SEARCH_AUTO_ORDER)


def format_web_search_provider_setting(raw: str) -> str:
    """Normalize for display/health: ``auto`` or a comma-joined chain."""
    text = (raw or "").strip().lower()
    if not text or text == "auto":
        return "auto"
    return ",".join(parse_web_search_provider_chain(text))


def _normalize_gerdoo_search_url(gerdoo_url: str) -> str:
    """Accept a base host or a full ``/search`` URL (Gerdoo / gerdoo.me style)."""
    raw = (gerdoo_url or "").strip()
    if not raw:
        return ""
    base = raw.rstrip("/")
    if base.endswith("/search"):
        return base
    return f"{base}/search"


def _search_via_gerdoo(
    query: str,
    *,
    gerdoo_url: str,
    max_results: int,
    timeout_sec: float,
) -> WebSearchContext:
    """GET ``{base}/search?query=...`` returning ``[{link,title,snippet}, ...]``."""
    endpoint = _normalize_gerdoo_search_url(gerdoo_url)
    if not endpoint:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="gerdoo",
            error="no_gerdoo_url",
        )

    url = f"{endpoint}?{urllib.parse.urlencode({'query': query})}"
    try:
        data = _http_get_json(url, timeout_sec=timeout_sec)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            if isinstance(payload, (dict, list)):
                parsed = _parse_external_web_search_payload(
                    payload, query=query, provider="gerdoo"
                )
                if parsed.matched:
                    return parsed
                if parsed.error:
                    return parsed
        except Exception:
            pass
        return WebSearchContext(
            matched=False,
            query=query,
            provider="gerdoo",
            error=f"HTTP {exc.code} از Gerdoo",
        )
    except urllib.error.URLError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="gerdoo",
            error=f"اتصال ناموفق به Gerdoo: {exc.reason}",
        )
    except (json.JSONDecodeError, TimeoutError, ValueError) as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="gerdoo",
            error=f"{type(exc).__name__}: {exc}",
        )

    if not data:
        return WebSearchContext(matched=False, query=query, provider="gerdoo")
    ctx = _parse_external_web_search_payload(data, query=query, provider="gerdoo")
    if ctx.results and len(ctx.results) > max_results:
        ctx.results = ctx.results[:max_results]
        ctx.context_text = _format_web_search_results(ctx.results)
    return ctx


def _search_via_perplexity(
    query: str,
    *,
    perplexity_url: str,
    max_results: int,
    timeout_sec: float,
) -> WebSearchContext:
    endpoint = _normalize_perplexity_search_url(perplexity_url)
    if not endpoint:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error="no_perplexity_url",
        )

    url = f"{endpoint}?{urllib.parse.urlencode({'query': query})}"
    try:
        data = _http_get_json(url, timeout_sec=timeout_sec)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            if isinstance(payload, dict):
                parsed = _parse_external_web_search_payload(
                    payload, query=query, provider="perplexity"
                )
                if parsed.matched:
                    return parsed
                if parsed.error:
                    return parsed
        except Exception:
            pass
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error=f"HTTP {exc.code} از سرویس Perplexity",
        )
    except urllib.error.URLError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error=f"اتصال ناموفق به Perplexity: {exc.reason}",
        )
    except (json.JSONDecodeError, TimeoutError, ValueError) as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="perplexity",
            error=f"{type(exc).__name__}: {exc}",
        )

    if not data:
        return WebSearchContext(matched=False, query=query, provider="perplexity")
    ctx = _parse_external_web_search_payload(data, query=query, provider="perplexity")
    if ctx.results and len(ctx.results) > max_results:
        ctx.results = ctx.results[:max_results]
        ctx.context_text = _format_web_search_results(ctx.results)
    return ctx


def _duckduckgo_instant_answer(
    query: str, *, timeout_sec: float
) -> list[WebSearchResult]:
    params = urllib.parse.urlencode(
        {
            "q": query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "t": "playroom",
        }
    )
    url = f"https://api.duckduckgo.com/?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Playroom/1.0 (child-assistant)"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        return []

    results: list[WebSearchResult] = []
    abstract = str(data.get("AbstractText") or "").strip()
    heading = str(data.get("Heading") or "").strip()
    abstract_url = str(data.get("AbstractURL") or "").strip() or None
    if abstract:
        results.append(
            WebSearchResult(
                title=heading or "خلاصه",
                url=abstract_url,
                snippet=abstract,
            )
        )

    answer = str(data.get("Answer") or "").strip()
    if answer and answer != abstract:
        results.append(WebSearchResult(title="پاسخ سریع", snippet=answer))

    related = data.get("RelatedTopics")
    if isinstance(related, list):
        for item in related:
            if not isinstance(item, dict):
                continue
            text = str(item.get("Text") or "").strip()
            first_url = str(item.get("FirstURL") or "").strip() or None
            if text:
                title = text.split(" - ", 1)[0][:80]
                results.append(
                    WebSearchResult(title=title, url=first_url, snippet=text)
                )
            if len(results) >= DEFAULT_WEB_SEARCH_MAX_RESULTS:
                break
    return results[:DEFAULT_WEB_SEARCH_MAX_RESULTS]


def _duckduckgo_html_results(
    query: str, *, max_results: int, timeout_sec: float
) -> list[WebSearchResult]:
    params = urllib.parse.urlencode({"q": query, "kp": "1"})  # kp=1 → safe search
    # html.duckduckgo.com often serves a bot interstitial; lite is more reliable.
    url = f"https://lite.duckduckgo.com/lite/?{params}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; Playroom/1.0; +https://github.com/playroom)"
            )
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        html = response.read().decode("utf-8", errors="replace")

    # DuckDuckGo lite: result-link (title+url) + result-snippet.
    title_re = re.compile(
        r'class=[\'"]result-link[\'"][^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'|href="([^"]+)"[^>]*class=[\'"]result-link[\'"][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    snippet_re = re.compile(
        r'class=[\'"]result-snippet[\'"][^>]*>(.*?)</(?:td|div|a|span)>',
        re.IGNORECASE | re.DOTALL,
    )
    raw_titles = title_re.findall(html)
    snippets = snippet_re.findall(html)

    def _strip_tags(value: str) -> str:
        cleaned = re.sub(r"<[^>]+>", " ", value)
        cleaned = cleaned.replace("&amp;", "&").replace("&quot;", '"').replace(
            "&#x27;", "'"
        )
        cleaned = urllib.parse.unquote(cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    def _unwrap_ddg_link(href: str) -> str:
        link = href.replace("&amp;", "&")
        if "uddg=" in link:
            # May be protocol-relative: //duckduckgo.com/l/?uddg=...
            if link.startswith("//"):
                link = "https:" + link
            parsed = urllib.parse.urlparse(link)
            qs = urllib.parse.parse_qs(parsed.query)
            encoded = qs.get("uddg", [None])[0]
            if encoded:
                return urllib.parse.unquote(encoded)
        return link

    results: list[WebSearchResult] = []
    for idx, groups in enumerate(raw_titles[:max_results]):
        href = groups[0] or groups[2]
        title_html = groups[1] or groups[3]
        title = _strip_tags(title_html)
        snippet = _strip_tags(snippets[idx]) if idx < len(snippets) else ""
        link = _unwrap_ddg_link(href)
        if title or snippet:
            results.append(WebSearchResult(title=title, url=link, snippet=snippet))
    return results


def _search_duckduckgo(
    query: str, *, max_results: int, timeout_sec: float
) -> WebSearchContext:
    results: list[WebSearchResult] = []
    try:
        results = _duckduckgo_instant_answer(query, timeout_sec=timeout_sec)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError):
        results = []

    if len(results) < max_results:
        try:
            html_results = _duckduckgo_html_results(
                query, max_results=max_results, timeout_sec=timeout_sec
            )
            seen = {(r.title, r.url) for r in results}
            for item in html_results:
                key = (item.title, item.url)
                if key in seen:
                    continue
                results.append(item)
                seen.add(key)
                if len(results) >= max_results:
                    break
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            pass

    results = results[:max_results]
    if not results:
        return WebSearchContext(matched=False, query=query, provider="duckduckgo")
    return WebSearchContext(
        matched=True,
        query=query,
        results=results,
        context_text=_format_web_search_results(results),
        provider="duckduckgo",
    )


def _wikipedia_opensearch(
    query: str, *, lang: str, limit: int, timeout_sec: float
) -> list[tuple[str, str]]:
    """Return list of (title, page_url) from MediaWiki opensearch."""
    params = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": query,
            "limit": str(limit),
            "namespace": "0",
            "format": "json",
        }
    )
    url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Playroom/1.0 (child-assistant; web-search)"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, list) or len(data) < 4:
        return []
    titles = data[1] if isinstance(data[1], list) else []
    urls = data[3] if isinstance(data[3], list) else []
    pairs: list[tuple[str, str]] = []
    for idx, title in enumerate(titles):
        title_s = str(title).strip()
        if not title_s:
            continue
        page_url = str(urls[idx]).strip() if idx < len(urls) else ""
        pairs.append((title_s, page_url))
    return pairs


def _wikipedia_summary(
    title: str, *, lang: str, timeout_sec: float
) -> str | None:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Playroom/1.0 (child-assistant; web-search)"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        return None
    extract = str(data.get("extract") or "").strip()
    return extract or None


def _wikipedia_title_relevant(query: str, title: str) -> bool:
    q = re.sub(r"\b(game|video|بازی)\b", "", query, flags=re.IGNORECASE).strip().lower()
    t = title.lower()
    if not q:
        return True
    if q in t or t.startswith(q):
        return True
    token = q.split()[0] if q.split() else q
    return len(token) >= 4 and (token in t or t.startswith(token))


def _search_wikipedia(
    query: str, *, max_results: int, timeout_sec: float
) -> WebSearchContext:
    """Reliable fallback for known games/topics when DuckDuckGo is flaky."""
    results: list[WebSearchResult] = []
    seen_titles: set[str] = set()
    # Prefer English for game titles (Persian transliterations often miss).
    for lang in ("en", "fa"):
        try:
            pairs = _wikipedia_opensearch(
                query, lang=lang, limit=max(max_results, 3), timeout_sec=timeout_sec
            )
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            json.JSONDecodeError,
            ValueError,
        ):
            continue
        for title, page_url in pairs:
            key = title.lower()
            if key in seen_titles:
                continue
            if not _wikipedia_title_relevant(query, title):
                continue
            try:
                extract = _wikipedia_summary(
                    title, lang=lang, timeout_sec=timeout_sec
                )
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                json.JSONDecodeError,
                ValueError,
            ):
                extract = None
            if not extract:
                continue
            seen_titles.add(key)
            results.append(
                WebSearchResult(
                    title=title,
                    url=page_url or None,
                    snippet=extract[:500],
                )
            )
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    if not results:
        return WebSearchContext(matched=False, query=query, provider="wikipedia")
    return WebSearchContext(
        matched=True,
        query=query,
        results=results,
        context_text=_format_web_search_results(results),
        provider="wikipedia",
    )


def _merge_web_search_results(
    *contexts: WebSearchContext, query: str, max_results: int
) -> WebSearchContext:
    merged: list[WebSearchResult] = []
    seen: set[tuple[str, str | None]] = set()
    providers: list[str] = []
    for ctx in contexts:
        if not ctx or not ctx.matched:
            continue
        if ctx.provider:
            providers.append(ctx.provider)
        for item in ctx.results:
            key = (item.title.lower(), item.url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
            if len(merged) >= max_results:
                break
        if len(merged) >= max_results:
            break
    if not merged:
        return WebSearchContext(matched=False, query=query, provider="auto")
    provider = "+".join(dict.fromkeys(providers)) or "auto"
    return WebSearchContext(
        matched=True,
        query=query,
        results=merged,
        context_text=_format_web_search_results(merged),
        provider=provider,
    )


def _search_via_api(
    query: str,
    *,
    api_url: str,
    api_key: str | None,
    max_results: int,
    timeout_sec: float,
) -> WebSearchContext:
    base = _normalize_api_base_url(api_url)
    if not base:
        return WebSearchContext(
            matched=False, query=query, provider="api", error="no_api_url"
        )

    headers: dict[str, str] = {}
    if api_key and api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    payload = {"query": query, "max_results": max_results}
    try:
        data = _http_post_json(
            f"{base}/v1/search",
            payload,
            headers=headers,
            timeout_sec=timeout_sec,
        )
    except urllib.error.HTTPError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="api",
            error=f"HTTP {exc.code} از {base}",
        )
    except urllib.error.URLError as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="api",
            error=f"اتصال ناموفق به {base}: {exc.reason}",
        )
    except (json.JSONDecodeError, TimeoutError, ValueError) as exc:
        return WebSearchContext(
            matched=False,
            query=query,
            provider="api",
            error=f"{type(exc).__name__}: {exc}",
        )

    if not data:
        return WebSearchContext(matched=False, query=query, provider="api")
    return _parse_external_web_search_payload(data, query=query, provider="api")


async def fetch_web_search_context(
    query: str,
    *,
    provider: str = "auto",
    api_url: str = "",
    api_key: str | None = None,
    gerdoo_url: str = "",
    perplexity_url: str = "",
    max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS,
    timeout_sec: float = DEFAULT_WEB_SEARCH_TIMEOUT_SEC,
) -> WebSearchContext | None:
    """
    Fetch web search snippets for creative/storyteller/gamer personas.

    Providers (``provider`` may be a single name, ``auto``, or a comma-separated
    fallback chain such as ``api,perplexity,duckduckgo,gerdoo``):
      - ``gerdoo``: GET ``{WEB_SEARCH_GERDOO_URL}/search?query=...``
      - ``api``: POST ``{WEB_SEARCH_API_URL}/v1/search``
      - ``perplexity``: GET ``{PERPLEXITY_URL}?query=...``
      - ``duckduckgo``: web search (Wikipedia as backup)
      - ``auto``: configured sources in default order
        (api → perplexity → duckduckgo → gerdoo)
    """
    cleaned = query.strip()
    if not cleaned:
        return None

    max_results = max(1, min(int(max_results), 10))
    chain = parse_web_search_provider_chain(provider)
    is_auto = (provider or "auto").strip().lower() in {"", "auto"}

    variants = _web_search_query_variants(cleaned)
    has_api = bool(_normalize_api_base_url(api_url))
    has_gerdoo = bool(_normalize_gerdoo_search_url(gerdoo_url))
    has_perplexity = bool(_normalize_perplexity_search_url(perplexity_url))

    def _try_api() -> WebSearchContext | None:
        if not has_api:
            return None
        last: WebSearchContext | None = None
        for variant in variants:
            ctx = _search_via_api(
                variant,
                api_url=api_url,
                api_key=api_key,
                max_results=max_results,
                timeout_sec=timeout_sec,
            )
            last = ctx
            if ctx.matched:
                ctx.query = cleaned
                return ctx
        return last

    def _try_gerdoo() -> WebSearchContext | None:
        if not has_gerdoo:
            return None
        last: WebSearchContext | None = None
        for variant in variants:
            ctx = _search_via_gerdoo(
                variant,
                gerdoo_url=gerdoo_url,
                max_results=max_results,
                timeout_sec=timeout_sec,
            )
            last = ctx
            if ctx.matched:
                ctx.query = cleaned
                return ctx
        return last

    def _try_perplexity() -> WebSearchContext | None:
        if not has_perplexity:
            return None
        last: WebSearchContext | None = None
        for variant in variants:
            ctx = _search_via_perplexity(
                variant,
                perplexity_url=perplexity_url,
                max_results=max_results,
                timeout_sec=timeout_sec,
            )
            last = ctx
            if ctx.matched:
                ctx.query = cleaned
                return ctx
        return last

    def _try_duckduckgo_wiki() -> WebSearchContext:
        ddg_hits: list[WebSearchContext] = []
        for variant in variants[:2]:
            ddg = _search_duckduckgo(
                variant,
                max_results=max_results,
                timeout_sec=min(timeout_sec, 6.0),
            )
            if ddg.matched:
                ddg_hits.append(ddg)
                break

        wiki_hits: list[WebSearchContext] = []
        if not ddg_hits:
            for variant in variants:
                wiki = _search_wikipedia(
                    variant,
                    max_results=max_results,
                    timeout_sec=min(timeout_sec, 8.0),
                )
                if wiki.matched:
                    wiki_hits.append(wiki)
                    break

        return _merge_web_search_results(
            *ddg_hits, *wiki_hits, query=cleaned, max_results=max_results
        )

    def _try_named(name: str) -> WebSearchContext | None:
        if name == "api":
            return _try_api()
        if name == "gerdoo":
            return _try_gerdoo()
        if name == "perplexity":
            return _try_perplexity()
        if name == "duckduckgo":
            return _try_duckduckgo_wiki()
        return None

    def _missing_config_error(name: str) -> str:
        return {
            "api": "no_api_url",
            "gerdoo": "no_gerdoo_url",
            "perplexity": "no_perplexity_url",
        }.get(name, "unavailable")

    def _run() -> WebSearchContext:
        # In auto mode, skip backends that are not configured so we do not
        # waste the chain on known-empty attempts.
        effective_chain = list(chain)
        if is_auto:
            available = {
                "api": has_api,
                "gerdoo": has_gerdoo,
                "perplexity": has_perplexity,
                "duckduckgo": True,
            }
            effective_chain = [name for name in chain if available.get(name)]
            if not effective_chain:
                effective_chain = ["duckduckgo"]

        last: WebSearchContext | None = None
        for name in effective_chain:
            ctx = _try_named(name)
            if ctx is None:
                last = WebSearchContext(
                    matched=False,
                    query=cleaned,
                    provider=name,
                    error=_missing_config_error(name),
                )
                continue
            last = ctx
            if ctx.matched:
                return ctx

        return last or WebSearchContext(
            matched=False,
            query=cleaned,
            provider=effective_chain[0] if effective_chain else "auto",
        )

    return await asyncio.to_thread(_run)


async def resolve_web_search_context(
    *,
    messages: list[ChatMessage],
    persona: PersonaId,
    enable_web_search: bool,
    provider: str = "auto",
    api_url: str = "",
    api_key: str | None = None,
    gerdoo_url: str = "",
    perplexity_url: str = "",
    max_results: int = DEFAULT_WEB_SEARCH_MAX_RESULTS,
    timeout_sec: float = DEFAULT_WEB_SEARCH_TIMEOUT_SEC,
    debug: bool = False,
    on_status: Callable[[str], Awaitable[None]] | None = None,
    llm_client: LLMClient | None = None,
    backend_model: str | None = None,
) -> WebSearchContext | None:
    """Gate + fetch web search for eligible personas."""
    user_message = _get_latest_user_message(messages)
    draft = build_web_search_query(messages)
    persona_ok = persona in WEB_SEARCH_PERSONAS or looks_like_explicit_web_search_request(
        user_message
    )
    should_fetch = bool(
        enable_web_search
        and persona_ok
        and draft
        and looks_like_web_search_request(user_message, persona=persona)
    )
    if not should_fetch:
        return None

    query = draft
    if llm_client is not None and backend_model:
        query = await rewrite_web_search_query(
            llm_client,
            backend_model=backend_model,
            messages=messages,
            draft=draft,
            timeout_sec=min(6.0, max(3.0, timeout_sec)),
        )

    if on_status:
        # Only expose the internet-search status when debug is on; otherwise
        # keep the child-facing progress the same as normal generation.
        if debug:
            await on_status(status_fetching_web_search())
        else:
            from .constants import MAX_GENERATION_ATTEMPTS
            from .status import status_generating_response

            await on_status(status_generating_response(1, MAX_GENERATION_ATTEMPTS, debug=debug))

    context = await fetch_web_search_context(
        query,
        provider=provider,
        api_url=api_url,
        api_key=api_key,
        gerdoo_url=gerdoo_url,
        perplexity_url=perplexity_url,
        max_results=max_results,
        timeout_sec=timeout_sec,
    )
    if debug and on_status and context:
        await on_status(
            _format_web_search_debug(
                query=query, provider=provider, context=context
            )
        )
        await asyncio.sleep(1.2)
    if context and not context.matched and on_status and debug:
        await on_status(status_web_search_unavailable())
    return context
def build_web_search_diag(
    *,
    query_sent: str | None,
    context: WebSearchContext | None,
) -> WebSearchQueryDiag | None:
    if not query_sent and context is None:
        return None
    return WebSearchQueryDiag(
        query_sent=(context.query if context and context.query else query_sent) or None,
        provider_used=context.provider if context else None,
        matched=bool(context and context.matched),
        results_count=len(context.results) if context else 0,
        error=context.error if context else None,
    )
