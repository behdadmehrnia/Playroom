"""FastAPI dependencies shared by route modules."""

from __future__ import annotations

from fastapi import Request

from api.config import Settings
from api.core import LLMClient

def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_llm_client(request: Request) -> LLMClient:
    return request.app.state.llm_client
