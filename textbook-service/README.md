# Textbook Service

سرویس API جداگانه برای بازیابی صفحه‌محور کتاب‌های درسی (پایه ۳ تا ۶).

## راه‌اندازی

```bash
cd textbook-service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## آماده‌سازی داده

1. فایل‌های PDF را در `data/pdfs/` قرار دهید.
2. `data/catalog.json` را با نام فایل‌ها و `page_offset` هر کتاب تنظیم کنید.
3. وابستگی‌های ایندکس (شامل [MinerU](https://github.com/opendatalab/mineru)) را نصب کنید — جدا از ایمیج runtime API است:

```bash
pip install -r requirements-indexer.txt
# اگر HuggingFace در دسترس نیست:
export MINERU_MODEL_SOURCE=modelscope
```

4. ایندکس را بسازید (پیش‌فرض: MinerU با `pipeline` + `lang=arabic` برای فارسی):

```bash
python indexer/build_index.py
# یا با مسیر سفارشی:
python indexer/build_index.py --pdf-dir /path/to/pdfs
# اجبار به اجرای دوبارهٔ MinerU (بدون cache):
python indexer/build_index.py --mineru-force
# فقط اگر MinerU نصب نیست:
python indexer/build_index.py --ocr-engine tesseract
```

خروجی خام MinerU در `data/mineru/` کش می‌شود تا ایندکس‌های بعدی سریع‌تر ساخته شوند.

## اجرای API

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

یا با Docker:

```bash
docker compose up --build
```

## زیرموضوع‌ها داخل هر درس (تاریخ، مدنی، ...)

کتاب‌ها در `catalog.json` با یک `subject` شناسایی می‌شوند (مثلاً `social` برای مطالعات اجتماعی).

زیرموضوع‌های داخل همان کتاب — مثل **تاریخ**، **جغرافیا**، **مدنی** — در `data/subject_topics.json` تعریف می‌شوند و به همان `subject` والد نگاشت می‌شوند.

مثال: اگر کاربر بگوید «تمرین صفحه ۵۰ تاریخ پایه پنجم»، سیستم:
1. `تاریخ` → کتاب `social` (مطالعات اجتماعی)
2. صفحه ۵۰ از همان PDF را برمی‌گرداند

برای افزودن یا ویرایش زیرموضوع‌ها، فایل `subject_topics.json` را ویرایش کنید.

## Endpointها

| Method | Path | توضیح |
|--------|------|--------|
| GET | `/health` | سلامت سرویس |
| POST | `/v1/retrieve` | بازیابی کانتکست از متن کاربر |
| GET | `/v1/page-image` | تصویر صفحه (`grade`, `subject`, `page`) |

### نمونه retrieve

```bash
curl -s -X POST http://localhost:8080/v1/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query": "تمرین صفحه 72 ریاضی پایه سوم", "include_neighbors": 1}'
```

## متغیرهای محیطی

| متغیر | پیش‌فرض | توضیح |
|-------|---------|--------|
| `TEXTBOOK_DATA_DIR` | `./data` | مسیر داده |
| `TEXTBOOK_API_KEY` | خالی | اگر تنظیم شود، Bearer الزامی است |
| `TEXTBOOK_PORT` | `8080` | پورت |

## اتصال به Pipe یار کودک

در Valves پایپ OpenWebUI:

- `TEXTBOOK_API_URL=http://textbook-service:8080` (یا `http://localhost:8080`)
- `ENABLE_TEXTBOOK_CONTEXT=true`
