"""HTTP route integration tests (no real LLM / network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.conftest import DummyLLM


def test_root(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Yar Kids API"
    assert "docs" in body


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
    assert body["response"] == "سلام!"
    assert body["persona"] == "creative"


def test_openai_chat_completions(client: TestClient) -> None:
    client.app.state.llm_client = DummyLLM(responses=["Hello from Yar Kids"])
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
    assert body["choices"][0]["message"]["content"] == "Hello from Yar Kids"
    assert "yarkids" in body


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
    assert body["output_text"] == "Hi there"
    assert "yarkids" in body
