"""Settings and configuration tests."""

from __future__ import annotations

import pytest

from api.config import Settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.enable_reflection is True
    assert s.uses_embedded_textbook() is True


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLAYROOM_BACKEND_MODEL", "gpt-test")
    monkeypatch.setenv("PLAYROOM_LLM_API_KEY", "secret")
    monkeypatch.setenv("PLAYROOM_ENABLE_REFLECTION", "false")
    monkeypatch.setenv("PLAYROOM_TEXTBOOK_API_URL", "http://external")
    monkeypatch.setenv("PLAYROOM_WEB_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setenv("PLAYROOM_CORS_ORIGINS", "http://a.test,http://b.test")

    s = Settings.from_env()
    assert s.backend_model == "gpt-test"
    assert s.llm_api_key == "secret"
    assert s.enable_reflection is False
    assert s.uses_embedded_textbook() is False
    assert s.normalized_web_search_provider() == "duckduckgo"
    assert s.cors_origins == ["http://a.test", "http://b.test"]


def test_settings_web_search_provider_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PLAYROOM_WEB_SEARCH_PROVIDER", "api,perplexity,duckduckgo,gerdoo"
    )
    monkeypatch.setenv(
        "PLAYROOM_WEB_SEARCH_GERDOO_URL", "http://search.example.com:8888"
    )
    s = Settings.from_env()
    assert s.normalized_web_search_provider() == "api,perplexity,duckduckgo,gerdoo"
    assert s.normalized_web_search_providers() == [
        "api",
        "perplexity",
        "duckduckgo",
        "gerdoo",
    ]
    assert s.web_search_gerdoo_url == "http://search.example.com:8888"


def test_settings_gerdoo_url_legacy_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PLAYROOM_WEB_SEARCH_GERDOO_URL", raising=False)
    monkeypatch.setenv("PLAYROOM_WEB_SEARCH_SIMPLE_URL", "http://legacy.test")
    s = Settings.from_env()
    assert s.web_search_gerdoo_url == "http://legacy.test"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("auto", "auto"),
        ("invalid", "auto"),
        ("never", "never"),
        ("ALWAYS", "always"),
    ],
)
def test_normalized_include_image(raw: str, expected: str) -> None:
    s = Settings(textbook_include_image=raw)
    assert s.normalized_include_image() == expected
