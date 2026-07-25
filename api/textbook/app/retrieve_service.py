from __future__ import annotations

import base64

from api.textbook.app.models import (
    FailureReason,
    IncludeImageMode,
    RetrieveRequest,
    RetrieveResponse,
)
from api.textbook.app.parser import parse_persian_query
from api.textbook.app.subjects import canonical_subject_title, topic_label
from api.textbook.app.store import (
    PageRecord,
    _LESSON_TOC_THRESHOLD,
    _lesson_marker_count,
    book_exists_for_grade,
    find_lesson_containing_page,
    get_lesson_bounds,
    get_lesson_pages,
    get_neighbor_pages,
    get_page,
    get_printed_page_bounds,
    grades_for_subject,
    lesson_search,
    resolve_image_path,
    topic_search,
)
from api.textbook.app.text_quality import is_text_garbled


def _book_title(page: PageRecord) -> str:
    return canonical_subject_title(page.subject, page.subject_title) or page.subject


def _page_text_for_context(page: PageRecord) -> tuple[str, bool]:
    """Return (text for LLM context, is_usable)."""
    raw = page.text.strip()
    if not raw:
        return "[متن استخراج نشد — از تصویر صفحه استفاده کن]", False
    if not page.text_usable or is_text_garbled(raw):
        title_bits = [_book_title(page), f"پایه {page.grade}", f"صفحه {page.printed_page}"]
        note = (
            f"[متن این صفحه ({'، '.join(title_bits)}) به‌درستی و کامل قابل استخراج نبود "
            "(مثلاً خط تحریری/نستعلیق). تصویر صفحه پیوست شده — محتوا را از تصویر بخوان.]"
        )
        return note, False
    return raw, True


def _format_page_block(page: PageRecord, *, topic: str | None = None) -> tuple[str, bool]:
    header = f"--- صفحه {page.printed_page} ({_book_title(page)}، پایه {page.grade})"
    if topic:
        header += f" — بخش: {topic}"
    header += " ---"
    body, usable = _page_text_for_context(page)
    return f"{header}\n{body}", usable


def _title_for(subject: str | None) -> str | None:
    return canonical_subject_title(subject)


def _out_of_range_response(
    *,
    grade: int | None,
    subject: str | None,
    page: int,
    min_page: int,
    max_page: int,
    confidence: float,
) -> RetrieveResponse:
    title = _title_for(subject)
    return RetrieveResponse(
        matched=False,
        match_type="none",
        grade=grade,
        subject=subject,
        subject_title=title,
        page=page,
        confidence=confidence,
        failure_reason="page_out_of_range",
        min_page=min_page,
        max_page=max_page,
    )


def _unmatched(
    *,
    grade: int | None = None,
    subject: str | None = None,
    page: int | None = None,
    lesson: int | None = None,
    chapter: int | None = None,
    confidence: float = 0.0,
    failure_reason: FailureReason | None = None,
    min_page: int | None = None,
    max_page: int | None = None,
    min_lesson: int | None = None,
    max_lesson: int | None = None,
    available_grades: list[int] | None = None,
) -> RetrieveResponse:
    return RetrieveResponse(
        matched=False,
        match_type="none",
        grade=grade,
        subject=subject,
        subject_title=_title_for(subject),
        page=page,
        lesson=lesson,
        chapter=chapter,
        confidence=confidence,
        failure_reason=failure_reason,
        min_page=min_page,
        max_page=max_page,
        min_lesson=min_lesson,
        max_lesson=max_lesson,
        available_grades=available_grades,
    )


def _build_exact_page_response(
    *,
    grade: int,
    subject: str,
    page: int,
    include_neighbors: int,
    include_image: IncludeImageMode,
    confidence: float,
    topic: str | None = None,
    detected_topic: str | None = None,
    chapter: int | None = None,
    lesson: int | None = None,
) -> RetrieveResponse | None:
    """Exact page (+ tiny neighbors). Returns None if the page is not in the index."""
    center = get_page(grade, subject, page)
    if not center:
        return None
    neighbor_n = min(include_neighbors, 1)
    neighbors = get_neighbor_pages(grade, subject, page, neighbor_n)
    needs_image = _needs_image(center, include_image)
    context_text, text_usable = _build_context_text(
        center, neighbors, topic=topic
    )
    lesson_hit = find_lesson_containing_page(grade, subject, page)
    response_lesson = lesson
    if lesson_hit is not None:
        lesson_no, start_page, end_page = lesson_hit
        span = (end_page - start_page) if end_page and start_page else 99
        if span <= 8:
            hint = (
                f"توجه: صفحه {page} داخل درس/فصل {lesson_no} "
                f"(صفحات {start_page} تا {end_page}) است. "
                f"کودک همین صفحه {page} را خواسته — فقط همین صفحه را "
                f"محتوای «این صفحه» بدان.\n\n"
            )
            context_text = hint + (context_text or "")
            if response_lesson is None:
                response_lesson = lesson_no
        else:
            hint = (
                f"توجه: کودک صفحه {page} را خواسته. "
                f"فقط همین صفحه (+همسایهٔ کوتاه) را توصیف کن؛ "
                f"از روی صفحات دیگر داستان نساز.\n\n"
            )
            context_text = hint + (context_text or "")
    response = RetrieveResponse(
        matched=True,
        match_type="exact_page",
        grade=grade,
        subject=subject,
        subject_title=_book_title(center),
        page=page,
        lesson=response_lesson,
        chapter=chapter,
        context_text=context_text,
        text_usable=text_usable,
        confidence=confidence,
        detected_topic=detected_topic,
        detected_topic_label=topic,
    )
    _attach_image(response, center, needs_image=needs_image)
    return response


def _resolve_page_bounds(
    grade: int | None,
    subject: str | None,
) -> tuple[int, int] | None:
    if not subject:
        return None
    return get_printed_page_bounds(grade, subject)

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


_MAX_LESSON_IMAGES = 2
_LLM_IMAGE_MAX_SIDE = 1280
_LLM_IMAGE_JPEG_QUALITY = 60
_LLM_IMAGE_MAX_BYTES = 450_000


def _encode_page_image_b64(page: PageRecord) -> str | None:
    """Compress page PNG to a small JPEG for LLM context (avoids OOM)."""
    image_file = resolve_image_path(page.image_path)
    if not image_file or not image_file.is_file():
        return None
    try:
        from io import BytesIO

        from PIL import Image

        with Image.open(image_file) as img:
            img = img.convert("RGB")
            img.thumbnail((_LLM_IMAGE_MAX_SIDE, _LLM_IMAGE_MAX_SIDE), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=_LLM_IMAGE_JPEG_QUALITY, optimize=True)
            raw = buf.getvalue()
        if len(raw) > _LLM_IMAGE_MAX_BYTES:
            return None
        return base64.b64encode(raw).decode("ascii")
    except Exception:  # noqa: BLE001 — image is optional
        return None


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
    encoded = _encode_page_image_b64(page)
    if encoded:
        response.image_base64 = encoded


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
        encoded = _encode_page_image_b64(page)
        if not encoded:
            continue
        encoded_images.append(encoded)
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
        f"({_book_title(primary)}، پایه {primary.grade}). "
        "برای درخواست‌هایی مثل کلمات سختِ کل درس یا بقیهٔ درس، از همهٔ این صفحات استفاده کن؛ "
        "از کودک نخواه صفحهٔ بعد را خودش باز کند."
    )
    if prefer_page is not None:
        header += (
            f" کودک صفحه {prefer_page} را مشخص کرده؛ "
            f"اگر پرسید «این صفحه / محتویات صفحه»، فقط بلوک «صفحه {prefer_page}» را توصیف کن "
            "و محتوای صفحات دیگر را به آن صفحه نسبت نده."
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
        subject_title=_book_title(primary),
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
        "در مورد",
        "درمورد",
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
        subject_title=_book_title(primary),
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
    # Structured fields from chat scope win; query is only for topic / legacy NL.
    from api.textbook.app.toc_agent import lookup_toc_by_title, lookup_toc_start_page

    parsed = (
        parse_persian_query(request.query)
        if (request.query or "").strip()
        else parse_persian_query("")
    )
    grade = request.grade if request.grade is not None else parsed.grade
    subject = request.subject or parsed.subject
    page = request.page if request.page is not None else parsed.page
    lesson = request.lesson if request.lesson is not None else parsed.lesson
    chapter = (
        request.chapter if request.chapter is not None else getattr(parsed, "chapter", None)
    )
    topic_display = topic_label(parsed.topic) if parsed.topic else parsed.topic_alias

    # Named lesson title in query (e.g. «ارزش علم») — resolve via TOC before
    # chapter-start lookup so we open the real درس, not the first page of فصل.
    title_needle = (parsed.search_text or request.query or "").strip()
    if (
        grade
        and subject
        and page is None
        and title_needle
        and _is_topic_search_query(
            request.query,
            parsed_topic=parsed.topic,
            wants_topic_search=parsed.wants_topic_search,
            search_text=parsed.search_text or title_needle,
        )
    ):
        title_page = lookup_toc_by_title(grade, subject, title_needle)
        if title_page is not None:
            page = title_page
            if not topic_display:
                topic_display = title_needle

    # Page + book without grade: still catch impossible page numbers against
    # the subject's printed-page range across grades (existing MinerU index).
    if page and subject and not grade:
        bounds = _resolve_page_bounds(None, subject)
        if bounds is not None:
            min_page, max_page = bounds
            if page < min_page or page > max_page:
                return _out_of_range_response(
                    grade=None,
                    subject=subject,
                    page=page,
                    min_page=min_page,
                    max_page=max_page,
                    confidence=parsed.confidence,
                )
        return _unmatched(
            grade=grade,
            subject=subject,
            page=page,
            lesson=lesson,
            chapter=chapter,
            confidence=parsed.confidence,
            failure_reason="need_grade_or_subject",
        )

    # A page/lesson/chapter is only meaningful together with a specific book + grade.
    if (page or lesson or chapter) and not (grade and subject):
        return _unmatched(
            grade=grade,
            subject=subject,
            page=page,
            lesson=lesson,
            chapter=chapter,
            confidence=parsed.confidence,
            failure_reason="need_grade_or_subject",
        )

    # Known book+grade that is not offered in the catalog/index
    # (e.g. کار و فناوری / تفکر و پژوهش فقط پایه ششم).
    if grade is not None and subject and not book_exists_for_grade(grade, subject):
        return _unmatched(
            grade=grade,
            subject=subject,
            page=page,
            lesson=lesson,
            chapter=chapter,
            confidence=max(parsed.confidence, 0.9),
            failure_reason="book_unavailable",
            available_grades=grades_for_subject(subject) or None,
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

    # Chapter via TOC map (فصل ≠ درس; OCR header maps conflate them).
    if grade and subject and chapter is not None and page is None:
        toc_page = lookup_toc_start_page(grade, subject, chapter=chapter)
        if toc_page is not None:
            page = toc_page
        elif lesson is None:
            # Fall through to topic/title search when the query has usable text
            # (e.g. «ارزش علم») instead of hard-failing lesson_missing.
            if not _is_topic_search_query(
                request.query,
                parsed_topic=parsed.topic,
                wants_topic_search=parsed.wants_topic_search,
                search_text=parsed.search_text or (request.query or "").strip() or None,
            ):
                return _unmatched(
                    grade=grade,
                    subject=subject,
                    chapter=chapter,
                    confidence=parsed.confidence,
                    failure_reason="lesson_missing",
                )

    # Exact page lookup — stay on that page (+ neighbors). Do NOT expand to the
    # whole lesson span: weak OCR chapter maps often glue several دروس together
    # (e.g. pages 30–43) and the model then attributes later-lesson text to the
    # child's page («صفحه ۳۴ چیه؟» → محتوای «ارزش علم» از صفحه ۳۶).
    if grade and subject and page:
        bounds = _resolve_page_bounds(grade, subject)
        if bounds is not None:
            min_page, max_page = bounds
            if page < min_page or page > max_page:
                return _out_of_range_response(
                    grade=grade,
                    subject=subject,
                    page=page,
                    min_page=min_page,
                    max_page=max_page,
                    confidence=parsed.confidence,
                )

        exact = _build_exact_page_response(
            grade=grade,
            subject=subject,
            page=page,
            include_neighbors=request.include_neighbors,
            include_image=request.include_image,
            confidence=max(parsed.confidence, 0.9),
            topic=topic_display,
            detected_topic=parsed.topic,
            chapter=chapter,
            lesson=lesson,
        )
        if exact is not None:
            return exact

        # Inside printed range but missing from index — do not guess content.
        min_page = bounds[0] if bounds else None
        max_page = bounds[1] if bounds else None
        return _unmatched(
            grade=grade,
            subject=subject,
            page=page,
            chapter=chapter,
            lesson=lesson,
            confidence=parsed.confidence,
            failure_reason="page_missing",
            min_page=min_page,
            max_page=max_page,
        )

    # Lesson lookup — OCR header map first, then TOC fallback.
    if grade and subject and lesson:
        lesson_bounds = get_lesson_bounds(grade, subject)
        if lesson_bounds is not None:
            min_lesson, max_lesson = lesson_bounds
            if lesson < min_lesson or lesson > max_lesson:
                return _unmatched(
                    grade=grade,
                    subject=subject,
                    lesson=lesson,
                    confidence=parsed.confidence,
                    failure_reason="lesson_out_of_range",
                    min_lesson=min_lesson,
                    max_lesson=max_lesson,
                )

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
        # Fallback to start page only (legacy behavior) — but never a TOC page
        # that only lists many دروس (would make the model invent the lesson body).
        center = lesson_search(grade, subject, lesson)
        if center and _lesson_marker_count(center.text or "") < _LESSON_TOC_THRESHOLD:
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
                subject_title=_book_title(center),
                page=center.printed_page,
                context_text=context_text,
                text_usable=text_usable,
                confidence=max(parsed.confidence, 0.8),
                detected_topic=parsed.topic,
                detected_topic_label=topic_display,
                lesson=lesson,
            )
            _attach_image(response, center, needs_image=needs_image)
            return response

        # OCR header miss / TOC-only hit → resolve via cached فهرست map.
        toc_page = lookup_toc_start_page(grade, subject, lesson=lesson)
        if toc_page is not None:
            exact = _build_exact_page_response(
                grade=grade,
                subject=subject,
                page=toc_page,
                include_neighbors=request.include_neighbors,
                include_image=request.include_image,
                confidence=max(parsed.confidence, 0.85),
                topic=topic_display,
                detected_topic=parsed.topic,
                lesson=lesson,
            )
            if exact is not None:
                return exact

        # In-range (or unknown bounds) but OCR header not found / only TOC hit.
        extra: dict[str, int] = {}
        if lesson_bounds is not None:
            extra["min_lesson"] = lesson_bounds[0]
            extra["max_lesson"] = lesson_bounds[1]
        return _unmatched(
            grade=grade,
            subject=subject,
            lesson=lesson,
            confidence=parsed.confidence,
            failure_reason="lesson_missing",
            **extra,
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

    return _unmatched(confidence=0.0)
