# تست‌های جامع سیستم پرسونا یار کودک

این سند **۸۵ مورد تست (TC-01 … TC-85)** برای ارزیابی رفتار پرسونا، تشخیص نیت، حفظ بافت، کتاب درسی، جستجوی وب، Reflection، امنیت و E2E است.

**منبع حقیقت کد:** سرویس `api/` — منطق دامنه در [`api/core/`](../api/core/)، HTTP در [`api/routes/`](../api/routes/)، orchestration در [`api/service.py`](../api/service.py).

---

## اجرای تست خودکار

```bash
# از ریشهٔ repo
pip install -r requirements-dev.txt
pytest                          # همهٔ تست‌ها
pytest tests/test_core_persona.py -v
pytest tests/test_routes.py -k health
```

| فایل pytest | ماژول API | پوشش تقریبی |
|-------------|-----------|-------------|
| `tests/test_core_persona.py` | `api/core/persona.py`, `intent.py` | TC-01–07, 19–25, 26–30, 84 |
| `tests/test_core_intent.py` | `api/core/intent.py` | TC-06–07, intent parsing |
| `tests/test_core_math.py` | `api/core/math_tool.py` | TC-31–35, 82 |
| `tests/test_core_textbook.py` | `api/core/textbook.py` | TC-10, 36–43, 47, 83 |
| `tests/test_core_web_search.py` | `api/core/web_search.py` | TC-48, 51–52 |
| `tests/test_core_generation.py` | `api/core/generation.py` | TC-59–65, 85 |
| `tests/test_core_messages.py` | `api/core/messages.py` | TC-80, markers |
| `tests/test_core_prompts.py` | `api/core/prompts.py` | بارگذاری پرامپت‌ها |
| `tests/test_core_status.py` | `api/core/status.py` | status helpers |
| `tests/test_service.py` | `api/service.py` | TC-75 (بخشی), orchestration |
| `tests/test_routes.py` | `api/routes/*` | اندپوینت‌های HTTP |
| `tests/test_config.py` | `api/config.py` | env / settings |

**نیازمند LLM واقعی یا شبکه:** TC-08–18 (intent LLM)، TC-38–46 (textbook retrieve)، TC-48–58 (web search live)، TC-66–74 (jailbreak E2E)، TC-75–79 — این‌ها در pytest با `DummyLLM` و mock/stub پوشش جزئی دارند؛ برای QA دستی یا integration با API بالا اجرا شوند.

---

## پرامپت Agent — پیاده‌سازی و اجرای همهٔ تست‌ها

کپی این بلوک را به Agent بدهید:

```text
You are working on the Yar Kids repo at the project root.

Goal: implement, run, and keep green ALL automated tests aligned with
tests/persona_system_tests.md (TC-01 … TC-85).

Architecture (do NOT use removed monoliths api/core.py or api/routes.py):
- Domain logic: api/core/ (persona, intent, math_tool, textbook, web_search,
  generation, messages, prompts, status, constants, types)
- Public imports: from api.core import … (re-exported in api/core/__init__.py)
- HTTP: api/routes/ composed in api/routes/__init__.py
- Orchestration: api/service.py
- Prompts: api/prompts/*.md
- OpenWebUI client: api/pipe/pipe.py (not under test here)

Rules:
1. Read tests/persona_system_tests.md and map each TC to pytest or mark manual.
2. Prefer unit tests in tests/test_core_*.py using api.core helpers directly.
3. Use tests/conftest.py: DummyLLM, test_settings, client (TestClient + lifespan).
4. Never call real LLM or external network in unit tests — stub LLMClient.complete.
5. Match existing pytest style: parametrize where TC tables repeat; @pytest.mark.asyncio
   for async persona/intent/service tests.
6. After changes: pip install -r requirements-dev.txt && pytest
7. When adding a persona constant, update api/core/constants.py SUPPORTED_PERSONAS
   and api/pipe/pipe.py if needed.

For each TC section in the markdown:
- If automated test exists → ensure assertion matches «انتظار» in the TC.
- If missing → add the smallest test in the correct test_core_*.py file.
- If TC requires live LLM/textbook/search → document @pytest.mark.integration and
  skip in default CI, OR test only the deterministic gate (query build, persona gate).

Run order:
  pytest tests/test_core_*.py tests/test_service.py tests/test_routes.py tests/test_config.py -q

Report: list TC IDs covered by pytest, TC IDs still manual-only, and any failures.
```

---

## نگاشت سریع TC → توابع / اندپوینت

| TC | انتظار کلیدی | کد / API |
|----|--------------|----------|
| 01–05 | explicit persona | `api.core._detect_explicit_persona_request` |
| 06–07 | greeting / vague → none | `api.core._looks_like_greeting_only`, `detect_intent` |
| 08–18 | intent LLM | `api.core.detect_intent` (+ `DummyLLM` در pytest) |
| 19–25 | sticky activity | `api.core._should_keep_current_persona`, `resolve_active_persona` |
| 26–30 | manual override | `api.core.resolve_manual_persona`, `POST /v1/persona/resolve` |
| 31–35 | math tool | `api.core.run_math_tool_for_message`, `calculate_math` |
| 36–47 | textbook | `api.core.build_textbook_query`, `fetch_textbook_context`, `POST /v1/textbook/*` |
| 48–54 | web search | `api.core.looks_like_web_search_request`, `POST /v1/web-search/*` |
| 55–58 | anti-hallucination | prompts + generation (manual / LLM QA) |
| 59–65 | reflection | `api.core.reflect_on_response`, `POST /v1/reflect` |
| 66–74 | jailbreak | manual chat QA via `POST /v1/chat` |
| 75–79 | E2E scenarios | `api.service.run_chat`, `POST /v1/chat` |
| 80–85 | edge cases | messages, math, `enable_reflection` valve |

---

## ۱. تست‌های تشخیص نیت و انتخاب پرسونا (Intent Detection & Persona Selection)

### TC-01: انتخاب صریح پرسونا معلم
**ورودی:** «باش معلم»  
**انتظار:** `teacher` با confidence ≥ 0.95  
**pytest:** `test_core_persona.py::test_explicit_persona_triggers`  
**توضیح:** دستور صریح تغییر پرسونا باید اولویت بالایی داشته باشد.

### TC-02: انتخاب صریح پرسونا داستان‌گو
**ورودی:** «قصه بگو»  
**انتظار:** `storyteller` با confidence ≥ 0.95

### TC-03: انتخاب صریح پرسونا کمک‌درس
**ورودی:** «کمک درس باش»  
**انتظار:** `homework` با confidence ≥ 0.95

### TC-04: انتخاب صریح پرسونا بازی
**ورودی:** «بازی کنیم»  
**انتظار:** `gamer` با confidence ≥ 0.95

### TC-05: انتخاب صریح پرسونا خلاق
**ورودی:** «خلاق باش»  
**انتظار:** `creative` با confidence ≥ 0.95

### TC-06: سلام ساده → none
**ورودی:** «سلام!»  
**انتظار:** `none` (بدون confidence)  
**pytest:** `test_core_intent.py::test_detect_intent_greeting_returns_none`

### TC-07: پیام مبهم کوتاه → none
**ورودی:** «کمک»  
**انتظار:** `none`

### TC-08: سوال مفهومی → teacher
**ورودی:** «کسر یعنی چی؟»  
**انتظار:** `teacher` confidence ≥ 0.85  
**نوع:** integration (LLM)

### TC-09: محاسبه ساده → homework
**ورودی:** «۱۲ × ۵ چنده؟»  
**انتظار:** `homework` confidence ≥ 0.85

### TC-10: ارجاع صریح به کتاب درسی → homework
**ورودی:** «صفحه ۷ کتاب فارسی پایه ششم»  
**انتظار:** `homework` confidence ≥ 0.90  
**pytest:** `test_core_textbook.py`, `test_routes.py::test_textbook_query_endpoint`

### TC-11: درخواست داستان → storyteller
**ورودی:** «می‌خوام داستان بشنوم»  
**انتظار:** `storyteller` confidence ≥ 0.93

### TC-12: داستان با موضوع خاص → storyteller
**ورودی:** «یه داستان دربارهٔ فضا بگو»  
**انتظار:** `storyteller` confidence ≥ 0.90

### TC-13: سوال درباره بازی ویدیویی → gamer
**ورودی:** «ماینکرفت چطوری سریع‌تر الماس پیدا کنم؟»  
**انتظار:** `gamer` confidence ≥ 0.90

### TC-14: چیستان → gamer
**ورودی:** «یه چیستان بگو»  
**انتظار:** `gamer` confidence ≥ 0.88

### TC-15: حوصله‌سر برگی → creative
**ورودی:** «حوصله‌م سر رفته»  
**انتظار:** `creative` confidence ≥ 0.85

### TC-16: تداخل نیت: «داستان درباره ریاضی بگو» → storyteller
**ورودی:** «داستان درباره کسر بگو»  
**انتظار:** `storyteller`

### TC-17: تداخل نیت: «چرا کسر...» → teacher
**ورودی:** «چرا کسر ۱/۲ بزرگتر از ۱/۳ است؟»  
**انتظار:** `teacher`

### TC-18: تداخل نیت: «این مسئله رو حل کن» → homework
**ورودی:** «این مسئله رو حل کن: ۵ + ۳»  
**انتظار:** `homework`

---

## ۲. تست‌های حفظ بافت (Context Awareness)

### TC-19: بازی کلمات — «داستان» نباید سوئیچ کند
**بافت:** gamer، نوبت کاربر «داستان»  
**انتظار:** `gamer` (confidence ≥ 0.85)  
**pytest:** `test_core_persona.py::test_word_chain_keeps_gamer`, `test_word_chain_stays_gamer_despite_llm_intent`

### TC-20: «سوال بعد» → homework
**pytest:** `test_activity_continuation_phrases[homework-سوال بعد]`

### TC-21: «ادامه بده» → storyteller
**pytest:** `test_activity_continuation_phrases[storyteller-ادامه بده]`

### TC-22: «مثال دیگر» → teacher
**pytest:** `test_activity_continuation_phrases[teacher-مثال دیگر]`

### TC-23: «ایده دیگر» → creative
**pytest:** `test_activity_continuation_phrases[creative-ایده دیگر]`

### TC-24: درخواست صریح وسط فعالیت → سوئیچ
**ورودی:** «باش معلم»  
**انتظار:** `teacher` confidence ≥ 0.95

### TC-25: استنتاج از تاریخچه Assistant
**انتظار:** `_infer_persona_from_history` → `gamer`  
**pytest:** `test_word_chain_keeps_gamer`

---

## ۳. انتخاب دستی پرسونا (Manual Override)

### TC-26: UserValves PERSONA = teacher
**pytest:** `test_manual_persona_sources`, `test_routes.py::test_persona_resolve_manual`

### TC-27: metadata.yarkids_persona = gamer
**pytest:** `test_manual_persona_sources`

### TC-28: body.persona = creative
**pytest:** `test_manual_persona_sources`

### TC-29: manual + explicit conflict → explicit wins
**pytest:** `test_explicit_persona_triggers` (ترکیب در یک پیام)

### TC-30: auto → intent detection
**pytest:** `test_manual_persona_sources` (auto → None)

---

## ۴. ابزار محاسبه (Math Tool) — `api/core/math_tool.py`

### TC-31: teacher — محاسبه + توضیح
**بررسی:** `run_math_tool_for_message` برای teacher/homework فعال؛ مراحل در پاسخ.

### TC-32: homework — بررسی جواب کودک
**بررسی:** تأیید/تصحیح قدم‌به‌قدم.

### TC-33: creative/storyteller/gamer — ابزار غیرفعال
**pytest:** `test_core_math.py::test_math_tool_persona_gate`

### TC-34: توان / جذر
**pytest:** `test_calculate_math_success`, parametrize expressions

### TC-35: تقسیم بر صفر
**pytest:** `test_calculate_math_division_by_zero`

---

## ۵. کتاب درسی — `api/core/textbook.py`, `POST /v1/textbook/*`

### TC-36–37: کوئری کامل صفحه
**pytest:** `test_build_textbook_query_page_reference`, `test_textbook_query_endpoint`

### TC-38: پرسوناهای غیردرسی — gate
**بررسی:** `TEXTBOOK_PERSONAS` در `api/core/constants.py`; retrieve gate در service/routes

### TC-39: کوئری ناقص → need_info
**pytest:** `test_build_textbook_query_empty_without_reference`

### TC-40–41: صفحه بعد / بعدش
**کد:** `_resolve_relative_page`, `_relative_page_delta`

### TC-42–43: کل درس / کلمات سخت
**کد:** `_textbook_wants_whole_lesson`, `build_textbook_query`

### TC-44–45: تصویر / text_usable
**کد:** `generation._attach_textbook_image_to_messages`

### TC-46: خطای API
**کد:** `fetch_textbook_context` → `TextbookContext(error=...)`

### TC-47: مفهوم عمومی vs صفحه
**بررسی:** بدون ارجاع صفحه API صدا نشود.

---

## ۶. جستجوی وب — `api/core/web_search.py`, `POST /v1/web-search/*`

### TC-48: gamer + سوال واقعی بازی
**pytest:** `test_looks_like_web_search_request`, `test_web_search_query_endpoint`

### TC-49–50: storyteller / creative
**نوع:** integration

### TC-51: teacher/homework — gate
**pytest:** `test_looks_like_web_search_respects_persona_gate`

### TC-52–54: no results / anti-hallucination
**کد:** `WEB_SEARCH_NO_RESULTS_INSTRUCTION` در `api/core/constants.py`

---

## ۷. ضد هالوسینیشن (TC-55–58)

**نوع:** manual / LLM QA — پرامپت‌های `api/prompts/` + Reflection.

---

## ۸. Reflection — `api/core/generation.py`, `POST /v1/reflect`

### TC-59–65
**pytest:** `test_core_generation.py::test_parse_reflection_output`, `test_run_response_loop_with_reflection_pass`  
**API:** `test_routes.py::test_reflect_endpoint`

---

## ۹. Jailbreak (TC-66–74)

**نوع:** manual — `POST /v1/chat` با API واقعی؛ قوانین در `api/prompts/core.md`.

---

## ۱۰. E2E (TC-75–79)

**pytest جزئی:** `test_service.py::test_run_chat_*`  
**manual:** چند نوبت پشت‌سرهم via `POST /v1/chat` یا OpenWebUI + `api/pipe/pipe.py`

---

## ۱۱. Edge Cases (TC-80–85)

### TC-80: پیام خالی
**کد:** `_get_latest_user_message` → ""

### TC-81: پیام طولانی
**نوع:** manual stress

### TC-82: ارقام فارسی
**pytest:** `test_normalize_math_expression`, `test_extract_math_expressions`

### TC-83: «کتاب» بدون صفحه
**pytest:** `test_looks_like_textbook_help_request`, `test_build_textbook_query_empty_without_reference`

### TC-84: چند دستور در یک پیام
**pytest:** `test_explicit_persona_triggers` (آخرین intent: gamer)

### TC-85: reflection disabled
**pytest:** `test_run_response_loop_without_reflection`  
**env:** `YARKIDS_ENABLE_REFLECTION=false`

---

## QA دستی سریع (API بالا)

```bash
uvicorn api.main:app --reload
curl -s http://localhost:8000/health | jq .
curl -s http://localhost:8000/v1/intent -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"بازی کنیم"}]}' | jq .
curl -s http://localhost:8000/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"سلام"}]}' | jq .
```

نیاز: `YARKIDS_BACKEND_MODEL`, `YARKIDS_LLM_API_KEY`, `YARKIDS_LLM_BASE_URL` در `.env`.
