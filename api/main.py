"""FastAPI application entry point for the Yar Kids API.

Run from the repo root::

    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

or::

    python -m api.main

The API is self-contained under ``/api``: domain logic lives in ``api.core``,
HTTP routes in ``api.routes``, and textbook retrieval is embedded in ``api.textbook``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from dotenv import load_dotenv

load_dotenv()

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
        version=__version__,
        lifespan=lifespan,
        openapi_tags=[
            {
                "name": "Health",
            },
            {
                "name": "Chat",
            },
            {
                "name": "OpenAI Compatibility",
            },
            {
                "name": "Personas",
            },
            {
                "name": "Intent",
            },
            {
                "name": "Textbook",
            },
            {
                "name": "Web Search",
            },
            {
                "name": "Generation",
            },
            {
                "name": "Reflection",
            },
        ],
    )

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
