"""Configuration for the Playroom API.

All settings are read from environment variables. Bool parsing reuses
``api.core.coerce_bool`` so the same tolerant semantics
(``1``/``true``/``yes`` ...) apply.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

from api.core import DEFAULT_TEXTBOOK_TIMEOUT_SEC, DEFAULT_WEB_SEARCH_TIMEOUT_SEC, coerce_bool


class Settings(BaseModel):
    """Runtime configuration loaded once at startup from the environment."""

    # --- LLM provider ---
    backend_model: str = Field(
        default="",
        description="Backend LLM model (required to generate replies).",
    )
    llm_base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL of the OpenAI-compatible API (without /chat/completions).",
    )
    llm_api_key: str = Field(
        default="",
        description="API key (bearer token) for the LLM service.",
    )
    llm_timeout_sec: float = Field(
        default=120.0,
        ge=5.0,
        description="Request timeout for the LLM service, in seconds.",
    )

    # --- Generation / agents ---
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    enable_reflection: bool = Field(default=True)
    enable_status_updates: bool = Field(default=True)
    enable_chat_title: bool = Field(default=True)
    chat_title_min_user_messages: int = Field(default=2, ge=1, le=6)

    # --- Textbook (embedded by default; optional external URL) ---
    enable_textbook_context: bool = Field(default=True)
    textbook_api_url: str = Field(
        default="",
        description=(
            "URL of an external textbook service. Empty / local / self = the embedded api.textbook package."
        ),
    )
    textbook_api_key: str = Field(default="")
    textbook_request_timeout_sec: float = Field(
        default=DEFAULT_TEXTBOOK_TIMEOUT_SEC, ge=1.0, le=1200.0
    )
    textbook_neighbor_pages: int = Field(default=2, ge=0, le=3)
    textbook_include_image: str = Field(default="always")
    textbook_debug: bool = Field(default=False)

    # --- Web search — creative / storyteller / gamer ---
    enable_web_search: bool = Field(default=True)
    web_search_provider: str = Field(
        default="auto",
        description=(
            "A single provider, auto, or a comma-separated fallback chain "
            "(e.g. gerdoo,api,duckduckgo)."
        ),
    )
    web_search_api_url: str = Field(default="")
    web_search_api_key: str = Field(default="")
    web_search_gerdoo_url: str = Field(
        default="",
        description=(
            "Base or full URL of the Gerdoo search service (gerdoo.me) "
            "(GET .../search?query=...). Empty = disabled."
        ),
    )
    web_search_perplexity_url: str = Field(
        default="",
        description=(
            "Base or full URL of a Perplexity-style search service "
            "(GET .../api/v1/search?query=...). Empty = disabled."
        ),
    )
    web_search_request_timeout_sec: float = Field(
        default=DEFAULT_WEB_SEARCH_TIMEOUT_SEC, ge=1.0, le=30.0
    )
    web_search_max_results: int = Field(default=5, ge=1, le=10)
    web_search_debug: bool = Field(default=False)

    # --- Server ---
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    @classmethod
    def from_env(cls) -> "Settings":
        def env(name: str, default: str = "") -> str:
            return os.environ.get(name, default)

        def env_int(name: str, default: int) -> int:
            raw = env(name).strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def env_float(name: str, default: float) -> float:
            raw = env(name).strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        def env_bool(name: str, default: bool) -> bool:
            raw = env(name)
            if not raw.strip():
                return default
            return coerce_bool(raw, default=default)

        cors_raw = env("PLAYROOM_CORS_ORIGINS", "*").strip()
        if cors_raw:
            cors_origins = [item.strip() for item in cors_raw.split(",") if item.strip()]
        else:
            cors_origins = ["*"]

        return cls(
            backend_model=env("PLAYROOM_BACKEND_MODEL").strip(),
            llm_base_url=env("PLAYROOM_LLM_BASE_URL", "https://api.openai.com/v1").strip(),
            llm_api_key=env("PLAYROOM_LLM_API_KEY").strip(),
            llm_timeout_sec=env_float("PLAYROOM_LLM_TIMEOUT_SEC", 120.0),
            temperature=env_float("PLAYROOM_TEMPERATURE", 0.7),
            enable_reflection=env_bool("PLAYROOM_ENABLE_REFLECTION", True),
            enable_status_updates=env_bool("PLAYROOM_ENABLE_STATUS_UPDATES", True),
            enable_chat_title=env_bool("PLAYROOM_ENABLE_CHAT_TITLE", True),
            chat_title_min_user_messages=env_int(
                "PLAYROOM_CHAT_TITLE_MIN_USER_MESSAGES", 2
            ),
            enable_textbook_context=env_bool("PLAYROOM_ENABLE_TEXTBOOK_CONTEXT", True),
            textbook_api_url=env("PLAYROOM_TEXTBOOK_API_URL", "").strip(),
            textbook_api_key=env("PLAYROOM_TEXTBOOK_API_KEY").strip(),
            textbook_request_timeout_sec=env_float(
                "PLAYROOM_TEXTBOOK_REQUEST_TIMEOUT_SEC", DEFAULT_TEXTBOOK_TIMEOUT_SEC
            ),
            textbook_neighbor_pages=env_int("PLAYROOM_TEXTBOOK_NEIGHBOR_PAGES", 2),
            textbook_include_image=env("PLAYROOM_TEXTBOOK_INCLUDE_IMAGE", "always").strip().lower(),
            textbook_debug=env_bool("PLAYROOM_TEXTBOOK_DEBUG", False),
            enable_web_search=env_bool("PLAYROOM_ENABLE_WEB_SEARCH", True),
            web_search_provider=env("PLAYROOM_WEB_SEARCH_PROVIDER", "auto").strip().lower(),
            web_search_api_url=env("PLAYROOM_WEB_SEARCH_API_URL").strip(),
            web_search_api_key=env("PLAYROOM_WEB_SEARCH_API_KEY").strip(),
            web_search_gerdoo_url=(
                env("PLAYROOM_WEB_SEARCH_GERDOO_URL").strip()
                or env("PLAYROOM_WEB_SEARCH_SIMPLE_URL").strip()  # legacy alias
            ),
            web_search_perplexity_url=env(
                "PLAYROOM_WEB_SEARCH_PERPLEXITY_URL"
            ).strip(),
            web_search_request_timeout_sec=env_float(
                "PLAYROOM_WEB_SEARCH_REQUEST_TIMEOUT_SEC", DEFAULT_WEB_SEARCH_TIMEOUT_SEC
            ),
            web_search_max_results=env_int("PLAYROOM_WEB_SEARCH_MAX_RESULTS", 5),
            web_search_debug=env_bool("PLAYROOM_WEB_SEARCH_DEBUG", False),
            host=env("PLAYROOM_API_HOST", "0.0.0.0").strip(),
            port=env_int("PLAYROOM_API_PORT", 8000),
            cors_origins=cors_origins,
        )

    def normalized_include_image(self) -> str:
        value = self.textbook_include_image.strip().lower()
        if value not in {"never", "auto", "always"}:
            return "auto"
        return value

    def normalized_web_search_provider(self) -> str:
        """Display form: ``auto`` or a validated comma-joined fallback chain."""
        from api.core.web_search import format_web_search_provider_setting

        return format_web_search_provider_setting(self.web_search_provider)

    def normalized_web_search_providers(self) -> list[str]:
        """Ordered fallback chain parsed from ``web_search_provider``."""
        from api.core.web_search import parse_web_search_provider_chain

        return parse_web_search_provider_chain(self.web_search_provider)

    def uses_embedded_textbook(self) -> bool:
        value = self.textbook_api_url.strip().lower()
        return value in {"", "local", "inprocess", "self", "embedded"}
