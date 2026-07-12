"""Yar Kids standalone FastAPI API.

Mirrors the orchestration logic of the OpenWebUI ``Pipe`` in ``pipe.py`` but
exposes it as a standalone HTTP API. All the reusable helpers (intent
detection, textbook-query building, textbook-service retrieval, prompt
building, reflection, ...) are imported directly from ``pipe`` so the logic
stays in a single source of truth. Only the OpenWebUI-specific bits (the
``OpenWebUILLMClient`` and the ``Pipe`` class) are replaced.

Run from the repo root::

    uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.5.0"
