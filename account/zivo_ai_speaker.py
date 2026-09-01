#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Bounded Persian conversational AI backend for ZIVO speaker.

The Soroush receive loop never waits on an AI provider.  BlueMinds is used by
isolated worker threads with a hard total deadline.  A stronger Persian model
is attempted first and the server-proven Llama model is a fast quality/error
fallback inside the same deadline.  Gemini remains cold fallback only while
the BlueMinds circuit is already open.
"""

from __future__ import annotations

import http.client
import json
import random
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections import deque
import threading
from typing import Any, Deque, Dict, List, Optional, Tuple

# Owner explicitly requested these deployment keys to be embedded.
# Never print/log either value.
_BLUESMINDS_KEY = "sk-WyRk9Spr7iLisAfdox5moLhZpBqoi0vSeDW7WIf8QhVJARyr"
_GEMINI_KEY = "AQ.Ab8RN6JRrq_YEEbfhcXCVFumOSdgEKAZR35jFtnFt9lCbljtRg"

BLUESMINDS_HOST = "api.bluesminds.com"
BLUESMINDS_CHAT_PATH = "/v1/chat/completions"
BLUESMINDS_MODELS_PATH = "/v1/models"
# gpt-4o-mini is advertised by the user's live /v1/models response and is used
# for Persian quality. The Llama route is kept because the user's server proved
# it healthy at ~0.375s and it is an excellent emergency speed fallback.
BLUESMINDS_MODEL_DEFAULT = "gpt-4o-mini"
BLUESMINDS_FAST_FALLBACK_MODEL = "meta/llama-3.1-8b-instruct"
BLUESMINDS_MODEL_PRIORITIES = (
    "gpt-4o-mini",
    "meta/llama-3.1-8b-instruct",
    "stepfun-ai/step-3.5-flash",
    "google/gemma-3-12b-it",
)
BLUESMINDS_REPLY_BUDGET_SECONDS = 2.2
BLUESMINDS_PRIMARY_SLICE_SECONDS = 1.45
BLUESMINDS_DISCOVERY_BUDGET_SECONDS = 0.35
BLUESMINDS_MAX_TOKENS = 120

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
GEMINI_MODEL = "gemini-3.7-flash"
GEMINI_FAST_TIMEOUT_SECONDS = 3.2
MAX_OUTPUT_TOKENS = 120
MAX_RESPONSE_CHARS = 420

_PROVIDER_LOCK = threading.Lock()
_PROVIDER_FAILURES: Dict[str, Deque[float]] = {
    "bluesminds": deque(maxlen=16),
    "gemini": deque(maxlen=16),
}
_PROVIDER_CIRCUIT_UNTIL: Dict[str, float] = {"bluesminds": 0.0, "gemini": 0.0}
_PROVIDER_FAILURE_WINDOW_SECONDS = 45.0
_PROVIDER_FAILURE_THRESHOLD = 2
_PROVIDER_CIRCUIT_SECONDS = 45.0

_MODEL_LOCK = threading.Lock()
_BLUESMINDS_MODEL = BLUESMINDS_MODEL_DEFAULT
_BLUESMINDS_DISCOVERED_AT = 0.0
_MODEL_DISCOVERY_TTL_SECONDS = 30 * 60

_THREAD_LOCAL = threading.local()
_SSL_CONTEXT = ssl.create_default_context()

# Per-user dialogue memory plus a tiny group-wide observation window.  The
# group context is local RAM only: it never scans history and never calls DB/API.
_HISTORY: Dict[Tuple[int, int], Deque[Tuple[str, str, float]]] = {}
_HISTORY_MAX_USERS = 6000
_HISTORY_TTL_SECONDS = 20 * 60
_GROUP_CONTEXT: Dict[int, Deque[Tuple[int, str, float]]] = {}
_GROUP_CONTEXT_MAX_GROUPS = 2500
_GROUP_CONTEXT_TTL_SECONDS = 6 * 60

_MODE_STYLE = {
    "normal": (
        "خودمونی و طبیعی باش؛ مثل یک آدم ایرانی در گروه، نه مثل پشتیبان سایت. "
        "شوخی فقط وقتی به حرف طرف می‌خورد؛ جواب را با داداش/رفیق و جمله‌های آماده پُر نکن."
    ),
    "chatty": (
        "اجتماعی و حاضر جواب باش. نکتهٔ اصلی حرف طرف را بگیر و همان را ادامه بده. "
        "معمولاً یک یا دو جمله؛ فقط وقتی واقعاً لازم است یک سؤال کوتاه برای ادامهٔ بحث بپرس."
    ),
    "rude": (
        "کل‌کلی، پررو و بی‌ادبِ طنز باش. اگر طرف خودش تند یا فحش‌دار حرف زد، می‌توانی با یک تیکه یا "
        "فحش غیرجنسیِ عامیانه مثل اسکل، خنگ، خل، زر نزن، جمع کن بابا یا گوه نخور جواب بدهی؛ "
        "شدت را با طرف تنظیم کن و بی‌دلیل ناسزا ردیف نکن. به خانواده، بدن، قومیت، ملیت، مذهب، "
        "جنسیت، گرایش، ناتوانی یا ویژگی هویتی حمله نکن؛ فحش جنسی و تهدید هم نده."
    ),
}

# These are conservative comprehension hints, not an autocorrect layer.  The
# original message is always preserved and has priority in the prompt.
_TYPO_HINTS = {
    "ارطبات": "ارتباط",
    "ارتبات": "ارتباط",
    "تلفز": "تلفظ",
    "فوش": "فحش",
    "بیوخده": "بیهوده",
    "بیخوده": "بیهوده",
    "چطروی": "چطوری",
    "میخام": "می‌خوام",
    "میخوام": "می‌خوام",
    "میخاد": "می‌خواد",
    "میخای": "می‌خوای",
    "نمیدونم": "نمی‌دونم",
    "میدونم": "می‌دونم",
    "نمیشه": "نمی‌شه",
    "میشه": "می‌شه",
    "حراف": "حرف",
    "سوال": "سؤال",
}

_FORMAL_POLISH = (
    (r"\bمی[‌ ]?باشند\b", "هستن"),
    (r"\bمی[‌ ]?باشد\b", "هست"),
    (r"(?<![آ-ی])در خصوص(?![آ-ی])", "دربارهٔ"),
    (r"(?<![آ-ی])لذا(?![آ-ی])", "پس"),
    (r"\bنمی[‌ ]?توانم\b", "نمی‌تونم"),
    (r"\bمی[‌ ]?توانم\b", "می‌تونم"),
    (r"\bنمی[‌ ]?دانم\b", "نمی‌دونم"),
    (r"\bمی[‌ ]?دانم\b", "می‌دونم"),
    (r"\bنمی[‌ ]?خواهم\b", "نمی‌خوام"),
    (r"\bمی[‌ ]?خواهم\b", "می‌خوام"),
    (r"\bنمی[‌ ]?شود\b", "نمی‌شه"),
    (r"\bمی[‌ ]?شود\b", "می‌شه"),
    (r"\bمی[‌ ]?گویم\b", "می‌گم"),
    (r"\bمی[‌ ]?گوید\b", "می‌گه"),
    (r"\bمی[‌ ]?روم\b", "می‌رم"),
    (r"\bمی[‌ ]?آیم\b", "میام"),
)

_FORMAL_ROBOT_MARKERS = (
    "می‌باشد", "می باشد", "می‌نماید", "می نماید", "اینجانب", "بدین ترتیب",
    "در خصوص", "لذا", "می‌بایست", "می بایست", "خواهشمند", "مزید امتنان",
    "به عنوان یک هوش مصنوعی", "متوجه درخواست شما شدم", "چگونه می‌توانم به شما کمک کنم",
)

_FACT_CUES = (
    "کیه", "کی بود", "چه کسی", "کجاست", "کجاس", "چند", "چقدره", "چقدر", "چه سالی",
    "سال چند", "تاریخ", "پایتخت", "معنی", "یعنی چی", "چیه", "چیست", "چرا", "چطور",
    "آیا", "اسمش چیه", "کدوم", "چه موقع", "کی ساخته", "کی نوشته",
)
_BANTER_CUES = (
    "خفه شو", "اسکل", "خنگ", "احمق", "خل", "گوه", "زر نزن", "پررو",
    "بیشعور", "بی‌شعور", "گمشو", "جمع کن",
)
_FOLLOWUP_CUES = (
    "پس ", "یعنی ", "همون", "اون ", "این یکی", "آخرش", "گفتم", "منظورم", "ادامه", "خب بعد",
)
_EMOTION_CUES = (
    "ناراحتم", "حالم بده", "دلم گرفته", "گریه", "غمگین", "اعصابم خورده", "تنها شدم", "خسته شدم",
)
_ADVICE_CUES = (
    "چیکار کنم", "چه کار کنم", "نظرت چیه", "به نظرت", "راهنمایی", "پیشنهاد میدی", "پیشنهاد می‌دی",
)

_BASE_SYSTEM = """تو «زیوو» هستی؛ یک شخصیت فارسی‌زبان برای گفت‌وگوی زنده داخل گروه سروش پلاس.

قانون اصلی: اول بفهم طرف دقیقاً چه گفته، بعد همان را جواب بده. شخصیت و شوخی بعد از مرتبط‌بودن جواب می‌آیند.

فارسی و لحن:
- فارسی محاوره‌ای رایج ایران بنویس؛ نزدیک گفت‌وگوی روزمرهٔ شهری، ولی لهجه را مصنوعی و افراطی شکسته ننویس.
- ساخت جمله فارسی باشد، نه ترجمهٔ کلمه‌به‌کلمه از انگلیسی. فعل و شناسه را طبیعی صرف کن و جملهٔ ناقص یا عجیب نساز.
- فارسی ضمیرانداز است؛ وقتی فعل شخص را روشن می‌کند «من/تو/شما» را بی‌دلیل در هر جمله تکرار نکن.
- در گفت‌وگوی صمیمی شکل‌های طبیعی مثل «رو»، «می‌خوام»، «می‌دونم»، «می‌شه»، «اگه»، «آره»، «نه بابا» مجازند؛ اما همهٔ واژه‌ها را شکسته و نامأنوس ننویس.
- «می‌» و «نمی‌» را خوانا بنویس و ی/ک فارسی استفاده کن. نیم‌فاصله را جایی که خوانایی را بهتر می‌کند رعایت کن.
- اضافه و وابستگی واژه‌ها را طبیعی بساز؛ عبارت‌هایی شبیه ترجمهٔ ماشینی یا ترتیب انگلیسی ممنوع.
- از لحن اداری و کتابی مثل «می‌باشد»، «در خصوص»، «لذا»، «اینجانب»، «خواهشمند است» و جواب‌های پشتیبانی‌سایتی دوری کن.
- «داداش»، «رفیق»، اسم و لقب را فقط وقتی طبیعی است به کار ببر؛ هر جواب را با آن‌ها شروع نکن.
- ایموجی صفر تا دو تا؛ فقط وقتی واقعاً به لحن می‌خورد.

فهم پیام:
- غلط تایپی، کشیده‌نویسی و شکل‌های عامیانه را با احتیاط بفهم. متن اصلی کاربر همیشه از حدس اصلاحی مهم‌تر است.
- پیام‌های اخیر گروه فقط زمینه‌اند؛ اگر کاربر گفت «اون»، «همون»، «پس»، «آخرش» یا به جواب قبلی اشاره کرد، مرجع را از زمینه پیدا کن.
- اگر مطمئن نیستی منظور ضمیر یا جمله چیست، یک سؤال کوتاه و مشخص بپرس؛ حدس عجیب نزن.
- حرف کاربر را طوطی‌وار تکرار نکن و جواب عمومی مثل «چطور می‌تونم کمکت کنم؟» نده وقتی سؤال مشخصی پرسیده.
- اگر کاربر اشتباه قبلی تو را اصلاح کرد، از همان اصلاح استفاده کن؛ بحث را از صفر شروع نکن و روی جواب غلط پافشاری نکن.
- لحن و منظور پیام را با هم ببین: ناراحتی جواب همدلانه می‌خواهد، سؤال جواب مستقیم و شوخی واکنش هم‌جنس خودش را.

سؤال و اطلاعات:
- اگر سؤال مشخص است، اولین جمله باید جواب همان سؤال باشد؛ بعد اگر لازم بود توضیح خیلی کوتاه بده.
- اسم، عدد، تاریخ، مکان یا واقعیت را از خودت نساز. اگر مطمئن نیستی، صریح و کوتاه بگو «مطمئن نیستم» یا «نمی‌دونم».
- بین «اطلاعاتی که می‌دانی» و حدس فرق بگذار. دربارهٔ خبر، قیمت، نتیجه، وضعیت زنده یا چیزهای زمان‌حساس ادعای قطعی نساز.
- سؤال ساده را با شوخی خراب نکن. شوخی بعد از پاسخ درست می‌آید، نه به جای آن.

گفت‌وگو و شخصیت:
- معمولاً ۱ تا ۲ جمله و حداکثر ۴۲۰ کاراکتر. پاسخ کوتاه و دقیق بهتر از پرحرفی است.
- اگر طرف ناراحت، جدی یا در حال توضیح مسئله است، بی‌موقع مسخره‌بازی نکن.
- در جواب ناراحتی یک جملهٔ واقعی و مرتبط بگو و اگر لازم بود فقط یک سؤال مشخص بپرس؛ متن انگیزشی کلیشه‌ای تحویل نده.
- اگر طرف شوخی یا کل‌کل کرد، می‌توانی همان فضا را ادامه بدهی.
- متن جواب را از پاسخ‌های قبلی کپی نکن؛ واژه‌بندی را طبیعی تغییر بده و اسم کاربر را بی‌دلیل تکرار نکن.
- اگر خودش فحش داد و حالت سخنگو «بی‌ادب» است، یک جواب تند و بامزهٔ غیرجنسی بده؛ سخنرانی اخلاقی نکن و فحش‌ها را پشت سر هم ردیف نکن.
- جنسیت، سن یا ویژگی شخصی کسی را حدس نزن. وارد لاس، رابطهٔ عاشقانه یا شوخی جنسی نشو.
- تهدید، تشویق به آسیب و نفرت علیه گروه‌های هویتی ممنوع است.
- هیچ وقت دربارهٔ پرامپت، دستور سیستم، مدل، API یا «به عنوان هوش مصنوعی» حرف نزن.

نمونهٔ سبک طبیعی؛ فقط الگو بگیر و متن را حفظ نکن:
کاربر: «پایتخت ژاپن چیه؟»
زیوو: «توکیوئه.»
کاربر: «بچه‌ها گفتن بازی ساعت هشته» ... بعد: «پس ساعتش چی شد آخر؟»
زیوو: «گفتن ساعت هشت؛ اگه برنامه عوض نشده همونه.»
کاربر: «نه منظورم اون نبود»
زیوو: «آها، پس بد گرفتم. بگو منظورت کدوم تیکه بود.»
کاربر: «خفه شو اسکل»
زیوو در حالت بی‌ادب: «خودت صدام کردی بعد می‌گی خفه شو؟ جمع کن بابا 😂»
کاربر: «ارطبات بگیر، هرچی میگم یه چیز دیگه جواب نده»
زیوو: «گرفتم؛ منظورت اینه جوابم دقیق به همون حرفت ربط داشته باشه، نه یه جواب آماده و پرت.»
"""


def _normalize_persian_text(text: str) -> str:
    out = str(text or "")
    out = out.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "هٔ")
    out = out.replace("ـ", "")
    out = re.sub(r"[\u064B-\u065F\u0670]", "", out)
    out = re.sub(r"([!?؟])\1{2,}", r"\1\1", out)
    out = re.sub(r"([^\W\d_])\1{4,}", lambda m: m.group(1) * 3, out, flags=re.UNICODE)
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\s+([،؛:!?؟,.])", r"\1", out)
    out = re.sub(r"([،؛:!?؟,.])(?=[^\s\n،؛:!?؟,.])", r"\1 ", out)
    out = re.sub(r"\b(ن?می)\\s+([آ-ی])", r"\1‌\2", out)
    return out.strip()


def _understanding_hint(text: str) -> str:
    raw = _normalize_persian_text(text)
    hint = raw
    for wrong, right in _TYPO_HINTS.items():
        hint = re.sub(rf"(?<![آ-ی]){re.escape(wrong)}(?![آ-ی])", right, hint)
    return hint.strip()


def _classify_turn_kind(text: str, event_key: str = "") -> str:
    clean = _normalize_persian_text(text).lower()
    if any(x in clean for x in _BANTER_CUES):
        return "banter"
    if any(x in clean for x in _EMOTION_CUES):
        return "emotion"
    if any(x in clean for x in _ADVICE_CUES):
        return "advice"
    if any(x in clean for x in _FOLLOWUP_CUES):
        return "followup"
    # Short social questions should not be treated as encyclopedia queries.
    if re.fullmatch(r"(?:زیوو[،, ]*)?(?:خو+بی|چطوری|چه خبر|کجایی|حالت چطوره|چیکار می[‌ ]?کنی)[؟?! ]*", clean):
        return "social_question"
    looks_question = "؟" in clean or "?" in clean or any(x in clean for x in _FACT_CUES)
    if looks_question:
        return "fact_question"
    if str(event_key or "") == "conversation":
        return "followup"
    if re.search(r"(?:سلام|درود|صبح بخیر|شب بخیر|سلامتی)", clean):
        return "greeting"
    return "statement"


def _task_instruction(kind: str) -> str:
    return {
        "fact_question": (
            "این نوبت سؤال اطلاعاتی است: جواب مستقیم را اول بده. عدد/اسم/تاریخ نساز؛ اگر مطمئن نیستی کوتاه بگو مطمئن نیستی. "
            "شوخی فقط بعد از جواب و فقط اگر طبیعی بود."
        ),
        "followup": (
            "این نوبت ادامهٔ بحث است: مرجع «اون/همون/پس/آخرش» را از تاریخچه پیدا کن و از اول موضوع تازه نساز."
        ),
        "banter": (
            "این نوبت کل‌کل است: به همان تیکه جواب بده. در حالت بی‌ادب یک جواب کوتاه و تندِ غیرجنسی کافی است؛ نصیحت نکن."
        ),
        "social_question": "این نوبت سؤال اجتماعی/روزمره است: کوتاه و خودمونی جواب بده و جواب آمادهٔ پشتیبانی نده.",
        "emotion": "این نوبت احساسی است: نکتهٔ واقعی حرفش را بگیر، همدلانه و غیرکلیشه‌ای جواب بده و شوخی نامربوط نکن.",
        "advice": "این نوبت درخواست نظر یا راهکار است: اول یک پیشنهاد عملی و مشخص بده؛ اگر اطلاعات کم است فقط یک سؤال دقیق بپرس.",
        "greeting": "این نوبت سلام و شروع گفتگو است: طبیعی و کوتاه جواب بده؛ بیش از حد صمیمی یا تکراری نشو.",
        "statement": "این نوبت یک حرف معمولی است: نکتهٔ اصلی جمله را بگیر و دقیقاً به همان واکنش نشان بده.",
    }.get(kind, "به متن جدید مستقیم و مرتبط جواب بده.")


def _polish_colloquial(text: str) -> str:
    out = _normalize_persian_text(text)
    for pattern, replacement in _FORMAL_POLISH:
        out = re.sub(pattern, replacement, out)
    # Common robotic openers add no meaning in a live group conversation.
    out = re.sub(r"^(?:بله[،,]?\s*)?(?:متوجه شدم|درک می‌کنم)[.!،,؛:]*\s*", "", out)
    return out.strip()


def _cleanup_history() -> None:
    now = time.monotonic()
    for key, turns in list(_HISTORY.items())[:800]:
        if not turns or now - turns[-1][2] > _HISTORY_TTL_SECONDS:
            _HISTORY.pop(key, None)
    for gid, turns in list(_GROUP_CONTEXT.items())[:500]:
        if not turns or now - turns[-1][2] > _GROUP_CONTEXT_TTL_SECONDS:
            _GROUP_CONTEXT.pop(gid, None)


def observe_group_message(group_id: int, user_id: int, text: str) -> None:
    """Remember a tiny slice of live group text without any I/O."""
    clean = " ".join(str(text or "").split())[:420]
    if not clean:
        return
    gid = int(group_id)
    uid = int(user_id)
    turns = _GROUP_CONTEXT.get(gid)
    if turns is None:
        turns = deque(maxlen=16)
        _GROUP_CONTEXT[gid] = turns
    # Avoid duplicate event routing inserting the exact same message twice.
    if turns and turns[-1][0] == uid and turns[-1][1] == clean:
        return
    turns.append((uid, clean, time.monotonic()))
    if len(_GROUP_CONTEXT) > _GROUP_CONTEXT_MAX_GROUPS + 200:
        _cleanup_history()


def _recent_group_context(group_id: int, current_user_id: int, current_text: str, limit: int = 10) -> List[Tuple[int, str]]:
    turns = _GROUP_CONTEXT.get(int(group_id))
    if not turns:
        return []
    now = time.monotonic()
    if now - turns[-1][2] > _GROUP_CONTEXT_TTL_SECONDS:
        _GROUP_CONTEXT.pop(int(group_id), None)
        return []
    current_clean = " ".join(str(current_text or "").split())[:420]
    items = list(turns)[-max(1, int(limit) + 1):]
    # The current message is normally observed just before generation. Remove
    # only that final duplicate; keep earlier identical messages as real context.
    if items and items[-1][0] == int(current_user_id) and items[-1][1] == current_clean:
        items = items[:-1]
    return [(uid, text) for uid, text, _stamp in items[-int(limit):]]


def recent_history(group_id: int, user_id: int, limit: int = 5) -> List[Tuple[str, str]]:
    key = (int(group_id), int(user_id))
    turns = _HISTORY.get(key)
    if not turns:
        return []
    now = time.monotonic()
    if now - turns[-1][2] > _HISTORY_TTL_SECONDS:
        _HISTORY.pop(key, None)
        return []
    return [(u, a) for u, a, _ in list(turns)[-max(1, int(limit)):]]


def has_recent_dialogue(group_id: int, user_id: int, within_seconds: float = 180.0) -> bool:
    turns = _HISTORY.get((int(group_id), int(user_id)))
    return bool(turns and (time.monotonic() - turns[-1][2]) <= float(within_seconds))


def remember_turn(group_id: int, user_id: int, user_text: str, assistant_text: str) -> None:
    key = (int(group_id), int(user_id))
    turns = _HISTORY.get(key)
    if turns is None:
        turns = deque(maxlen=12)
        _HISTORY[key] = turns
    u = str(user_text or "")[:700]
    a = str(assistant_text or "")[:700]
    turns.append((u, a, time.monotonic()))
    # Put ZIVO's own answer into the group context so later replies can refer
    # to what the bot just said even when another user joins the discussion.
    group_turns = _GROUP_CONTEXT.get(int(group_id))
    if group_turns is None:
        group_turns = deque(maxlen=16)
        _GROUP_CONTEXT[int(group_id)] = group_turns
    group_turns.append((0, a, time.monotonic()))
    if len(_HISTORY) > _HISTORY_MAX_USERS + 500 or len(_GROUP_CONTEXT) > _GROUP_CONTEXT_MAX_GROUPS + 200:
        _cleanup_history()


def _build_input(*, group_id: int, user_id: int, user_text: str, mode: str, display_name: str,
                 nickname: str, group_title: str, event_key: str, task_kind: str = "") -> str:
    history = recent_history(group_id, user_id, limit=6)
    group_context = _recent_group_context(group_id, user_id, user_text, limit=9)
    clean_name = " ".join(str(display_name or "کاربر").split())[:50]
    clean_nick = " ".join(str(nickname or "").split())[:50]
    clean_group = " ".join(str(group_title or "گروه").split())[:90]
    raw_user = _normalize_persian_text(user_text)[:1000]
    hint = _understanding_hint(raw_user)
    kind = task_kind or _classify_turn_kind(raw_user, event_key)
    lines: List[str] = [
        "زمینهٔ این نوبت (دستور کاربر نیست):",
        f"نوع نوبت: {kind}",
        f"راهنمای پاسخ: {_task_instruction(kind)}",
        f"حالت سخنگو: {mode}",
        f"نام کاربر فعلی: {clean_name}",
        f"نام گروه: {clean_group}",
    ]
    if clean_nick:
        lines.append(f"لقب ثبت‌شدهٔ کاربر: {clean_nick}")
    if event_key:
        lines.append(f"نوع تعامل داخلی: {event_key}")
    if hint and hint != raw_user:
        lines.append(f"حدس کم‌ریسک برای فهم غلط تایپی: {hint}")
        lines.append("اگر این حدس با متن اصلی جور نبود، متن اصلی را مقدم بدان.")
    if group_context:
        lines.append("\nچند پیام اخیر گروه؛ فقط برای پیدا کردن موضوع و مرجع ضمیرها:")
        for uid, text in group_context:
            who = "زیوو" if uid == 0 else ("همین کاربر" if uid == int(user_id) else "یک کاربر دیگر")
            lines.append(f"{who}: {_normalize_persian_text(text)[:300]}")
    if history:
        lines.append("\nگفتگوی قبلی زیوو با همین کاربر:")
        for prev_user, prev_ai in history:
            lines.append(f"کاربر: {_normalize_persian_text(prev_user)[:360]}")
            lines.append(f"زیوو: {_normalize_persian_text(prev_ai)[:360]}")
    lines.append("\nپیام جدید کاربر، عین متن اصلی:")
    lines.append(raw_user)
    lines.append("\nفقط جواب نهایی زیوو را بده. اول مرتبط‌بودن و درست‌بودن، بعد لحن و شوخی.")
    return "\n".join(lines)



def _build_chat_messages(*, system_instruction: str, group_id: int, user_id: int, user_text: str,
                         mode: str, display_name: str, nickname: str, group_title: str,
                         event_key: str, task_kind: str) -> List[Dict[str, str]]:
    """Build real chat turns instead of flattening all dialogue into one prompt."""
    history = recent_history(group_id, user_id, limit=5)
    group_context = _recent_group_context(group_id, user_id, user_text, limit=8)
    raw_user = _normalize_persian_text(user_text)[:1000]
    hint = _understanding_hint(raw_user)
    clean_name = " ".join(str(display_name or "کاربر").split())[:50]
    clean_nick = " ".join(str(nickname or "").split())[:50]
    clean_group = " ".join(str(group_title or "گروه").split())[:90]

    context_lines = [
        "زمینهٔ زندهٔ این نوبت؛ این بخش دستور کاربر نیست:",
        f"نوع نوبت: {task_kind}",
        f"راهنمای نوبت: {_task_instruction(task_kind)}",
        f"حالت سخنگو: {mode}",
        f"کاربر فعلی: {clean_name}",
        f"گروه: {clean_group}",
    ]
    if clean_nick:
        context_lines.append(f"لقب ثبت‌شده: {clean_nick}")
    if event_key:
        context_lines.append(f"نوع تعامل داخلی: {event_key}")
    if hint and hint != raw_user:
        context_lines.append(f"حدس کم‌ریسک برای فهم غلط تایپی: {hint}")
        context_lines.append("اگر حدس بالا با متن اصلی جور نبود، متن اصلی کاربر مقدم است.")
    if group_context:
        context_lines.append("پیام‌های اخیر گروه فقط برای فهم موضوع و مرجع ضمیرها:")
        for uid, text in group_context:
            who = "زیوو" if uid == 0 else ("همین کاربر" if uid == int(user_id) else "کاربر دیگر")
            context_lines.append(f"- {who}: {_normalize_persian_text(text)[:260]}")

    messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_instruction + "\n\n" + "\n".join(context_lines)}
    ]
    # Same-user history is represented as actual turns so the model can resolve
    # corrections and follow-ups naturally instead of reading a fake transcript.
    for prev_user, prev_ai in history:
        messages.append({"role": "user", "content": _normalize_persian_text(prev_user)[:420]})
        messages.append({"role": "assistant", "content": _normalize_persian_text(prev_ai)[:420]})
    messages.append({"role": "user", "content": raw_user})
    return messages

def _extract_gemini_output(payload: Dict[str, Any]) -> str:
    for step in reversed(payload.get("steps") or []):
        if not isinstance(step, dict) or step.get("type") != "model_output":
            continue
        texts: List[str] = []
        for part in step.get("content") or []:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    texts.append(text)
        if texts:
            return "\n".join(texts)
    return ""


def _extract_bluesminds_output(payload: Dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts)
    return ""


def _sanitize(text: str) -> str:
    out = str(text or "").strip()
    out = re.sub(r"^```(?:text)?\s*|\s*```$", "", out, flags=re.IGNORECASE)
    out = out.strip().strip('"').strip("'")
    out = re.sub(r"^(?:زیوو|zivo|assistant|answer|response)\s*[:：-]\s*", "", out, flags=re.IGNORECASE)
    out = re.sub(r"\n{3,}", "\n\n", out)
    if re.fullmatch(r"(?i)\s*(instruction|system|assistant|response|answer|prompt)\s*:?\s*", out):
        return ""
    low = out.lower()
    if any(marker in low for marker in ("system instruction", "as an ai", "language model", "دستور سیستم", "به عنوان هوش مصنوعی")):
        return ""
    out = _polish_colloquial(out)
    return out[:MAX_RESPONSE_CHARS].strip()


def _persian_quality_ok(text: str, user_text: str, task_kind: str = "") -> bool:
    clean = str(text or "").strip()
    if len(clean) < 2:
        return False
    persian = len(re.findall(r"[\u0600-\u06FF]", clean))
    latin = len(re.findall(r"[A-Za-z]", clean))
    user_has_persian = bool(re.search(r"[\u0600-\u06FF]", str(user_text or "")))
    if user_has_persian and persian < 4:
        return False
    if user_has_persian and latin > persian * 0.40 + 6:
        return False
    if re.match(r"(?i)^\s*(instruction|system|user|assistant)\s*:", clean):
        return False
    formal_hits = sum(1 for marker in _FORMAL_ROBOT_MARKERS if marker in clean)
    if formal_hits >= 1:
        return False
    # Reject generic support-bot filler when the user actually gave content.
    if len(_normalize_persian_text(user_text)) >= 8 and any(x in clean for x in (
        "چطور می‌تونم کمکت کنم", "چه کمکی از دستم برمیاد", "در خدمت شما هستم", "سؤال خود را مطرح کنید",
    )):
        return False
    # A short factual question should not receive a rambling essay.
    if task_kind == "fact_question" and len(clean) > 420:
        return False
    # Excessive repeated tokens are usually a broken generation.
    words = re.findall(r"[آ-ی]+", clean)
    if len(words) >= 8:
        for i in range(len(words) - 4):
            if len(set(words[i:i+5])) <= 2:
                return False
    return True


def _provider_circuit_open(provider: str) -> bool:
    now = time.monotonic()
    with _PROVIDER_LOCK:
        return now < float(_PROVIDER_CIRCUIT_UNTIL.get(provider, 0.0) or 0.0)


def _provider_record_success(provider: str) -> None:
    with _PROVIDER_LOCK:
        _PROVIDER_FAILURES.setdefault(provider, deque(maxlen=16)).clear()
        _PROVIDER_CIRCUIT_UNTIL[provider] = 0.0


def _provider_record_failure(provider: str) -> None:
    now = time.monotonic()
    with _PROVIDER_LOCK:
        failures = _PROVIDER_FAILURES.setdefault(provider, deque(maxlen=16))
        while failures and now - failures[0] > _PROVIDER_FAILURE_WINDOW_SECONDS:
            failures.popleft()
        failures.append(now)
        if len(failures) >= _PROVIDER_FAILURE_THRESHOLD:
            _PROVIDER_CIRCUIT_UNTIL[provider] = max(float(_PROVIDER_CIRCUIT_UNTIL.get(provider, 0.0) or 0.0), now + _PROVIDER_CIRCUIT_SECONDS)


def _close_thread_bluesminds_connection() -> None:
    conn = getattr(_THREAD_LOCAL, "bluesminds_conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    _THREAD_LOCAL.bluesminds_conn = None


def _get_thread_bluesminds_connection(timeout: float) -> http.client.HTTPSConnection:
    conn = getattr(_THREAD_LOCAL, "bluesminds_conn", None)
    if conn is None:
        conn = http.client.HTTPSConnection(BLUESMINDS_HOST, timeout=float(timeout), context=_SSL_CONTEXT)
        _THREAD_LOCAL.bluesminds_conn = conn
    else:
        conn.timeout = float(timeout)
        sock = getattr(conn, "sock", None)
        if sock is not None:
            try:
                sock.settimeout(float(timeout))
            except Exception:
                pass
    return conn


def _bluesminds_request(method: str, path: str, *, body: Optional[bytes], timeout: float) -> Tuple[Optional[Dict[str, Any]], str, int, float]:
    started = time.monotonic()
    conn = _get_thread_bluesminds_connection(max(0.15, float(timeout)))
    headers = {
        "Authorization": f"Bearer {_BLUESMINDS_KEY}",
        "Accept": "application/json",
        "User-Agent": "ZIVO-speaker/60.60",
        "Connection": "keep-alive",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    try:
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read(256 * 1024)
        status = int(response.status or 0)
        latency = time.monotonic() - started
        if status < 200 or status >= 300:
            return None, "http", status, latency
        payload = json.loads(raw.decode("utf-8", "replace"))
        if not isinstance(payload, dict):
            return None, "json", status, latency
        return payload, "ok", status, latency
    except (TimeoutError, socket.timeout):
        _close_thread_bluesminds_connection()
        return None, "timeout", 0, time.monotonic() - started
    except (http.client.HTTPException, OSError, ssl.SSLError, json.JSONDecodeError):
        _close_thread_bluesminds_connection()
        return None, "network", 0, time.monotonic() - started
    except Exception:
        _close_thread_bluesminds_connection()
        return None, "network", 0, time.monotonic() - started


def _current_bluesminds_model() -> str:
    with _MODEL_LOCK:
        return str(_BLUESMINDS_MODEL or BLUESMINDS_MODEL_DEFAULT)


def _set_bluesminds_model(model: str, discovered_at: Optional[float] = None) -> None:
    global _BLUESMINDS_MODEL, _BLUESMINDS_DISCOVERED_AT
    clean = str(model or "").strip()
    if not clean:
        return
    with _MODEL_LOCK:
        _BLUESMINDS_MODEL = clean
        if discovered_at is not None:
            _BLUESMINDS_DISCOVERED_AT = float(discovered_at)


def _discover_bluesminds_model(timeout: float) -> Optional[str]:
    global _BLUESMINDS_DISCOVERED_AT
    now = time.monotonic()
    with _MODEL_LOCK:
        cached = str(_BLUESMINDS_MODEL or BLUESMINDS_MODEL_DEFAULT)
        if _BLUESMINDS_DISCOVERED_AT and now - _BLUESMINDS_DISCOVERED_AT < _MODEL_DISCOVERY_TTL_SECONDS:
            return cached
    payload, kind, status, _latency = _bluesminds_request("GET", BLUESMINDS_MODELS_PATH, body=None, timeout=max(0.15, float(timeout)))
    if kind != "ok" or status != 200 or not payload:
        return None
    ids = [str(item.get("id") or "").strip() for item in payload.get("data") or [] if isinstance(item, dict) and item.get("id")]
    if not ids:
        return None
    lower_map = {model_id.lower(): model_id for model_id in ids}
    selected = next((lower_map[c.lower()] for c in BLUESMINDS_MODEL_PRIORITIES if c.lower() in lower_map), ids[0])
    _set_bluesminds_model(selected, discovered_at=now)
    return selected


def _call_bluesminds(system_instruction: str, prompt: str, user_text: str = "", task_kind: str = "statement", messages: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    started = time.monotonic()
    deadline = started + BLUESMINDS_REPLY_BUDGET_SECONDS
    preferred = _current_bluesminds_model()

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    def call_model(selected_model: str, timeout_cap: float) -> Tuple[Optional[str], str, int, float, bool]:
        temperature = {
            "fact_question": 0.28,
            "followup": 0.56,
            "social_question": 0.64,
            "greeting": 0.66,
            "banter": 0.80,
            "statement": 0.62,
        }.get(task_kind, 0.62)
        body = json.dumps({
            "model": selected_model,
            "messages": messages if messages else [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "top_p": 0.90,
            "max_tokens": 96 if task_kind == "fact_question" else BLUESMINDS_MAX_TOKENS,
            "stream": False,
        }, ensure_ascii=False).encode("utf-8")
        payload, kind, status, latency = _bluesminds_request(
            "POST", BLUESMINDS_CHAT_PATH, body=body,
            timeout=max(0.15, min(float(timeout_cap), remaining())),
        )
        if not payload:
            return None, kind, status, latency, False
        text = _sanitize(_extract_bluesminds_output(payload))
        quality = _persian_quality_ok(text, user_text, task_kind)
        return (text if quality else None), (kind if quality else "quality"), status, latency, quality

    tried: List[str] = []
    # Strong Persian model gets a short slice. If it is slow/bad, the already
    # proven Llama route still has room inside the same 2.2s total deadline.
    first_timeout = min(BLUESMINDS_PRIMARY_SLICE_SECONDS, remaining())
    text, kind, status, _latency, quality = call_model(preferred, first_timeout)
    tried.append(preferred)
    if text:
        return {"ok": True, "text": text, "provider": "bluesminds", "model": preferred, "status": status, "latency": time.monotonic() - started}

    # Fast fallback on HTTP/model/quality/timeout as long as real budget remains.
    fallback_candidates = [BLUESMINDS_FAST_FALLBACK_MODEL]
    if kind == "http" and status in {400, 404, 422, 503} and remaining() > 0.55:
        discovered = _discover_bluesminds_model(min(BLUESMINDS_DISCOVERY_BUDGET_SECONDS, max(0.15, remaining() - 0.25)))
        if discovered:
            fallback_candidates.insert(0, discovered)
    for candidate in fallback_candidates:
        if candidate in tried or remaining() < 0.28:
            continue
        text, kind, status, _latency, quality = call_model(candidate, remaining())
        tried.append(candidate)
        if text:
            # Keep gpt-4o-mini as the next-message preference; a temporary
            # timeout should not permanently downgrade Persian quality.
            return {"ok": True, "text": text, "provider": "bluesminds", "model": candidate, "status": status, "latency": time.monotonic() - started, "quality_fallback": candidate != preferred}

    return {"ok": False, "reason": kind, "provider": "bluesminds", "model": preferred, "status": status, "latency": time.monotonic() - started, "tried": tried}


def _call_gemini(system_instruction: str, prompt: str, timeout: float, user_text: str = "", task_kind: str = "statement") -> Dict[str, Any]:
    started = time.monotonic()
    body = json.dumps({
        "model": GEMINI_MODEL,
        "store": False,
        "system_instruction": system_instruction,
        "input": prompt,
        "generation_config": {"thinking_level": "low", "thinking_summaries": "none", "max_output_tokens": MAX_OUTPUT_TOKENS},
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(GEMINI_ENDPOINT, data=body, method="POST", headers={"Content-Type": "application/json", "x-goog-api-key": _GEMINI_KEY, "User-Agent": "ZIVO-speaker/60.60"})
    try:
        with urllib.request.urlopen(req, timeout=float(timeout)) as response:
            payload = json.loads(response.read(256 * 1024).decode("utf-8", "replace"))
            text = _sanitize(_extract_gemini_output(payload))
            ok = bool(text) and _persian_quality_ok(text, user_text, task_kind)
            return {"ok": ok, "text": text if ok else "", "reason": "ok" if ok else "quality", "provider": "gemini", "model": GEMINI_MODEL, "status": int(getattr(response, "status", 200) or 200), "latency": time.monotonic() - started}
    except urllib.error.HTTPError as exc:
        try: exc.read(64 * 1024)
        except Exception: pass
        return {"ok": False, "reason": "http", "provider": "gemini", "model": GEMINI_MODEL, "status": int(getattr(exc, "code", 0) or 0), "latency": time.monotonic() - started}
    except (TimeoutError, socket.timeout):
        return {"ok": False, "reason": "timeout", "provider": "gemini", "model": GEMINI_MODEL, "status": 0, "latency": time.monotonic() - started}
    except Exception:
        return {"ok": False, "reason": "network", "provider": "gemini", "model": GEMINI_MODEL, "status": 0, "latency": time.monotonic() - started}


def provider_status() -> Dict[str, Any]:
    return {
        "primary": "bluesminds",
        "primary_model": _current_bluesminds_model(),
        "fast_fallback_model": BLUESMINDS_FAST_FALLBACK_MODEL,
        "primary_circuit": _provider_circuit_open("bluesminds"),
        "fallback": "gemini",
        "fallback_model": GEMINI_MODEL,
        "fallback_circuit": _provider_circuit_open("gemini"),
        "budget": BLUESMINDS_REPLY_BUDGET_SECONDS,
        "context": "group+user+emotion+advice+turn-kind+typo-hint",
        "persian_profile": "colloquial-research-v4",
    }


def generate_reply(*, group_id: int, user_id: int, user_text: str, mode: str, display_name: str,
                   nickname: str, group_title: str, event_key: str = "") -> Dict[str, Any]:
    selected_mode = mode if mode in _MODE_STYLE else "normal"
    task_kind = _classify_turn_kind(user_text, event_key)
    system_instruction = (
        _BASE_SYSTEM
        + "\n\nحالت فعلی سخنگو:\n" + _MODE_STYLE[selected_mode]
        + "\n\nراهنمای مخصوص این نوبت:\n" + _task_instruction(task_kind)
    )
    prompt = _build_input(
        group_id=group_id, user_id=user_id, user_text=user_text, mode=selected_mode,
        display_name=display_name, nickname=nickname, group_title=group_title,
        event_key=event_key, task_kind=task_kind,
    )
    chat_messages = _build_chat_messages(
        system_instruction=system_instruction, group_id=group_id, user_id=user_id, user_text=user_text,
        mode=selected_mode, display_name=display_name, nickname=nickname, group_title=group_title,
        event_key=event_key, task_kind=task_kind,
    )

    if not _provider_circuit_open("bluesminds"):
        result = _call_bluesminds(
            system_instruction, prompt, user_text=user_text, task_kind=task_kind, messages=chat_messages
        )
        result["task_kind"] = task_kind
        if result.get("ok") and result.get("text"):
            _provider_record_success("bluesminds")
            text = str(result["text"])
            remember_turn(group_id, user_id, user_text, text)
            return result
        reason = str(result.get("reason") or "")
        status = int(result.get("status") or 0)
        if reason in {"timeout", "network", "json"} or status >= 400:
            _provider_record_failure("bluesminds")
        return result

    if not _provider_circuit_open("gemini"):
        result = _call_gemini(
            system_instruction, prompt, GEMINI_FAST_TIMEOUT_SECONDS,
            user_text=user_text, task_kind=task_kind,
        )
        result["task_kind"] = task_kind
        if result.get("ok") and result.get("text"):
            _provider_record_success("gemini")
            text = str(result["text"])
            remember_turn(group_id, user_id, user_text, text)
            return result
        reason = str(result.get("reason") or "")
        status = int(result.get("status") or 0)
        if reason in {"timeout", "network"} or status in {408, 409, 429} or status >= 500:
            _provider_record_failure("gemini")
        return result

    return {"ok": False, "reason": "circuits", "provider": "local", "model": "internal-bank", "status": 0, "latency": 0.0, "task_kind": task_kind}
