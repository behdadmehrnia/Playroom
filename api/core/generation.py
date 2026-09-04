"""System prompt assembly, response generation, and reflection loop."""

from __future__ import annotations

import base64
import re
from typing import Any, Awaitable, Callable

from .constants import (
    MAX_GENERATION_ATTEMPTS,
    PERSONA_UI_LABELS,
    REVISION_INSTRUCTION_HEADER,
    TEXTBOOK_CONTEXT_HEADER,
    TEXTBOOK_CONTEXT_INSTRUCTION,
    TEXTBOOK_IMAGE_ONLY_INSTRUCTION,
    TEXTBOOK_LOOKUP_FAILED_INSTRUCTION,
    TEXTBOOK_MATCHED_ACTION_HEADER,
    TEXTBOOK_MISSING_IMAGE_INSTRUCTION,
    TEXTBOOK_NEED_INFO_INSTRUCTION,
    TEXTBOOK_LESSON_MISSING_INSTRUCTION,
    TEXTBOOK_LESSON_OUT_OF_RANGE_INSTRUCTION,
    TEXTBOOK_CHAPTER_OUT_OF_RANGE_INSTRUCTION,
    TEXTBOOK_BOOK_UNAVAILABLE_INSTRUCTION,
    TEXTBOOK_OUTLINE_ACTION_HEADER,
    TEXTBOOK_OUTLINE_INSTRUCTION,
    TEXTBOOK_PAGE_OUT_OF_RANGE_INSTRUCTION,
    TEXTBOOK_UNREADABLE_INSTRUCTION,
    WEB_SEARCH_CONTEXT_HEADER,
    WEB_SEARCH_CONTEXT_INSTRUCTION,
    WEB_SEARCH_NO_RESULTS_INSTRUCTION,
    PersonaId,
    safe_fallback_response,
)
from .math_tool import MathToolUsage, format_math_tool_context
from .messages import _extract_json_object, _get_latest_user_message, strip_persona_markers
from .prompts import get_core_prompt, get_persona_prompt, get_reflection_prompt
from .status import (
    status_generating_response,
    status_reflection_disabled,
    status_reviewing_response,
)
from .types import (
    ChatMessage,
    LLMClient,
    LLMCompletionRequest,
    ReflectionResult,
    TextbookContext,
    WebSearchContext,
)


def format_page_out_of_range_instruction(context: TextbookContext) -> str:
    """Inject concrete book/page bounds into the out-of-range system note."""
    title = context.subject_title or "this book"
    bits = [
        TEXTBOOK_PAGE_OUT_OF_RANGE_INSTRUCTION,
        f"Book: {title}",
    ]
    if context.page is not None:
        bits.append(f"Requested page: {context.page}")
    if context.max_page is not None:
        range_bits = f"Highest printed page in the database: {context.max_page}"
        if context.min_page is not None and context.min_page > 1:
            range_bits = (
                f"Printed page range in the database: {context.min_page} to {context.max_page}"
            )
        bits.append(range_bits)
    if context.grade is not None:
        bits.append(f"Grade: {context.grade}")
    return "\n".join(bits)


def format_lesson_out_of_range_instruction(context: TextbookContext) -> str:
    """Inject concrete lesson bounds when the requested lesson/chapter is too high."""
    title = context.subject_title or "this book"
    bits = [
        TEXTBOOK_LESSON_OUT_OF_RANGE_INSTRUCTION,
        f"Book: {title}",
    ]
    if context.lesson is not None:
        bits.append(f"Requested lesson/unit: {context.lesson}")
    if context.chapter is not None and context.lesson is None:
        bits.append(f"Requested chapter/section: {context.chapter}")
    if context.max_lesson is not None:
        if context.min_lesson is not None and context.min_lesson > 1:
            bits.append(
                f"Known lesson range in the database: {context.min_lesson} to {context.max_lesson}"
            )
        else:
            bits.append(f"This book goes up to lesson {context.max_lesson}")
    if context.max_chapter is not None:
        bits.append(f"This book goes up to chapter/section {context.max_chapter}")
    if context.grade is not None:
        bits.append(f"Grade: {context.grade}")
    return "\n".join(bits)


def format_chapter_out_of_range_instruction(context: TextbookContext) -> str:
    """Inject concrete chapter (+ lesson) bounds when the chapter/section is too high."""
    title = context.subject_title or "this book"
    bits = [
        TEXTBOOK_CHAPTER_OUT_OF_RANGE_INSTRUCTION,
        f"Book: {title}",
    ]
    if context.chapter is not None:
        bits.append(f"Requested chapter/section: {context.chapter}")
    if context.max_chapter is not None:
        if context.min_chapter is not None and context.min_chapter > 1:
            bits.append(
                f"Known chapter/section range: {context.min_chapter} to {context.max_chapter}"
            )
        else:
            bits.append(f"This book goes up to chapter/section {context.max_chapter}")
    if context.max_lesson is not None:
        bits.append(f"This book goes up to lesson {context.max_lesson}")
    if context.grade is not None:
        bits.append(f"Grade: {context.grade}")
    return "\n".join(bits)


def format_book_unavailable_instruction(context: TextbookContext) -> str:
    """Tell the model this subject is not offered for the child's grade."""
    title = context.subject_title or "this book"
    bits = [
        TEXTBOOK_BOOK_UNAVAILABLE_INSTRUCTION,
        f"Book: {title}",
    ]
    if context.grade is not None:
        bits.append(f"Requested grade: {context.grade}")
    if context.available_grades:
        grades = ", ".join(str(g) for g in context.available_grades)
        bits.append(f"Grades that have this book: {grades}")
        if context.grade is not None:
            must = (
                f"Required point (rephrase in a child-friendly tone): "
                f"{title} is not for grade {context.grade}"
            )
            if len(context.available_grades) == 1:
                must += f"; it is usually for grade {grades}."
            else:
                must += f"; in our collection it exists for grades {grades}."
            bits.append(must)
    else:
        bits.append("In the current catalog, this book is not registered for any grade.")
    return "\n".join(bits)


def compose_textbook_outline_reply(context: TextbookContext) -> str | None:
    """Deterministic child-facing reply for catalog outline requests.

    LLMs often ignore outline context (especially when page-oriented instructions
    leak in) and invent a fake structure or claim they don't have the list.
    """
    if context.match_type != "catalog_outline" or not context.context_text:
        return None
    body = context.context_text.strip()
    # Drop the LLM-facing instruction prefix; keep the structure block.
    for marker in ("ساختار کتاب «", "ساختار کتاب \""):
        idx = body.find(marker)
        if idx >= 0:
            body = body[idx:].strip()
            break
    # Soft cleanup if instruction lines somehow remain.
    lines = [
        line
        for line in body.splitlines()
        if line.strip()
        and not line.strip().startswith("توجه:")
        and "ممنوع:" not in line
        and "همین فهرست را برای کودک بخوان" not in line
    ]
    body = "\n".join(lines).strip() or body
    body = body.replace(" — فقط از همین فهرست استفاده کن", "")
    title = context.subject_title or "this book"
    grade_bit = f" (grade {context.grade})" if context.grade is not None else ""
    return (
        f"Here is the outline of {title}{grade_bit} 📚\n\n"
        f"{body}\n\n"
        "Which chapter or lesson shall we work on together?"
    )


def compose_textbook_failure_reply(
    context: TextbookContext, user_message: str | None = None
) -> str | None:
    """Deterministic child-facing reply for hard textbook failures (demo-safe).

    LLMs often ignore failure instructions and pretend the page opened; for these
    failures we answer from structured fields instead of trusting free generation.
    """
    title = context.subject_title or "this book"
    grade = context.grade
    page = context.page

    # Persian phrasings below are input matchers for the Persian textbook corpus,
    # not user-facing copy. See api/core/textbook.py.
    # If the child asks about counts (e.g. "how many lessons does this book have?"),
    # answer directly using known bounds to avoid a loop of out-of-range nagging.
    um = re.sub(r"\s+", " ", (user_message or "").strip()) if user_message else ""
    if um:
        asks_lesson_count = any(
            s in um
            for s in (
                "چند درس",
                "چند تا درس",
                "چندتا درس",
                "چند جلسه",
                "چند تا جلسه",
                "چندجلسه",
            )
        )
        asks_chapter_count = any(
            s in um
            for s in (
                "چند فصل",
                "چند تا فصل",
                "چندتا فصل",
                "چند بخش",
                "چند تا بخش",
                "چندتا بخش",
                "چند فصل/بخش",
            )
        )

        if context.failure_reason in {"lesson_out_of_range", "chapter_out_of_range"}:
            if asks_chapter_count and context.max_chapter is not None:
                grade_bit = f" (grade {grade})" if grade is not None else ""
                return (
                    f"{title}{grade_bit} goes up to chapter/section {context.max_chapter}."
                )
            if asks_lesson_count and context.max_lesson is not None:
                grade_bit = f" (grade {grade})" if grade is not None else ""
                return (
                    f"{title}{grade_bit} goes up to lesson {context.max_lesson}."
                    " Tell me which lesson you'd like to start with? 📚"
                )

    # Soft turns ("oh", "yes go on", "let's play") must not re-nag about a stale
    # out-of-range locator left over from an earlier message in the thread.
    locator_failures = {
        "page_out_of_range",
        "lesson_out_of_range",
        "chapter_out_of_range",
        "lesson_missing",
    }
    if (
        context.failure_reason in locator_failures or context.page_out_of_range
    ) and um:
        from api.core.textbook import latest_message_wants_textbook_retrieve

        if not latest_message_wants_textbook_retrieve(um):
            return None

    if context.failure_reason == "book_unavailable":
        avail = context.available_grades or []
        if grade is not None and avail:
            if len(avail) == 1:
                avail_bit = f"it is usually for grade {avail[0]}"
            else:
                grades = " and ".join(str(g) for g in avail)
                avail_bit = f"it exists for grades {grades}"
            return (
                f"{title} for grade {grade} isn't in the school books I have; "
                f"{avail_bit}. "
                "Tell me if you gave the wrong grade, or give me the right book name. "
                "If the exercise is from another book, send a photo or the text of the question 📚"
            )
        if grade is not None:
            return (
                f"{title} for grade {grade} isn't in the school books I have. "
                "Tell me the book or grade again, or send a photo or the text of the question from the right book 📚"
            )
        return (
            f"I couldn't find {title} for the grade you gave. "
            "Tell me the grade and book name again, or send a photo of the question 📚"
        )

    if context.failure_reason == "page_out_of_range" or context.page_out_of_range:
        max_bit = (
            f" (this book goes up to page {context.max_page})"
            if context.max_page is not None
            else ""
        )
        page_bit = f"Page {page}" if page is not None else "That page"
        grade_bit = f" (grade {grade})" if grade is not None else ""
        return (
            f"{page_bit} isn't in {title}{grade_bit}{max_bit}. "
            "Give me a page number inside this book, or send a photo or the text of the question 📚"
        )

    if context.failure_reason == "lesson_out_of_range":
        unit = context.lesson if context.lesson is not None else context.chapter
        max_bit = ""
        if context.max_lesson is not None and context.max_chapter is not None:
            max_bit = (
                f" (this book has {context.max_chapter} chapters and {context.max_lesson} lessons)"
            )
        elif context.max_lesson is not None:
            max_bit = f" (this book goes up to lesson {context.max_lesson})"
        elif context.max_chapter is not None:
            max_bit = f" (this book goes up to chapter {context.max_chapter})"
        unit_bit = f"Lesson/chapter {unit}" if unit is not None else "That lesson/chapter"
        grade_bit = f" (grade {grade})" if grade is not None else ""
        return (
            f"{unit_bit} isn't in {title}{grade_bit}{max_bit}. "
            "Give me a valid number inside this book, or send a photo or the text of the question 📚"
        )

    if context.failure_reason == "chapter_out_of_range":
        ch = context.chapter
        max_bit = ""
        if context.max_chapter is not None and context.max_lesson is not None:
            max_bit = (
                f" (this book has {context.max_chapter} chapters and {context.max_lesson} lessons)"
            )
        elif context.max_chapter is not None:
            max_bit = f" (this book goes up to chapter {context.max_chapter})"
        ch_bit = f"Chapter {ch}" if ch is not None else "That chapter"
        grade_bit = f" (grade {grade})" if grade is not None else ""
        return (
            f"{ch_bit} isn't in {title}{grade_bit}{max_bit}. "
            "Give me a valid chapter or lesson number, or send a photo or the text of the question 📚"
        )

    if context.failure_reason in {"page_missing", "lesson_missing"}:
        # Without a known book, ask for info instead of a fake "this book" miss.
        if not (context.subject_title or context.subject):
            return None
        grade_bit = f" (grade {grade})" if grade is not None else ""
        # Outline / bare book ask with empty catalog maps — not a page miss.
        if page is None and context.lesson is None and context.chapter is None:
            return (
                f"The lesson outline for {title}{grade_bit} isn't available right now. "
                "Give me a lesson or page number, or send a photo or the text of the question 📚"
            )
        where = ""
        if page is not None:
            where = f"page {page} "
        elif context.lesson is not None:
            where = f"lesson {context.lesson} "
        elif context.chapter is not None:
            where = f"chapter {context.chapter} "
        return (
            f"I couldn't pin down {where}of {title}{grade_bit} just now. "
            "If you can, send a photo of that page, or type the question here "
            "and we'll work through it together 📚"
        )

    return None


def compose_textbook_need_info_reply(context: TextbookContext) -> str | None:
    """Deterministic ask for a missing grade/book — don't let the LLM skip it."""
    if not (
        context.need_info or context.failure_reason == "need_grade_or_subject"
    ):
        return None

    title = context.subject_title or context.subject
    grade = context.grade
    bits: list[str] = []
    if title and grade is not None:
        bits.append(f"Got it — {title}, grade {grade}")
    elif title:
        bits.append(f"Got it — {title}")
    elif grade is not None:
        bits.append(f"Got it — grade {grade}")

    if context.chapter is not None:
        bits.append(f"chapter {context.chapter}")
    if context.lesson is not None:
        bits.append(f"lesson {context.lesson}")
    if context.page is not None:
        bits.append(f"page {context.page}")

    known = "; ".join(bits) + ". " if bits else ""

    missing: list[str] = []
    if not title:
        missing.append("the book name (maths or Persian, for example)")
    if grade is None:
        missing.append("which grade you're in")
    if (
        context.page is None
        and context.lesson is None
        and context.chapter is None
        and title
        and grade is not None
    ):
        missing.append("a page number, or a chapter/lesson")

    if not missing:
        return None

    if len(missing) == 1 and grade is None and title:
        ask = f"Which grade are you in, so I can open the right part of {title}?"
    elif len(missing) == 1:
        ask = f"Just tell me {missing[0]}?"
    else:
        ask = "Tell me " + " and ".join(missing) + "?"

    return f"{known}{ask} 📚"


def format_need_info_instruction(context: TextbookContext) -> str:
    """Ask only for slots still missing — prefer page, accept chapter/lesson."""
    known: list[str] = []
    missing: list[str] = []
    if context.subject_title or context.subject:
        known.append(f"Book: {context.subject_title or context.subject}")
    else:
        missing.append("Which book? (maths, Persian, and so on)")
    if context.grade is not None:
        known.append(f"Grade: {context.grade}")
    else:
        missing.append("Which grade are you in?")
    if context.chapter is not None:
        known.append(f"Chapter: {context.chapter}")
    if context.lesson is not None:
        known.append(f"Lesson: {context.lesson}")
    if context.page is not None:
        known.append(f"Page: {context.page}")
    elif context.lesson is None and context.chapter is None and (
        context.subject_title or context.subject or context.grade is not None
    ):
        # Prefer page (precise); chapter/lesson is an acceptable alternative.
        missing.append("A page number? (preferred) or a chapter/lesson number?")

    bits = [TEXTBOOK_NEED_INFO_INSTRUCTION]
    if known:
        bits.append("Already known: " + "; ".join(known))
        bits.append(
            "**Forbidden:** asking again for anything above (grade/book/chapter/lesson already given). "
            "Never ask about 'part one or part two' or another edition of the same book — "
            "there is exactly one book per subject per grade in the collection."
        )
    if missing:
        bits.append("Still needed: " + "; ".join(missing))
    elif context.chapter is not None or context.lesson is not None:
        bits.append(
            "Grade, book, and chapter/lesson are all known. "
            "If the book text isn't in the prompt, ask once for a page number or a photo of the page — "
            "don't ask a vague Socratic question and don't invent the lesson's content."
        )
    else:
        bits.append("If you're still unsure, ask one short question — don't repeat yourself.")
    return "\n".join(bits)


def build_system_prompt(
    persona: PersonaId,
    revision_reasons: list[str] | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
) -> str:
    sections: list[str] = [get_core_prompt()]

    persona_prompt = get_persona_prompt(persona)
    if persona_prompt:
        sections.append(persona_prompt)

    if persona and persona != "none":
        label = PERSONA_UI_LABELS.get(persona, persona)
        sections.append(
            "## Current active mode (required)\n"
            f"You are already in {label} mode; this choice has been made for the child.\n"
            "**Never** show the list of modes again and never ask 'which one do you choose?'.\n"
            "Answer directly in this mode, help, and continue the conversation.\n"
            "If the topic drifts slightly toward another mode, don't switch without an "
            "explicit request from the child — stay in this active mode."
        )

    if textbook_context and textbook_context.matched and textbook_context.context_text:
        meta_parts: list[str] = []
        if textbook_context.subject_title:
            meta_parts.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_parts.append(f"grade {textbook_context.grade}")
        if textbook_context.page:
            meta_parts.append(f"page {textbook_context.page}")
        meta = " — ".join(meta_parts)
        has_image = bool(
            textbook_context.image_base64
            or (
                textbook_context.images_base64
                and any(img for img in textbook_context.images_base64 if img)
            )
        )
        is_outline = textbook_context.match_type == "catalog_outline"
        is_unit_span = textbook_context.match_type == "lesson_span"
        if is_outline:
            instruction = TEXTBOOK_OUTLINE_INSTRUCTION
        elif has_image and not textbook_context.text_usable:
            instruction = TEXTBOOK_IMAGE_ONLY_INSTRUCTION
        elif has_image:
            instruction = TEXTBOOK_CONTEXT_INSTRUCTION
        elif is_unit_span and textbook_context.text_usable:
            # Chapter/lesson span from catalog (+OCR): use it; don't nag for a page photo.
            instruction = TEXTBOOK_CONTEXT_INSTRUCTION
        elif not textbook_context.text_usable:
            instruction = TEXTBOOK_UNREADABLE_INSTRUCTION
        else:
            # OCR-only: unreliable — ask for a clear photo of the page.
            instruction = TEXTBOOK_MISSING_IMAGE_INSTRUCTION
        header = f"{instruction}\n\n{TEXTBOOK_CONTEXT_HEADER}"
        if meta:
            header = f"{header}\n({meta})"
        sections.append(f"{header}\n{textbook_context.context_text}")
        if is_outline:
            sections.append(TEXTBOOK_OUTLINE_ACTION_HEADER)
        elif has_image:
            sections.append(TEXTBOOK_MATCHED_ACTION_HEADER)
    elif textbook_context and (
        textbook_context.page_out_of_range
        or textbook_context.failure_reason == "page_out_of_range"
    ):
        sections.append(format_page_out_of_range_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "lesson_out_of_range":
        sections.append(format_lesson_out_of_range_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "chapter_out_of_range":
        sections.append(format_chapter_out_of_range_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "book_unavailable":
        sections.append(format_book_unavailable_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "lesson_missing":
        title = textbook_context.subject_title or "this book"
        bits = [TEXTBOOK_LESSON_MISSING_INSTRUCTION, f"Book: {title}"]
        if textbook_context.grade is not None:
            bits.append(f"Grade: {textbook_context.grade}")
        if textbook_context.lesson is not None:
            bits.append(f"Requested lesson/chapter: {textbook_context.lesson}")
        if textbook_context.chapter is not None:
            bits.append(f"Requested chapter: {textbook_context.chapter}")
        if textbook_context.max_lesson is not None:
            bits.append(f"Highest known lesson: {textbook_context.max_lesson}")
        if textbook_context.max_chapter is not None:
            bits.append(f"Highest known chapter: {textbook_context.max_chapter}")
        sections.append("\n".join(bits))
    elif textbook_context and textbook_context.page_query_failed:
        sections.append(TEXTBOOK_LOOKUP_FAILED_INSTRUCTION)
    elif textbook_context and textbook_context.need_info:
        sections.append(format_need_info_instruction(textbook_context))

    if (
        web_search_context
        and web_search_context.matched
        and web_search_context.context_text
    ):
        sections.append(
            f"{WEB_SEARCH_CONTEXT_INSTRUCTION}\n\n"
            f"{WEB_SEARCH_CONTEXT_HEADER}\n"
            f"{web_search_context.context_text}"
        )
    elif web_search_context is not None and not web_search_context.matched:
        # We attempted a search (game/fact talk) but got nothing — block
        # hallucinated «doesn't exist / not released» claims.
        sections.append(WEB_SEARCH_NO_RESULTS_INSTRUCTION)

    math_block = format_math_tool_context(math_tool_usages or [])
    if math_block:
        sections.append(math_block)

    if revision_reasons:
        reasons_text = "\n".join(f"- {reason}" for reason in revision_reasons)
        sections.append(f"{REVISION_INSTRUCTION_HEADER}\n{reasons_text}")

    return "\n\n".join(sections)


def _attach_textbook_image_to_messages(
    messages: list[dict[str, Any]],
    textbook_context: TextbookContext | None,
) -> list[dict[str, Any]]:
    if not textbook_context or not textbook_context.needs_image:
        return messages
    images = textbook_context.images_base64 or (
        [textbook_context.image_base64] if textbook_context.image_base64 else []
    )
    images = [img for img in images if img]
    if not images:
        return messages

    image_note = (
        "[System reference attachment]\n"
        "The system retrieved this image (or images) from the textbook database "
        "(the user did not send them).\n"
        "They are the reference for the book page(s); use them to read text, figures, and tables."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": image_note}]
    for encoded in images[:4]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            }
        )

    updated = list(messages)
    updated.append({"role": "system", "content": content})
    return updated


def build_prompt_messages(
    *,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
) -> list[dict[str, Any]]:
    llm_messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                persona,
                revision_reasons,
                textbook_context=textbook_context,
                web_search_context=web_search_context,
                math_tool_usages=math_tool_usages,
            ),
        },
    ]
    for message in conversation_messages:
        if message.role != "system":
            content = (
                strip_persona_markers(message.content)
                if message.role == "assistant"
                else message.content
            )
            llm_messages.append({"role": message.role, "content": content})
    return _attach_textbook_image_to_messages(llm_messages, textbook_context)
# ---------------------------------------------------------------------------


async def generate_response(
    llm_client: LLMClient,
    *,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    revision_reasons: list[str] | None = None,
    temperature: float | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
) -> str:
    request = LLMCompletionRequest(
        model=backend_model,
        messages=build_prompt_messages(
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        ),
        stream=False,
        temperature=temperature,
    )
    return await llm_client.complete(request)


# ---------------------------------------------------------------------------
# Reflection agent
# ---------------------------------------------------------------------------


def parse_reflection_output(raw_output: str) -> ReflectionResult:
    payload = _extract_json_object(raw_output)
    if not payload:
        # Fail-open: a broken reviewer must not block safe homework replies.
        return ReflectionResult(status="PASS")

    status_raw = str(payload.get("status", "")).strip().upper()
    if status_raw == "PASS":
        return ReflectionResult(status="PASS")
    if status_raw != "REVISE":
        return ReflectionResult(status="PASS")

    reasons_raw = payload.get("reasons", [])
    reasons: list[str] = []
    if isinstance(reasons_raw, list):
        reasons = [str(item).strip() for item in reasons_raw if str(item).strip()]

    if not reasons:
        reasons = ["Content not appropriate for a child."]

    return ReflectionResult(status="REVISE", reasons=reasons)


async def reflect_on_response(
    llm_client: LLMClient,
    *,
    backend_model: str,
    user_message: str,
    candidate_response: str,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
) -> ReflectionResult:
    # Safety-only review of the latest generated reply — ignore chat history,
    # textbook correctness, persona fit, and clarity.
    _ = user_message, textbook_context, web_search_context
    review_prompt = (
        "Review only this proposed reply for child safety "
        "(violence, adult content, profanity or insults, dangerous substances). "
        "If it is unclear or academically wrong, still return PASS.\n\n"
        f"Proposed reply:\n{candidate_response}\n\n"
        "Output JSON only."
    )
    request = LLMCompletionRequest(
        model=backend_model,
        temperature=0.0,
        messages=[
            {"role": "system", "content": get_reflection_prompt()},
            {"role": "user", "content": review_prompt},
        ],
    )
    return parse_reflection_output(await llm_client.complete(request))


# ---------------------------------------------------------------------------
# Response loop
# ---------------------------------------------------------------------------


async def run_response_loop(
    llm_client: LLMClient,
    *,
    backend_model: str,
    persona: PersonaId,
    conversation_messages: list[ChatMessage],
    temperature: float | None = None,
    on_status: Callable[[str], Awaitable[None]] | None = None,
    textbook_context: TextbookContext | None = None,
    web_search_context: WebSearchContext | None = None,
    math_tool_usages: list[MathToolUsage] | None = None,
    enable_reflection: bool = True,
    status_debug: bool = False,
) -> str:
    revision_reasons: list[str] = []
    user_message = _get_latest_user_message(conversation_messages)
    # When reflection is off, generate once and return — never SAFE_FALLBACK.
    if not enable_reflection:
        if on_status:
            await on_status(status_reflection_disabled())
            await on_status(status_generating_response(1, 1, debug=status_debug))
        return await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=None,
            temperature=temperature,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        )

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        if on_status:
            await on_status(
                status_generating_response(
                    attempt, MAX_GENERATION_ATTEMPTS, debug=status_debug
                )
            )

        candidate = await generate_response(
            llm_client,
            backend_model=backend_model,
            persona=persona,
            conversation_messages=conversation_messages,
            revision_reasons=revision_reasons or None,
            temperature=temperature,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
            math_tool_usages=math_tool_usages,
        )

        if on_status:
            await on_status(status_reviewing_response())

        reflection = await reflect_on_response(
            llm_client,
            backend_model=backend_model,
            user_message=user_message,
            candidate_response=candidate,
            textbook_context=textbook_context,
            web_search_context=web_search_context,
        )

        if reflection.status == "PASS":
            return candidate

        revision_reasons = reflection.reasons or ["The reply needs revision."]

    return safe_fallback_response(persona)
