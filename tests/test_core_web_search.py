"""Web search heuristics and payload parsing tests."""

from __future__ import annotations

import pytest

from api.core import (
    ChatMessage,
    WebSearchContext,
    WebSearchResult,
    build_web_search_query,
    looks_like_web_search_request,
)
from api.core.web_search import (
    _merge_web_search_results,
    _normalize_perplexity_search_url,
    _parse_external_web_search_payload,
    _web_search_query_variants,
)


def test_looks_like_web_search_request() -> None:
    assert looks_like_web_search_request("ماینکرفت چطور الماس پیدا کنم؟") is True
    assert looks_like_web_search_request("داستان یه ربات فضایی بگو") is False


def test_looks_like_web_search_respects_persona_gate() -> None:
    assert looks_like_web_search_request("ماینکرفت چطور الماس پیدا کنم؟") is True
    # Game-talk heuristic is gamer-only.
    assert looks_like_web_search_request("بازی minecraft", persona="teacher") is False
    assert looks_like_web_search_request("بازی minecraft", persona="gamer") is True
    assert looks_like_web_search_request("داستان یه ربات فضایی بگو") is False


def test_explicit_internet_ask_is_web_search() -> None:
    from api.core.web_search import looks_like_explicit_web_search_request

    text = "الان رئیس جمهور ایران کیه؟ از اینترنت بگو"
    assert looks_like_explicit_web_search_request(text) is True
    assert looks_like_web_search_request(text, persona="homework") is True
    assert looks_like_explicit_web_search_request("سلام خوبی") is False
    assert looks_like_web_search_request("یه تمرین ریاضی حل کنیم", persona="homework") is False


def test_build_web_search_query() -> None:
    messages = [
        ChatMessage(role="user", content="ماینکرفت چطور الماس پیدا کنم؟"),
    ]
    query = build_web_search_query(messages)
    assert "ماینکرفت" in query or "الماس" in query


def test_web_search_query_variants() -> None:
    variants = _web_search_query_variants("minecraft diamond")
    assert variants[0] == "minecraft diamond"
    assert len(variants) >= 1


def test_normalize_perplexity_search_url() -> None:
    assert _normalize_perplexity_search_url("https://api.perplexity.ai").endswith(
        "/search"
    )
    assert _normalize_perplexity_search_url(
        "https://api.perplexity.ai/api/v1/search"
    ).endswith("/search")


def test_parse_external_web_search_payload() -> None:
    ctx = _parse_external_web_search_payload(
        {
            "results": [
                {"title": "Tip", "snippet": "Use iron pickaxe", "url": "https://x.test"}
            ]
        },
        query="minecraft",
        provider="api",
    )
    assert ctx.matched is True
    assert len(ctx.results) == 1
    assert ctx.results[0].snippet == "Use iron pickaxe"


def test_merge_web_search_results_deduplicates() -> None:
    item = WebSearchResult(title="A", url="https://a.test", snippet="one")
    ctx_a = WebSearchContext(matched=True, query="q", provider="a", results=[item])
    ctx_b = WebSearchContext(
        matched=True,
        query="q",
        provider="b",
        results=[WebSearchResult(title="A", url="https://a.test", snippet="two")],
    )
    merged = _merge_web_search_results(ctx_a, ctx_b, query="q", max_results=5)
    assert merged.matched is True
    assert len(merged.results) == 1
