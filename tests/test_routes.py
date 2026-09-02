"""HTTP route integration tests (no real LLM / network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DummyLLM
from api.core.messages import strip_persona_markers


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["backend_model"] == "test-model"
    assert body["llm_ready"] is True


def test_personas_catalog(client: TestClient) -> None:
    r = client.get("/v1/personas")
    assert r.status_code == 200
    body = r.json()
    values = {p["value"] for p in body["personas"]}
    assert "teacher" in values
    assert "gamer" in values
    assert "teacher" in body["textbook_personas"]
    assert "gamer" in body["web_search_personas"]


def test_textbook_query_endpoint(client: TestClient) -> None:
    r = client.post(
        "/v1/textbook/query",
        json={
            "messages": [
                {"role": "user", "content": "صفحه ۷ کتاب فارسی پایه ششم"}
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["query"]
    assert body["looks_like_page_query"] is True


def test_web_search_query_endpoint(client: TestClient) -> None:
    r = client.post(
        "/v1/web-search/query",
        json={
            "messages": [
                {"role": "user", "content": "ماینکرفت چطور الماس پیدا کنم؟"}
            ],
            "persona": "gamer",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["looks_like_search_request"] is True
    assert body["query"]


def test_web_search_provider_endpoints_exist(client: TestClient, monkeypatch) -> None:  # noqa: ANN001
    from api.core.types import WebSearchContext, WebSearchResult
    import api.routes.web_search as web_search_routes

    async def fake_fetch(query, *, provider, **kwargs):  # noqa: ANN001
        return WebSearchContext(
            matched=True,
            query=query,
            provider=provider,
            results=[WebSearchResult(title="T", snippet="S", url="https://x")],
            context_text="1. T\nS",
        )

    monkeypatch.setattr(web_search_routes, "fetch_web_search_context", fake_fetch)

    for name in ("api", "perplexity", "duckduckgo", "gerdoo"):
        r = client.post(
            f"/v1/web-search/providers/{name}",
            json={"query": "New god of war release", "max_results": 3},
        )
        assert r.status_code == 200, name
        body = r.json()
        assert body["provider"] == name
        assert body["matched"] is True
        assert body["results_count"] == 1
        assert body["query"] == "New god of war release"

def test_intent_endpoint(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(
        responses=['{"persona":"homework","confidence":0.9}']
    )
    r = client.post(
        "/v1/intent",
        json={
            "messages": [{"role": "user", "content": "۱۲ × ۵ چنده؟"}],
            "model": "test-model",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["intent"]["persona"] == "homework"


def test_persona_resolve_manual(client: TestClient) -> None:
    r = client.post(
        "/v1/persona/resolve",
        json={
            "messages": [{"role": "user", "content": "سلام"}],
            "persona": "teacher",
            "model": "test-model",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["persona"] == "teacher"
    assert body["source"] == "manual"


def test_generate_endpoint(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(responses=["پاسخ تست"])
    r = client.post(
        "/v1/generate",
        json={
            "messages": [{"role": "user", "content": "سلام"}],
            "persona": "creative",
            "model": "test-model",
        },
    )
    assert r.status_code == 200
    assert r.json()["response"] == "پاسخ تست"


def test_reflect_endpoint(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(responses=['{"status":"PASS"}'])
    r = client.post(
        "/v1/reflect",
        json={
            "user_message": "سلام",
            "candidate_response": "سلام دوست من!",
            "model": "test-model",
        },
    )
    assert r.status_code == 200
    assert r.json()["reflection"]["status"] == "PASS"


def test_chat_endpoint_non_stream(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(responses=["سلام!"])
    r = client.post(
        "/v1/chat",
        json={
            "messages": [{"role": "user", "content": "سلام"}],
            "persona": "creative",
            "model": "test-model",
            "stream": False,
            "enable_reflection": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert strip_persona_markers(body["response"]) == "سلام!"
    assert body["persona"] == "creative"


def test_openai_chat_completions(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(responses=["Hello from Playroom"])
    r = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "hi"}],
            "persona": "creative",
            "stream": False,
            "enable_reflection": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion"
    assert strip_persona_markers(body["choices"][0]["message"]["content"]) == "Hello from Playroom"
    assert "playroom" in body


def test_openai_responses(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(responses=["Hi there"])
    r = client.post(
        "/v1/responses",
        json={
            "input": "hello",
            "persona": "creative",
            "stream": False,
            "enable_reflection": False,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "response"
    assert strip_persona_markers(body["output_text"]) == "Hi there"
    assert "playroom" in body
