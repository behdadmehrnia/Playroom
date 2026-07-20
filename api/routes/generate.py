"""Single-shot generation and reflection endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.config import Settings
from api.core import (
    LLMClient,
    SUPPORTED_PERSONAS,
    VALID_PERSONAS,
    generate_response,
    reflect_on_response,
)
from api.models import GenerateRequest, GenerateResponse, ReflectRequest, ReflectResponse

from .deps import get_llm_client, get_settings
from .helpers import resolve_backend_model, to_chat_messages

router = APIRouter()

@router.post("/v1/generate", response_model=GenerateResponse)
async def generate_endpoint(
    req: GenerateRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> GenerateResponse:
    if req.persona not in VALID_PERSONAS:
        raise HTTPException(
            status_code=400,
            detail=f"persona must be one of: {', '.join(sorted(SUPPORTED_PERSONAS))} or none",
        )
    model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    temperature = (
        req.temperature if req.temperature is not None else settings.temperature
    )
    response = await generate_response(
        llm_client,
        backend_model=model,
        persona=req.persona,  # type: ignore[arg-type]
        conversation_messages=messages,
        revision_reasons=req.revision_reasons,
        temperature=temperature,
        textbook_context=req.textbook_context,
        web_search_context=req.web_search_context,
    )
    return GenerateResponse(response=response)


@router.post("/v1/reflect", response_model=ReflectResponse)
async def reflect_endpoint(
    req: ReflectRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> ReflectResponse:
    model = resolve_backend_model(settings, req.model)
    reflection = await reflect_on_response(
        llm_client,
        backend_model=model,
        user_message=req.user_message,
        candidate_response=req.candidate_response,
        textbook_context=req.textbook_context,
        web_search_context=req.web_search_context,
    )
    return ReflectResponse(reflection=reflection)
