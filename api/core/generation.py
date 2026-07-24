"""System prompt assembly, response generation, and reflection loop."""

from __future__ import annotations

import base64
from typing import Any, Awaitable, Callable

from .constants import (
    MAX_GENERATION_ATTEMPTS,
    REVISION_INSTRUCTION_HEADER,
    SAFE_FALLBACK_RESPONSE,
    TEXTBOOK_CONTEXT_HEADER,
    TEXTBOOK_CONTEXT_INSTRUCTION,
    TEXTBOOK_IMAGE_ONLY_INSTRUCTION,
    TEXTBOOK_LOOKUP_FAILED_INSTRUCTION,
    TEXTBOOK_NEED_INFO_INSTRUCTION,
    TEXTBOOK_LESSON_MISSING_INSTRUCTION,
    TEXTBOOK_LESSON_OUT_OF_RANGE_INSTRUCTION,
    TEXTBOOK_BOOK_UNAVAILABLE_INSTRUCTION,
    TEXTBOOK_PAGE_OUT_OF_RANGE_INSTRUCTION,
    TEXTBOOK_UNREADABLE_INSTRUCTION,
    WEB_SEARCH_CONTEXT_HEADER,
    WEB_SEARCH_CONTEXT_INSTRUCTION,
    WEB_SEARCH_NO_RESULTS_INSTRUCTION,
    PersonaId,
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
    title = context.subject_title or "این کتاب"
    bits = [
        TEXTBOOK_PAGE_OUT_OF_RANGE_INSTRUCTION,
        f"کتاب: {title}",
    ]
    if context.page is not None:
        bits.append(f"صفحهٔ درخواستی: {context.page}")
    if context.max_page is not None:
        range_bits = f"حداکثر صفحهٔ چاپی در پایگاه: {context.max_page}"
        if context.min_page is not None and context.min_page > 1:
            range_bits = (
                f"محدودهٔ صفحات چاپی در پایگاه: {context.min_page} تا {context.max_page}"
            )
        bits.append(range_bits)
    if context.grade is not None:
        bits.append(f"پایه: {context.grade}")
    return "\n".join(bits)


def format_lesson_out_of_range_instruction(context: TextbookContext) -> str:
    """Inject concrete lesson bounds when the requested درس/فصل is too high."""
    title = context.subject_title or "این کتاب"
    bits = [
        TEXTBOOK_LESSON_OUT_OF_RANGE_INSTRUCTION,
        f"کتاب: {title}",
    ]
    if context.lesson is not None:
        bits.append(f"درس/فصل درخواستی: {context.lesson}")
    if context.max_lesson is not None:
        if context.min_lesson is not None and context.min_lesson > 1:
            bits.append(
                f"محدودهٔ درس‌های شناخته‌شده در پایگاه: {context.min_lesson} تا {context.max_lesson}"
            )
        else:
            bits.append(f"این کتاب تا درس/فصل {context.max_lesson} دارد")
    if context.grade is not None:
        bits.append(f"پایه: {context.grade}")
    return "\n".join(bits)


def format_book_unavailable_instruction(context: TextbookContext) -> str:
    """Tell the model this subject is not offered for the child's grade."""
    title = context.subject_title or "این کتاب"
    bits = [
        TEXTBOOK_BOOK_UNAVAILABLE_INSTRUCTION,
        f"کتاب: {title}",
    ]
    if context.grade is not None:
        bits.append(f"پایهٔ درخواستی: {context.grade}")
    if context.available_grades:
        grades = "، ".join(str(g) for g in context.available_grades)
        bits.append(f"پایه‌هایی که این کتاب را دارند: {grades}")
        if context.grade is not None:
            must = (
                f"پاسخ اجباری (با لحن کودکانه بازنویسی کن): "
                f"{title} برای پایه {context.grade} نیست"
            )
            if len(context.available_grades) == 1:
                must += f"؛ معمولاً برای پایهٔ {grades} است."
            else:
                must += f"؛ در کتاب‌های ما برای پایه‌های {grades} هست."
            bits.append(must)
    else:
        bits.append("در فهرست فعلی، این کتاب برای هیچ پایه‌ای ثبت نشده است.")
    return "\n".join(bits)


def compose_textbook_failure_reply(context: TextbookContext) -> str | None:
    """Deterministic child-facing reply for hard textbook failures (demo-safe).

    LLMs often ignore book_unavailable and ask for a photo of the missing book;
    for this failure we answer from the structured fields instead.
    """
    if context.failure_reason != "book_unavailable":
        return None
    title = context.subject_title or "این کتاب"
    grade = context.grade
    avail = context.available_grades or []
    if grade is not None and avail:
        if len(avail) == 1:
            avail_bit = f"معمولاً برای پایهٔ {avail[0]} است"
        else:
            grades = " و ".join(str(g) for g in avail)
            avail_bit = f"برای پایه‌های {grades} هست"
        return (
            f"کتاب «{title}» برای پایه {grade} توی کتاب‌های مدرسه‌ای که من دارم نیست؛ "
            f"{avail_bit}. "
            "اگر پایه را اشتباه گفتی بگو، یا اسم کتاب درست را بگو. "
            "اگر تمرین از کتاب دیگری است، عکس یا متن همان سوال را بفرست 📚"
        )
    if grade is not None:
        return (
            f"کتاب «{title}» برای پایه {grade} توی کتاب‌های مدرسه‌ای که من دارم نیست. "
            "اسم کتاب یا پایه را دوباره بگو، یا عکس/متن سوال را از کتاب درست بفرست 📚"
        )
    return (
        f"کتاب «{title}» را برای پایه‌ای که گفتی پیدا نکردم. "
        "پایه و نام کتاب را دوباره بگو، یا عکس سوال را بفرست 📚"
    )


def format_need_info_instruction(context: TextbookContext) -> str:
    """Ask only for slots still missing — prefer page, accept chapter/lesson."""
    known: list[str] = []
    missing: list[str] = []
    if context.subject_title or context.subject:
        known.append(f"کتاب: {context.subject_title or context.subject}")
    else:
        missing.append("کدام کتاب؟ (مثلاً ریاضی، فارسی، هدیه های آسمان)")
    if context.grade is not None:
        known.append(f"پایه/کلاس: {context.grade}")
    else:
        missing.append("کلاس چندمی؟")
    if context.lesson is not None:
        known.append(f"درس/فصل: {context.lesson}")
    if context.page is not None:
        known.append(f"صفحه: {context.page}")
    elif context.lesson is None and (
        context.subject_title or context.subject or context.grade is not None
    ):
        # Prefer page (precise); chapter/lesson is an acceptable alternative.
        missing.append("شمارهٔ صفحه؟ (ترجیح) یا شمارهٔ فصل/درس؟")

    bits = [TEXTBOOK_NEED_INFO_INSTRUCTION]
    if known:
        bits.append("همین الان می‌دانیم: " + "؛ ".join(known))
    if missing:
        bits.append("هنوز لازم است بپرسی: " + "؛ ".join(missing))
    else:
        bits.append("اگر هنوز مطمئن نیستی، یک سوال کوتاه بپرس — چیز تکراری نپرس.")
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

    if textbook_context and textbook_context.matched and textbook_context.context_text:
        meta_parts: list[str] = []
        if textbook_context.subject_title:
            meta_parts.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_parts.append(f"پایه {textbook_context.grade}")
        if textbook_context.page:
            meta_parts.append(f"صفحه {textbook_context.page}")
        meta = " — ".join(meta_parts)
        if textbook_context.text_usable:
            instruction = TEXTBOOK_CONTEXT_INSTRUCTION
        elif textbook_context.image_base64:
            instruction = TEXTBOOK_IMAGE_ONLY_INSTRUCTION
        else:
            instruction = TEXTBOOK_UNREADABLE_INSTRUCTION
        header = f"{instruction}\n\n{TEXTBOOK_CONTEXT_HEADER}"
        if meta:
            header = f"{header}\n({meta})"
        sections.append(f"{header}\n{textbook_context.context_text}")
    elif textbook_context and (
        textbook_context.page_out_of_range
        or textbook_context.failure_reason == "page_out_of_range"
    ):
        sections.append(format_page_out_of_range_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "lesson_out_of_range":
        sections.append(format_lesson_out_of_range_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "book_unavailable":
        sections.append(format_book_unavailable_instruction(textbook_context))
    elif textbook_context and textbook_context.failure_reason == "lesson_missing":
        title = textbook_context.subject_title or "این کتاب"
        bits = [TEXTBOOK_LESSON_MISSING_INSTRUCTION, f"کتاب: {title}"]
        if textbook_context.grade is not None:
            bits.append(f"پایه: {textbook_context.grade}")
        if textbook_context.lesson is not None:
            bits.append(f"درس/فصل درخواستی: {textbook_context.lesson}")
        if textbook_context.max_lesson is not None:
            bits.append(f"حداکثر درس شناخته‌شده: {textbook_context.max_lesson}")
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
        "[ضمیمهٔ مرجع سیستمی]\n"
        "این تصویر(ها) را سیستم از پایگاه کتاب درسی بازیابی کرده است "
        "(کاربر آن‌ها را نفرستاده است).\n"
        "فقط مرجعِ صفحه(های) کتاب هستند؛ برای خواندن متن/شکل/جدول از آن‌ها استفاده کن."
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": image_note}]
    for encoded in images[:4]:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
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
        return ReflectionResult(status="REVISE", reasons=["خروجی بازبین قابل parse نبود."])

    status_raw = str(payload.get("status", "")).strip().upper()
    if status_raw == "PASS":
        return ReflectionResult(status="PASS")

    reasons_raw = payload.get("reasons", [])
    reasons: list[str] = []
    if isinstance(reasons_raw, list):
        reasons = [str(item).strip() for item in reasons_raw if str(item).strip()]

    if not reasons:
        reasons = ["پاسخ برای کودک مناسب تشخیص داده نشد."]

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
    textbook_note = ""
    if textbook_context and textbook_context.matched:
        meta_bits: list[str] = []
        if textbook_context.subject_title:
            meta_bits.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_bits.append(f"پایه {textbook_context.grade}")
        if textbook_context.page:
            meta_bits.append(f"صفحه {textbook_context.page}")
        meta = "، ".join(meta_bits) if meta_bits else "صفحهٔ کتاب"
        textbook_note = (
            f"\n\nتوجه بازبین: سیستم متن/تصویر واقعیِ {meta} را به نویسنده داده است. "
            "اگر پاسخ بر اساس همان صفحه صحبت می‌کند، آن را توهم حساب نکن و PASS بده "
            "(مگر اینکه ناامن یا نامناسب باشد)."
        )
    elif textbook_context and (
        textbook_context.page_query_failed
        or textbook_context.page_out_of_range
        or textbook_context.need_info
    ):
        textbook_note = (
            "\n\nتوجه بازبین: نویسنده متن صفحه را نداشته؛ اگر محتوای دقیق صفحه را ساخته، REVISE."
        )

    web_note = ""
    if web_search_context and web_search_context.matched:
        web_note = (
            "\n\nتوجه بازبین: سیستم نتایج واقعی جستجوی وب را به نویسنده داده است. "
            "اگر پاسخ بر اساس همان نتایج است، آن را توهم حساب نکن و PASS بده "
            "(مگر اینکه ناامن یا نامناسب سن باشد)."
        )
    elif web_search_context is not None and not web_search_context.matched:
        web_note = (
            "\n\nتوجه بازبین: نویسنده نتایج جستجو نداشته. "
            "اگر ادعا کرده بازی وجود ندارد / هنوز منتشر نشده بدون شواهد، REVISE."
        )

    review_prompt = (
        f"پیام کودک:\n{user_message}\n\n"
        f"پاسخ پیشنهادی:\n{candidate_response}"
        f"{textbook_note}{web_note}\n\n"
        "فقط JSON خروجی بده."
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
) -> str:
    revision_reasons: list[str] = []
    user_message = _get_latest_user_message(conversation_messages)
    # When reflection is off, generate once and return — never SAFE_FALLBACK.
    if not enable_reflection:
        if on_status:
            await on_status(status_reflection_disabled())
            await on_status(status_generating_response(1, 1))
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
            await on_status(status_generating_response(attempt, MAX_GENERATION_ATTEMPTS))

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

        revision_reasons = reflection.reasons or ["پاسخ نیاز به اصلاح دارد."]

    return SAFE_FALLBACK_RESPONSE
