"""FastAPI application entry point for the Yar Kids API.

Run from the repo root::

    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

or::

    python -m api.main

Environment variables (see ``api.config``) configure the LLM provider, the
textbook-service connection, generation defaults and the server. The Pipe in
``pipe.py`` is left untouched; this app simply reuses its module-level helpers
and replaces the OpenWebUI-specific ``OpenWebUILLMClient`` with the
OpenAI-compatible client in ``api.llm``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from api import __version__
from api.config import Settings
from api.llm import LLMError, OpenAICompatibleLLMClient
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = Settings.from_env()
    app.state.settings = settings
    app.state.llm_client = OpenAICompatibleLLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        timeout_sec=settings.llm_timeout_sec,
    )

    # Apply CORS origins from settings now that they are loaded.
    allowed = settings.cors_origins or ["*"]
    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            mw.kwargs["allow_origins"] = allowed
            mw.kwargs["allow_credentials"] = "*" not in allowed
            break

    try:
        yield
    finally:
        await app.state.llm_client.aclose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Yar Kids API",
        description=(
            "دستیار کودک‌دوست — API مستقل با معماری Persona، Intent Detection و Reflection. "
            "این API منطق Pipe در pipe.py را به‌صورت یک سرویس FastAPI مستقل exposing می‌کند."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    # CORS with permissive defaults; the actual allowed origins are patched
    # from settings inside the lifespan once they are loaded.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.exception_handler(LLMError)
    async def handle_llm_error(_: Request, exc: LLMError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"detail": f"LLM provider error: {exc}"},
        )

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = Settings.from_env()
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
