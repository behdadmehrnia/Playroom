# یار کودک (Yar Kids)

Pipe Function برای OpenWebUI — دستیار کودک‌دوست.

## ساختار پروژه

```
yarkids/
├── pipe.py                 # کل منطق + کلاس Pipe
└── prompts/
    ├── core.md             # Core Prompt
    ├── intent_detection.md
    ├── reflection.md
    └── personas/
        ├── creative.md
        ├── storyteller.md
        ├── teacher.md
        └── homework.md
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

مقادیر مجاز: `auto` | `creative` | `storyteller` | `teacher` | `homework`

همچنین می‌توانید مستقیم روی body بفرستید: `body.yarkids_persona` یا `body.persona`

### UserValves (OpenWebUI خام)

Chat Controls → Valves → **شخصیت یار کودک**

### Valves (تنظیمات ادمین)

| پارامتر | توضیح |
|---------|--------|
| `BACKEND_MODEL` | مدل LLM پشتیبان (الزامی) |
| `TEMPERATURE` | دمای تولید |
| `ENABLE_STATUS_UPDATES` | نمایش وضعیت در UI |

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
