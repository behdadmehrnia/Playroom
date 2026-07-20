"""Settings and configuration tests."""

from __future__ import annotations

import pytest

from api.config import Settings


def test_settings_defaults() -> None:
    s = Settings()
    assert s.enable_reflection is True
    assert s.uses_embedded_textbook() is True


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YARKIDS_BACKEND_MODEL", "gpt-test")
    monkeypatch.setenv("YARKIDS_LLM_API_KEY", "secret")
    monkeypatch.setenv("YARKIDS_ENABLE_REFLECTION", "false")
    monkeypatch.setenv("YARKIDS_TEXTBOOK_API_URL", "http://external")
    monkeypatch.setenv("YARKIDS_WEB_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setenv("YARKIDS_CORS_ORIGINS", "http://a.test,http://b.test")

    s = Settings.from_env()
    assert s.backend_model == "gpt-test"
    assert s.llm_api_key == "secret"
    assert s.enable_reflection is False
    assert s.uses_embedded_textbook() is False
    assert s.normalized_web_search_provider() == "duckduckgo"
    assert s.cors_origins == ["http://a.test", "http://b.test"]


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
