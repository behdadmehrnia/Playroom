"""Landing page for the Yar Kids API."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Landing"])

LANDING_PAGE_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>یار کودک</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 36 17'%3E%3Cpath d='M8.5 0.5C12.9183 0.5 16.5 4.08172 16.5 8.5C16.5 12.9183 12.9183 16.5 8.5 16.5C4.08172 16.5 0.5 12.9183 0.5 8.5C0.5 4.08172 4.08172 0.5 8.5 0.5Z' stroke='%23FFC828'/%3E%3Cpath d='M27.5 17C32.1944 17 36 13.1944 36 8.5C36 3.80558 32.1944 0 27.5 0C22.8056 0 19 3.80558 19 8.5C19 13.1944 22.8056 17 27.5 17Z' fill='%23FFC828'/%3E%3C/svg%3E">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700;900&display=swap" rel="stylesheet">
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 2rem;
            direction: rtl;
        }
        .container {
            max-width: 960px;
            width: 100%;
            text-align: center;
        }
        h1 {
            font-size: 3.2rem;
            font-weight: 900;
            margin-bottom: 0.5rem;
            color: #f9d423;
        }
        .subtitle {
            font-size: 1.15rem;
            color: #999;
            margin-bottom: 3rem;
            max-width: 600px;
            margin-left: auto;
            margin-right: auto;
            line-height: 1.8;
        }
        .section-title {
            font-size: 1.8rem;
            font-weight: 700;
            color: #f9d423;
            margin-bottom: 0.5rem;
        }
        .section-desc {
            color: #888;
            margin-bottom: 2rem;
            font-size: 0.95rem;
        }
        .features {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 1.25rem;
            margin-bottom: 4rem;
        }
        .feature-card {
            background: #242424;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 1.5rem;
            text-align: right;
            transition: border-color 0.3s, box-shadow 0.3s;
        }
        .feature-card:hover {
            border-color: #f9d423;
            box-shadow: 0 0 20px rgba(249, 212, 35, 0.08);
        }
        .feature-icon {
            font-size: 2rem;
            margin-bottom: 0.75rem;
        }
        .feature-title {
            font-size: 1.1rem;
            font-weight: 700;
            color: #f9d423;
            margin-bottom: 0.5rem;
        }
        .feature-desc {
            color: #999;
            line-height: 1.7;
            font-size: 0.92rem;
        }
        .personas {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 1.25rem;
            margin-bottom: 4rem;
        }
        .persona-card {
            background: #242424;
            border: 1px solid #333;
            border-radius: 12px;
            padding: 1.5rem 1rem;
            text-align: center;
            transition: border-color 0.3s, transform 0.2s;
        }
        .persona-card:hover {
            border-color: #f9d423;
            transform: translateY(-3px);
        }
        .persona-emoji {
            font-size: 2.5rem;
            margin-bottom: 0.75rem;
        }
        .persona-name {
            font-size: 1.05rem;
            font-weight: 700;
            color: #f9d423;
            margin-bottom: 0.35rem;
        }
        .persona-desc {
            color: #888;
            font-size: 0.82rem;
            line-height: 1.6;
        }
        .divider {
            border: none;
            border-top: 1px solid #333;
            margin: 0 0 3rem 0;
        }
        .cta-section {
            padding: 2.5rem 2rem;
            background: #242424;
            border-radius: 12px;
            border: 1px solid #333;
        }
        .cta-section h2 {
            color: #f9d423;
            font-size: 1.5rem;
            margin-bottom: 1rem;
        }
        .cta-button {
            display: inline-block;
            padding: 1.2rem 2.7rem;
            background: #f9d423;
            color: #1a1a1a;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 700;
            font-size: 1.2rem;
            transition: background 0.3s, box-shadow 0.3s;
        }
        .cta-button:hover {
            background: #e6c320;
            box-shadow: 0 4px 20px rgba(249, 212, 35, 0.25);
        }
        .footer {
            margin-top: 3rem;
            color: #555;
            font-size: 0.85rem;
            padding-bottom: 1rem;
        }
        .footer a {
            color: #f9d423;
            text-decoration: none;
        }
        .footer a:hover {
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 style="display: flex; align-items: center; justify-content: center; gap: 1rem;">
            <svg width="56" height="28" viewBox="0 0 36 17" fill="none" xmlns="http://www.w3.org/2000/svg">
                <path d="M8.5 0.5C12.9183 0.5 16.5 4.08172 16.5 8.5C16.5 12.9183 12.9183 16.5 8.5 16.5C4.08172 16.5 0.5 12.9183 0.5 8.5C0.5 4.08172 4.08172 0.5 8.5 0.5Z" stroke="#FFC828"/>
                <path d="M27.5 17C32.1944 17 36 13.1944 36 8.5C36 3.80558 32.1944 0 27.5 0C22.8056 0 19 3.80558 19 8.5C19 13.1944 22.8056 17 27.5 17Z" fill="#FFC828"/>
            </svg>
            یار کودک
        </h1>
        <p class="subtitle">دستیار هوش مصنوعی اختصاصی کودکان — بخشی از اکوسیستم هوش مصنوعی  یار</p>

        <hr class="divider">

        <div class="section-title">قابلیت‌ها</div>
        <p class="section-desc">امکاناتی که یار کودک را از سایر دستیارها متمایز می‌کند</p>

        <div class="features">
            <div class="feature-card">
                <div class="feature-icon">🧠</div>
                <div class="feature-title">دانش به‌روز</div>
                <div class="feature-desc">با دسترسی به جستجوی وب، همیشه آخرین اطلاعات را در اختیار کودکان قرار می‌دهد.</div>
            </div>

            <div class="feature-card">
                <div class="feature-icon">🛡️</div>
                <div class="feature-title">امن برای کودکان</div>
                <div class="feature-desc">طراحی شده با فیلترهای ایمنی و پاسخ‌های مناسب سن کودکان.</div>
            </div>

            <div class="feature-card">
                <div class="feature-icon">📚</div>
                <div class="feature-title">دانش کتاب درسی</div>
                <div class="feature-desc">دسترسی مستقیم به محتوای کتاب‌های درسی برای کمک در تکالیف و یادگیری.</div>
            </div>

            <div class="feature-card">
                <div class="feature-icon">🔍</div>
                <div class="feature-title">تشخیص نیت هوشمند</div>
                <div class="feature-desc">به‌صورت خودکار نیت کودک را تشخیص داده و بهترین پاسخ را ارائه می‌دهد.</div>
            </div>

            <div class="feature-card">
                <div class="feature-icon">💬</div>
                <div class="feature-title">چت بلادرنگ</div>
                <div class="feature-desc">پاسخ‌دهی آنی با جریان داده (SSE) برای تجربه‌ای روان و تعاملی.</div>
            </div>

            <div class="feature-card">
                <div class="feature-icon">🔄</div>
                <div class="feature-title">بازبینی پاسخ</div>
                <div class="feature-desc">بررسی و بازنویسی خودکار پاسخ‌ها برای اطمینان از کیفیت و دقت.</div>
            </div>
        </div>

        <hr class="divider">

        <div class="section-title">پرسوناهای یار کودک</div>
        <p class="section-desc">هر پرسونا یک نقش متفاوت دارد تا کودک بهترین تجربه را داشته باشد</p>

        <div class="personas">
            <div class="persona-card">
                <div class="persona-emoji">🎨</div>
                <div class="persona-name">خلاق</div>
                <div class="persona-desc">ایده‌پردازی خلاقانه و کشف راه‌های جدید</div>
            </div>

            <div class="persona-card">
                <div class="persona-emoji">📖</div>
                <div class="persona-name">داستان‌گو</div>
                <div class="persona-desc">قصه‌گویی تعاملی و ماجراجویی‌های جذاب</div>
            </div>

            <div class="persona-card">
                <div class="persona-emoji">👩‍🏫</div>
                <div class="persona-name">معلم</div>
                <div class="persona-desc">آموزش مفهومی و توضیح ساده دروس</div>
            </div>

            <div class="persona-card">
                <div class="persona-emoji">📝</div>
                <div class="persona-name">کمک‌درس</div>
                <div class="persona-desc">حل تمرین و تکالیف قدم‌به‌قدم</div>
            </div>

            <div class="persona-card">
                <div class="persona-emoji">🎮</div>
                <div class="persona-name">بازی و سرگرمی</div>
                <div class="persona-desc">بازی کلمات، چیستان و معما</div>
            </div>
        </div>

        <hr class="divider">

        <div class="cta-section">
            <h2>همین حالا شروع کنید!</h2>
            <a href="https://yarai.ir" target="_blank" class="cta-button">
               رفتن به هوش مصنوعی یار
            </a>
        </div>

        <div class="footer">
            <p>بخشی از اکوسیستم هوش مصنوعی  یار</p>
            <p style="margin-top: 0.4rem;">تمامی حقوق برای شرکت یار محفوظ می باشد</p>
            <p style="margin-top: 0.6rem; font-size: 0.65rem;">Built with ❤️ by <a href="https://t.me/BMDarkLight" target="_blank">Behdad</a>  |  <a href="/docs">API Documentation</a></p>
        </div>
    </div>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    """صفحه اصلی Yar Kids — معرفی قابلیت‌ها و هدایت به yarai.ir"""
    return HTMLResponse(content=LANDING_PAGE_HTML)
