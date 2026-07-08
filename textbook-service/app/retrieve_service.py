from __future__ import annotations

import base64

from app.models import IncludeImageMode, MatchType, RetrieveRequest, RetrieveResponse
from app.parser import parse_persian_query
from app.subjects import SUBJECT_TITLES, topic_label
from app.store import (
    PageRecord,
    get_neighbor_pages,
    get_page,
    lesson_search,
    resolve_image_path,
    topic_search,
)
from app.text_quality import is_text_garbled


def _page_text_for_context(page: PageRecord) -> tuple[str, bool]:
    """Return (text for LLM context, is_usable)."""
    raw = page.text.strip()
    if not raw:
        return "[متن استخراج نشد — از تصویر صفحه استفاده کن]", False
    if not page.text_usable or is_text_garbled(raw):
        title_bits = [page.subject_title, f"پایه {page.grade}", f"صفحه {page.printed_page}"]
        note = (
            f"[متن این صفحه ({'، '.join(title_bits)}) به‌درستی و کامل قابل استخراج نبود "
            "(مثلاً خط تحریری/نستعلیق). تصویر صفحه پیوست شده — محتوا را از تصویر بخوان.]"
        )
        return note, False
    return raw, True


def _format_page_block(page: PageRecord, *, topic: str | None = None) -> tuple[str, bool]:
    header = f"--- صفحه {page.printed_page} ({page.subject_title}، پایه {page.grade})"
    if topic:
        header += f" — بخش: {topic}"
    header += " ---"
    body, usable = _page_text_for_context(page)
    return f"{header}\n{body}", usable


def _build_context_text(
    center: PageRecord,
    neighbors: list[PageRecord],
    *,
    topic: str | None = None,
) -> tuple[str, bool]:
    blocks: list[str] = []
    center_block, center_ok = _format_page_block(center, topic=topic)
    blocks.append(center_block)
    all_usable = center_ok
    for neighbor in neighbors:
        nb, nb_ok = _format_page_block(neighbor)
        blocks.append(nb)
        all_usable = all_usable and nb_ok
    return "\n\n".join(blocks), all_usable


def _needs_image(page: PageRecord, include_image: IncludeImageMode) -> bool:
    if include_image == "never":
        return False
    if include_image == "always":
        return True
    # auto
    if page.is_scanned:
        return True
    if not page.text_usable:
        return True
    if len(page.text.strip()) < 40:
        return True
    if is_text_garbled(page.text):
        return True
    return False


def _attach_image(
    response: RetrieveResponse,
    page: PageRecord,
    *,
    needs_image: bool,
) -> None:
    if not needs_image:
        return
    response.needs_image = True
    if page.grade and page.subject and page.printed_page:
        response.image_url = (
            f"/v1/page-image?grade={page.grade}&subject={page.subject}&page={page.printed_page}"
        )
    image_file = resolve_image_path(page.image_path)
    if image_file and image_file.is_file():
        encoded = base64.b64encode(image_file.read_bytes()).decode("ascii")
        response.image_base64 = encoded


def _is_topic_search_query(query: str, *, parsed_topic: str | None = None) -> bool:
    """
    Topic search should only run for real content requests, not bare subject picks.

    Examples that SHOULD search:
      - «درس ستایش فارسی ششم»
      - «معنی شعر ستایش»
      - «تمرین سوم ریاضی»

    Examples that should NOT search:
      - «ریاضی»
      - «فارسی»
    """
    normalized = query.strip()
    if not normalized:
        return False
    if parsed_topic:
        return True
    content_markers = ("درس", "تمرین", "متن", "شعر", "معنی", "سوال", "بخوان", "بخوانیم")
    return any(marker in normalized for marker in content_markers)


def retrieve_context(request: RetrieveRequest) -> RetrieveResponse:
    parsed = parse_persian_query(request.query)
    grade = request.grade or parsed.grade
    subject = request.subject or parsed.subject
    page = request.page or parsed.page
    lesson = parsed.lesson
    topic_display = topic_label(parsed.topic) if parsed.topic else parsed.topic_alias

    # A page number is only meaningful together with a specific book.
    # If the user gave a page but we can't resolve grade AND subject, do NOT
    # guess a random page — report not matched so the assistant asks for the
    # missing grade/subject instead of hallucinating.
    if page and not (grade and subject):
        return RetrieveResponse(
            matched=False,
            match_type="none",
            grade=grade,
            subject=subject,
            subject_title=SUBJECT_TITLES.get(subject) if subject else None,
            page=page,
            confidence=parsed.confidence,
        )

    # Exact page lookup
    if grade and subject and page:
        center = get_page(grade, subject, page)
        if center:
            neighbors = get_neighbor_pages(grade, subject, page, request.include_neighbors)
            needs_image = _needs_image(center, request.include_image)
            context_text, text_usable = _build_context_text(
                center, neighbors, topic=topic_display
            )
            response = RetrieveResponse(
                matched=True,
                match_type="exact_page",
                grade=grade,
                subject=subject,
                subject_title=center.subject_title or SUBJECT_TITLES.get(subject, subject),
                page=page,
                context_text=context_text,
                text_usable=text_usable,
                confidence=max(parsed.confidence, 0.9),
                detected_topic=parsed.topic,
                detected_topic_label=topic_display,
            )
            _attach_image(response, center, needs_image=needs_image)
            return response
        # Page requested but not in index → not matched (do not guess)
        return RetrieveResponse(
            matched=False,
            match_type="none",
            grade=grade,
            subject=subject,
            subject_title=SUBJECT_TITLES.get(subject, subject),
            page=page,
            confidence=parsed.confidence,
        )

    # Lesson / chapter lookup (درس دوازدهم، فصل سوم) — resolve to its start page.
    if grade and subject and lesson:
        center = lesson_search(grade, subject, lesson)
        if center:
            neighbors = get_neighbor_pages(
                grade, subject, center.printed_page, request.include_neighbors
            )
            needs_image = _needs_image(center, request.include_image)
            context_text, text_usable = _build_context_text(
                center, neighbors, topic=topic_display
            )
            response = RetrieveResponse(
                matched=True,
                match_type="lesson",
                grade=grade,
                subject=subject,
                subject_title=center.subject_title or SUBJECT_TITLES.get(subject, subject),
                page=center.printed_page,
                context_text=context_text,
                text_usable=text_usable,
                confidence=max(parsed.confidence, 0.8),
                detected_topic=parsed.topic,
                detected_topic_label=topic_display,
            )
            _attach_image(response, center, needs_image=needs_image)
            return response
        # Lesson requested but not found → not matched (do not guess)
        return RetrieveResponse(
            matched=False,
            match_type="none",
            grade=grade,
            subject=subject,
            subject_title=SUBJECT_TITLES.get(subject, subject),
            confidence=parsed.confidence,
        )

    # Topic FTS search — only for real topical content requests
    if grade and subject and _is_topic_search_query(request.query, parsed_topic=parsed.topic):
        hits = topic_search(request.query, grade=grade, subject=subject, limit=2)
        if hits:
            blocks: list[str] = []
            all_usable = True
            for hit in hits:
                block, ok = _format_page_block(hit)
                blocks.append(block)
                all_usable = all_usable and ok
            primary = hits[0]
            needs_image = _needs_image(primary, request.include_image)
            response = RetrieveResponse(
                matched=True,
                match_type="topic_search",
                grade=grade,
                subject=subject,
                subject_title=primary.subject_title or SUBJECT_TITLES.get(subject, subject),
                page=primary.printed_page,
                context_text="\n\n".join(blocks),
                text_usable=all_usable,
                confidence=max(parsed.confidence, 0.6),
            )
            _attach_image(response, primary, needs_image=needs_image)
            return response

    return RetrieveResponse(matched=False, match_type="none", confidence=0.0)
