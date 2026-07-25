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
        .cta-actions {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 0.85rem;
        }
        .cta-link-secondary {
            display: inline-block;
            color: #999;
            text-decoration: none;
            font-size: 0.82rem;
            font-weight: 500;
            border-bottom: 1px solid #555;
            padding-bottom: 0.1rem;
            transition: color 0.2s, border-color 0.2s;
        }
        .cta-link-secondary:hover {
            color: #f9d423;
            border-color: #f9d423;
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
            <div class="cta-actions">
                <a href="https://yarai.ir" target="_blank" class="cta-button">
                   رفتن به هوش مصنوعی یار
                </a>
                <a href="/chat" class="cta-link-secondary">امتحان کردن مستقیم یار کودک</a>
            </div>
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


CHAT_PAGE_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>چت مستقیم — یار کودک</title>
    <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 36 17'%3E%3Cpath d='M8.5 0.5C12.9183 0.5 16.5 4.08172 16.5 8.5C16.5 12.9183 12.9183 16.5 8.5 16.5C4.08172 16.5 0.5 12.9183 0.5 8.5C0.5 4.08172 4.08172 0.5 8.5 0.5Z' stroke='%23FFC828'/%3E%3Cpath d='M27.5 17C32.1944 17 36 13.1944 36 8.5C36 3.80558 32.1944 0 27.5 0C22.8056 0 19 3.80558 19 8.5C19 13.1944 22.8056 17 27.5 17Z' fill='%23FFC828'/%3E%3C/svg%3E">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700;900&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            height: 100vh;
            display: flex;
            direction: rtl;
            overflow: hidden;
        }
        .sidebar {
            width: 240px;
            flex-shrink: 0;
            background: #1f1f1f;
            border-left: 1px solid #333;
            display: flex;
            flex-direction: column;
            z-index: 30;
        }
        .sidebar-top {
            padding: 0.85rem;
            border-bottom: 1px solid #333;
            display: flex;
            flex-direction: column;
            gap: 0.55rem;
        }
        .new-chat {
            width: 100%;
            border: 1px dashed #555;
            background: transparent;
            color: #f9d423;
            font-family: inherit;
            font-size: 0.88rem;
            font-weight: 600;
            padding: 0.65rem 0.75rem;
            border-radius: 8px;
            cursor: pointer;
            transition: border-color 0.2s, background 0.2s;
        }
        .new-chat:hover:not(:disabled) {
            border-color: #f9d423;
            background: rgba(249, 212, 35, 0.06);
        }
        .new-chat:disabled,
        .session-open:disabled,
        .session-del:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }
        body.is-busy .session-item { pointer-events: none; }
        body.is-busy .new-chat { pointer-events: none; }
        .session-list {
            flex: 1;
            overflow-y: auto;
            padding: 0.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
        }
        .session-item {
            display: flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 8px;
            padding: 0.15rem;
        }
        .session-item.active { background: #2a2a2a; }
        .session-item.active .session-open { color: #f9d423; }
        .session-open {
            flex: 1;
            min-width: 0;
            text-align: right;
            border: none;
            background: transparent;
            color: #bbb;
            font-family: inherit;
            font-size: 0.82rem;
            padding: 0.55rem 0.5rem;
            cursor: pointer;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .session-open:hover { color: #f9d423; }
        .session-del {
            flex-shrink: 0;
            width: 28px;
            height: 28px;
            border: none;
            border-radius: 6px;
            background: transparent;
            color: #666;
            cursor: pointer;
            font-size: 0.95rem;
            line-height: 1;
        }
        .session-del:hover { color: #ff8a8a; background: #2a1a1a; }
        .session-empty {
            color: #555;
            font-size: 0.8rem;
            text-align: center;
            padding: 1.5rem 0.75rem;
            line-height: 1.7;
        }
        .main {
            flex: 1;
            min-width: 0;
            display: flex;
            flex-direction: column;
            height: 100vh;
        }
        header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            padding: 0.85rem 1.1rem;
            border-bottom: 1px solid #333;
            background: #242424;
            flex-shrink: 0;
            position: relative;
        }
        .header-start {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            min-width: 0;
        }
        .menu-toggle {
            display: none;
            border: 1px solid #333;
            background: #1a1a1a;
            color: #f9d423;
            width: 36px;
            height: 36px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 1.1rem;
            font-family: inherit;
        }
        .brand {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            color: #f9d423;
            font-weight: 800;
            font-size: 1.1rem;
            text-decoration: none;
            flex-shrink: 0;
        }
        .persona-wrap {
            position: relative;
            display: none;
            align-items: center;
        }
        .persona-wrap.visible { display: flex; }
        .persona-sep { color: #555; font-size: 0.85rem; }
        .persona-btn {
            appearance: none;
            border: none;
            background: transparent;
            color: #999;
            font-family: inherit;
            font-size: 0.78rem;
            font-weight: 500;
            cursor: pointer;
            padding: 0.2rem 0.35rem;
            border-radius: 6px;
            max-width: 140px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .persona-btn:hover, .persona-btn.open {
            color: #f9d423;
            background: rgba(249, 212, 35, 0.08);
        }
        .persona-hint { color: #666 !important; font-size: 0.72rem !important; }
        .persona-hint:hover { color: #f9d423 !important; }
        .persona-menu {
            display: none;
            position: absolute;
            top: calc(100% + 0.45rem);
            right: 0;
            min-width: 210px;
            background: #242424;
            border: 1px solid #333;
            border-radius: 10px;
            padding: 0.35rem;
            z-index: 40;
            box-shadow: 0 10px 30px rgba(0,0,0,0.35);
        }
        .persona-menu.open { display: block; }
        .persona-option {
            display: block;
            width: 100%;
            text-align: right;
            border: none;
            background: transparent;
            color: #e0e0e0;
            font-family: inherit;
            font-size: 0.85rem;
            padding: 0.55rem 0.7rem;
            border-radius: 7px;
            cursor: pointer;
        }
        .persona-option:hover { background: #333; }
        .persona-option.active {
            color: #1a1a1a;
            background: #f9d423;
            font-weight: 700;
        }
        .back { color: #888; text-decoration: none; font-size: 0.85rem; flex-shrink: 0; }
        .back:hover { color: #f9d423; }
        #messages {
            flex: 1;
            overflow-y: auto;
            padding: 1.25rem;
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
        }
        .empty {
            margin: auto;
            text-align: center;
            color: #666;
            max-width: 280px;
            line-height: 1.8;
            font-size: 0.95rem;
        }
        .empty strong { color: #f9d423; font-weight: 700; }
        .bubble {
            max-width: min(720px, 92%);
            padding: 0.85rem 1rem;
            border-radius: 14px;
            line-height: 1.75;
            word-break: break-word;
            font-size: 0.95rem;
        }
        .bubble.user {
            align-self: flex-start;
            background: #f9d423;
            color: #1a1a1a;
            border-bottom-right-radius: 4px;
            white-space: pre-wrap;
        }
        .bubble.assistant {
            align-self: flex-end;
            background: #242424;
            border: 1px solid #333;
            color: #e0e0e0;
            border-bottom-left-radius: 4px;
        }
        .bubble.error {
            align-self: flex-end;
            background: #2a1a1a;
            border: 1px solid #664444;
            color: #ffb4b4;
            white-space: pre-wrap;
        }
        .bubble.typing { color: #888; font-style: italic; white-space: pre-wrap; }
        .bubble.assistant.md p { margin: 0 0 0.65em; }
        .bubble.assistant.md p:last-child { margin-bottom: 0; }
        .bubble.assistant.md ul,
        .bubble.assistant.md ol { margin: 0.4em 0 0.65em; padding-right: 1.3em; }
        .bubble.assistant.md li { margin: 0.2em 0; }
        .bubble.assistant.md strong { color: #f9d423; font-weight: 700; }
        .bubble.assistant.md em { color: #ccc; }
        .bubble.assistant.md a { color: #f9d423; }
        .bubble.assistant.md code {
            font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
            font-size: 0.86em;
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 4px;
            padding: 0.05em 0.35em;
        }
        .bubble.assistant.md pre {
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 8px;
            padding: 0.75rem;
            overflow-x: auto;
            margin: 0.5em 0;
        }
        .bubble.assistant.md pre code { border: none; background: transparent; padding: 0; }
        .bubble.assistant.md h1,
        .bubble.assistant.md h2,
        .bubble.assistant.md h3 {
            color: #f9d423;
            font-size: 1.05em;
            margin: 0.4em 0 0.5em;
        }
        .bubble.assistant.md blockquote {
            border-right: 3px solid #f9d423;
            margin: 0.5em 0;
            padding: 0.15em 0.8em;
            color: #aaa;
        }
        form {
            display: flex;
            gap: 0.65rem;
            padding: 0.9rem 1.1rem;
            border-top: 1px solid #333;
            background: #242424;
            flex-shrink: 0;
        }
        #input {
            flex: 1;
            resize: none;
            min-height: 48px;
            max-height: 140px;
            padding: 0.75rem 0.9rem;
            border-radius: 10px;
            border: 1px solid #333;
            background: #1a1a1a;
            color: #e0e0e0;
            font-family: inherit;
            font-size: 0.95rem;
            outline: none;
        }
        #input:focus { border-color: #f9d423; }
        #send {
            padding: 0 1.25rem;
            border: none;
            border-radius: 10px;
            background: #f9d423;
            color: #1a1a1a;
            font-family: inherit;
            font-weight: 700;
            font-size: 0.95rem;
            cursor: pointer;
        }
        #send:hover:not(:disabled) { background: #e6c320; }
        #send:disabled { opacity: 0.45; cursor: not-allowed; }
        .sidebar-backdrop {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.45);
            z-index: 25;
        }
        @media (max-width: 720px) {
            .sidebar {
                position: fixed;
                top: 0;
                right: 0;
                bottom: 0;
                transform: translateX(105%);
                transition: transform 0.2s ease;
                box-shadow: -8px 0 24px rgba(0,0,0,0.35);
            }
            body.sidebar-open .sidebar { transform: translateX(0); }
            body.sidebar-open .sidebar-backdrop { display: block; }
            .menu-toggle { display: inline-flex; align-items: center; justify-content: center; }
        }
    </style>
</head>
<body>
    <div class="sidebar-backdrop" id="sidebarBackdrop"></div>
    <aside class="sidebar" id="sidebar">
        <div class="sidebar-top">
            <button type="button" class="new-chat" id="newChatBtn">＋ گفتگوی جدید</button>
        </div>
        <div class="session-list" id="sessionList"></div>
    </aside>

    <div class="main">
        <header>
            <div class="header-start">
                <button type="button" class="menu-toggle" id="menuToggle" aria-label="سشن‌ها">☰</button>
                <a class="brand" href="/">
                    <svg width="40" height="20" viewBox="0 0 36 17" fill="none" xmlns="http://www.w3.org/2000/svg">
                        <path d="M8.5 0.5C12.9183 0.5 16.5 4.08172 16.5 8.5C16.5 12.9183 12.9183 16.5 8.5 16.5C4.08172 16.5 0.5 12.9183 0.5 8.5C0.5 4.08172 4.08172 0.5 8.5 0.5Z" stroke="#FFC828"/>
                        <path d="M27.5 17C32.1944 17 36 13.1944 36 8.5C36 3.80558 32.1944 0 27.5 0C22.8056 0 19 3.80558 19 8.5C19 13.1944 22.8056 17 27.5 17Z" fill="#FFC828"/>
                    </svg>
                    یار کودک
                </a>
                <div class="persona-wrap" id="personaWrap">
                    <span class="persona-sep">·</span>
                    <button type="button" class="persona-btn" id="personaBtn" aria-haspopup="listbox" aria-expanded="false" title="انتخاب پرسونا">پرسونا</button>
                    <div class="persona-menu" id="personaMenu" role="listbox"></div>
                </div>
                <button type="button" class="persona-btn persona-hint" id="personaHint" title="انتخاب پرسونا">· انتخاب پرسونا</button>
            </div>
            <a class="back" href="/">بازگشت</a>
        </header>

        <div id="messages"></div>

        <form id="form">
            <textarea id="input" rows="1" placeholder="پیامت را بنویس..." autofocus></textarea>
            <button type="submit" id="send">بفرست</button>
        </form>
    </div>

    <script>
        const COOKIE_PREFIX = 'ykc_';
        const COOKIE_META = 'ykc_n';
        // Encoded chunk size must stay under ~4KB cookie limit (name + attrs).
        const ENCODED_CHUNK = 2800;
        const MAX_SESSIONS = 10;
        const MAX_MESSAGES = 24;
        const MAX_CONTENT = 2000;

        const messagesEl = document.getElementById('messages');
        const form = document.getElementById('form');
        const input = document.getElementById('input');
        const sendBtn = document.getElementById('send');
        const personaWrap = document.getElementById('personaWrap');
        const personaBtn = document.getElementById('personaBtn');
        const personaMenu = document.getElementById('personaMenu');
        const personaHint = document.getElementById('personaHint');
        const sessionList = document.getElementById('sessionList');
        const newChatBtn = document.getElementById('newChatBtn');
        const menuToggle = document.getElementById('menuToggle');
        const sidebarBackdrop = document.getElementById('sidebarBackdrop');

        const FALLBACK_PERSONAS = [
            { value: 'auto', label: '✨ خودکار' },
            { value: 'creative', label: '🎨 خلاق' },
            { value: 'storyteller', label: '📖 داستان‌گو' },
            { value: 'teacher', label: '📚 معلم' },
            { value: 'homework', label: '✏️ کمک‌درس' },
            { value: 'gamer', label: '🎮 بازی و سرگرمی' },
        ];
        let personas = FALLBACK_PERSONAS.slice();
        let selectedPersona = 'auto';
        let activePersona = null;
        let history = [];
        let store = { activeId: null, selectedPersona: 'auto', sessions: [] };
        let requestToken = 0;
        let isBusy = false;

        if (window.marked) marked.setOptions({ breaks: true, gfm: true });

        function setBusy(busy) {
            isBusy = !!busy;
            document.body.classList.toggle('is-busy', isBusy);
            sendBtn.disabled = isBusy;
            newChatBtn.disabled = isBusy;
            renderSessionList();
        }

        function uid() {
            return 's' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
        }

        function getCookie(name) {
            const parts = document.cookie.split('; ');
            for (let i = 0; i < parts.length; i++) {
                const row = parts[i];
                const eq = row.indexOf('=');
                if (eq === -1) continue;
                if (row.slice(0, eq) === name) return row.slice(eq + 1);
            }
            return null; // keep encoded; decodeURIComponent in readCookies
        }
        function setCookieEncoded(name, encodedValue) {
            // encodedValue must already be encodeURIComponent'd (or a slice of it)
            document.cookie = name + '=' + encodedValue + '; path=/; max-age=31536000; SameSite=Lax';
        }
        function delCookie(name) {
            document.cookie = name + '=; path=/; max-age=0; SameSite=Lax';
        }

        function clearCookieChunks() {
            const n = parseInt(decodeURIComponent(getCookie(COOKIE_META) || '0'), 10) || 0;
            for (let i = 0; i < Math.max(n, 40); i++) delCookie(COOKIE_PREFIX + i);
            delCookie(COOKIE_META);
            delCookie('yarkids_chat');
        }

        function writeCookies(raw) {
            clearCookieChunks();
            const encoded = encodeURIComponent(raw);
            const parts = [];
            for (let i = 0; i < encoded.length; i += ENCODED_CHUNK) {
                parts.push(encoded.slice(i, i + ENCODED_CHUNK));
            }
            if (!parts.length) parts.push(encodeURIComponent('{}'));
            setCookieEncoded(COOKIE_META, encodeURIComponent(String(parts.length)));
            parts.forEach((p, idx) => setCookieEncoded(COOKIE_PREFIX + idx, p));
        }

        function readCookies() {
            const nRaw = getCookie(COOKIE_META);
            const n = nRaw ? parseInt(decodeURIComponent(nRaw), 10) || 0 : 0;
            if (!n) {
                const legacy = getCookie('yarkids_chat');
                return legacy ? decodeURIComponent(legacy) : '';
            }
            let encoded = '';
            for (let i = 0; i < n; i++) {
                const part = getCookie(COOKIE_PREFIX + i);
                if (part == null) return ''; // incomplete — treat as missing
                encoded += part;
            }
            try {
                return decodeURIComponent(encoded);
            } catch (_) {
                return '';
            }
        }

        function sessionById(id) {
            return store.sessions.find((s) => s.id === id) || null;
        }

        function getCurrentSession() {
            return sessionById(store.activeId);
        }

        function touchSession(session, messages, persona, actPersona) {
            if (!session) return;
            session.messages = (messages || []).map((m) => ({
                role: m.role,
                content: String(m.content || ''),
            }));
            session.persona = persona || 'auto';
            session.activePersona = actPersona || null;
            session.updatedAt = Date.now();
            const firstUser = session.messages.find((m) => m.role === 'user');
            if (firstUser) {
                session.title = firstUser.content.trim().slice(0, 40) || 'گفتگوی جدید';
            } else if (!session.title) {
                session.title = 'گفتگوی جدید';
            }
        }

        function buildPersistable() {
            // newest first
            const sessions = store.sessions
                .slice()
                .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
                .slice(0, MAX_SESSIONS)
                .map((s) => ({
                    id: s.id,
                    title: String(s.title || 'گفتگوی جدید').slice(0, 60),
                    updatedAt: s.updatedAt || 0,
                    persona: s.persona || 'auto',
                    activePersona: s.activePersona || null,
                    messages: (s.messages || []).slice(-MAX_MESSAGES).map((m) => ({
                        role: m.role,
                        content: String(m.content || '').slice(0, MAX_CONTENT),
                    })),
                }));

            // keep active session even if it would fall outside top N
            if (store.activeId && !sessions.some((s) => s.id === store.activeId)) {
                const active = store.sessions.find((s) => s.id === store.activeId);
                if (active) {
                    sessions.pop();
                    sessions.unshift({
                        id: active.id,
                        title: String(active.title || 'گفتگوی جدید').slice(0, 60),
                        updatedAt: active.updatedAt || Date.now(),
                        persona: active.persona || 'auto',
                        activePersona: active.activePersona || null,
                        messages: (active.messages || []).slice(-MAX_MESSAGES).map((m) => ({
                            role: m.role,
                            content: String(m.content || '').slice(0, MAX_CONTENT),
                        })),
                    });
                }
            }

            let payload = {
                activeId: store.activeId,
                selectedPersona: store.selectedPersona || 'auto',
                sessions: sessions,
            };

            // shrink until encoded cookie set is reasonable (~8 chunks max)
            let raw = JSON.stringify(payload);
            let guard = 0;
            while (encodeURIComponent(raw).length > ENCODED_CHUNK * 10 && guard < 40) {
                guard += 1;
                let shrunk = false;
                for (const s of payload.sessions) {
                    if (s.messages.length > 2) {
                        s.messages.shift();
                        shrunk = true;
                    }
                }
                if (!shrunk) {
                    for (const s of payload.sessions) {
                        for (const m of s.messages) {
                            if (m.content.length > 120) {
                                m.content = m.content.slice(0, Math.floor(m.content.length * 0.7));
                                shrunk = true;
                            }
                        }
                    }
                }
                if (!shrunk && payload.sessions.length > 1) {
                    // drop oldest non-active
                    const idx = payload.sessions.map((s) => s.id).lastIndexOf(
                        payload.sessions.filter((s) => s.id !== payload.activeId).slice(-1)[0]?.id
                    );
                    const dropId = payload.sessions.filter((s) => s.id !== payload.activeId).pop()?.id;
                    if (dropId) {
                        payload.sessions = payload.sessions.filter((s) => s.id !== dropId);
                        shrunk = true;
                    }
                }
                if (!shrunk) break;
                raw = JSON.stringify(payload);
            }
            return payload;
        }

        function saveStore() {
            // flush active UI state into its session object first
            const current = getCurrentSession();
            if (current) {
                touchSession(current, history, selectedPersona, activePersona);
            }
            store.selectedPersona = selectedPersona;
            const persistable = buildPersistable();
            // sync in-memory store to what we persist (same ids/messages)
            const byId = new Map(store.sessions.map((s) => [s.id, s]));
            persistable.sessions.forEach((ps) => {
                const live = byId.get(ps.id);
                if (live) {
                    live.title = ps.title;
                    live.updatedAt = ps.updatedAt;
                    live.persona = ps.persona;
                    live.activePersona = ps.activePersona;
                    live.messages = ps.messages.slice();
                }
            });
            store.sessions = persistable.sessions.map((ps) => {
                const live = byId.get(ps.id);
                return live || ps;
            });
            store.activeId = persistable.activeId;
            store.selectedPersona = persistable.selectedPersona;
            writeCookies(JSON.stringify(persistable));
            renderSessionList();
        }

        function loadStore() {
            try {
                const raw = readCookies();
                if (!raw) return;
                const data = JSON.parse(raw);
                if (!data || !Array.isArray(data.sessions)) return;
                store = {
                    activeId: data.activeId || (data.sessions[0] && data.sessions[0].id) || null,
                    selectedPersona: data.selectedPersona || 'auto',
                    sessions: data.sessions.map((s) => ({
                        id: s.id,
                        title: s.title || 'گفتگوی جدید',
                        updatedAt: s.updatedAt || 0,
                        persona: s.persona || 'auto',
                        activePersona: s.activePersona || null,
                        messages: Array.isArray(s.messages) ? s.messages.slice() : [],
                    })),
                };
            } catch (_) { /* ignore corrupt cookie */ }
        }

        function ensureSession() {
            let s = getCurrentSession();
            if (s) return s;
            s = {
                id: uid(),
                title: 'گفتگوی جدید',
                updatedAt: Date.now(),
                persona: selectedPersona,
                activePersona: activePersona,
                messages: [],
            };
            store.sessions.unshift(s);
            store.activeId = s.id;
            return s;
        }

        function loadSessionIntoUi(session) {
            history = (session && session.messages) ? session.messages.slice() : [];
            selectedPersona = (session && session.persona) || 'auto';
            activePersona = (session && session.activePersona) || null;
            store.selectedPersona = selectedPersona;
            renderMessages();
            updatePersonaChip();
            renderPersonaMenu();
        }

        function createSession() {
            if (isBusy) return;
            // save current chat BEFORE switching
            const prev = getCurrentSession();
            if (prev) touchSession(prev, history, selectedPersona, activePersona);

            const s = {
                id: uid(),
                title: 'گفتگوی جدید',
                updatedAt: Date.now(),
                persona: 'auto',
                activePersona: null,
                messages: [],
            };
            store.sessions.unshift(s);
            store.activeId = s.id;
            selectedPersona = 'auto';
            activePersona = null;
            history = [];
            saveStore();
            renderMessages();
            updatePersonaChip();
            renderPersonaMenu();
            closeSidebarMobile();
            input.focus();
        }

        function switchSession(id) {
            if (isBusy) return;
            if (store.activeId === id) {
                closeSidebarMobile();
                return;
            }
            const prev = getCurrentSession();
            if (prev) touchSession(prev, history, selectedPersona, activePersona);

            store.activeId = id;
            const s = getCurrentSession();
            if (!s) return;
            loadSessionIntoUi(s);
            saveStore();
            closeSidebarMobile();
            input.focus();
        }

        function deleteSession(id) {
            if (isBusy) return;
            if (store.activeId === id) {
                const prev = getCurrentSession();
                if (prev) touchSession(prev, history, selectedPersona, activePersona);
            }
            store.sessions = store.sessions.filter((s) => s.id !== id);
            if (store.activeId === id) {
                if (store.sessions.length) {
                    store.sessions.sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0));
                    store.activeId = store.sessions[0].id;
                    loadSessionIntoUi(store.sessions[0]);
                } else {
                    store.activeId = null;
                    history = [];
                    selectedPersona = 'auto';
                    activePersona = null;
                    ensureSession();
                    renderMessages();
                    updatePersonaChip();
                    renderPersonaMenu();
                }
            }
            saveStore();
        }

        function renderSessionList() {
            sessionList.innerHTML = '';
            if (!store.sessions.length) {
                const empty = document.createElement('div');
                empty.className = 'session-empty';
                empty.textContent = 'هنوز گفتگویی نیست';
                sessionList.appendChild(empty);
                return;
            }
            store.sessions
                .slice()
                .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
                .forEach((s) => {
                    const row = document.createElement('div');
                    row.className = 'session-item' + (s.id === store.activeId ? ' active' : '');
                    const openBtn = document.createElement('button');
                    openBtn.type = 'button';
                    openBtn.className = 'session-open';
                    openBtn.textContent = s.title || 'گفتگوی جدید';
                    openBtn.title = isBusy ? 'تا پایان پاسخ صبر کن' : (s.title || 'گفتگوی جدید');
                    openBtn.disabled = isBusy;
                    openBtn.addEventListener('click', () => switchSession(s.id));
                    const delBtn = document.createElement('button');
                    delBtn.type = 'button';
                    delBtn.className = 'session-del';
                    delBtn.setAttribute('aria-label', 'حذف');
                    delBtn.textContent = '×';
                    delBtn.disabled = isBusy;
                    delBtn.addEventListener('click', (e) => {
                        e.stopPropagation();
                        deleteSession(s.id);
                    });
                    row.appendChild(openBtn);
                    row.appendChild(delBtn);
                    sessionList.appendChild(row);
                });
        }

        function renderEmpty() {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.id = 'empty';
            empty.innerHTML = 'با <strong>یار کودک</strong> مستقیم حرف بزن.<br>سوالت را بنویس تا شروع کنیم.';
            messagesEl.appendChild(empty);
        }

        function renderMessages() {
            messagesEl.innerHTML = '';
            if (!history.length) {
                renderEmpty();
                return;
            }
            history.forEach((m) => {
                if (m.role === 'user') addBubble('user', m.content, null, false, false);
                else addBubble('assistant', m.content, null, true, false);
            });
            messagesEl.scrollTop = messagesEl.scrollHeight;
        }

        function labelFor(value) {
            const hit = personas.find((p) => p.value === value);
            return hit ? hit.label : (value || '');
        }
        function shortLabel(value) {
            const full = labelFor(value);
            const parts = full.trim().split(/\\s+/);
            return parts.length > 1 ? parts.slice(1).join(' ') : full;
        }
        function updatePersonaChip() {
            const showValue = selectedPersona !== 'auto'
                ? selectedPersona
                : (activePersona && activePersona !== 'none' ? activePersona : null);
            if (showValue) {
                personaWrap.classList.add('visible');
                personaHint.hidden = true;
                personaBtn.textContent = shortLabel(showValue);
            } else {
                personaWrap.classList.remove('visible');
                personaHint.hidden = false;
            }
        }
        function renderPersonaMenu() {
            personaMenu.innerHTML = '';
            personas.forEach((p) => {
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'persona-option' + (p.value === selectedPersona ? ' active' : '');
                btn.textContent = p.label;
                btn.setAttribute('role', 'option');
                btn.addEventListener('click', () => {
                    selectedPersona = p.value;
                    activePersona = p.value !== 'auto' ? p.value : null;
                    closePersonaMenu();
                    updatePersonaChip();
                    renderPersonaMenu();
                    saveStore();
                });
                personaMenu.appendChild(btn);
            });
        }
        function openPersonaMenu() {
            if (!personaWrap.classList.contains('visible')) {
                personaWrap.classList.add('visible');
                personaHint.hidden = true;
                personaBtn.textContent = shortLabel(selectedPersona !== 'auto' ? selectedPersona : 'auto');
            }
            personaMenu.classList.add('open');
            personaBtn.classList.add('open');
            personaBtn.setAttribute('aria-expanded', 'true');
        }
        function closePersonaMenu() {
            personaMenu.classList.remove('open');
            personaBtn.classList.remove('open');
            personaBtn.setAttribute('aria-expanded', 'false');
            updatePersonaChip();
        }

        personaBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (personaMenu.classList.contains('open')) closePersonaMenu();
            else openPersonaMenu();
        });
        personaHint.addEventListener('click', (e) => {
            e.stopPropagation();
            openPersonaMenu();
        });
        document.addEventListener('click', () => closePersonaMenu());
        personaMenu.addEventListener('click', (e) => e.stopPropagation());

        function openSidebarMobile() { document.body.classList.add('sidebar-open'); }
        function closeSidebarMobile() { document.body.classList.remove('sidebar-open'); }
        menuToggle.addEventListener('click', () => {
            if (document.body.classList.contains('sidebar-open')) closeSidebarMobile();
            else openSidebarMobile();
        });
        sidebarBackdrop.addEventListener('click', closeSidebarMobile);
        newChatBtn.addEventListener('click', createSession);

        async function loadPersonas() {
            try {
                const res = await fetch('/v1/personas');
                if (!res.ok) return;
                const data = await res.json();
                if (Array.isArray(data.personas) && data.personas.length) {
                    personas = data.personas.map((p) => ({ value: p.value, label: p.label }));
                    if (!personas.some((p) => p.value === 'auto')) {
                        personas.unshift({ value: 'auto', label: '✨ خودکار' });
                    }
                }
            } catch (_) {}
            renderPersonaMenu();
            updatePersonaChip();
        }

        function renderMarkdown(text) {
            if (window.marked && window.DOMPurify) {
                return DOMPurify.sanitize(marked.parse(String(text || '')));
            }
            return String(text || '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\\n/g, '<br>');
        }

        function addBubble(role, text, extraClass, asMarkdown, scroll) {
            const empty = document.getElementById('empty');
            if (empty) empty.remove();
            const div = document.createElement('div');
            div.className = 'bubble ' + role + (extraClass ? ' ' + extraClass : '');
            if (asMarkdown) {
                div.classList.add('md');
                div.innerHTML = renderMarkdown(text);
            } else {
                div.textContent = text;
            }
            messagesEl.appendChild(div);
            if (scroll !== false) messagesEl.scrollTop = messagesEl.scrollHeight;
            return div;
        }

        function autoResize() {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        }
        input.addEventListener('input', autoResize);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                form.requestSubmit();
            }
        });

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!text || isBusy || sendBtn.disabled) return;

            const session = ensureSession();
            const sessionId = session.id;
            const token = ++requestToken;

            addBubble('user', text);
            history.push({ role: 'user', content: text });
            touchSession(session, history, selectedPersona, activePersona);
            saveStore();

            input.value = '';
            autoResize();
            setBusy(true);
            const typing = addBubble('assistant', 'در حال فکر کردن...', 'typing');

            // snapshot messages for THIS session only (avoid using UI history after switch)
            const messagesForRequest = history.slice();
            const personaForRequest = selectedPersona;

            const payload = { messages: messagesForRequest };
            if (personaForRequest && personaForRequest !== 'auto') payload.persona = personaForRequest;

            try {
                const res = await fetch('/v1/chat/completions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await res.json().catch(() => ({}));

                // Always attach reply to the originating session, never the currently open one.
                const target = sessionById(sessionId);
                if (!target) {
                    if (typing && typing.parentNode) typing.remove();
                    return;
                }

                if (!res.ok) {
                    const detail = (data && (data.detail || data.error || data.message)) || ('خطا ' + res.status);
                    // roll back the user message only if still last in THAT session
                    const msgs = (target.messages || []).slice();
                    if (msgs.length && msgs[msgs.length - 1].role === 'user' && msgs[msgs.length - 1].content === text) {
                        msgs.pop();
                    }
                    touchSession(target, msgs, target.persona, target.activePersona);
                    if (token === requestToken && store.activeId === sessionId) {
                        if (typing && typing.parentNode) typing.remove();
                        history = msgs.slice();
                        addBubble('assistant', String(detail), 'error');
                    } else if (typing && typing.parentNode) {
                        typing.remove();
                    }
                    saveStore();
                    return;
                }

                const reply = data?.choices?.[0]?.message?.content
                    || data?.response
                    || 'پاسخی دریافت نشد.';
                const resolved = data?.yarkids?.persona || data?.persona || null;

                const msgs = (target.messages || []).slice();
                // ensure user message is present (already saved), then append assistant
                msgs.push({ role: 'assistant', content: reply });
                let nextActive = target.activePersona;
                if (resolved && resolved !== 'none') nextActive = resolved;
                touchSession(target, msgs, target.persona, nextActive);

                if (token === requestToken && store.activeId === sessionId) {
                    if (typing && typing.parentNode) typing.remove();
                    history = msgs.slice();
                    if (resolved && resolved !== 'none') {
                        activePersona = resolved;
                        updatePersonaChip();
                        renderPersonaMenu();
                    }
                    addBubble('assistant', reply, null, true);
                } else if (typing && typing.parentNode) {
                    typing.remove();
                }
                saveStore();
            } catch (err) {
                const target = sessionById(sessionId);
                if (target) {
                    const msgs = (target.messages || []).slice();
                    if (msgs.length && msgs[msgs.length - 1].role === 'user' && msgs[msgs.length - 1].content === text) {
                        msgs.pop();
                    }
                    touchSession(target, msgs, target.persona, target.activePersona);
                    if (token === requestToken && store.activeId === sessionId) {
                        history = msgs.slice();
                        if (typing && typing.parentNode) typing.remove();
                        addBubble('assistant', 'ارتباط با سرور برقرار نشد. دوباره تلاش کن.', 'error');
                    } else if (typing && typing.parentNode) {
                        typing.remove();
                    }
                    saveStore();
                } else if (typing && typing.parentNode) {
                    typing.remove();
                }
            } finally {
                if (token === requestToken) {
                    setBusy(false);
                    input.focus();
                }
            }
        });

        // boot
        loadStore();
        ensureSession();
        const current = getCurrentSession();
        loadSessionIntoUi(current);
        saveStore();
        loadPersonas();
    </script>
</body>
</html>
"""



@router.get("/", response_class=HTMLResponse)
async def landing_page() -> HTMLResponse:
    """صفحه اصلی Yar Kids — معرفی قابلیت‌ها و هدایت به yarai.ir"""
    return HTMLResponse(content=LANDING_PAGE_HTML)


@router.get("/chat", response_class=HTMLResponse)
async def chat_playground() -> HTMLResponse:
    """اینترفیس ساده چت مستقیم با یار کودک (OpenAI-compatible)."""
    return HTMLResponse(content=CHAT_PAGE_HTML)
