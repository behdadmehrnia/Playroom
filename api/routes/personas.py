"""Persona resolution endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.config import Settings
from api.core import LLMClient, resolve_active_persona, resolve_manual_persona
from api.models import PersonaResolveRequest, PersonaResolveResponse

from .deps import get_llm_client, get_settings
from .helpers import build_resolve_body, resolve_backend_model, to_chat_messages

router = APIRouter()

@router.post("/v1/persona/resolve", response_model=PersonaResolveResponse)
async def resolve_persona_endpoint(
    req: PersonaResolveRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> PersonaResolveResponse:
    model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    body = build_resolve_body(req.metadata)

    manual = resolve_manual_persona(user_persona=req.persona, body=body)

    resolution = await resolve_active_persona(
        llm_client,
        backend_model=model,
        messages=messages,
        user_persona=req.persona,
        body=body,
    )
    persona = resolution.persona

    if resolution.ask_confirmation and resolution.pending_switch_to:
        return PersonaResolveResponse(
            persona=persona,
            source="confirm",
            confidence=1.0,
            pending_persona=resolution.pending_switch_to,
        )
    if manual and persona == manual:
        return PersonaResolveResponse(persona=manual, source="manual")
    if persona == "none":
        return PersonaResolveResponse(persona="none", source="default")
    return PersonaResolveResponse(persona=persona, source="intent")
