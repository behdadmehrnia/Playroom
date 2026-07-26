from __future__ import annotations

import base64
import re

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
    book_exists_for_grade,
    find_lesson_containing_page,
    format_catalog_outline,
    get_catalog_book,
    get_chapter_bounds,
    get_chapter_pages,
    get_lesson_bounds,
    get_lesson_pages,
    get_neighbor_pages,
    get_page,
    get_printed_page_bounds,
    grades_for_subject,
    lookup_catalog_entry_by_title,
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
    min_chapter: int | None = None,
    max_chapter: int | None = None,
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
        min_chapter=min_chapter,
        max_chapter=max_chapter,
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
    """Prefer attaching page images: OCR text is unreliable for exercises/figures."""
    if include_image == "never":
        return False
    if include_image == "always":
        return True
    # auto — still prefer vision whenever we have a page record
    return True


_MAX_LESSON_IMAGES = 3
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
            for quality in (_LLM_IMAGE_JPEG_QUALITY, 45, 35):
                buf = BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True)
                raw = buf.getvalue()
                if len(raw) <= _LLM_IMAGE_MAX_BYTES:
                    return base64.b64encode(raw).decode("ascii")
            # Last resort: smaller thumbnail
            img.thumbnail((960, 960), Image.Resampling.LANCZOS)
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=35, optimize=True)
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
    """Attach up to N page images; prefer the child's page, then earliest pages."""
    if include_image == "never" or not pages:
        return
    # Always mark that vision is preferred for this span (even if encode fails).
    response.needs_image = True
    ranked = sorted(
        pages,
        key=lambda p: (
            0 if prefer_page is not None and p.printed_page == prefer_page else 1,
            p.printed_page,
        ),
    )
    encoded_images: list[str] = []
    first_with_path: PageRecord | None = None
    for page in ranked:
        if first_with_path is None and page.image_path:
            first_with_path = page
        encoded = _encode_page_image_b64(page)
        if not encoded:
            continue
        encoded_images.append(encoded)
        if len(encoded_images) >= _MAX_LESSON_IMAGES:
            break
    anchor = next((p for p in ranked if prefer_page and p.printed_page == prefer_page), None)
    anchor = anchor or first_with_path or pages[0]
    if anchor.grade and anchor.subject and anchor.printed_page:
        response.image_url = (
            f"/v1/page-image?grade={anchor.grade}"
            f"&subject={anchor.subject}&page={anchor.printed_page}"
        )
    if not encoded_images:
        return
    response.image_base64 = encoded_images[0]
    if len(encoded_images) > 1:
        response.image_base64 = "\n---YK_IMAGE---\n".join(encoded_images)


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
    chapter: int | None = None,
    unit_label: str = "درس",
    outline_prefix: str | None = None,
) -> RetrieveResponse:
    primary = pages[0]
    label_bits = []
    if chapter is not None:
        book = get_catalog_book(primary.grade, primary.subject)
        parent = (book.parent_label if book else None) or "فصل"
        label_bits.append(f"{parent} {chapter}")
    if lesson_number:
        label_bits.append(f"{unit_label} {lesson_number}")
    if start_page and end_page:
        label_bits.append(f"صفحات {start_page} تا {end_page}")
    span_label = " — ".join(label_bits) if label_bits else f"کل {unit_label}"
    header = (
        f"توجه: متن کامل «{span_label}» در ادامه آمده است "
        f"({_book_title(primary)}، پایه {primary.grade}). "
        "برای درخواست‌هایی مثل کلمات سختِ کل درس یا بقیهٔ درس یا تمرین‌های این بخش، "
        "از همهٔ این صفحات استفاده کن؛ از کودک نخواه صفحهٔ بعد را خودش باز کند."
    )
    if prefer_page is not None:
        header += (
            f" کودک صفحه {prefer_page} را مشخص کرده؛ "
            f"اگر پرسید «این صفحه / محتویات صفحه»، فقط بلوک «صفحه {prefer_page}» را توصیف کن "
            "و محتوای صفحات دیگر را به آن صفحه نسبت نده."
        )
    blocks: list[str] = []
    if outline_prefix:
        blocks.append(outline_prefix)
    blocks.append(header)
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
        lesson=lesson_number,
        chapter=chapter,
    )
    _attach_lesson_images(
        response,
        pages,
        include_image=include_image,
        prefer_page=prefer_page,
    )
    return response


def _build_outline_response(
    *,
    grade: int,
    subject: str,
    chapter: int | None,
    confidence: float,
) -> RetrieveResponse | None:
    outline = format_catalog_outline(grade, subject, chapter=chapter)
    if not outline:
        return None
    book = get_catalog_book(grade, subject)
    title = book.title if book else subject
    return RetrieveResponse(
        matched=True,
        match_type="catalog_outline",
        grade=grade,
        subject=subject,
        subject_title=title,
        page=None,
        context_text=(
            "توجه: فهرست ساختار کتاب از روی نقشهٔ رسمی catalog آمده است. "
            "**همین فهرست را برای کودک بخوان** (عنوان و شمارهٔ واحدها). "
            "فقط از همین برچسب‌ها (فصل/بخش/درس/جلسه/مهارت/پروژه) استفاده کن؛ "
            "ساختار یا شمارهٔ واحدی که اینجا نیست اختراع نکن. "
            "**ممنوع:** گفتن «لیست را ندارم» یا «کتاب‌ها ممکن است تغییر کنند».\n\n"
            + outline
        ),
        text_usable=True,
        confidence=confidence,
        detected_topic_label="فهرست کتاب",
        chapter=chapter,
    )


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
    kind = request.kind if request.kind is not None else getattr(parsed, "kind", None)
    wants_outline = bool(request.wants_outline or getattr(parsed, "wants_outline", False))
    topic_display = topic_label(parsed.topic) if parsed.topic else parsed.topic_alias

    def _unit_label() -> str:
        from api.textbook.app.store import KIND_LABELS

        return KIND_LABELS.get(kind or "lesson", "درس")

    # Named lesson/chapter title («ارزش علم»، «هفت خان رستم»، «کسر») —
    # prefer full unit span so exercise / "کل درس" style asks get every page.
    # When the user already named فصل/درس N, don't let a weak leftover topic
    # (book-name fragment) override the numeric unit.
    title_needle = (parsed.search_text or request.query or "").strip()
    title_hit = None
    # Allow short catalog titles («کسر») once grade+subject are known.
    can_title_lookup = bool(title_needle) and (
        parsed.wants_topic_search
        or parsed.topic
        or len(title_needle.split()) >= 2
        or len(title_needle) >= 3
        or _is_topic_search_query(
            request.query,
            parsed_topic=parsed.topic,
            wants_topic_search=parsed.wants_topic_search,
            search_text=parsed.search_text or title_needle,
        )
    )
    strong_title = bool(title_needle) and (
        (lesson is None and chapter is None) or len(title_needle.split()) >= 2
    )
    if (
        grade
        and subject
        and page is None
        and not wants_outline
        and strong_title
        and can_title_lookup
    ):
        # Try cleaned search_text first, then raw query — stopwords can drop
        # connectors that are part of real titles («تقسیم با باقی‌مانده»).
        needles: list[str] = []
        for candidate in (parsed.search_text, request.query, title_needle):
            cleaned = (candidate or "").strip()
            if cleaned and cleaned not in needles:
                needles.append(cleaned)
        best_hit = None
        for needle in needles:
            hit = lookup_catalog_entry_by_title(grade, subject, needle)
            if hit is None:
                continue
            if best_hit is None or hit.score > best_hit.score:
                best_hit = hit
        title_hit = best_hit
        if title_hit is not None and not topic_display:
            topic_display = title_hit.title or title_needle

    if (
        title_hit is not None
        and grade
        and subject
        and page is None
        and lesson is None
        and (chapter is None or title_hit.unit == "lesson")
    ):
        if title_hit.unit == "lesson" and title_hit.number is not None:
            from api.textbook.app.store import KIND_LABELS

            pages, lesson_no, start_page, end_page = get_lesson_pages(
                grade,
                subject,
                lesson_number=title_hit.number,
                kind=title_hit.kind,
            )
            if pages:
                return _build_lesson_span_response(
                    pages,
                    lesson_number=lesson_no or title_hit.number,
                    start_page=start_page,
                    end_page=end_page,
                    include_image=request.include_image,
                    confidence=max(parsed.confidence, 0.9),
                    prefer_page=start_page,
                    topic=topic_display,
                    chapter=title_hit.chapter,
                    unit_label=KIND_LABELS.get(title_hit.kind, "درس"),
                )
        elif title_hit.unit == "chapter" and title_hit.number is not None:
            chapter = title_hit.number
        else:
            page = title_hit.start_page
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

    # A page/lesson/chapter/outline is only meaningful with a specific book + grade.
    if (page or lesson or chapter or wants_outline) and not (grade and subject):
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

    # Catalog structure outline («لیست فصل‌ها / فهرست مهارت‌ها»)
    if wants_outline and grade and subject:
        if chapter is not None:
            chapter_bounds = get_chapter_bounds(grade, subject)
            if chapter_bounds is not None:
                min_ch, max_ch = chapter_bounds
                if chapter < min_ch or chapter > max_ch:
                    lesson_bounds = get_lesson_bounds(grade, subject, kind=kind)
                    return _unmatched(
                        grade=grade,
                        subject=subject,
                        chapter=chapter,
                        confidence=max(parsed.confidence, 0.9),
                        failure_reason="chapter_out_of_range",
                        min_chapter=min_ch,
                        max_chapter=max_ch,
                        min_lesson=lesson_bounds[0] if lesson_bounds else None,
                        max_lesson=lesson_bounds[1] if lesson_bounds else None,
                    )
            elif get_catalog_book(grade, subject) is not None:
                # Flat book: no parent units — report child bounds instead.
                lesson_bounds = get_lesson_bounds(grade, subject, kind=kind)
                if lesson_bounds is not None and (
                    chapter < lesson_bounds[0] or chapter > lesson_bounds[1]
                ):
                    return _unmatched(
                        grade=grade,
                        subject=subject,
                        chapter=chapter,
                        lesson=chapter,
                        confidence=max(parsed.confidence, 0.9),
                        failure_reason="lesson_out_of_range",
                        min_lesson=lesson_bounds[0],
                        max_lesson=lesson_bounds[1],
                    )
        outline = _build_outline_response(
            grade=grade,
            subject=subject,
            chapter=chapter,
            confidence=max(parsed.confidence, 0.9),
        )
        if outline is not None:
            return outline
        return _unmatched(
            grade=grade,
            subject=subject,
            chapter=chapter,
            confidence=parsed.confidence,
            failure_reason="lesson_missing",
        )

    # Whole-lesson span (کل درس / بقیه درس / کلمات سخت کل درس)
    if parsed.wants_whole_lesson and grade and subject and (page or lesson):
        pages, lesson_no, start_page, end_page = get_lesson_pages(
            grade,
            subject,
            lesson_number=lesson,
            page=page,
            kind=kind,
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
                unit_label=_unit_label(),
            )

    # Parent unit span (فصل/بخش) — full pages + child outline for exercises.
    if grade and subject and chapter is not None and page is None and lesson is None:
        book = get_catalog_book(grade, subject)
        chapter_bounds = get_chapter_bounds(grade, subject)
        lesson_bounds = get_lesson_bounds(grade, subject, kind=kind)

        # Flat books have no فصل/بخش map — kids often say «فصل» for «درس».
        if book is not None and not book.chapters and lesson_bounds is not None:
            if lesson_bounds[0] <= chapter <= lesson_bounds[1]:
                pages, lesson_no, start_page, end_page = get_lesson_pages(
                    grade,
                    subject,
                    lesson_number=chapter,
                    kind=kind,
                )
                if pages:
                    return _build_lesson_span_response(
                        pages,
                        lesson_number=lesson_no or chapter,
                        start_page=start_page,
                        end_page=end_page,
                        include_image=request.include_image,
                        confidence=max(parsed.confidence, 0.85),
                        prefer_page=start_page,
                        topic=topic_display,
                        unit_label=_unit_label(),
                    )
            return _unmatched(
                grade=grade,
                subject=subject,
                chapter=chapter,
                lesson=chapter,
                confidence=max(parsed.confidence, 0.9),
                failure_reason="lesson_out_of_range",
                min_lesson=lesson_bounds[0],
                max_lesson=lesson_bounds[1],
            )

        if chapter_bounds is not None:
            min_ch, max_ch = chapter_bounds
            if chapter < min_ch or chapter > max_ch:
                return _unmatched(
                    grade=grade,
                    subject=subject,
                    chapter=chapter,
                    confidence=max(parsed.confidence, 0.9),
                    failure_reason="chapter_out_of_range",
                    min_chapter=min_ch,
                    max_chapter=max_ch,
                    min_lesson=lesson_bounds[0] if lesson_bounds else None,
                    max_lesson=lesson_bounds[1] if lesson_bounds else None,
                )

        pages, ch_no, start_page, end_page = get_chapter_pages(
            grade, subject, chapter_number=chapter
        )
        outline = format_catalog_outline(grade, subject, chapter=chapter)
        if pages:
            parent_label = (book.parent_label if book else None) or "فصل"
            return _build_lesson_span_response(
                pages,
                lesson_number=None,
                start_page=start_page,
                end_page=end_page,
                include_image=request.include_image,
                confidence=max(parsed.confidence, 0.9),
                prefer_page=start_page,
                topic=topic_display,
                chapter=ch_no or chapter,
                unit_label=parent_label,
                outline_prefix=outline,
            )
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
                min_chapter=chapter_bounds[0] if chapter_bounds else None,
                max_chapter=chapter_bounds[1] if chapter_bounds else None,
                min_lesson=lesson_bounds[0] if lesson_bounds else None,
                max_lesson=lesson_bounds[1] if lesson_bounds else None,
            )

    # Exact page lookup — stay on that page (+ neighbors).
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

    # Child unit lookup via catalog (درس/جلسه/مهارت/پروژه).
    if grade and subject and lesson:
        lesson_bounds = get_lesson_bounds(grade, subject, kind=kind)
        chapter_bounds = get_chapter_bounds(grade, subject)
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
                    min_chapter=chapter_bounds[0] if chapter_bounds else None,
                    max_chapter=chapter_bounds[1] if chapter_bounds else None,
                )

        pages, lesson_no, start_page, end_page = get_lesson_pages(
            grade,
            subject,
            lesson_number=lesson,
            kind=kind,
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
                unit_label=_unit_label(),
            )

        extra: dict[str, int] = {}
        if lesson_bounds is not None:
            extra["min_lesson"] = lesson_bounds[0]
            extra["max_lesson"] = lesson_bounds[1]
        if chapter_bounds is not None:
            extra["min_chapter"] = chapter_bounds[0]
            extra["max_chapter"] = chapter_bounds[1]
        return _unmatched(
            grade=grade,
            subject=subject,
            lesson=lesson,
            confidence=parsed.confidence,
            failure_reason="lesson_missing",
            **extra,
        )

    # Topic / named-content FTS search — expand to full lesson when possible.
    # If the leftover looks like a structure ask («فصول»، «درس‌ها»)، prefer outline.
    if _is_topic_search_query(
        request.query,
        parsed_topic=parsed.topic,
        wants_topic_search=parsed.wants_topic_search,
        search_text=parsed.search_text,
    ):
        outline_like = bool(
            re.search(
                r"(?:فصول|دروس|جلسات|فصل[\u200c\s]*ها|درس[\u200c\s]*ها|ساختار|فهرست)",
                (parsed.search_text or request.query or ""),
            )
        )
        if outline_like and grade and subject:
            outline = _build_outline_response(
                grade=grade,
                subject=subject,
                chapter=chapter,
                confidence=max(parsed.confidence, 0.85),
            )
            if outline is not None:
                return outline
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
                    confidence=max(parsed.confidence, 0.7),
                    topic=parsed.topic,
                    topic_label=topic_display,
                    search_label=parsed.search_text or topic_display,
                )

    # Known book but nothing matched — not a missing grade/subject.
    if grade and subject:
        return _unmatched(
            grade=grade,
            subject=subject,
            page=page,
            lesson=lesson,
            chapter=chapter,
            confidence=parsed.confidence,
            failure_reason="lesson_missing",
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
