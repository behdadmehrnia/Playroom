from __future__ import annotations

import base64

from app.models import IncludeImageMode, MatchType, RetrieveRequest, RetrieveResponse
from app.parser import parse_persian_query
from app.subjects import SUBJECT_TITLES, topic_label
from app.store import PageRecord, get_neighbor_pages, get_page, resolve_image_path, topic_search


def _format_page_block(page: PageRecord, *, topic: str | None = None) -> str:
    header = f"--- صفحه {page.printed_page} ({page.subject_title}، پایه {page.grade})"
    if topic:
        header += f" — بخش: {topic}"
    header += " ---"
    body = page.text.strip() if page.text.strip() else "[متن این صفحه در ایندکس موجود نیست — احتمالاً اسکن است]"
    return f"{header}\n{body}"


def _build_context_text(
    center: PageRecord,
    neighbors: list[PageRecord],
    *,
    topic: str | None = None,
) -> str:
    blocks = [_format_page_block(center, topic=topic)]
    for neighbor in neighbors:
        blocks.append(_format_page_block(neighbor))
    return "\n\n".join(blocks)


def _needs_image(page: PageRecord, include_image: IncludeImageMode) -> bool:
    if include_image == "never":
        return False
    if include_image == "always":
        return True
    # auto
    if page.is_scanned:
        return True
    if len(page.text.strip()) < 40:
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


def retrieve_context(request: RetrieveRequest) -> RetrieveResponse:
    parsed = parse_persian_query(request.query)
    grade = request.grade or parsed.grade
    subject = request.subject or parsed.subject
    page = request.page or parsed.page
    topic_display = topic_label(parsed.topic) if parsed.topic else parsed.topic_alias

    # Exact page lookup
    if grade and subject and page:
        center = get_page(grade, subject, page)
        if center:
            neighbors = get_neighbor_pages(grade, subject, page, request.include_neighbors)
            needs_image = _needs_image(center, request.include_image)
            response = RetrieveResponse(
                matched=True,
                match_type="exact_page",
                grade=grade,
                subject=subject,
                subject_title=center.subject_title or SUBJECT_TITLES.get(subject, subject),
                page=page,
                context_text=_build_context_text(center, neighbors, topic=topic_display),
                confidence=max(parsed.confidence, 0.9),
                detected_topic=parsed.topic,
                detected_topic_label=topic_display,
            )
            _attach_image(response, center, needs_image=needs_image)
            return response

    # Topic FTS fallback when grade+subject known
    if grade and subject:
        hits = topic_search(request.query, grade=grade, subject=subject, limit=2)
        if hits:
            blocks = [_format_page_block(hit) for hit in hits]
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
                confidence=max(parsed.confidence, 0.6),
            )
            _attach_image(response, primary, needs_image=needs_image)
            return response

    # Broader topic search
    hits = topic_search(request.query, grade=grade, subject=subject, limit=2)
    if hits:
        primary = hits[0]
        blocks = [_format_page_block(hit) for hit in hits]
        needs_image = _needs_image(primary, request.include_image)
        response = RetrieveResponse(
            matched=True,
            match_type="topic_search",
            grade=primary.grade,
            subject=primary.subject,
            subject_title=primary.subject_title,
            page=primary.printed_page,
            context_text="\n\n".join(blocks),
            confidence=0.5,
        )
        _attach_image(response, primary, needs_image=needs_image)
        return response

    return RetrieveResponse(matched=False, match_type="none", confidence=0.0)
