"""Intent detection via LLM (and lightweight local shortcuts)."""

from __future__ import annotations

from typing import Any

from .constants import INTENT_CONFIDENCE_THRESHOLD, PersonaId, VALID_PERSONAS
from .messages import _extract_json_object, _get_latest_user_message, _looks_like_greeting_only
from .prompts import get_intent_detection_prompt
from .types import ChatMessage, IntentDetectionResult, LLMClient, LLMCompletionRequest

def parse_intent_detection_output(raw_output: str) -> IntentDetectionResult:
    payload = _extract_json_object(raw_output)
    if not payload:
        return IntentDetectionResult(persona="none")

    persona_raw = str(payload.get("persona", "none")).strip().lower()
    if persona_raw not in VALID_PERSONAS:
        return IntentDetectionResult(persona="none")

    persona: PersonaId = persona_raw  # type: ignore[assignment]
    if persona == "none":
        return IntentDetectionResult(persona="none")

    confidence_raw = payload.get("confidence")
    if confidence_raw is None:
        return IntentDetectionResult(persona="none")

    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        return IntentDetectionResult(persona="none")

    if confidence < INTENT_CONFIDENCE_THRESHOLD:
        return IntentDetectionResult(persona="none")

    return IntentDetectionResult(persona=persona, confidence=confidence)


async def detect_intent(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    current_persona: PersonaId | None = None,
) -> IntentDetectionResult:
    user_text = _get_latest_user_message(messages)
    if not user_text:
        return IntentDetectionResult(persona="none")

    # Bare greetings must not lock a persona (e.g. "hi" -> none).
    if _looks_like_greeting_only(user_text):
        return IntentDetectionResult(persona="none")

    from .persona import (
        _detect_explicit_persona_request,
        _detect_ongoing_activity,
        _format_recent_messages,
        _should_keep_current_persona,
    )

    explicit = _detect_explicit_persona_request(user_text)
    if explicit:
        return IntentDetectionResult(persona=explicit, confidence=0.98)

    # Hard stick: during an active persona session, short/continuation turns
    # must NOT go to the LLM (e.g. a word-chain answer that happens to be "story").
    if (
        current_persona
        and current_persona != "none"
        and _should_keep_current_persona(user_text, current_persona, messages)
    ):
        return IntentDetectionResult(persona=current_persona, confidence=0.97)

    activity = _detect_ongoing_activity(messages, current_persona)
    system_prompt = get_intent_detection_prompt()
    if current_persona and current_persona != "none":
        system_prompt += (
            f"\n\n⚠️ Persona stickiness: the user is currently in {current_persona} mode"
            + (f", activity: {activity}" if activity else "")
            + ".\n"
            "Keep this mode by default unless the change request is genuinely explicit.\n"
            "A soft switch is allowed only between these pairs:\n"
            "- creative ↔ storyteller\n"
            "- teacher ↔ homework\n"
            "For any other change (e.g. gamer<->teacher or creative<->homework), return the new "
            "persona only on a very explicit, decisive request; otherwise keep "
            f"{current_persona}.\n"
            "A single word like 'story' / 'game' / 'teacher' mid-activity is not a change request.\n"
            "'keep going', 'next question', 'another example', 'another idea' mean staying in the same persona."
        )

    history = _format_recent_messages(messages, max_turns=6)
    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": system_prompt},
            *history,
        ],
    )
    return parse_intent_detection_output(await llm_client.complete(request))
