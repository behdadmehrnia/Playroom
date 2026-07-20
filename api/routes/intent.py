"""Intent detection endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.config import Settings
from api.core import LLMClient
from api.models import IntentRequest, IntentResponse
from api.service import detect_intent_for

from .deps import get_llm_client, get_settings
from .helpers import resolve_backend_model, to_chat_messages

router = APIRouter()

@router.post("/v1/intent", response_model=IntentResponse)
async def detect_intent_endpoint(
    req: IntentRequest,
    settings: Settings = Depends(get_settings),
    llm_client: LLMClient = Depends(get_llm_client),
) -> IntentResponse:
    model = resolve_backend_model(settings, req.model)
    messages = to_chat_messages(req.messages)
    intent, user_text = await detect_intent_for(
        llm_client=llm_client, backend_model=model, messages=messages, current_persona=req.persona
    )
    return IntentResponse(intent=intent, latest_user_message=user_text)
