"""Persian child-friendly chat title generation for OpenWebUI / pipe."""

from __future__ import annotations

import re
from .messages import _looks_like_greeting_only, _looks_like_welcome_or_menu
from .prompts import get_chat_title_prompt
from .types import ChatMessage, LLMClient, LLMCompletionRequest

PLACEHOLDER_CHAT_TITLE = "گفتگوی تازه"
CHAT_TITLE_METADATA_KEY = "yarkids_chat_title"
DEFAULT_MIN_USER_MESSAGES_FOR_TITLE = 2

_TITLE_GEN_MARKERS: tuple[str, ...] = (
    "generate a concise",
    "generate a title",
    "create a title",
    "chat title",
    "summarizing the chat",
    "3-5 word title",
    "3-5 words",
    "title with an emoji",
    "عنوان گفتگو",
    "عنوان کوتاه",
)

_GENERIC_TITLE_RE = re.compile(
    r"(?ix)^"
    r"(?:👋|✨|🌟|😊)?\s*"
    r"(?:"
    r"introduction\s+to\b.*|"
    r"new\s+chat|"
    r"chat\b|"
    r"yar[\s\-]*(?:e[\s\-]*)?koodak\b.*|"
    r"یار[\s\-]*کودک|"
    r"گفتگوی?\s*تازه|"
    r"سلام(?:\s+و\s+احوالپرسی)?|"
    r"خوش[\s\-]*آمد(?:ید|ی)?"
    r")"
    r".*$"
)

_MAX_TITLE_CHARS = 48


def looks_like_title_generation_request(messages: list[ChatMessage]) -> bool:
    """True when OpenWebUI (or similar) asks the model to name the chat."""
    blob = "\n".join(m.content for m in messages if m.content).lower()
    if not blob.strip():
        return False
    hits = sum(1 for marker in _TITLE_GEN_MARKERS if marker in blob)
    return hits >= 1 and (
        "title" in blob
        or "عنوان" in blob
        or "emoji" in blob
        or "summar" in blob
    )


def is_generic_chat_title(title: str | None) -> bool:
    if not title or not title.strip():
        return True
    cleaned = title.strip()
    if cleaned == PLACEHOLDER_CHAT_TITLE:
        return True
    return bool(_GENERIC_TITLE_RE.match(cleaned))


_CHAT_HISTORY_SPLIT_RE = re.compile(
    r"(?:###\s*)?Chat History\s*:?\s*",
    re.IGNORECASE,
)
_HISTORY_TURN_RE = re.compile(
    r"^(?:User|Assistant|Human|AI|کودک|یار کودک)\s*:\s*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)


def _parse_embedded_chat_history(text: str) -> list[ChatMessage]:
    """Parse OpenWebUI title-task blob that embeds history in one message."""
    parts = _CHAT_HISTORY_SPLIT_RE.split(text, maxsplit=1)
    if len(parts) < 2:
        return []
    history = parts[1].strip()
    if not history:
        return []

    messages: list[ChatMessage] = []
    current_role: str | None = None
    current_bits: list[str] = []

    def _flush() -> None:
        nonlocal current_role, current_bits
        if current_role and current_bits:
            content = "\n".join(current_bits).strip()
            if content:
                messages.append(ChatMessage(role=current_role, content=content))
        current_role = None
        current_bits = []

    for line in history.splitlines():
        match = re.match(
            r"^(User|Assistant|Human|AI|کودک|یار کودک)\s*:\s*(.*)$",
            line.strip(),
            flags=re.IGNORECASE,
        )
        if match:
            _flush()
            label = match.group(1).lower()
            current_role = (
                "assistant"
                if label in {"assistant", "ai", "یار کودک"}
                else "user"
            )
            rest = match.group(2).strip()
            current_bits = [rest] if rest else []
        elif current_role is not None:
            current_bits.append(line)
    _flush()
    return messages


def extract_conversation_for_title(messages: list[ChatMessage]) -> list[ChatMessage]:
    """Drop title-task prompts; keep real chat turns (incl. embedded OWUI history)."""
    kept: list[ChatMessage] = []
    for message in messages:
        text = (message.content or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in _TITLE_GEN_MARKERS) or (
            message.role == "system" and ("title" in lowered or "عنوان" in text)
        ):
            embedded = _parse_embedded_chat_history(text)
            if embedded:
                kept.extend(embedded)
            continue
        kept.append(message)
    return kept


def count_user_messages(messages: list[ChatMessage]) -> int:
    return sum(
        1
        for m in messages
        if m.role == "user" and (m.content or "").strip()
    )


def conversation_ready_for_title(
    messages: list[ChatMessage],
    *,
    min_user_messages: int = DEFAULT_MIN_USER_MESSAGES_FOR_TITLE,
) -> bool:
    """Require a bit of real context — not just the first سلام."""
    convo = extract_conversation_for_title(messages)
    users = [
        m.content.strip()
        for m in convo
        if m.role == "user" and m.content.strip()
    ]
    if not users:
        return False
    if len(users) >= min_user_messages:
        return True
    # Single substantive ask (homework / story / game) is enough.
    if len(users) == 1 and not _looks_like_greeting_only(users[0]):
        return len(users[0]) >= 12
    return False


def sanitize_chat_title(raw: str) -> str:
    text = (raw or "").strip()
    text = text.strip("«»\"'`").strip()
    text = re.sub(r"\s+", " ", text)
    # Model sometimes returns "Title: …"
    text = re.sub(r"^(?:عنوان|title)\s*[:：\-]\s*", "", text, flags=re.I)
    text = text.strip("«»\"'`").strip()
    if "\n" in text:
        text = text.split("\n", 1)[0].strip()
    if len(text) > _MAX_TITLE_CHARS:
        text = text[:_MAX_TITLE_CHARS].rstrip(" ،,")
    return text or PLACEHOLDER_CHAT_TITLE


def format_title_conversation(messages: list[ChatMessage], *, limit: int = 8) -> str:
    lines: list[str] = []
    for message in messages[-limit:]:
        if message.role == "assistant" and _looks_like_welcome_or_menu(message.content):
            role = "یار کودک"
            content = "(خوش‌آمدگویی کوتاه)"
        elif message.role == "user":
            role = "کودک"
            content = message.content.strip()
        elif message.role == "assistant":
            role = "یار کودک"
            content = message.content.strip()
            if len(content) > 180:
                content = content[:180] + "…"
        else:
            continue
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


async def generate_chat_title(
    llm_client: LLMClient,
    *,
    backend_model: str,
    messages: list[ChatMessage],
    min_user_messages: int = DEFAULT_MIN_USER_MESSAGES_FOR_TITLE,
) -> str:
    """Return a Persian child-friendly title, or a placeholder if too early."""
    convo = extract_conversation_for_title(messages)
    if not conversation_ready_for_title(convo, min_user_messages=min_user_messages):
        return PLACEHOLDER_CHAT_TITLE

    transcript = format_title_conversation(convo)
    if not transcript.strip():
        return PLACEHOLDER_CHAT_TITLE

    prompt = get_chat_title_prompt()
    request = LLMCompletionRequest(
        model=backend_model,
        messages=[
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "بر اساس این گفتگو فقط یک عنوان فارسی کودکانه بنویس:\n\n"
                    f"{transcript}"
                ),
            },
        ],
        temperature=0.4,
    )
    try:
        raw = await llm_client.complete(request)
    except Exception:  # noqa: BLE001 — title must never break chat
        return PLACEHOLDER_CHAT_TITLE
    title = sanitize_chat_title(raw)
    if is_generic_chat_title(title) and conversation_ready_for_title(
        convo, min_user_messages=min_user_messages
    ):
        # Avoid English/generic leftovers from a confused model.
        if any(ord(ch) > 127 for ch in title):
            return title
        return PLACEHOLDER_CHAT_TITLE
    return title


def should_emit_chat_title(
    messages: list[ChatMessage],
    *,
    current_title: str | None,
    min_user_messages: int = DEFAULT_MIN_USER_MESSAGES_FOR_TITLE,
) -> bool:
    """Emit/overwrite when we have context and the current title is still generic."""
    if not conversation_ready_for_title(
        messages, min_user_messages=min_user_messages
    ):
        return False
    return is_generic_chat_title(current_title)
