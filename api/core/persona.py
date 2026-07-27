"""Persona resolution: manual override, history, confirmation, intent fallback."""

from __future__ import annotations

import re
from typing import Any

from .constants import (
    ACTIVE_PERSONA_METADATA_KEY,
    ACTIVE_TEXTBOOK_SCOPE_METADATA_KEY,
    MANUAL_PERSONA_METADATA_KEY,
    PENDING_PERSONA_METADATA_KEY,
    PersonaId,
    SUPPORTED_PERSONAS,
)
from .messages import (
    _detect_menu_persona_pick,
    _get_latest_user_message,
    _last_assistant_is_welcome,
    _looks_like_greeting_only,
    _looks_like_welcome_or_menu,
    _normalize_persona,
    append_persona_marker,
    extract_persona_marker,
    strip_persona_markers,
)
from .types import ChatMessage, LLMClient, PersonaResolution


async def _detect_intent_via_llm(*args: Any, **kwargs: Any):
    """Lazy wrapper to avoid import cycle with intent ↔ persona."""
    from .intent import detect_intent

    return await detect_intent(*args, **kwargs)

_ACTIVITY_PATTERNS: dict[PersonaId, tuple[str, ...]] = {
    "gamer": (
        "بازی کلمات",
        "کلمه‌های زنجیره‌ای",
        "کلمه های زنجیره",
        "زنجیره",
        "آخرین حرف",
        "حرف آخر",
        "کلمه بگو",
        "کلمه اول",
        "نوبت تو",
        "نوبت توئه",
        "نوبت من",
        "چیستان",
        "معما",
        "حدس بزن",
        "بازی کنیم",
        "بریم بازی",
        "شروع می‌کنم",
        "با «",
        "با \"",
    ),
    "storyteller": (
        "ادامه بده",
        "بعدش چی شد",
        "سپس",
        "و بعد",
        "داستان را ادامه",
        "شخصیت داستان",
        "ماجرا ادامه",
        "داستان بگو",
        "قصه بگو",
        "می‌خوام داستان",
    ),
    "teacher": (
        "مثال دیگر",
        "مثال دیگه",
        "مشکل مشابه",
        "بخش دیگر",
        "قدم بعد",
        "مرحله بعد",
        "نمی‌فهمم",
        "معلوم نشد",
        "دوباره توضیح",
        "یعنی چی",
        "توضیح بده",
    ),
    "homework": (
        "سوال بعد",
        "تمرین بعد",
        "بخش ب",
        "قسمتی دیگر",
        "جوابش چیه",
        "مرحله بعد",
        "چطور حل",
        "مراحل",
        "این مسئله",
        "حل کن",
    ),
    "creative": (
        "ایده دیگر",
        "ایده دیگه",
        "پیشنهاد دیگر",
        "چیزی دیگر",
        "نوع دیگر",
        "راه دیگر",
        "ایده بده",
        "حوصله",
    ),
}

_ACTIVITY_CONTINUATION: dict[PersonaId, tuple[str, ...]] = {
    "gamer": ("نوبت من", "ادامه", "یکی دیگه", "چیستان دیگه", "معما دیگه"),
    "storyteller": (
        "ادامه بده",
        "بعدش",
        "بعدش چی شد",
        "و بعد",
        "ادامه داستان",
        "بعدی",
    ),
    "teacher": ("مثال دیگر", "مثال دیگه", "دوباره توضیح", "قدم بعد", "مرحله بعد"),
    "homework": ("سوال بعد", "تمرین بعد", "بعدی", "مرحله بعد", "یکی دیگه"),
    "creative": ("ایده دیگر", "ایده دیگه", "پیشنهاد دیگر", "چیزی دیگر", "یکی دیگه"),
}

_ACTIVITY_DISPLAY_NAMES: dict[PersonaId, str] = {
    "gamer": "بازی کلمات/چیستان",
    "storyteller": "قصه‌گویی تعاملی",
    "teacher": "آموزش مفهومی",
    "homework": "حل تمرین قدم‌به‌قدم",
    "creative": "ایده‌پردازی خلاقانه",
}

PERSONA_FA_LABELS: dict[PersonaId, str] = {
    "creative": "خلاق",
    "storyteller": "داستان‌گو",
    "teacher": "معلم",
    "homework": "کمک‌درس",
    "gamer": "بازی و سرگرمی",
    "none": "یار کودک",
}

# Within these pairs, persona may switch immediately (no confirmation).
# Any switch outside a pair requires an explicit high-confidence ask + confirmation.
SOFT_PERSONA_SWITCH_PAIRS: frozenset[frozenset[str]] = frozenset(
    {
        frozenset({"creative", "storyteller"}),
        frozenset({"teacher", "homework"}),
    }
)


def _is_soft_persona_switch(current: PersonaId, desired: PersonaId) -> bool:
    """True when current→desired is an allowed easy sibling switch."""
    if current == desired:
        return True
    if current == "none" or desired == "none":
        return False
    return frozenset({current, desired}) in SOFT_PERSONA_SWITCH_PAIRS


_CONFIRM_YES_RE = re.compile(
    r"^(?:بله|آره|باشه|موافقم|باشه برو|بله برو|آره برو|باشه عوض کن|بله عوض کن)"
    r"(?:\s|$|[!.،,])",
    re.IGNORECASE,
)
_CONFIRM_NO_RE = re.compile(
    r"^(?:نه|نخیر|نه همین|نه همون|نمی‌خوام|نمیخوام|ادامه بده|همین‌جا|همینجا)"
    r"(?:\s|$|[!.،,])",
    re.IGNORECASE,
)


def _is_activity_continuation(text: str, persona: PersonaId) -> bool:
    """True when the latest user message continues the current activity."""
    cleaned = text.strip()
    if not cleaned:
        return False
    for phrase in _ACTIVITY_CONTINUATION.get(persona, ()):
        if cleaned == phrase or cleaned.startswith(phrase):
            return True
    return False


_WORD_CHAIN_SIGNALS = (
    "زنجیره",
    "نوبت تو",
    "نوبت توئه",
    "کلمه بگو",
    "با حرف",
    "حرف «",
    'حرف "',
    "آخرین حرف",
    "حرف آخر",
    "کلمه اول",
    "کلمه‌های زنجیر",
    "کلمه های زنجیر",
    "بازی کلمات",
    "بازی کلمه‌",
)


def _is_persona_switch_confirmation(content: str) -> bool:
    """True when the assistant message is asking to confirm a persona switch."""
    if "بریم سراغ «" in content:
        return True
    # Older copy used bare «مطمئنی؟»; current copy says «مطمئنی این کار رو بکنیم؟».
    if "مطمئنی؟" in content or "مطمئنی این" in content:
        return True
    return False


def _looks_like_word_chain_awaiting_answer(messages: list[ChatMessage]) -> bool:
    """True when the latest assistant turn is waiting for a word-chain reply."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        content = message.content
        if _is_persona_switch_confirmation(content):
            continue
        return any(signal in content for signal in _WORD_CHAIN_SIGNALS)
    return False


def _looks_like_hard_switch_request(text: str) -> bool:
    """True only for clear persona-switch intent (not a single keyword)."""
    if _detect_explicit_persona_request(text):
        return True
    lowered = text.strip().lower()
    switch_phrases = (
        "بریم سراغ",
        "حالم عوض",
        "حالت عوض",
        "دیگه بازی نه",
        "دیگه قصه نه",
        "می‌خوام داستان بشنوم",
        "میخوام داستان بشنوم",
        "می‌خوام قصه",
        "میخوام قصه",
        "بریم درس",
        "بریم بازی",
        "دیگه درس",
    )
    return any(phrase in lowered for phrase in switch_phrases)


def _should_keep_current_persona(
    text: str,
    persona: PersonaId,
    messages: list[ChatMessage],
) -> bool:
    """Sticky rule: keep persona unless a hard switch is clearly requested."""
    if not text.strip():
        return True
    if _looks_like_hard_switch_request(text):
        return False
    # Concrete textbook page/lesson asks must leave sticky gamer/creative/etc.
    # so teacher/homework can retrieve the real page (avoid invented homework).
    from .textbook import looks_like_textbook_session_switch

    if looks_like_textbook_session_switch(text) and persona not in {"teacher", "homework"}:
        return False
    if _is_activity_continuation(text, persona):
        return True
    # Word-chain answers like «داستان» must stay on gamer.
    cleaned = text.strip()
    if (
        persona == "gamer"
        and len(cleaned) <= 40
        and "?" not in cleaned
        and "؟" not in cleaned
        and _looks_like_word_chain_awaiting_answer(messages)
    ):
        return True
    if _detect_ongoing_activity(messages, persona):
        # Mid-session message without hard switch → stay.
        return True
    # Even without explicit activity markers, short replies stay sticky
    # when history already confirms the same persona (not the welcome menu).
    if len(cleaned) <= 40 and "?" not in cleaned and "؟" not in cleaned:
        if extract_persona_marker(
            next((m.content for m in reversed(messages) if m.role == "assistant"), "")
        ) == persona:
            return True
    return False

def _detect_ongoing_activity(
    messages: list[ChatMessage], current_persona: PersonaId | None
) -> str | None:
    """Check if user is in the middle of an activity with the current persona."""
    if not current_persona or current_persona == "none":
        return None

    patterns = _ACTIVITY_PATTERNS.get(current_persona, ())
    if not patterns:
        return None

    window = messages[-12:]
    if not window:
        return None

    prior = window[:-1] if len(window) >= 2 else window
    for message in prior:
        if any(pattern in message.content for pattern in patterns):
            return _ACTIVITY_DISPLAY_NAMES.get(current_persona, current_persona)

    latest = window[-1].content if window else ""
    if _is_activity_continuation(latest, current_persona):
        if _infer_persona_from_history(messages) == current_persona or any(
            pattern in message.content
            for message in prior
            for pattern in patterns
        ):
            return _ACTIVITY_DISPLAY_NAMES.get(current_persona, current_persona)
    return None


def _format_recent_messages(messages: list[ChatMessage], max_turns: int = 6) -> list[dict[str, str]]:
    """Format recent conversation for intent detection context."""
    formatted = []
    for m in messages[-max_turns:]:
        if m.role != "system":
            content = (
                strip_persona_markers(m.content)
                if m.role == "assistant"
                else m.content
            )
            formatted.append({"role": m.role, "content": content})
    return formatted


_EXPLICIT_PERSONA_TRIGGERS: dict[str, tuple[str, ...]] = {
    "creative": (
        "خلاق باش",
        "باش خلاق",
        "خلاق شو",
        "حالت خلاق",
        "شخصیت خلاق",
        "mode creative",
    ),
    "storyteller": (
        "داستان بگو",
        "قصه بگو",
        "داستان‌گو باش",
        "داستان گو باش",
        "قصه‌گو باش",
        "قصه گو باش",
        "باش داستان‌گو",
        "باش داستان گو",
        "باش قصه‌گو",
        "باش قصه گو",
        "حالت داستان",
        "شخصیت داستان",
        "mode storyteller",
    ),
    "teacher": (
        "معلم باش",
        "باش معلم",
        "حالت معلم",
        "شخصیت معلم",
        "mode teacher",
    ),
    "homework": (
        "کمک درس باش",
        "کمک‌درس باش",
        "باش کمک درس",
        "باش کمک‌درس",
        "حالت کمک درس",
        "شخصیت کمک درس",
        "mode homework",
    ),
    "gamer": (
        "بازی باش",
        "بازی کن",
        "بازی کنیم",
        "بریم بازی",
        "باش بازی",
        "باش گیمر",
        "گیمر باش",
        "حالت بازی",
        "شخصیت بازی",
        "mode gamer",
    ),
}


def _infer_persona_from_history(messages: list[ChatMessage]) -> PersonaId | None:
    """Infer the current persona from recent assistant responses."""
    assistant_msgs = [m.content for m in messages[-8:] if m.role == "assistant"]
    if not assistant_msgs:
        return None

    # Prefer explicit sticky markers written into prior replies (legacy only).
    for content in reversed(assistant_msgs):
        if _looks_like_welcome_or_menu(content):
            continue
        marked = extract_persona_marker(content)
        if marked:
            return marked

    # Strong mid-activity signals only — never match the welcome menu.
    PERSONA_RESPONSE_PATTERNS: dict[PersonaId, tuple[str, ...]] = {
        "gamer": (
            "نوبت تو",
            "نوبت توئه",
            "کلمه بگو",
            "کلمه اول",
            "زنجیره",
            "بازی کلمات",
            "کلمه‌های زنجیره‌ای",
            "با حرف",
            "حدس بزن",
            "نوبت من",
            "حرف آخر",
            "شروع می‌کنم",
        ),
        "storyteller": (
            "داستان کامل",
            "داستان مشترک",
            "با هم داستان",
            "اول ماجرا",
            "دنیای خیال",
            "ادامه داستان",
            "شخصیت داستان",
            "حالت داستان‌گو",
            "حالت داستان گو",
        ),
        "teacher": (
            "به زبان ساده",
            "قدم اول",
            "قدم بعد",
            "درک کردی",
            "توضیح دهم",
            "حالت معلم",
        ),
        "homework": (
            "حل کنیم",
            "مرحله بعد",
            "سوال بعد",
            "حالت کمک‌درس",
            "حالت کمک درس",
        ),
        "creative": (
            "ایده دیگر",
            "ایده دیگه",
            "حالت خلاق",
            "بیا بسازیم",
        ),
    }

    for content in reversed(assistant_msgs):
        if _is_persona_switch_confirmation(content):
            continue
        if _looks_like_welcome_or_menu(content):
            continue
        lowered = content.lower()
        for persona, patterns in PERSONA_RESPONSE_PATTERNS.items():
            if any(p in lowered for p in patterns):
                return persona
    return None


def _detect_explicit_persona_request(text: str) -> PersonaId | None:
    """Detect explicit persona switch; last matching trigger in the message wins."""
    lowered = text.strip().lower()
    matches: list[tuple[int, str]] = []
    for persona, triggers in _EXPLICIT_PERSONA_TRIGGERS.items():
        for trigger in triggers:
            start = 0
            needle = trigger.lower()
            while True:
                idx = lowered.find(needle, start)
                if idx < 0:
                    break
                matches.append((idx, persona))
                start = idx + max(len(needle), 1)
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[-1][1]  # type: ignore[return-value]


def _extract_pending_switch_from_history(
    messages: list[ChatMessage],
) -> PersonaId | None:
    """Read pending switch target from the last confirmation question."""
    for message in reversed(messages):
        if message.role != "assistant":
            continue
        content = message.content
        if not _is_persona_switch_confirmation(content):
            continue
        match = re.search(r"بریم سراغ «([^»]+)»", content)
        if not match:
            match = re.search(r"به «([^»]+)» عوض", content)
        if not match:
            return None
        label = match.group(1).strip()
        for persona_id, fa_label in PERSONA_FA_LABELS.items():
            if fa_label == label and persona_id != "none":
                return persona_id
        return None
    return None


def format_persona_switch_confirmation(
    current: PersonaId, pending: PersonaId
) -> str:
    """Ask the child before leaving the current persona (cross-family switches)."""
    current_label = PERSONA_FA_LABELS.get(current, current)
    pending_label = PERSONA_FA_LABELS.get(pending, pending)
    return (
        f"الان داریم با هم در حالت «{current_label}» کار می‌کنیم و می‌خوام همون‌جا بمونیم "
        f"مگر خودت واقعاً بخوای عوضش کنیم.\n\n"
        f"به نظر می‌رسه می‌خوای بریم سراغ «{pending_label}». "
        f"مطمئنی این کار رو بکنیم؟\n\n"
        f"اگر آره و مطمئنی، بگو «بله برو».\n"
        f"اگر نه، بگو «نه همین‌جا» تا همون حالت «{current_label}» رو ادامه بدیم."
    )



def resolve_manual_persona(
    *,
    user_persona: str | None = None,
    body: dict[str, Any] | None = None,
) -> PersonaId | None:
    """
    Resolve manually selected persona from chat UserValves or request metadata.

    OpenWebUI exposes UserValves in Chat Controls → Valves sidebar.
    When persona is "auto" or empty, returns None so intent detection runs.
    """
    manual = _normalize_persona(user_persona)
    if manual:
        return manual

    if not body:
        return None

    metadata = body.get("metadata") or {}
    if isinstance(metadata, dict):
        metadata_persona = metadata.get(MANUAL_PERSONA_METADATA_KEY)
        if isinstance(metadata_persona, str):
            manual = _normalize_persona(metadata_persona)
            if manual:
                return manual

    # Custom frontend (e.g. Yar UI): send persona directly on the request body.
    for key in ("yarkids_persona", "persona", "PERSONA"):
        direct = body.get(key)
        if isinstance(direct, str):
            manual = _normalize_persona(direct)
            if manual:
                return manual

    params = body.get("params") or {}
    if isinstance(params, dict):
        params_persona = params.get("PERSONA") or params.get("persona")
        if isinstance(params_persona, str):
            manual = _normalize_persona(params_persona)
            if manual:
                return manual

    return None


def get_user_persona_selection(__user__: dict[str, Any] | None) -> str | None:
    """Read persona from OpenWebUI UserValves (Chat Controls sidebar)."""
    if not __user__:
        return None

    valves = __user__.get("valves")
    if valves is None:
        return None

    persona = dict(valves).get("PERSONA")
    if isinstance(persona, str) and persona.strip():
        return persona.strip()

    return None


# ---------------------------------------------------------------------------

async def resolve_active_persona(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    user_persona: str | None = None,
    body: dict[str, Any] | None = None,
    on_detecting_status: Callable[[], Awaitable[None]] | None = None,
) -> PersonaResolution:
    """
    Resolve persona with sticky behaviour.

    - Manual UserValves persona wins immediately (no confirmation),
      except concrete textbook asks which need homework/teacher tools.
    - Auto-detected persona sticks across turns (via metadata/history).
    - Easy switches without confirmation only within sibling pairs:
      creative↔storyteller and teacher↔homework.
    - Any other persona change requires a clear signal + confirmation
      («بله برو» / «نه همین‌جا»), except the very first selection.
    - Mid-activity short answers (e.g. word-chain «داستان») never switch.
    """
    from .textbook import looks_like_textbook_session_switch, resolve_textbook_scope

    manual_persona = resolve_manual_persona(user_persona=user_persona, body=body)
    latest_user_msg = _get_latest_user_message(messages)

    sticky_scope: dict[str, Any] | None = None
    if body:
        metadata = body.get("metadata") or {}
        if isinstance(metadata, dict):
            raw_scope = metadata.get(ACTIVE_TEXTBOOK_SCOPE_METADATA_KEY)
            if isinstance(raw_scope, dict):
                sticky_scope = raw_scope

    def _textbook_force_persona() -> PersonaId | None:
        """Homework/teacher when the child clearly needs catalog/page tools."""
        if not latest_user_msg:
            return None
        # Soft confirms («بله برو») are persona switches, not textbook asks.
        if _CONFIRM_YES_RE.search(latest_user_msg.strip()) or _CONFIRM_NO_RE.search(
            latest_user_msg.strip()
        ):
            return None
        if re.search(r"برای\s*تدریس|طرح\s*درس|ایده\s*(?:ی\s*)?تدریس", latest_user_msg):
            return "teacher"
        if looks_like_textbook_session_switch(latest_user_msg):
            return "homework"
        # Clarifying follow-ups («خود کتاب فارسی») while list/unit scope is pending.
        from .textbook import (
            _extract_subject_token,
            latest_message_wants_textbook_retrieve,
        )

        scope = resolve_textbook_scope(messages, sticky=sticky_scope)
        # Only when a real book is already identified — bare topic_query like
        # «داستان» (word-chain) must NOT force homework.
        pending_book = (
            scope.has_outline_lookup()
            or scope.has_chapter_lookup()
            or scope.has_lesson_lookup()
            or scope.has_page_lookup()
            or (
                scope.grade is not None
                and scope.subject_id is not None
                and bool(scope.topic_query)
            )
        )
        if not pending_book:
            return None
        if latest_message_wants_textbook_retrieve(latest_user_msg):
            return "homework"
        # Clarifying book answers without a new locator.
        if re.search(
            r"خود\s*کتاب|همین\s*کتاب|کتاب\s*درسی|کتاب\s*اصلی",
            latest_user_msg,
        ):
            return "homework"
        if _extract_subject_token(latest_user_msg):
            return "homework"
        # Do NOT treat bare «بله/آره» as textbook — that blocks persona confirms.
        return None

    textbook_persona = _textbook_force_persona()

    # Manual Chat Controls persona wins — but never blocks real textbook work.
    if manual_persona:
        if textbook_persona and manual_persona not in {"teacher", "homework"}:
            return PersonaResolution(persona=textbook_persona)
        return PersonaResolution(persona=manual_persona)

    # Hard stay during word-chain even if sticky metadata/history was lost —
    # unless the child clearly asks for a textbook page/lesson.
    if (
        latest_user_msg
        and _looks_like_word_chain_awaiting_answer(messages)
        and not _looks_like_hard_switch_request(latest_user_msg)
        and not textbook_persona
    ):
        return PersonaResolution(persona="gamer")

    # Recover sticky persona (metadata → history).
    current_persona: PersonaId | None = None
    if body:
        metadata = body.get("metadata") or {}
        if isinstance(metadata, dict):
            prev_persona = metadata.get(ACTIVE_PERSONA_METADATA_KEY)
            if isinstance(prev_persona, str):
                normalized = _normalize_persona(prev_persona)
                if normalized:
                    current_persona = normalized
    if current_persona is None:
        current_persona = _infer_persona_from_history(messages)

    # Answer a pending switch confirmation BEFORE textbook force can sticky-keep
    # homework on a stale out-of-range page from earlier in the thread.
    pending = _extract_pending_switch_from_history(messages)
    if pending and latest_user_msg and current_persona and current_persona != "none":
        if _CONFIRM_YES_RE.search(latest_user_msg.strip()):
            return PersonaResolution(persona=pending)
        if _CONFIRM_NO_RE.search(latest_user_msg.strip()):
            return PersonaResolution(persona=current_persona)

    # «سلام» alone: stay on none until the child actually picks an activity.
    if (
        latest_user_msg
        and _looks_like_greeting_only(latest_user_msg)
        and (not current_persona or current_persona == "none")
    ):
        return PersonaResolution(persona="none")

    # Welcome-menu short picks («بازی»، «داستان»، …) are first selections, not switches.
    # Concrete textbook asks leave sticky play modes immediately (no confirmation).
    # Must run BEFORE menu-pick so «لیست درس‌های فارسی…» is never treated as a
    # vague welcome-menu choice that skips catalog tools.
    if textbook_persona and (
        not current_persona
        or current_persona == "none"
        or current_persona not in {"teacher", "homework"}
    ):
        return PersonaResolution(persona=textbook_persona)
    if textbook_persona and current_persona in {"teacher", "homework"}:
        # Stay on teacher if already there (unless explicit homework-only cue).
        if textbook_persona == "teacher":
            return PersonaResolution(persona="teacher")
        return PersonaResolution(persona=current_persona)

    menu_pick = (
        _detect_menu_persona_pick(latest_user_msg) if latest_user_msg else None
    )
    if menu_pick and (
        not current_persona
        or current_persona == "none"
        or _last_assistant_is_welcome(messages)
    ):
        return PersonaResolution(persona=menu_pick)

    # Sticky keep without calling the LLM when appropriate.
    if (
        current_persona
        and current_persona != "none"
        and latest_user_msg
        and _should_keep_current_persona(latest_user_msg, current_persona, messages)
    ):
        return PersonaResolution(persona=current_persona)

    if on_detecting_status:
        await on_detecting_status()

    intent = await _detect_intent_via_llm(
        llm_client,
        backend_model=backend_model,
        messages=messages,
        current_persona=current_persona,
    )
    desired = intent.persona
    confidence = intent.confidence if intent.confidence is not None else 0.0
    explicit = (
        _detect_explicit_persona_request(latest_user_msg) if latest_user_msg else None
    )

    # First selection (no sticky yet): accept immediately.
    if not current_persona or current_persona == "none":
        # Prefer textbook tools over creative/storyteller guesses for book asks.
        if textbook_persona:
            return PersonaResolution(persona=textbook_persona)
        return PersonaResolution(persona=desired if desired != "none" else "none")

    # Same persona or none → stay.
    if desired in (None, "none", current_persona):
        return PersonaResolution(persona=current_persona)

    # Sibling pairs may switch freely (creative↔storyteller, teacher↔homework).
    if _is_soft_persona_switch(current_persona, desired):
        return PersonaResolution(persona=desired)

    # Cross-family: only offer a confirmation when the child was explicit
    # or intent is very confident — otherwise stay put (don't thrash).
    strong_cross_family = explicit == desired or confidence >= 0.9
    if not strong_cross_family:
        return PersonaResolution(persona=current_persona)

    return PersonaResolution(
        persona=current_persona,
        pending_switch_to=desired,
        ask_confirmation=True,
    )
