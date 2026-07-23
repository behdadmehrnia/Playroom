"""Load markdown prompts from api/prompts/."""

from __future__ import annotations

from .constants import PROMPTS_DIR, PersonaId, SUPPORTED_PERSONAS

_prompt_cache: dict[str, str] = {}


def _load_prompt(relative_path: str) -> str:
    """Load and cache a markdown prompt file from the prompts directory."""
    if relative_path in _prompt_cache:
        return _prompt_cache[relative_path]

    path = PROMPTS_DIR / relative_path
    text = path.read_text(encoding="utf-8").strip()
    _prompt_cache[relative_path] = text
    return text


def get_core_prompt() -> str:
    return _load_prompt("core.md")


def get_persona_prompt(persona: PersonaId) -> str | None:
    if persona == "none":
        return None
    if persona not in SUPPORTED_PERSONAS:
        return None
    return _load_prompt(f"personas/{persona}.md")


def get_intent_detection_prompt() -> str:
    return _load_prompt("intent_detection.md")


def get_reflection_prompt() -> str:
    template = _load_prompt("reflection.md")
    return template.replace("{{CORE_PROMPT}}", get_core_prompt())


def get_chat_title_prompt() -> str:
    return _load_prompt("chat_title.md")
