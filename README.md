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

## انتخاب Persona در چت

OpenWebUI از **UserValves** پشتیبانی می‌کند — یک dropdown داخل بخش چت:

1. مدل **یار کودک** را انتخاب کنید
2. سایدبار **Chat Controls** (کنترل‌های چت) را باز کنید
3. بخش **Valves** را پیدا کنید
4. از منوی **PERSONA** پرسونا را انتخاب کنید:
   - **خودکار** → Intent Detection اجرا می‌شود
   - **خلاق / داستان‌گو / معلم / کمک‌درس** → همان پرسونا ثابت می‌ماند

> نیاز به تغییر در هسته OpenWebUI نیست. این قابلیت استاندارد Pipe Function است.

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
