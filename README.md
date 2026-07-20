# یار کودک (Yar Kids)

دستیار کودک‌دوست — سرویس FastAPI مستقل به‌همراه Pipe کلاینت برای OpenWebUI.

## ساختار پروژه

```
yarkids/
├── api/                        # سرویس FastAPI (منبع حقیقت منطق)
│   ├── main.py                 # entrypoint: uvicorn api.main:app
│   ├── config.py / llm.py      # env settings + LLM client
│   ├── service.py              # chat orchestration (calls api.core)
│   ├── models.py               # HTTP request/response schemas
│   ├── core/                   # domain logic (import via api.core)
│   │   ├── persona.py / intent.py
│   │   ├── textbook.py / web_search.py
│   │   ├── generation.py / math_tool.py
│   │   └── prompts.py          # loads api/prompts/*.md
│   ├── routes/                 # HTTP endpoints (composed router)
│   │   ├── chat.py / health.py
│   │   ├── openai_compat.py    # /v1/chat/completions, /v1/responses
│   │   └── …                   # intent, personas, textbook, web-search, …
│   ├── prompts/                # پرامپت‌های .md
│   ├── textbook/               # بازیابی کتاب درسی (embedded)
│   ├── requirements-runtime.txt  # deps for Docker / API runtime
│   ├── requirements.txt        # + MinerU indexer (local PDF indexing)
│   └── pipe/
│       ├── pipe.py             # ★ Pipe کلاینت OpenWebUI (توصیه‌شده)
│       ├── pipe_logic.py       # [DEPRECATED] منطق محلی
│       └── generate-logic-pipe.py
```

### وابستگی‌ها

```bash
# اجرای API (همان چیزی که Docker نصب می‌کند)
pip install -r api/requirements-runtime.txt

# + ایندکس PDF محلی (MinerU — سنگین)
pip install -r api/requirements.txt
```

## اجرای API

```bash
docker compose up -d --build
# یا
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

تنظیمات از env (مثلاً `YARKIDS_BACKEND_MODEL`, `YARKIDS_LLM_API_KEY`, …) — نمونه: `.env.example`.

## تست

```bash
pip install -r requirements-dev.txt
pytest
```

تست‌ها بر اساس ماژول‌های `api/core/` و `api/routes/` سازمان‌دهی شده‌اند (`tests/test_core_*.py`, `tests/test_routes.py`, …).  
چک‌لیست تست دستی (پرامپت + انتظار): [`tests/README.md`](tests/README.md).

## نصب در OpenWebUI (مسیر توصیه‌شده)

1. سرویس `api/` را بالا بیاورید.
2. در **Admin → Functions** فایل `api/pipe/pipe.py` را import کنید.
3. Function را فعال کنید و در Valves مقدار `API_BASE_URL` را به آدرس سرویس بزنید
   (مثلاً `http://host.docker.internal:8000`).
4. مدل **یار کودک مستقل** در لیست مدل‌ها ظاهر می‌شود.

> منطق دیگر داخل Pipe اجرا نمی‌شود؛ همهٔ مراحل در API انجام می‌شود.

## نسخهٔ منسوخ (منطق محلی)

`api/pipe/pipe_logic.py` منسوخ است. فقط اگر به یک فایل تک‌فایلی بدون API نیاز دارید:

```bash
python api/pipe/generate-logic-pipe.py
```

خروجی: `api/pipe/pipe_logic_embedded.py` — برای import مستقیم در OpenWebUI.
برای استقرار جدید از `api/pipe/pipe.py` + API استفاده کنید.

## انتخاب شخصیت (یک مدل — چند شخصیت)

فقط **یک مدل** در لیست مدل‌ها نمایش داده می‌شود.

انتخاب شخصیت از یکی از این مسیرها:

| مسیر | مناسب برای |
|------|------------|
| **UserValves** | OpenWebUI استاندارد (Chat Controls → Valves) |
| **`metadata.yarkids_persona`** | UI سفارشی «یار» (dropdown کنار چت) |
| **خودکار** | اگر چیزی انتخاب نشود → Intent Detection |

### اتصال UI سفارشی (dropdown کنار چت)

وقتی کاربر از dropdown شخصیت انتخاب کرد، هنگام ارسال پیام این مقدار را بفرستید:

```json
{
  "model": "yarkids_api",
  "messages": [...],
  "metadata": {
    "yarkids_persona": "creative"
  }
}
```

مقادیر مجاز: `auto` | `creative` | `storyteller` | `teacher` | `homework` | `gamer`

همچنین می‌توانید مستقیم روی body بفرستید: `body.yarkids_persona` یا `body.persona`

### UserValves (OpenWebUI خام)

Chat Controls → Valves → **شخصیت یار کودک**

### Valves کلاینت API (`api/pipe/pipe.py`)

| پارامتر | توضیح |
|---------|--------|
| `API_BASE_URL` | آدرس پایهٔ سرویس `api/` (الزامی) |
| `API_KEY` | Bearer اختیاری |
| `MODEL` | مدل سمت API (خالی = پیش‌فرض API) |
| `TEMPERATURE` | دمای تولید |
| `ENABLE_STATUS_UPDATES` | نمایش وضعیت در UI |
| `ENABLE_REFLECTION` | بازبینی پاسخ |
| `ENABLE_TEXTBOOK_CONTEXT` | بازیابی کتاب درسی |
| `ENABLE_WEB_SEARCH` | جستجوی وب |
| `REQUEST_TIMEOUT_SEC` | مهلت درخواست |

تنظیمات LLM / textbook / web search روی خود سرویس API (env) پیکربندی می‌شوند.

## کتاب درسی

برای پرسوناهای **معلم** و **کمک‌درسی**، API از ماژول embedded `api/textbook/` کانتکست صفحهٔ کتاب را می‌گیرد (پیش‌فرض؛ بدون سرویس جدا).

جزئیات داده و ایندکس: زیر `api/textbook/`.

اگر بازیابی در دسترس نباشد، یار کودک بدون کانتکست کتاب ادامه می‌دهد.

## جستجوی وب

برای پرسوناهای **خلاق**، **داستان‌گو** و **بازی و سرگرمی**، وقتی سؤال کودک واقعی/به‌روز به نظر برسد، سیستم قبل از تولید پاسخ در اینترنت جستجو می‌کند و خلاصهٔ نتایج را به پرامپت تزریق می‌کند.

- `WEB_SEARCH_PROVIDER` (env API):
  - `duckduckgo` — DuckDuckGo داخلی (+ Wikipedia)
  - `api` — `POST {WEB_SEARCH_API_URL}/v1/search`
  - `perplexity` — `GET {WEB_SEARCH_PERPLEXITY_URL}/api/v1/search?query=...`
  - `auto` — هر منبعی که در دسترس باشد، به ترتیب: api → perplexity → duckduckgo
- در API: `POST /v1/web-search/query` و `POST /v1/web-search/retrieve`
- اگر جستجو شکست بخورد، چت بدون نتایج ادامه می‌یابد (حدس نمی‌زند)

## API سازگار با OpenAI

سرویس `api/` علاوه بر `/v1/chat` این اندپوینت‌ها را هم ارائه می‌دهد (مدل کلاینت نادیده گرفته می‌شود؛ از `YARKIDS_BACKEND_MODEL` استفاده می‌شود):

| مسیر | توضیح |
|------|--------|
| `POST /v1/chat/completions` | Chat Completions استاندارد (+ alias: `/v1/chat/completion`) |
| `POST /v1/responses` | Responses API |

در پاسخ (و در آخرین chunk استریم) فیلد `yarkids` شامل پرسونای فعال، لاگ‌ها، کوئری/نتیجهٔ کتاب درسی، جستجوی وب، و استفاده از ابزار ریاضی است.

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"سلام"}]}'
```

## ویرایش پرامپت‌ها

هر پرامپت در فایل `.md` جداگانه است. برای تغییر رفتار مدل، فایل‌های زیر `api/prompts/` را ویرایش کنید:

| فایل | کاربرد |
|------|--------|
| `api/prompts/core.md` | هویت و قوانین ایمنی |
| `api/prompts/personas/*.md` | رفتار هر پرسونا |
| `api/prompts/intent_detection.md` | تشخیص نیت |
| `api/prompts/reflection.md` | بازبینی کیفیت (`{{CORE_PROMPT}}` جایگزین می‌شود) |

## افزودن پرسونای جدید

1. فایل `api/prompts/personas/<id>.md` بسازید.
2. شناسه را به `SUPPORTED_PERSONAS` در `api/core/constants.py` (و در صورت نیاز `api/pipe/pipe.py`) اضافه کنید.
3. گزینه را به `UserValves.PERSONA` (dropdown) در کلاینت Pipe اضافه کنید.
4. پرسونا را در `api/prompts/intent_detection.md` معرفی کنید.