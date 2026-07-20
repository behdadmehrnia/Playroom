"""OpenWebUI Pipe packaging for Yar Kids.

Preferred entry point for OpenWebUI:
    ``api/pipe/pipe.py`` — thin client that delegates to the standalone API.

Deprecated (local full logic; do not use in new deployments):
    ``api/pipe/pipe_logic.py`` — generate a single-file artifact with
    ``python api/pipe/generate-logic-pipe.py`` if you still need it.
"""

from __future__ import annotations

__all__: list[str] = []
