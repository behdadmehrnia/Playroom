"""System prompt assembly, response generation, and reflection loop."""

from __future__ import annotations

import base64
from typing import Any, Awaitable, Callable

from .constants import (
    MAX_GENERATION_ATTEMPTS,
    PERSONA_UI_LABELS,
    REVISION_INSTRUCTION_HEADER,
    SAFE_FALLBACK_RESPONSE,
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
        bits.append(f"درس/واحد درخواستی: {context.lesson}")
    if context.chapter is not None and context.lesson is None:
        bits.append(f"فصل/بخش درخواستی: {context.chapter}")
    if context.max_lesson is not None:
        if context.min_lesson is not None and context.min_lesson > 1:
            bits.append(
                f"محدودهٔ درس‌های شناخته‌شده در پایگاه: {context.min_lesson} تا {context.max_lesson}"
            )
        else:
            bits.append(f"این کتاب تا درس {context.max_lesson} دارد")
    if context.max_chapter is not None:
        bits.append(f"این کتاب تا فصل/بخش {context.max_chapter} دارد")
    if context.grade is not None:
        bits.append(f"پایه: {context.grade}")
    return "\n".join(bits)


def format_chapter_out_of_range_instruction(context: TextbookContext) -> str:
    """Inject concrete chapter (+ lesson) bounds when فصل/بخش is too high."""
    title = context.subject_title or "این کتاب"
    bits = [
        TEXTBOOK_CHAPTER_OUT_OF_RANGE_INSTRUCTION,
        f"کتاب: {title}",
    ]
    if context.chapter is not None:
        bits.append(f"فصل/بخش درخواستی: {context.chapter}")
    if context.max_chapter is not None:
        if context.min_chapter is not None and context.min_chapter > 1:
            bits.append(
                f"محدودهٔ فصل/بخش‌های شناخته‌شده: {context.min_chapter} تا {context.max_chapter}"
            )
        else:
            bits.append(f"این کتاب تا فصل/بخش {context.max_chapter} دارد")
    if context.max_lesson is not None:
        bits.append(f"این کتاب تا درس {context.max_lesson} دارد")
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


def compose_textbook_outline_reply(context: TextbookContext) -> str | None:
    """Deterministic child-facing reply for catalog outline requests.

    LLMs often ignore outline context (especially when page-oriented instructions
    leak in) and invent «دوره اول/دوم» or claim they don't have the list.
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
    title = context.subject_title or "این کتاب"
    grade_bit = f" پایه {context.grade}" if context.grade is not None else ""
    return (
        f"این هم فهرست کتاب «{title}»{grade_bit} 📚\n\n"
        f"{body}\n\n"
        "کدوم فصل یا درس رو می‌خوای با هم کار کنیم؟"
    )


def compose_textbook_failure_reply(context: TextbookContext) -> str | None:
    """Deterministic child-facing reply for hard textbook failures (demo-safe).

    LLMs often ignore failure instructions and pretend the page opened; for these
    failures we answer from structured fields instead of trusting free generation.
    """
    title = context.subject_title or "این کتاب"
    grade = context.grade
    page = context.page

    if context.failure_reason == "book_unavailable":
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

    if context.failure_reason == "page_out_of_range" or context.page_out_of_range:
        max_bit = (
            f" (این کتاب تا صفحهٔ {context.max_page} دارد)"
            if context.max_page is not None
            else ""
        )
        page_bit = f"صفحهٔ {page}" if page is not None else "این صفحه"
        grade_bit = f" پایه {grade}" if grade is not None else ""
        return (
            f"{page_bit} توی کتاب «{title}»{grade_bit} نیست{max_bit}. "
            "یک شمارهٔ صفحهٔ داخل همین کتاب بگو، یا عکس/متن سوال را بفرست 📚"
        )

    if context.failure_reason == "lesson_out_of_range":
        unit = context.lesson if context.lesson is not None else context.chapter
        max_bit = ""
        if context.max_lesson is not None and context.max_chapter is not None:
            max_bit = (
                f" (این کتاب تا فصل {context.max_chapter} و تا درس {context.max_lesson} دارد)"
            )
        elif context.max_lesson is not None:
            max_bit = f" (این کتاب تا درس {context.max_lesson} دارد)"
        elif context.max_chapter is not None:
            max_bit = f" (این کتاب تا فصل {context.max_chapter} دارد)"
        unit_bit = f"درس/فصل {unit}" if unit is not None else "این درس/فصل"
        grade_bit = f" پایه {grade}" if grade is not None else ""
        return (
            f"{unit_bit} توی کتاب «{title}»{grade_bit} نیست{max_bit}. "
            "یک شمارهٔ درست داخل همین کتاب بگو، یا عکس/متن سوال را بفرست 📚"
        )

    if context.failure_reason == "chapter_out_of_range":
        ch = context.chapter
        max_bit = ""
        if context.max_chapter is not None and context.max_lesson is not None:
            max_bit = (
                f" (این کتاب تا فصل {context.max_chapter} و تا درس {context.max_lesson} دارد)"
            )
        elif context.max_chapter is not None:
            max_bit = f" (این کتاب تا فصل {context.max_chapter} دارد)"
        ch_bit = f"فصل {ch}" if ch is not None else "این فصل"
        grade_bit = f" پایه {grade}" if grade is not None else ""
        return (
            f"{ch_bit} توی کتاب «{title}»{grade_bit} نیست{max_bit}. "
            "یک شمارهٔ فصل یا درس درست بگو، یا عکس/متن سوال را بفرست 📚"
        )

    if context.failure_reason in {"page_missing", "lesson_missing"}:
        # Without a known book, ask for info instead of a fake «این کتاب» miss.
        if not (context.subject_title or context.subject):
            return None
        grade_bit = f" پایه {grade}" if grade is not None else ""
        # Outline / bare book ask with empty catalog maps — not a page miss.
        if page is None and context.lesson is None and context.chapter is None:
            return (
                f"فهرست درس‌های کتاب «{title}»{grade_bit} الان در دسترس نیست. "
                "یک شمارهٔ درس یا صفحه بگو، یا عکس/متن سوال را بفرست 📚"
            )
        where = ""
        if page is not None:
            where = f"صفحهٔ {page} "
        elif context.lesson is not None:
            where = f"درس {context.lesson} "
        elif context.chapter is not None:
            where = f"فصل {context.chapter} "
        return (
            f"الان نتونستم {where}از کتاب «{title}»{grade_bit} رو دقیق پیدا کنم. "
            "اگر می‌تونی عکس همون صفحه رو بفرست، یا متن سوال/درک مطلب رو اینجا بنویس "
            "تا با هم حلش کنیم 📚"
        )

    return None


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
    if context.chapter is not None:
        known.append(f"فصل: {context.chapter}")
    if context.lesson is not None:
        known.append(f"درس: {context.lesson}")
    if context.page is not None:
        known.append(f"صفحه: {context.page}")
    elif context.lesson is None and context.chapter is None and (
        context.subject_title or context.subject or context.grade is not None
    ):
        # Prefer page (precise); chapter/lesson is an acceptable alternative.
        missing.append("شمارهٔ صفحه؟ (ترجیح) یا شمارهٔ فصل/درس؟")

    bits = [TEXTBOOK_NEED_INFO_INSTRUCTION]
    if known:
        bits.append("همین الان می‌دانیم: " + "؛ ".join(known))
        bits.append(
            "**ممنوع:** دوباره پرسیدن موارد بالا (پایه/کتاب/فصل/درس که قبلاً گفته شده). "
            "هرگز «دوره اول یا دوم» یا نسخهٔ دیگری از همان کتاب را نپرس — "
            "برای هر پایه فقط یک کتاب فارسی/ریاضی/… در مجموعه هست."
        )
    if missing:
        bits.append("هنوز لازم است بپرسی: " + "؛ ".join(missing))
    elif context.chapter is not None or context.lesson is not None:
        bits.append(
            "پایه و کتاب و فصل/درس مشخص است. "
            "اگر متن کتاب در پرامپت نیست، فقط یک‌بار شمارهٔ صفحه یا عکس صفحه را بخواه — "
            "سوال کلی و سقراطی نپرس و محتوای درس را از خودت نساز."
        )
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

    if persona and persona != "none":
        label = PERSONA_UI_LABELS.get(persona, persona)
        sections.append(
            "## حالت فعال فعلی (الزامی)\n"
            f"الان از قبل در حالت «{label}» هستی و این انتخاب برای کودک انجام شده است.\n"
            "**هرگز** دوباره لیست پرسونا/حالت‌ها را نشان نده و نپرس «کدام را انتخاب می‌کنی؟».\n"
            "مستقیماً در همین حالت جواب بده، کمک کن، و گفتگو را ادامه بده.\n"
            "اگر حس کردی موضوع کمی به حالت دیگری نزدیک شده، بدون درخواست صریح کودک "
            "حالت را عوض نکن — در همین حالت فعال بمان."
        )

    if textbook_context and textbook_context.matched and textbook_context.context_text:
        meta_parts: list[str] = []
        if textbook_context.subject_title:
            meta_parts.append(textbook_context.subject_title)
        if textbook_context.grade:
            meta_parts.append(f"پایه {textbook_context.grade}")
        if textbook_context.page:
            meta_parts.append(f"صفحه {textbook_context.page}")
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
        title = textbook_context.subject_title or "این کتاب"
        bits = [TEXTBOOK_LESSON_MISSING_INSTRUCTION, f"کتاب: {title}"]
        if textbook_context.grade is not None:
            bits.append(f"پایه: {textbook_context.grade}")
        if textbook_context.lesson is not None:
            bits.append(f"درس/فصل درخواستی: {textbook_context.lesson}")
        if textbook_context.chapter is not None:
            bits.append(f"فصل درخواستی: {textbook_context.chapter}")
        if textbook_context.max_lesson is not None:
            bits.append(f"حداکثر درس شناخته‌شده: {textbook_context.max_lesson}")
        if textbook_context.max_chapter is not None:
            bits.append(f"حداکثر فصل شناخته‌شده: {textbook_context.max_chapter}")
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
        or (
            textbook_context.failure_reason
            in {
                "page_missing",
                "lesson_missing",
                "book_unavailable",
                "lesson_out_of_range",
                "chapter_out_of_range",
            }
        )
    ):
        textbook_note = (
            "\n\nتوجه بازبین: نویسنده متن صفحه را نداشته. "
            "اگر وانمود کرده صفحه را باز کرده، محتوای دقیق ساخته، "
            "یا گفته «یک لحظه صبر کن صفحه را می‌بینم»، REVISE."
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
