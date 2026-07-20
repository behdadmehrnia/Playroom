"""Shared constants, persona sets, and prompt/instruction strings."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

MODEL_ID = "yarkids"
MODEL_NAME = "یار کودک"
MAX_GENERATION_ATTEMPTS = 3
INTENT_CONFIDENCE_THRESHOLD = 0.7
MANUAL_PERSONA_METADATA_KEY = "yarkids_persona"
ACTIVE_PERSONA_METADATA_KEY = "yarkids_active_persona"
PENDING_PERSONA_METADATA_KEY = "yarkids_pending_persona"
# Legacy HTML marker (may still appear in older chat history).
_PERSONA_MARKER_RE = re.compile(r"<!--\s*yarkids:([a-z_]+)\s*-->", re.IGNORECASE)
# Invisible sticky marker: Word Joiner + 2 zero-width chars + Word Joiner.
# Zero-width space/non-joiner/joiner encode the persona without showing in the UI.
_ZW_MARK = "\u2060"
_ZW_DIGIT = {"0": "\u200b", "1": "\u200c", "2": "\u200d"}
_ZW_DIGIT_INV = {v: k for k, v in _ZW_DIGIT.items()}
_PERSONA_ZW_CODE: dict[str, str] = {
    "creative": "00",
    "storyteller": "01",
    "teacher": "02",
    "homework": "10",
    "gamer": "11",
}
_ZW_CODE_PERSONA: dict[str, str] = {v: k for k, v in _PERSONA_ZW_CODE.items()}
_ZW_PERSONA_MARKER_RE = re.compile(
    f"{_ZW_MARK}([{_ZW_DIGIT['0']}{_ZW_DIGIT['1']}{_ZW_DIGIT['2']}]{{2}}){_ZW_MARK}"
)
PERSONA_AUTO_VALUE = "auto"
SUPPORTED_PERSONAS = ("creative", "storyteller", "teacher", "homework", "gamer")
REVISION_INSTRUCTION_HEADER = "بازبینی لازم است. پاسخ قبلی مناسب نبود. دلایل:"
TEXTBOOK_CONTEXT_HEADER = (
    "متن کتاب درسی بازیابی‌شده (مرجع — برای راهنمایی آموزشی؛ جواب نهایی را بدون آموزش روش نده):"
)
TEXTBOOK_CONTEXT_INSTRUCTION = (
    "مهم: متن واقعی صفحهٔ کتاب درسی در ادامه آمده است. "
    "فقط و فقط از همین متن برای کمک به کودک استفاده کن. "
    "چیزی از خودت به متن اضافه نکن و محتوای صفحه را حدس نزن. "
    "**همین حالا همین صفحه را در اختیار داری.** "
    "مستقیم و مهربان با محتوای همین صفحه کمک را شروع کن "
    "(مثلاً بگو در این صفحه چه تمرینی هست و از کجا شروع کنیم). "
    "اگر کودک خواست متن را بنویسی یا کلمات سخت را مشخص کنی، از همین متن استفاده کن. "
    "اگر چند صفحه از یک درس آمده، برای «کل درس / بقیهٔ درس / کلمات سخت درس» از همهٔ صفحات استفاده کن "
    "و از کودک نخواه صفحهٔ بعد را خودش باز کند. "
    "ممنوع: پرسیدن دوبارهٔ پایه/کتاب/صفحه؛ گفتن «صبر کن صفحه را باز کنم»؛ "
    "خواستنِ «یک خط از صفحه را بنویس» وقتی متن صفحه را داری؛ "
    "نوشتن پرانتز یا توضیح دربارهٔ سیستم/پرامپت/کانتکست؛ "
    "وانمود کردن که هنوز صفحه نرسیده. "
    "اگر تصویر صفحه هم ضمیمه شد، آن را «صفحهٔ کتاب» بنام — نه تصویر ارسالی کودک "
    "(مگر واقعاً در تاریخچهٔ کاربر تصویر آمده باشد)."
)
TEXTBOOK_IMAGE_ONLY_INSTRUCTION = (
    "مهم: متن این صفحه از فایل کتاب به‌درستی استخراج نشد و متنِ زیر ناخواناست، "
    "اما تصویر صفحه پیوست شده است. "
    "فقط و فقط محتوای صفحه را از روی «تصویر پیوست‌شده» بخوان و به کودک کمک کن. "
    "به متن ناخوانای زیر استناد نکن و محتوای صفحه را از خودت حدس نزن. "
    "این تصویر، ضمیمهٔ مرجع از پایگاه کتاب است و تصویر ارسالیِ کاربر نیست؛ "
    "پس هرگز نگو «تصویری که فرستادی» مگر اینکه واقعاً کاربر تصویری فرستاده باشد. "
    "دربارهٔ سیستم یا فرستادن تصویر حرف نزن؛ مستقیم از روی صفحه کمک کن. "
    "**ممنوع:** گفتن «کتاب‌ها ممکن است تغییر کنند» یا خواستنِ یک خط از صفحه وقتی تصویر صفحه را داری."
)
TEXTBOOK_UNREADABLE_INSTRUCTION = (
    "توجه مهم: صفحهٔ درخواستی پیدا شد، اما متن آن از فایل کتاب ناخوانا استخراج شد "
    "و تصویری هم برای نمایش در دسترس نیست. "
    "به‌هیچ‌وجه محتوای صفحه، شعر، متن یا تمرین را از خودت نساز و حدس نزن. "
    "صادقانه و مهربان به کودک بگو الان نتوانستی متن این صفحه را درست بخوانی، "
    "و از او بخواه بخشی از متن یا سوالش را خودش بنویسد تا با هم کار کنید. "
    "دربارهٔ سیستم یا پرامپت حرف نزن."
)
TEXTBOOK_LOOKUP_FAILED_INSTRUCTION = (
    "توجه مهم: کودک صفحه/درس مشخصی خواسته، اما متن آن صفحه الان در پرامپت نیست "
    "(پیدا نشد یا سرویس در دسترس نبود). "
    "به‌هیچ‌وجه محتوای آن صفحه/درس را از خودت نساز و حدس نزن "
    "(حتی نام یا موضوع درس را هم از خودت نگو). "
    "**هرگز نگو «به کتابت دسترسی ندارم» و هرگز دربارهٔ سیستم/پرامپت/صبر برای باز شدن صفحه حرف نزن.** "
    "اگر پایه و کتاب و شمارهٔ صفحه را قبلاً گفته: مهربان بگو الان نتوانستی همان صفحه را پیدا کنی "
    "و بخواه یک خط از تمرین یا صورت سوال را خودش بنویسد. "
    "اگر یکی از این سه تا را نگفته: فقط همان موردِ گم‌شده را بپرس "
    "(صفحه؟ پایه؟ کدام کتاب؟). "
    "هرگز وانمود نکن که متن یا تصویری را می‌بینی که نداری."
)
TEXTBOOK_NEED_INFO_INSTRUCTION = (
    "توجه: کودک دربارهٔ تمرین/درس/صفحهٔ کتاب صحبت می‌کند، اما هنوز اطلاعات کافی برای "
    "پیدا کردن دقیق صفحه نداری. "
    "**هرگز نگو «به کتابت دسترسی ندارم» و دربارهٔ سیستم حرف نزن.** "
    "مهربان و کوتاه فقط مواردی را که هنوز نمی‌دانی بپرس: "
    "۱) شمارهٔ صفحه؟ ۲) کلاس چندم؟ ۳) کدام کتاب/درس؟ "
    "محتوای صفحه را از خودت نساز؛ فقط اطلاعات لازم را بپرس."
)
DEFAULT_TEXTBOOK_TIMEOUT_SEC = 5.0
WEB_SEARCH_CONTEXT_HEADER = (
    "نتایج جستجوی اینترنت (مرجع به‌روز — فقط برای حقایق؛ چیز ساختگی اضافه نکن):"
)
WEB_SEARCH_CONTEXT_INSTRUCTION = (
    "مهم: نتایج واقعی جستجوی وب در ادامه آمده است. "
    "اگر سؤال کودک به اطلاعات واقعی/به‌روز نیاز دارد (بازی، واقعیت، راهنما)، "
    "فقط از همین نتایج استفاده کن و چیزی از خودت اختراع نکن. "
    "**ممنوع بدون استناد به همین نتایج:** گفتن «این بازی وجود ندارد»، "
    "«هنوز ساخته/منتشر نشده»، یا تصحیح نام بازی به نسخهٔ دیگر. "
    "اگر نتایج می‌گویند بازی اعلام/منتشر شده، همان را ملایم و مناسب سن بگو؛ "
    "اگر نتایج مبهم‌اند، بگو مطمئن نیستی — حدس نزن. "
    "محتوای نامناسب سن، خشن یا بزرگسال را از نتایج نادیده بگیر. "
    "لینک خام یا آدرس سایت را برای کودک نخوان مگر خیلی لازم باشد؛ "
    "به‌جایش خلاصهٔ ساده و ایمن بگو. "
    "دربارهٔ سیستم، سرچ، یا «اینترنت» به‌صورت فنی حرف نزن — "
    "مثل دوستی که چیزها را می‌داند جواب بده. "
    "اگر نتایج کافی نبودند، صادقانه بگو مطمئن نیستی و حدس نزن."
)
WEB_SEARCH_NO_RESULTS_INSTRUCTION = (
    "توجه: کودک دربارهٔ یک بازی یا واقعیت صحبت می‌کند، اما الان نتایج جستجوی وب "
    "در پرامپت نیست (پیدا نشد یا سرویس در دسترس نبود). "
    "**هرگز نگو این بازی وجود ندارد / هنوز ساخته نشده / منتشر نشده** مگر کاملاً مطمئن باشی. "
    "اگر مطمئن نیستی: هیجان‌زده با علاقه‌اش همراهی کن، بگو جزئیات دقیق را الان مطمئن نیستی، "
    "و بپرس دوست دارد دربارهٔ چه چیز بازی حرف بزنید یا بازی کلامی کنید. "
    "دربارهٔ سیستم یا جستجو حرف نزن."
)
DEFAULT_WEB_SEARCH_TIMEOUT_SEC = 8.0
DEFAULT_WEB_SEARCH_MAX_RESULTS = 5
SAFE_FALLBACK_RESPONSE = (
    "متأسفم، الان نتوانستم پاسخ مناسبی برایت بدهم. "
    "بیایید با هم یک موضوع دیگر را امتحان کنیم! "
    "می‌توانی دربارهٔ یک داستان، یک سوال درسی، یا یک ایدهٔ خلاقانه از من بپرسی."
)

# Child-friendly labels for persona dropdown and status messages.
PERSONA_UI_LABELS: dict[str, str] = {
    "auto": "✨ خودکار",
    "creative": "🎨 خلاق",
    "storyteller": "📖 داستان‌گو",
    "teacher": "📚 معلم",
    "homework": "✏️ کمک‌درس",
    "gamer": "🎮 بازی و سرگرمی",
    "none": "😊 یار کودک",
}

PERSONA_DROPDOWN_OPTIONS: list[dict[str, str]] = [
    {"value": "auto", "label": "✨ خودکار — خودم انتخاب می‌کنم!"},
    {"value": "creative", "label": "🎨 خلاق"},
    {"value": "storyteller", "label": "📖 داستان‌گو"},
    {"value": "teacher", "label": "📚 معلم"},
    {"value": "homework", "label": "✏️ کمک‌درس"},
    {"value": "gamer", "label": "🎮 بازی و سرگرمی"},
]

STREAM_CHUNK_SIZE = 16
# Brief pause so the UI can paint status before it is cleared for streaming.
STATUS_DISPLAY_PAUSE_SEC = 0.12

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

PersonaId = Literal["creative", "storyteller", "teacher", "homework", "gamer", "none"]
ReflectionStatus = Literal["PASS", "REVISE"]
VALID_PERSONAS: set[PersonaId] = {
    "creative",
    "storyteller",
    "teacher",
    "homework",
    "gamer",
    "none",
}
TEXTBOOK_PERSONAS: frozenset[PersonaId] = frozenset({"teacher", "homework"})
WEB_SEARCH_PERSONAS: frozenset[PersonaId] = frozenset(
    {"creative", "storyteller", "gamer"}
)
