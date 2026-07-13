# یار کودک (Yar Kids)

Pipe Function برای OpenWebUI — دستیار کودک‌دوست.

## ساختار پروژه

```
yarkids/
├── pipe.py                 # کل منطق + کلاس Pipe (+ کلاینت textbook-service)
├── scripts/
│   └── build_embedded_pipe.py
├── prompts/                # پرامپت‌های یار کودک
└── textbook-service/       # API جدا — بازیابی کتاب درسی
    ├── app/                # FastAPI
    ├── indexer/            # build_index.py
    └── data/               # catalog.json, pdfs/, index.sqlite
```

## نصب در OpenWebUI

1. **کل پوشه** `yarkids` (شامل `pipe.py` و `prompts/`) را در محیط OpenWebUI قرار دهید.
2. در **Admin → Functions** فایل `pipe.py` را import کنید.
3. Function را فعال کنید.
4. در Valves مقدار `BACKEND_MODEL` را تنظیم کنید.
5. مدل **یار کودک** در لیست مدل‌ها ظاهر می‌شود.

> پرامپت‌ها از فایل‌های `.md` کنار `pipe.py` خوانده می‌شوند. حتماً پوشه `prompts/` را هم کپی کنید.

## نسخه تک‌فایلی برای OpenWebUI

اگر فقط یک فایل می‌خواهید import کنید (بدون پوشه `prompts/`):

```bash
python scripts/build_embedded_pipe.py
```

خروجی: `pipe_embedded.py` — همان منطق `pipe.py` با پرامپت‌های embed شده.

این فایل را مستقیم در **Admin → Functions** import کنید.

## انتخاب شخصیت (یک مدل — چند شخصیت)

فقط **یک مدل** «یار کودک» در لیست مدل‌ها نمایش داده می‌شود.

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
  "model": "yarkids",
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

### Valves (تنظیمات ادمین)

| پارامتر | توضیح |
|---------|--------|
| `BACKEND_MODEL` | مدل LLM پشتیبان (الزامی) |
| `TEMPERATURE` | دمای تولید |
| `ENABLE_STATUS_UPDATES` | نمایش وضعیت در UI |
| `ENABLE_TEXTBOOK_CONTEXT` | بازیابی کتاب درسی (معلم/کمک‌درسی) |
| `TEXTBOOK_API_URL` | آدرس textbook-service |
| `TEXTBOOK_API_KEY` | کلید API اختیاری |
| `TEXTBOOK_REQUEST_TIMEOUT_SEC` | مهلت درخواست (ثانیه) |
| `TEXTBOOK_NEIGHBOR_PAGES` | صفحات همسایه (۰–۳) |
| `TEXTBOOK_INCLUDE_IMAGE` | `never` / `auto` / `always` |
| `ENABLE_WEB_SEARCH` | جستجوی وب (خلاق / داستان‌گو / بازی و سرگرمی) |
| `WEB_SEARCH_PROVIDER` | `auto` / `duckduckgo` / `api` |
| `WEB_SEARCH_API_URL` | آدرس سرویس جستجوی سفارشی (اختیاری) |
| `WEB_SEARCH_API_KEY` | کلید API اختیاری |
| `WEB_SEARCH_MAX_RESULTS` | حداکثر تعداد نتایج (۱–۱۰) |

## کتاب درسی (textbook-service)

برای پرسوناهای **معلم** و **کمک‌درسی**، Pipe از API جداگانهٔ `textbook-service` کانتکست صفحهٔ کتاب را می‌گیرد.

1. PDFها را در `textbook-service/data/pdfs/` بگذارید و `catalog.json` را تنظیم کنید.
2. وابستگی ایندکس را نصب کنید: `pip install -r textbook-service/requirements-indexer.txt` (شامل MinerU).
3. ایندکس بسازید: `python textbook-service/indexer/build_index.py` (پیش‌فرض: MinerU؛ کش در `data/mineru/`).
4. API را اجرا کنید: `cd textbook-service && docker compose up` یا `uvicorn app.main:app --port 8080`
5. در Valves پایپ: `TEXTBOOK_API_URL=http://localhost:8080`

جزئیات: [textbook-service/README.md](textbook-service/README.md)

اگر API در دسترس نباشد، یار کودک بدون کانتکست کتاب ادامه می‌دهد.

## جستجوی وب (creative / storyteller / gamer)

برای پرسوناهای **خلاق**، **داستان‌گو** و **بازی و سرگرمی**، وقتی سؤال کودک واقعی/به‌روز به نظر برسد (مثلاً نکات بازی، «چطور …؟»، نام بازی)، سیستم قبل از تولید پاسخ در اینترنت جستجو می‌کند و خلاصهٔ نتایج را به پرامپت تزریق می‌کند.

- پیش‌فرض: DuckDuckGo داخلی (بدون کلید، با safe search)
- اختیاری: سرویس سفارشی با `WEB_SEARCH_API_URL` که `POST /v1/search` را با `{ "query", "max_results" }` بپذیرد و `{ "matched", "results": [{ "title", "url", "snippet" }], "context_text" }` برگرداند
- در API: `POST /v1/web-search/query` و `POST /v1/web-search/retrieve`
- اگر جستجو شکست بخورد، چت بدون نتایج ادامه می‌یابد (حدس نمی‌زند)

## ویرایش پرامپت‌ها

هر پرامپت در فایل `.md` جداگانه است. برای تغییر رفتار مدل، فایل مربوطه را ویرایش کنید:

| فایل | کاربرد |
|------|--------|
| `prompts/core.md` | هویت و قوانین ایمنی |
| `prompts/personas/*.md` | رفتار هر پرسونا |
| `prompts/intent_detection.md` | تشخیص نیت |
| `prompts/reflection.md` | بازبینی کیفیت (`{{CORE_PROMPT}}` جایگزین می‌شود) |

## افزودن پرسونای جدید

1. فایل `prompts/personas/<id>.md` بسازید.
2. شناسه را به `SUPPORTED_PERSONAS` در `pipe.py` اضافه کنید.
3. گزینه را به `UserValves.PERSONA` (dropdown) اضافه کنید.
4. پرسونا را در `prompts/intent_detection.md` معرفی کنید.
