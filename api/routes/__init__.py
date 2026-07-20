"""HTTP routes for the standalone Yar Kids API.

Route modules are grouped by concern; this package composes a single ``router``
for ``api.main`` and mounts the embedded textbook API under ``/v1``.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.textbook.app.routes import router as textbook_router

from .chat import router as chat_router
from .generate import router as generate_router
from .health import router as health_router
from .intent import router as intent_router
from .openai_compat import router as openai_compat_router
from .personas import router as personas_router
from .textbook import router as textbook_routes_router
from .web_search import router as web_search_router

router = APIRouter()
router.include_router(health_router)
router.include_router(intent_router)
router.include_router(personas_router)
router.include_router(textbook_routes_router)
router.include_router(web_search_router)
router.include_router(generate_router)
router.include_router(chat_router)
router.include_router(openai_compat_router)
router.include_router(textbook_router, prefix="/v1", tags=["Textbook"])

__all__ = ["router"]
