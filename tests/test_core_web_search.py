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
    _normalize_gerdoo_search_url,
    _normalize_perplexity_search_url,
    _parse_external_web_search_payload,
    _web_search_query_variants,
    parse_web_search_provider_chain,
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


def test_sanitize_web_search_query() -> None:
    from api.core.web_search import sanitize_web_search_query

    assert sanitize_web_search_query('  "God of War new release"  ') == "God of War new release"
    assert sanitize_web_search_query("Query: Minecraft diamonds") == "Minecraft diamonds"
    assert sanitize_web_search_query("```\nForza Horizon 6\n```") == "Forza Horizon 6"


@pytest.mark.asyncio
async def test_rewrite_web_search_query_uses_llm() -> None:
    from api.core.web_search import rewrite_web_search_query

    class _FakeLLM:
        async def complete(self, request):  # noqa: ANN001
            assert "گاد آو وار" in request.messages[-1]["content"]
            return "God of War new release"

    messages = [
        ChatMessage(role="user", content="بازی کنیم"),
        ChatMessage(
            role="user",
            content="جدیدترین بازی گاد آو واری که میخواد بیاد چیه",
        ),
    ]
    query = await rewrite_web_search_query(
        _FakeLLM(),  # type: ignore[arg-type]
        backend_model="test-model",
        messages=messages,
    )
    assert query == "God of War new release"
    assert "گاد" not in query


@pytest.mark.asyncio
async def test_rewrite_web_search_query_falls_back_on_error() -> None:
    from api.core.web_search import rewrite_web_search_query

    class _BrokenLLM:
        async def complete(self, request):  # noqa: ANN001
            raise RuntimeError("boom")

    messages = [
        ChatMessage(
            role="user",
            content="جدیدترین بازی گاد آو واری که میخواد بیاد چیه",
        ),
    ]
    query = await rewrite_web_search_query(
        _BrokenLLM(),  # type: ignore[arg-type]
        backend_model="test-model",
        messages=messages,
        draft="گاد آو وار جدید",
    )
    assert query == "گاد آو وار جدید"


def test_god_of_war_ask_triggers_search_gate() -> None:
    text = "جدیدترین بازی گاد آو واری که میخواد بیاد چیه"
    assert looks_like_web_search_request(text, persona="gamer") is True


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


def test_normalize_gerdoo_search_url() -> None:
    assert (
        _normalize_gerdoo_search_url("http://185.149.192.142:8888")
        == "http://185.149.192.142:8888/search"
    )
    assert (
        _normalize_gerdoo_search_url("http://185.149.192.142:8888/search")
        == "http://185.149.192.142:8888/search"
    )
    assert _normalize_gerdoo_search_url("") == ""


def test_parse_web_search_provider_chain() -> None:
    assert parse_web_search_provider_chain("auto") == [
        "api",
        "perplexity",
        "duckduckgo",
        "gerdoo",
    ]
    assert parse_web_search_provider_chain("gerdoo") == ["gerdoo"]
    assert parse_web_search_provider_chain("api,perplexity,duckduckgo,gerdoo") == [
        "api",
        "perplexity",
        "duckduckgo",
        "gerdoo",
    ]
    assert parse_web_search_provider_chain("simple,api") == ["gerdoo", "api"]
    assert parse_web_search_provider_chain("nope,also-bad") == [
        "api",
        "perplexity",
        "duckduckgo",
        "gerdoo",
    ]


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


def test_parse_external_web_search_list_payload() -> None:
    """Gerdoo provider returns a bare JSON array with link/title/snippet."""
    ctx = _parse_external_web_search_payload(
        [
            {
                "link": "https://www.sargarme.com/god-of-war-gow-new-game-ps5-leaked/",
                "title": "زمان رونمایی از بازی جدید God of War فاش شد",
                "snippet": "گزارش‌ها نشان می‌دهد که شرکت سونی رونمایی می‌کند.",
            },
            {
                "link": "https://www.zoomg.ir/playstation/2338-god-of-war-ps4-sony/",
                "title": "نسخه‌ی جدید God of War در دست ساخت است",
                "snippet": "کوری بالروگ یکی از کارگردانان استودیو سانتا مونیکا",
            },
        ],
        query="New god of war release",
        provider="gerdoo",
    )
    assert ctx.matched is True
    assert ctx.provider == "gerdoo"
    assert len(ctx.results) == 2
    assert ctx.results[0].url == (
        "https://www.sargarme.com/god-of-war-gow-new-game-ps5-leaked/"
    )
    assert "God of War" in ctx.results[0].title
    assert ctx.context_text is not None
    assert "منبع:" in ctx.context_text


def test_search_via_gerdoo_fetches_list_results(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.core import web_search as web_search_mod

    sample = [
        {
            "link": "https://example.com/gow",
            "title": "God of War",
            "snippet": "New release rumors",
        }
    ]

    def fake_get_json(url: str, *, headers=None, timeout_sec: float):  # noqa: ANN001
        assert url.startswith("http://185.149.192.142:8888/search?")
        assert "query=" in url
        return sample

    monkeypatch.setattr(web_search_mod, "_http_get_json", fake_get_json)

    ctx = web_search_mod._search_via_gerdoo(
        "New god of war release",
        gerdoo_url="http://185.149.192.142:8888",
        max_results=5,
        timeout_sec=8.0,
    )
    assert ctx.matched is True
    assert ctx.provider == "gerdoo"
    assert len(ctx.results) == 1
    assert ctx.results[0].url == "https://example.com/gow"


@pytest.mark.asyncio
async def test_fetch_web_search_fallback_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    from api.core import web_search as web_search_mod

    calls: list[str] = []

    def fake_gerdoo(query, *, gerdoo_url, max_results, timeout_sec):  # noqa: ANN001
        calls.append("gerdoo")
        return WebSearchContext(
            matched=False, query=query, provider="gerdoo", error="empty"
        )

    def fake_api(query, *, api_url, api_key, max_results, timeout_sec):  # noqa: ANN001
        calls.append("api")
        return WebSearchContext(
            matched=True,
            query=query,
            provider="api",
            results=[WebSearchResult(title="Hit", snippet="from api", url="https://a")],
            context_text="1. Hit\nfrom api",
        )

    monkeypatch.setattr(web_search_mod, "_search_via_gerdoo", fake_gerdoo)
    monkeypatch.setattr(web_search_mod, "_search_via_api", fake_api)

    ctx = await web_search_mod.fetch_web_search_context(
        "test query",
        provider="gerdoo,api,duckduckgo",
        gerdoo_url="http://gerdoo.test",
        api_url="http://api.test",
        max_results=3,
        timeout_sec=5.0,
    )
    assert ctx is not None
    assert ctx.matched is True
    assert ctx.provider == "api"
    assert "gerdoo" in calls
    assert "api" in calls
    assert calls.index("gerdoo") < calls.index("api")
    assert "duckduckgo" not in calls


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
