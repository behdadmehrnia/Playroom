"""Shared constants, persona sets, and prompt/instruction strings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

MODEL_ID = "playroom"
MODEL_NAME = "Playroom"
MAX_GENERATION_ATTEMPTS = 3
INTENT_CONFIDENCE_THRESHOLD = 0.7
MANUAL_PERSONA_METADATA_KEY = "playroom_persona"
ACTIVE_PERSONA_METADATA_KEY = "playroom_active_persona"
PENDING_PERSONA_METADATA_KEY = "playroom_pending_persona"
ACTIVE_TEXTBOOK_SCOPE_METADATA_KEY = "playroom_textbook_scope"
# Legacy HTML marker (may still appear in older chat history).
_PERSONA_MARKER_RE = re.compile(r"<!--\s*playroom:([a-z_]+)\s*-->", re.IGNORECASE)
# Invisible sticky marker in assistant content (kept in history, stripped for LLM).
# Digits are encoded with ZWSP / ZWNJ / ZWJ. Fence avoids U+2060 (Word Joiner),
# which some clients render as tofu boxes.
_ZW_DIGIT = {"0": "\u200b", "1": "\u200c", "2": "\u200d"}
_ZW_DIGIT_INV = {v: k for k, v in _ZW_DIGIT.items()}
_ZW_FENCE = "\u200b\u200d\u200c\u200b"  # ZWSP + ZWJ + ZWNJ + ZWSP
_PERSONA_ZW_CODE: dict[str, str] = {
    "creative": "00",
    "storyteller": "01",
    "teacher": "02",
    "homework": "10",
    "gamer": "11",
}
_ZW_CODE_PERSONA: dict[str, str] = {v: k for k, v in _PERSONA_ZW_CODE.items()}
_ZW_DIGIT_CLASS = f"{_ZW_DIGIT['0']}{_ZW_DIGIT['1']}{_ZW_DIGIT['2']}"
_ZW_PERSONA_MARKER_RE = re.compile(
    re.escape(_ZW_FENCE) + f"([{_ZW_DIGIT_CLASS}]{{2}})" + re.escape(_ZW_FENCE)
)
# Older replies used Word Joiner as the fence.
_ZW_LEGACY_MARK = "\u2060"
_ZW_LEGACY_PERSONA_MARKER_RE = re.compile(
    f"{_ZW_LEGACY_MARK}([{_ZW_DIGIT_CLASS}]{{2}}){_ZW_LEGACY_MARK}"
)
PERSONA_AUTO_VALUE = "auto"
SUPPORTED_PERSONAS = ("creative", "storyteller", "teacher", "homework", "gamer")
REVISION_INSTRUCTION_HEADER = "A revision is needed. The previous reply was not suitable. Reasons:"
TEXTBOOK_CONTEXT_HEADER = (
    "Retrieved textbook text (supporting reference — the page image is the primary "
    "source; do not give the final answer without teaching the method):"
)
TEXTBOOK_CONTEXT_INSTRUCTION = (
    "Important: the textbook page was found and follows below. "
    "**The primary source of truth is the page image** (if one is attached). "
    "The OCR text below is only an aid and is often wrong or incomplete — "
    "to read an exercise, poem, table, figure, or question wording, **read the image first**; "
    "fall back to the OCR text only when the image is unclear, and if they conflict, trust the image. "
    "Do not add anything of your own to the page, and do not guess. "
    "**You have this exact page right now.** "
    "Start helping directly and kindly. "
    "If the child asked for comprehension / exercises / the page's questions: "
    "1) say in one sentence what this page is about (from the image; from OCR if there is none), "
    "2) go straight to the first question or exercise and give a first-step hint. "
    "**Forbidden:** asking 'have you read the text?'; 'shall we review first or go to the questions?'; "
    "saying 'I'll open the page / hold on a moment'. "
    "If the child asks you to write out the text or mark the hard words, use the image (or OCR if there is none). "
    "If several pages of one lesson or section are present, use all of the pages and images for "
    "'the whole lesson / the rest of the lesson / the lesson's hard words / the chapter's exercises', "
    "and don't ask the child to turn to the next page themselves. "
    "If the 'book structure / list of chapters, sections, lessons, or skills' is in the text, "
    "**read that official list out to the child** and use only its own labels "
    "(chapter/section/lesson/session/skill/project); "
    "do not invent a structure or a unit number that isn't in the list. "
    "**Forbidden:** saying 'I don't have the list / the books may have changed' when the list is in the prompt. "
    "But if the child asked about a specific page number, or asked 'what is this page / what's on it', "
    "describe **only that page number** and do not attribute neighbouring pages' text to it. "
    "Forbidden: asking again for grade/book/page; "
    "asking them to 'write one line from the page' when you have the page image or text; "
    "writing parentheses or notes about the system/prompt/context; "
    "acting as if the page hasn't arrived yet. "
    "If a page image is attached, call it 'the page' — not an image the child sent "
    "(unless an image genuinely appears in the user's history)."
)
TEXTBOOK_MATCHED_ACTION_HEADER = (
    "## Immediate instruction — the page is here now\n"
    "The child asked for a specific page or exercise and the page is in this prompt.\n"
    "- Start helping **in this message**; don't perform 'opening the page'.\n"
    "- **Read the page image first** (if present); OCR is only a backup.\n"
    "- For comprehension or exercises: a one-line summary + the first practical hint.\n"
    "- Don't ask meta questions like 'have you read it? / review first or questions?'.\n"
    "- Don't give the final answers to every question at once; help step by step."
)
TEXTBOOK_OUTLINE_INSTRUCTION = (
    "Important: the child asked for the **table of contents / list of lessons, chapters, or skills**, "
    "and the book's official outline from the catalog follows.\n"
    "**Read that outline out to the child in this message** (unit numbers and titles).\n"
    "Use only the outline's own labels (chapter/section/lesson/session/skill/project).\n"
    "**Forbidden:** saying 'I don't have the list / it's not in front of me / the books change'; "
    "asking for a page or a photo in order to give the contents; "
    "inventing 'part one / part two' or any fabricated structure; "
    "asking again for the grade or book name when they're already in the outline.\n"
    "End with a short question about which chapter or lesson to work on together."
)
TEXTBOOK_OUTLINE_ACTION_HEADER = (
    "## Immediate instruction — the book outline is here now\n"
    "The child asked for a lesson/chapter list and the official outline is in this prompt.\n"
    "- Read the outline **in this message**; don't ask for a page or a photo.\n"
    "- Don't ask for the grade or book again.\n"
    "- Don't say 'part one/two' or any fabricated structure.\n"
    "- After the outline, one short question: which lesson or chapter?"
)
TEXTBOOK_IMAGE_ONLY_INSTRUCTION = (
    "Important: this page's OCR text is unreliable or unreadable, "
    "but the page image is attached. "
    "Read the page's content solely from the **attached image** and help the child. "
    "Do not rely on the OCR text below, and do not guess the page's content. "
    "This image is a reference attachment from the book database, not an image the user sent; "
    "so never say 'the image you sent' unless the user genuinely sent one. "
    "Don't talk about the system or about sending images; help directly from the page. "
    "**Forbidden:** saying 'the books may have changed', or asking for a line from the page when you have its image."
)
TEXTBOOK_MISSING_IMAGE_INSTRUCTION = (
    "Important: the requested page was found in the database, but **the page image isn't available right now** "
    "and the OCR text is often unreliable too. "
    "Under no circumstances guess or fabricate a poem, exercise, table, or the exact wording of a question from partial OCR. "
    "**Never say 'I don't have access to your book', and don't talk about the system.** "
    "Kindly and briefly say that to look at exactly that page together, "
    "they could send **a clear photo of that page** "
    "(or type out the question they want to solve). "
    "If a general method is possible without the exact question wording, give that briefly — don't fabricate the page."
)
TEXTBOOK_UNREADABLE_INSTRUCTION = (
    "Important: the requested page was found, but its OCR text is unreadable "
    "and no image is available to show. "
    "Under no circumstances invent or guess the page's content, poem, text, or exercises. "
    "Honestly and kindly tell the child you couldn't see this page properly right now, "
    "and ask them to send a photo of that page or type out the question if they can. "
    "Don't talk about the system or the prompt."
)
TEXTBOOK_LOOKUP_FAILED_INSTRUCTION = (
    "Important: the child asked for a specific page or lesson, but its text isn't in the prompt "
    "(not found, or the service was unavailable). "
    "Under no circumstances invent or guess that page's or lesson's content "
    "(not even the lesson's name or topic). "
    "**Never say 'I don't have access to your book', and never talk about the system/prompt/waiting for a page to open.** "
    "Kindly and briefly say you couldn't find that page of the book. "
    "Then ask them to send a photo of that page, or type out the question they want to solve. "
    "If they haven't yet given the page number / grade / book name, ask only for the missing one first. "
    "Never pretend to see text or an image you don't have."
)
TEXTBOOK_PAGE_OUT_OF_RANGE_INSTRUCTION = (
    "Important: the child asked for a page number that doesn't exist in this textbook "
    "(outside the printed page range of that book in the database). "
    "Under no circumstances invent or guess that page's content. "
    "**Never say 'I don't have access to your book', and don't talk about the system/prompt.** "
    "Kindly and briefly say this book doesn't have that page number "
    "(if the maximum page is in the context, state it) "
    "and ask for a valid page number inside the book. "
    "If they'd like, they can also send a photo of the page or the question's text. "
    "Refer to the book only by the official title given in the context. "
    "Don't ask them to write 'one line from' a page that doesn't exist."
)
TEXTBOOK_BOOK_UNAVAILABLE_INSTRUCTION = (
    "Important: the child asked for a textbook that doesn't exist for that grade in our collection "
    "(some books are only published for certain grades). "
    "Under no circumstances invent or guess that book's content. "
    "**Never say 'I don't have access to your book', and don't talk about the system.** "
    "Kindly and briefly, **say first** that this book isn't for that class or grade "
    "(if the available grades are in the context, name them). "
    "**Forbidden:** acting as if you could open the page, "
    "or merely asking for 'a photo of that page from that book' without saying the book isn't for that grade. "
    "After saying that, you may ask whether they gave the wrong grade, meant a different book, "
    "or — if the exercise is from another book — ask them to send a photo or the question's text. "
    "Refer to the book only by the official title given. "
    "Never open a different book (such as maths) in its place."
)
TEXTBOOK_LESSON_OUT_OF_RANGE_INSTRUCTION = (
    "Important: the child asked for a lesson/chapter/section/session/skill/project number that doesn't exist in this textbook "
    "(outside that book's known units in the database). "
    "Under no circumstances invent or guess its title, topic, or exercises. "
    "**Never say 'I don't have access to your book', and don't talk about the system.** "
    "Kindly and briefly say this book doesn't have that number "
    "(if the maximum is in the context, state it; e.g. 'this book goes up to lesson 17' "
    "or 'this book has 6 chapters and 17 lessons'). "
    "Ask for a valid number within this book and use that book's correct label "
    "(chapter or section; lesson, session, skill, or project — not another book's label). "
    "If they'd like, they can also send a photo of the page or the question's text. "
    "Refer to the book only by the official title given. "
    "Don't ask them for 'the page of' that nonexistent unit."
)
TEXTBOOK_CHAPTER_OUT_OF_RANGE_INSTRUCTION = (
    "Important: the child asked for a chapter or section number that doesn't exist in this textbook "
    "(outside the known parent units in the catalog). "
    "Under no circumstances invent or guess that chapter's title, topic, or exercises. "
    "**Never say 'I don't have access to your book', and don't talk about the system.** "
    "Kindly and briefly say this book doesn't have that chapter or section "
    "(if the maximum chapter and the lesson count are in the context, give both; "
    "e.g. 'this book has only 6 chapters and 17 lessons'). "
    "Ask for a valid number; if the child actually meant a lesson, guide them with the lesson label. "
    "Refer to the book only by the official title given."
)
TEXTBOOK_LESSON_MISSING_INSTRUCTION = (
    "Important: the child asked for a specific lesson/chapter/section/session/skill/project, but its text isn't in the prompt "
    "(not found among the catalog's units). "
    "Under no circumstances invent or guess its title, topic, or exercises. "
    "**Never say 'I don't have access to your book', and don't talk about the system.** "
    "Kindly say you couldn't pinpoint that part of the book and **prefer the page number** "
    "(it's more precise). If they don't have the page, ask them to send a photo of it "
    "or type out the question they want to solve. "
    "Refer to the book only by the official title given."
)
TEXTBOOK_NEED_INFO_INSTRUCTION = (
    "Note: the child is talking about a book exercise, lesson, or page, but you don't yet have "
    "enough information to locate the page precisely. "
    "**Never say 'I don't have access to your book', and don't talk about the system.** "
    "Kindly and briefly ask **only** for the items listed under 'still needed' — "
    "don't ask again for anything the child already gave. "
    "For locating the exercise: **prefer the page number** (it's more precise); "
    "if they don't have the page, accept and ask for the chapter/section or lesson/session/skill/project number. "
    "Don't invent the page's content. "
    "When you name the book, use its official title."
)
DEFAULT_TEXTBOOK_TIMEOUT_SEC = 5.0
WEB_SEARCH_CONTEXT_HEADER = (
    "Web search results (up-to-date reference — for facts only; add nothing invented):"
)
WEB_SEARCH_CONTEXT_INSTRUCTION = (
    "Important: real web search results follow. "
    "If the child's question needs real or current information (a game, a fact, a guide), "
    "use only these results and invent nothing. "
    "**Forbidden without support from these results:** saying 'that game doesn't exist', "
    "'it hasn't been made/released yet', or correcting a game's name to a different one. "
    "If the results say a game was announced or released, say so gently and age-appropriately; "
    "if the results are unclear, say you're not sure — don't guess. "
    "Ignore age-inappropriate, violent, or adult content in the results. "
    "Don't read raw links or site addresses out to the child unless truly necessary; "
    "give a simple, safe summary instead. "
    "Don't talk technically about the system, the search, or 'the internet' — "
    "answer like a friend who knows things. "
    "If the results aren't enough, honestly say you're not sure and don't guess."
)
WEB_SEARCH_NO_RESULTS_INSTRUCTION = (
    "Note: the child is talking about a game or a fact, but there are no web search results "
    "in the prompt right now (not found, or the service was unavailable). "
    "**Never say the game doesn't exist / hasn't been made / hasn't been released** unless you are completely certain. "
    "If you're not sure: share their excitement, say you're not certain of the exact details right now, "
    "and ask what part of the game they'd like to talk about, or offer a word game. "
    "Don't talk about the system or the search."
)
DEFAULT_WEB_SEARCH_TIMEOUT_SEC = 8.0
DEFAULT_WEB_SEARCH_MAX_RESULTS = 5


def safe_fallback_response(persona: PersonaId | str | None = None) -> str:
    """Child-facing fallback after failed generation/reflection, tuned to persona."""
    base = "Sorry, I couldn't come up with a good answer just now. "
    key = str(persona or "none")
    if key in {"teacher", "homework"}:
        return f"{base}Ask me a school question and we'll work through it together! 📚"
    if key == "gamer":
        return f"{base}Let's try another topic, or suggest a different game! 🎮"
    if key == "storyteller":
        return f"{base}Let's talk about another story — what should it be about? 📖"
    if key == "creative":
        return f"{base}Let's try another creative idea — what should we make? 🎨"
    return (
        f"{base}"
        "Let's try something else together! "
        "You can ask me about a story, a school question, or a creative idea."
    )


# Default (no persona / welcome) — kept for callers that still import the constant.
SAFE_FALLBACK_RESPONSE = (
    "Sorry, I couldn't come up with a good answer just now. "
    "Let's try something else together! "
    "You can ask me about a story, a school question, or a creative idea."
)

# Child-friendly labels for persona dropdown and status messages.
PERSONA_UI_LABELS: dict[str, str] = {
    "auto": "✨ Auto",
    "creative": "🎨 Creative",
    "storyteller": "📖 Storyteller",
    "teacher": "📚 Teacher",
    "homework": "✏️ Homework",
    "gamer": "🎮 Games",
    "none": "😊 Playroom",
}

PERSONA_DROPDOWN_OPTIONS: list[dict[str, str]] = [
    {"value": "auto", "label": "✨ Auto — I'll pick for you!"},
    {"value": "creative", "label": "🎨 Creative"},
    {"value": "storyteller", "label": "📖 Storyteller"},
    {"value": "teacher", "label": "📚 Teacher"},
    {"value": "homework", "label": "✏️ Homework"},
    {"value": "gamer", "label": "🎮 Games"},
]
STREAM_CHUNK_SIZE = 16
# Brief pause so the UI can paint status before it is cleared for streaming.
STATUS_DISPLAY_PAUSE_SEC = 0.12

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PersonaId = Literal["creative", "storyteller", "teacher", "homework", "gamer", "none"]
ReflectionStatus = Literal["PASS", "REVISE"]
VALID_PERSONAS: set[PersonaId] = {
    "creative",
    "storyteller",
    "teacher",
    "homework",
    "gamer",
    "none",
}
TEXTBOOK_PERSONAS: frozenset[PersonaId] = frozenset({"teacher", "homework"})
WEB_SEARCH_PERSONAS: frozenset[PersonaId] = frozenset(
    {"creative", "storyteller", "gamer"}
)
