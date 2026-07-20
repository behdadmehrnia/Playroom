from __future__ import annotations

import base64

from api.textbook.app.models import IncludeImageMode, MatchType, RetrieveRequest, RetrieveResponse
from api.textbook.app.parser import parse_persian_query
from api.textbook.app.subjects import SUBJECT_TITLES, topic_label
from api.textbook.app.store import (
    PageRecord,
    get_lesson_pages,
    get_neighbor_pages,
    get_page,
    lesson_search,
    resolve_image_path,
    topic_search,
)
from api.textbook.app.text_quality import is_text_garbled


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


_MAX_LESSON_IMAGES = 4


def _attach_lesson_images(
    response: RetrieveResponse,
    pages: list[PageRecord],
    *,
    include_image: IncludeImageMode,
    prefer_page: int | None = None,
) -> None:
    """Attach up to N page images, prioritizing unreadable pages and the user's page."""
    if include_image == "never" or not pages:
        return
    ranked = sorted(
        pages,
        key=lambda p: (
            0 if prefer_page is not None and p.printed_page == prefer_page else 1,
            0 if _needs_image(p, "auto" if include_image == "always" else include_image) else 1,
            p.printed_page,
        ),
    )
    encoded_images: list[str] = []
    for page in ranked:
        if include_image != "always" and not _needs_image(page, include_image):
            continue
        image_file = resolve_image_path(page.image_path)
        if not image_file or not image_file.is_file():
            continue
        encoded_images.append(base64.b64encode(image_file.read_bytes()).decode("ascii"))
        if len(encoded_images) >= _MAX_LESSON_IMAGES:
            break
    if not encoded_images:
        return
    response.needs_image = True
    response.image_base64 = encoded_images[0]
    # Stash extras in context_text header note; pipe reads image_base64 only today.
    # Extra images are joined with a delimiter the pipe understands.
    if len(encoded_images) > 1:
        response.image_base64 = "\n---YK_IMAGE---\n".join(encoded_images)
    first = pages[0]
    response.image_url = (
        f"/v1/page-image?grade={first.grade}&subject={first.subject}&page={first.printed_page}"
    )


def _build_lesson_span_response(
    pages: list[PageRecord],
    *,
    lesson_number: int | None,
    start_page: int | None,
    end_page: int | None,
    include_image: IncludeImageMode,
    confidence: float,
    prefer_page: int | None = None,
    topic: str | None = None,
) -> RetrieveResponse:
    primary = pages[0]
    label_bits = []
    if lesson_number:
        label_bits.append(f"درس {lesson_number}")
    if start_page and end_page:
        label_bits.append(f"صفحات {start_page} تا {end_page}")
    span_label = " — ".join(label_bits) if label_bits else "کل درس"
    header = (
        f"توجه: متن کامل «{span_label}» در ادامه آمده است "
        f"({primary.subject_title}، پایه {primary.grade}). "
        "برای درخواست‌هایی مثل کلمات سختِ کل درس یا بقیهٔ درس، از همهٔ این صفحات استفاده کن؛ "
        "از کودک نخواه صفحهٔ بعد را خودش باز کند."
    )
    blocks: list[str] = [header]
    all_usable = True
    for page in pages:
        block, ok = _format_page_block(page, topic=topic)
        blocks.append(block)
        all_usable = all_usable and ok
    response = RetrieveResponse(
        matched=True,
        match_type="lesson_span",
        grade=primary.grade,
        subject=primary.subject,
        subject_title=primary.subject_title or SUBJECT_TITLES.get(primary.subject, primary.subject),
        page=prefer_page or primary.printed_page,
        context_text="\n\n".join(blocks),
        text_usable=all_usable,
        confidence=confidence,
        detected_topic_label=span_label,
    )
    _attach_lesson_images(
        response,
        pages,
        include_image=include_image,
        prefer_page=prefer_page,
    )
    return response


def _is_topic_search_query(
    query: str,
    *,
    parsed_topic: str | None = None,
    wants_topic_search: bool = False,
    search_text: str | None = None,
) -> bool:
    """
    Topic search should only run for real content requests, not bare subject picks.

    Examples that SHOULD search:
      - «درس ستایش فارسی ششم»
      - «معنی شعر ستایش»
      - «کجای کتاب مربوط به میرزا کوچک خان»
      - «تمرین سوم ریاضی»

    Examples that should NOT search:
      - «ریاضی»
      - «فارسی»
    """
    if wants_topic_search:
        return True
    if parsed_topic:
        return True
    # Only treat free-text as topical when it looks like a real name/phrase.
    # Single tokens like «ستایش» (5 chars) should search; bare subjects are
    # usually stripped out of search_text by the parser.
    if search_text and (len(search_text.split()) >= 2 or len(search_text) >= 5):
        return True
    normalized = query.strip()
    if not normalized:
        return False
    content_markers = (
        "تمرین",
        "متن",
        "شعر",
        "معنی",
        "سوال",
        "بخوان",
        "بخوانیم",
        "مربوط",
        "کجا",
        "درباره",
        "فعالیت",
        "داستان",
    )
    return any(marker in normalized for marker in content_markers)


def _topic_hit_score(page: PageRecord, needle: str) -> int:
    text = (page.text or "").replace("\u200c", "")
    compact = text.replace(" ", "")
    tokens = [t.replace("\u200c", "") for t in needle.split() if len(t) >= 2]
    score = 0
    for token in tokens:
        if token in text:
            score += 3
    for i in range(len(tokens)):
        for j in range(i + 1, min(i + 3, len(tokens) + 1)):
            part = "".join(tokens[i:j])
            if len(part) >= 4 and part in compact:
                score += 6
    return score


def _run_topic_search(
    *,
    query: str,
    search_text: str | None,
    grade: int | None,
    subject: str | None,
    limit: int = 5,
) -> list[PageRecord]:
    needle = (search_text or query).strip()
    if not needle:
        return []

    candidates: list[PageRecord] = []
    seen: set[tuple[int, str, int]] = set()

    def _add(pages: list[PageRecord]) -> None:
        for page in pages:
            key = (page.grade, page.subject, page.printed_page)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(page)

    # Prefer scoped search, then relax grade/subject so distinctive names still match.
    _add(topic_search(needle, grade=grade, subject=subject, limit=limit))
    if subject is not None:
        _add(topic_search(needle, grade=grade, subject=None, limit=limit))
    if grade is not None or subject is not None:
        _add(topic_search(needle, grade=None, subject=None, limit=limit))
    if not candidates:
        _add(topic_search(needle, grade=None, subject=None, limit=limit))

    if not candidates:
        return []
    ranked = sorted(
        candidates,
        key=lambda p: _topic_hit_score(p, needle),
        reverse=True,
    )
    best = _topic_hit_score(ranked[0], needle)
    if best >= 6:
        ranked = [p for p in ranked if _topic_hit_score(p, needle) >= max(3, best // 2)]
    return ranked[:limit]


def _expand_topic_hits_to_lesson(
    hits: list[PageRecord],
    *,
    topic: str | None,
    include_image: IncludeImageMode,
    confidence: float,
    search_label: str | None,
) -> RetrieveResponse | None:
    """
    Prefer a full lesson span around the best topic hit so the model gets
    complete textbook context (not just a single matching page).
    """
    if not hits:
        return None
    primary = hits[0]
    pages, lesson_no, start_page, end_page = get_lesson_pages(
        primary.grade,
        primary.subject,
        page=primary.printed_page,
    )
    # Only treat as a lesson when we actually span more than the hit page.
    if len(pages) >= 2 and start_page is not None and end_page is not None:
        if end_page > start_page:
            return _build_lesson_span_response(
                pages,
                lesson_number=lesson_no,
                start_page=start_page,
                end_page=end_page,
                include_image=include_image,
                confidence=confidence,
                prefer_page=primary.printed_page,
                topic=topic or search_label,
            )
    return None


def _build_topic_search_response(
    hits: list[PageRecord],
    *,
    include_neighbors: int,
    include_image: IncludeImageMode,
    confidence: float,
    topic: str | None,
    topic_label: str | None,
    search_label: str | None,
) -> RetrieveResponse:
    """Build topic-search context: lesson span when possible, else pages + neighbors."""
    expanded = _expand_topic_hits_to_lesson(
        hits,
        topic=topic_label or topic,
        include_image=include_image,
        confidence=max(confidence, 0.7),
        search_label=search_label,
    )
    if expanded is not None:
        # Keep match_type as topic_search so callers know how we found it,
        # but retain the full lesson body from the span builder.
        expanded.match_type = "topic_search"
        if search_label and not expanded.detected_topic_label:
            expanded.detected_topic_label = search_label
        expanded.detected_topic = topic or expanded.detected_topic
        return expanded

    # Fallback: primary hit ± neighbors, plus up to two extra distinct hits.
    primary = hits[0]
    neighbor_radius = max(include_neighbors, 2)
    ordered: list[PageRecord] = []
    seen: set[tuple[int, str, int]] = set()

    def _push(page: PageRecord) -> None:
        key = (page.grade, page.subject, page.printed_page)
        if key in seen:
            return
        seen.add(key)
        ordered.append(page)

    for neighbor in get_neighbor_pages(
        primary.grade, primary.subject, primary.printed_page, neighbor_radius
    ):
        if neighbor.printed_page < primary.printed_page:
            _push(neighbor)
    _push(primary)
    for neighbor in get_neighbor_pages(
        primary.grade, primary.subject, primary.printed_page, neighbor_radius
    ):
        if neighbor.printed_page > primary.printed_page:
            _push(neighbor)

    for hit in hits[1:3]:
        # Skip hits already covered by the primary window.
        if hit.grade == primary.grade and hit.subject == primary.subject:
            if abs(hit.printed_page - primary.printed_page) <= neighbor_radius:
                continue
        _push(hit)
        for neighbor in get_neighbor_pages(
            hit.grade, hit.subject, hit.printed_page, 1
        ):
            _push(neighbor)

    blocks: list[str] = []
    all_usable = True
    for page in ordered:
        block, ok = _format_page_block(page, topic=topic_label or search_label)
        blocks.append(block)
        all_usable = all_usable and ok

    response = RetrieveResponse(
        matched=True,
        match_type="topic_search",
        grade=primary.grade,
        subject=primary.subject,
        subject_title=primary.subject_title
        or SUBJECT_TITLES.get(primary.subject, primary.subject),
        page=primary.printed_page,
        context_text="\n\n".join(blocks),
        text_usable=all_usable,
        confidence=max(confidence, 0.6),
        detected_topic=topic,
        detected_topic_label=topic_label or search_label,
    )
    _attach_image(response, primary, needs_image=_needs_image(primary, include_image))
    return response


def retrieve_context(request: RetrieveRequest) -> RetrieveResponse:
    parsed = parse_persian_query(request.query)
    grade = request.grade or parsed.grade
    subject = request.subject or parsed.subject
    page = request.page or parsed.page
    lesson = parsed.lesson
    topic_display = topic_label(parsed.topic) if parsed.topic else parsed.topic_alias

    # A page/lesson is only meaningful together with a specific book + grade.
    if (page or lesson) and not (grade and subject):
        return RetrieveResponse(
            matched=False,
            match_type="none",
            grade=grade,
            subject=subject,
            subject_title=SUBJECT_TITLES.get(subject) if subject else None,
            page=page,
            confidence=parsed.confidence,
        )

    # Whole-lesson span (کل درس / بقیه درس / کلمات سخت کل درس)
    if parsed.wants_whole_lesson and grade and subject and (page or lesson):
        pages, lesson_no, start_page, end_page = get_lesson_pages(
            grade,
            subject,
            lesson_number=lesson,
            page=page,
        )
        if pages:
            return _build_lesson_span_response(
                pages,
                lesson_number=lesson_no or lesson,
                start_page=start_page,
                end_page=end_page,
                include_image=request.include_image,
                confidence=max(parsed.confidence, 0.9),
                prefer_page=page,
                topic=topic_display,
            )

    # Exact page lookup
    if grade and subject and page:
        # If user asked for a numbered lesson without "کل درس", still prefer
        # the single page they named; whole-lesson is handled above.
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

    # Lesson / chapter lookup — return the full lesson span (all its pages).
    if grade and subject and lesson:
        pages, lesson_no, start_page, end_page = get_lesson_pages(
            grade,
            subject,
            lesson_number=lesson,
        )
        if pages:
            return _build_lesson_span_response(
                pages,
                lesson_number=lesson_no or lesson,
                start_page=start_page,
                end_page=end_page,
                include_image=request.include_image,
                confidence=max(parsed.confidence, 0.85),
                prefer_page=start_page,
                topic=topic_display,
            )
        # Fallback to start page only (legacy behavior)
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
        return RetrieveResponse(
            matched=False,
            match_type="none",
            grade=grade,
            subject=subject,
            subject_title=SUBJECT_TITLES.get(subject, subject),
            confidence=parsed.confidence,
        )

    # Topic / named-content FTS search — expand to full lesson when possible.
    if _is_topic_search_query(
        request.query,
        parsed_topic=parsed.topic,
        wants_topic_search=parsed.wants_topic_search,
        search_text=parsed.search_text,
    ):
        # Prefer having at least one of grade/subject; still allow global search
        # for distinctive names like «میرزا کوچک خان».
        if grade or subject or (parsed.search_text and len(parsed.search_text) >= 4):
            hits = _run_topic_search(
                query=request.query,
                search_text=parsed.search_text,
                grade=grade,
                subject=subject,
                limit=5,
            )
            if hits:
                return _build_topic_search_response(
                    hits,
                    include_neighbors=request.include_neighbors,
                    include_image=request.include_image,
                    confidence=parsed.confidence,
                    topic=parsed.topic,
                    topic_label=topic_display,
                    search_label=parsed.search_text,
                )

    return RetrieveResponse(matched=False, match_type="none", confidence=0.0)
