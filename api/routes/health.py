"""Root, health, and persona catalog endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api import __version__
from api.config import Settings
from api.core import PERSONA_DROPDOWN_OPTIONS, TEXTBOOK_PERSONAS, WEB_SEARCH_PERSONAS
from api.llm import OpenAICompatibleLLMClient
from api.models import HealthResponse, PersonaInfo, PersonasResponse

from .deps import get_llm_client, get_settings

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Settings = Depends(get_settings),
    llm_client: OpenAICompatibleLLMClient = Depends(get_llm_client),
) -> HealthResponse:
    warnings: list[str] = []
    if not settings.backend_model:
        warnings.append("YARKIDS_BACKEND_MODEL not set")
    if not settings.llm_api_key:
        warnings.append("YARKIDS_LLM_API_KEY not set")

    textbook_mode = "embedded" if settings.uses_embedded_textbook() else "external"

    llm_ready = bool(
        settings.backend_model and settings.llm_api_key and settings.llm_base_url
    )
    return HealthResponse(
        status="ok",
        version=__version__,
        backend_model=settings.backend_model,
        llm_base_url=settings.llm_base_url,
        llm_ready=llm_ready,
        textbook_api_url=settings.textbook_api_url or "embedded",
        textbook_enabled=settings.enable_textbook_context,
        textbook_mode=textbook_mode,
        web_search_enabled=settings.enable_web_search,
        web_search_provider=settings.normalized_web_search_provider(),
        reflection_enabled=settings.enable_reflection,
        warnings=warnings,
    )


@router.get("/v1/personas", response_model=PersonasResponse, tags=["Personas"])
async def personas() -> PersonasResponse:
    return PersonasResponse(
        personas=[
            PersonaInfo(value=opt["value"], label=opt["label"])
            for opt in PERSONA_DROPDOWN_OPTIONS
        ],
        textbook_personas=sorted(TEXTBOOK_PERSONAS),
        web_search_personas=sorted(WEB_SEARCH_PERSONAS),
    )
