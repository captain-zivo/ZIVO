#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import random
import re
from typing import Dict, List, Optional

SPEAKER_MODES = {"normal", "chatty", "rude"}
SPEAKER_MODE_LABELS = {
    "normal": "معمولی",
    "chatty": "پرحرف",
    "rude": "بی ادب/شوخ",
}
SPEAKER_MODE_ALIASES = {
    "معمولی": "normal",
    "عادی": "normal",
    "نرمال": "normal",
    "پرحرف": "chatty",
    "پر حرف": "chatty",
    "بی ادب": "rude",
    "بی‌ادب": "rude",
    "شیطون": "rude",
    "شیطان": "rude",
    "شوخ": "rude",
}
SPEAKER_EVENT_LABELS = {
    "call": "صدا زدن ربات",
    "hello": "سلام",
    "how": "احوال پرسی",
    "thanks": "تشکر",
    "bye": "خداحافظی",
    "friendly": "صمیمی",
    "laugh": "خنده",
    "sad": "ناراحتی",
    "bored": "بی‌حوصلگی",
    "love": "محبت",
    "join": "عضو جدید",
}
SPEAKER_EVENT_ALIASES = {
    "صدا": "call",
    "صدا زدن": "call",
    "صدا زدن ربات": "call",
    "اسم ربات": "call",
    "سلام": "hello",
    "احوال": "how",
    "احوال پرسی": "how",
    "خوبی": "how",
    "تشکر": "thanks",
    "مرسی": "thanks",
    "خداحافظ": "bye",
    "خداحافظی": "bye",
    "بای": "bye",
    "صمیمی": "friendly",
    "رفیق": "friendly",
    "خنده": "laugh",
    "ناراحت": "sad",
    "ناراحتی": "sad",
    "بی حوصله": "bored",
    "بی‌حوصله": "bored",
    "حوصله": "bored",
    "محبت": "love",
    "دوست داشتن": "love",
    "عضو جدید": "join",
    "ورود": "join",
    "ورود عضو": "join",
}

_LAST_RESPONSE: Dict[tuple, str] = {}

DEFAULT_RESPONSES: Dict[str, Dict[str, List[str]]] = {
    "normal": {
        "call": [
            "جانم {name}؟ 👀",
            "{name} جان، بگو 😊",
            "بله {name}؟ زیوو اینجاست ⚡",
            "جان دلم {name}، چی شده؟ 😄",
        ],
        "hello": [
            "سلام {name} جان 👋 خوش اومدی.",
            "سلام {name} 😄 چه خبر؟",
            "درود {name} جان 🌱",
        ],
        "how": [
            "خوبم {name} جان 😄 تو چطوری؟",
            "روبه راهم {name}، تو چه خبر؟ 👀",
            "تا وقتی گروه آرومه منم خوبم 😂 تو خوبی {name}؟",
        ],
        "thanks": [
            "قربانت {name} 🤍",
            "خواهش می کنم {name} جان 🌹",
            "کاری نکردم {name} 😄",
        ],
        "bye": [
            "فعلا {name} جان 👋 مراقب خودت باش.",
            "به سلامت {name} 🤍",
            "بای بای {name} 😄",
        ],
        "friendly": [
            "عشقی {name} 😂🤍",
            "قربون مرامت {name} 😄",
            "رفیق خودمی {name} 🤝",
        ],
        "laugh": [
            "😂 خوبه حداقل خنده‌ات گرفت {name}!",
            "خندیدی منم مأموریتم انجام شد 😄",
            "این خنده رو نگه دار؛ به گروه میاد {name} 😂",
        ],
        "sad": [
            "اوه {name}... اگه دوست داری بگو چی شده؛ گوش می‌دم 🤍",
            "متأسفم حالت خوب نیست {name}. یکم نفس بکش، بعد آروم بگو چی اذیتت کرده.",
            "کنارتیم {name} 🤍 لازم نیست همین الان همه‌چیز رو تنهایی جمع کنی.",
        ],
        "bored": [
            "حوصله‌ات سر رفته؟ بنویس «سرگرمی» تا یه چیزی برات رو کنم 😄",
            "بیا یه دوز راه بنداز: «بازی دوز»؛ شاید گروه جون گرفت 🎮",
            "یه «چالش» یا «معما» بزن {name}، بی‌حوصلگی رو بندازیم بیرون.",
        ],
        "love": [
            "منم هواتو دارم {name} 🤍",
            "قربون محبتت {name}؛ چسبید به قلب دیجیتالی زیوو 😄",
            "این همه محبت رو کجا بذارم آخه؟ 😂🤍",
        ],
        "join": [
            "خوش اومدی {name} 👋 امیدوارم اینجا بهت خوش بگذره.",
            "{name} جان خوش اومدی به جمعمون 🌟",
            "به به، {name} هم رسید 😄 خوش اومدی.",
        ],
    },
    "chatty": {
        "call": [
            "جانم {name}؟ 👀 من کامل حواسم بهته؛ بگو ببینم این دفعه چه کاری با زیوو داری 😄",
            "{name} جان صدام کردی؟ من اینجام ⚡ بگو چه خبر شده تا با هم جمعش کنیم.",
            "بله قربان {name} 😂 زیوو حاضر و آماده است، فقط دستور بده ببینم چی می خوای.",
            "جانم {name}، شنیدم اسممو گفتی 😄 بگو؛ من که از حرف زدن خسته نمی شم.",
        ],
        "hello": [
            "سلاممم {name} 👋😄 چه عجب! بیا بگو امروز چه خبر بوده، گروه بدون خبر تازه مزه نمی ده.",
            "سلام {name} جان 🌟 حالت چطوره؟ امیدوارم امروز کمتر از دیروز دردسر درست کرده باشی 😂",
            "درود به {name} 😄 من که اینجام؛ تو بگو روزت چطور گذشته؟",
        ],
        "how": [
            "من خوبم {name} جان 😄 سرم شلوغه ولی انرژی دارم؛ تو بگو اوضاع دلت چطوره؟",
            "خوبم رفیق 😂 هنوز سرور منفجر نشده پس یعنی همه چی عالیه. تو خوبی {name}؟",
            "روبه راهم {name}؛ یه چشمم به گروه، یه چشمم به شماهاست 👀 تو چه خبر؟",
        ],
        "thanks": [
            "قربونت {name} 🤍 همین که کار راه افتاد من راضیم؛ حالا برو کیفشو ببر 😄",
            "خواهش می کنم {name} جان 🌹 من برای همین اینجام، فقط زیادی لوسم نکن 😂",
            "مرسی که مرسی گفتی {name} 😂 خیلی ها کارشون که راه می افته غیبشون می زنه.",
        ],
        "bye": [
            "فعلا {name} جان 👋 برو به کارت برس ولی زیاد غیبت نزنه، دوباره بیا یه سری به زیوو بزن 😄",
            "به سلامت {name} 🤍 راه باز، اینترنت پرسرعت، اعصاب آروم 😂",
            "بای بای {name} 👋 من همینجا کشیک می دم تا برگردی.",
        ],
        "friendly": [
            "قربون مرامت {name} 😂🤍 با این مدل حرف زدنت آدم دلش می خواد بیشتر جواب بده.",
            "عشقی {name} 😄 تو خوب حرف بزن، زیوو هم هواتو داره.",
            "رفیق خودمی {name} 🤝 از اون آدمایی شدی که زیوو باهاش راحت حرف می زنه 😂",
        ],
        "laugh": [
            "😂 بالاخره تونستم بخندونمت {name}! حالا همین انرژی رو نگه دار که گروه زیادی جدی نشه.",
            "خنده‌ات ثبت شد {name}؛ یک امتیاز برای زیوو و صفر برای اخم امروز 😄",
            "ایول 😂 وقتی تو می‌خندی انگار نصف گروه هم خودکار حالش بهتر می‌شه.",
        ],
        "sad": [
            "{name} جان، ناراحتیت رو سبک نشمار. اگه گفتنش حالت رو بهتر می‌کنه، من بی‌قضاوت گوش می‌دم 🤍",
            "می‌فهمم الان شاید جملهٔ قشنگ کمکی نکنه؛ فقط بدون لازم نیست تنهایی ازش رد بشی {name}.",
            "آروم باش {name}؛ اول یک نفس عمیق، بعد فقط همون تیکه‌ای رو بگو که بیشتر اذیتت می‌کنه.",
        ],
        "bored": [
            "خب {name}، عملیات نجات از بی‌حوصلگی شروع شد 😄 «بازی دوز»، «معما» یا «چالش»؛ یکی رو انتخاب کن.",
            "حوصله‌ات سر رفته و زیوو هم دقیقاً برای همین لحظه‌هاست 😂 بنویس «سرگرمی» تا شانسی انتخاب کنم.",
            "یه پیشنهاد: «شیپ» رو بزن ببینیم الگوریتم امروز کیا رو کنار هم می‌ذاره 😂💞",
        ],
        "love": [
            "منم دوستت دارم {name} 🤍 البته از نوع رباتیِ وفادار که هم جواب می‌ده هم گروه رو جمع می‌کنه 😄",
            "قربون دل مهربونت {name}؛ این پیام رفت توی پوشهٔ چیزای قشنگ امروز 🤍",
            "این‌جوری حرف بزنی زیوو لوس می‌شه‌ها 😂🤍 ولی آره، منم هواتو دارم.",
        ],
        "join": [
            "به به {name} هم به جمع اضافه شد 👋😄 خوش اومدی! یه دور گروه رو نگاه کن، بعدش خودت می فهمی اینجا چه خبره 😂",
            "{name} جان خوش اومدی 🌟 جا برات باز کردیم؛ امیدوارم هم خوش بگذره هم زود با بچه ها جور بشی.",
            "یه تازه وارد داریم 😄 {name} خوش اومدی! نترس، زیوو بیشتر پارس می کنه تا گاز بگیره 😂",
        ],
    },
    "rude": {
        "call": [
            "جانم {name}، باز چه گندی زدی که منو صدا کردی؟ 😂",
            "چی می خوای {name}؟ دو دقیقه منو ول کنی می میری؟ 😂",
            "ها {name}؟ بگو، قبل از اینکه پشیمون شم جواب بدم 😏",
            "جانم مغز فندقی 😂 بگو ببینم این دفعه چه شاهکاری کردی {name}.",
            "{name} باز شروع کردی؟ 😂 بگو دیگه، اعصابمو خورد نکن.",
        ],
        "hello": [
            "سلام {name} 😂 بالاخره پیدات شد، فکر کردم اینترنتت از دستت فرار کرده.",
            "به به {name}، باز این کله خراب پیداش شد 😂 سلام دیوونه.",
            "سلام اسکل دوست داشتنی 😂 چه خبر {name}؟",
            "سلام {name}، امروز اومدی آدم باشی یا باز می خوای گروه رو به فنا بدی؟ 😂",
        ],
        "how": [
            "خوبم {name}، تا وقتی شماها کمتر مزخرف بگید عالی هم می شم 😂 تو چطوری؟",
            "من خوبم کله خر 😂 نگران من نباش {name}، خودتو جمع کن.",
            "خوبم {name}، هنوز از دست شما خل و چل ها سکته نکردم 😂",
            "چه مرگمه مگه؟ 😂 خوبم {name}، تو زنده ای هنوز؟",
        ],
        "thanks": [
            "گوه نخور {name} 😂 کاری نکردم، برو حالشو ببر.",
            "مرسی به چشمت {name} 😂 دفعه بعد کمتر دردسر بساز.",
            "خواهش می کنم اسکل 😂 فقط نگو زیوو بی معرفته {name}.",
            "قربونت کله خراب 😂 حالا دیگه لوس نشو {name}.",
        ],
        "bye": [
            "برو به سلامت {name} 😂 فقط درو پشت سرت نبند، باز برمی گردی.",
            "فعلا کله خراب 👋😂 {name} زیاد گم و گور نشی.",
            "خدافظ {name}، برو یکم به مغزت استراحت بده 😂",
            "بای {name} 😂 برو قبل از اینکه دوباره یه خرابکاری کنی.",
        ],
        "friendly": [
            "عشقی دیوونه 😂🤍 {name} با تو می شه کل کل کرد.",
            "قربونت اسکل دوست داشتنی 😂 {name} تو خودی شدی دیگه.",
            "خفه شو بابا، خودت عشقی 😂🤍 {name}",
            "گوه نخور که خجالتم می دی 😂 {name} خودت رفیق مایی.",
            "کله خراب 😂 زیادی باحالی {name}، ادامه بده.",
        ],
        "laugh": [
            "بخند کله‌خراب 😂 حداقل یه کار مفید امروز کردی {name}.",
            "دیدی بالاخره خندیدی؟ الکی قیافه نگیر {name} 😂",
            "خنده‌ات گرفت؟ پس زیاد هم یخچال نبودی 😂",
        ],
        "sad": [
            "کل‌کل سر جاش، ولی ناراحتی شوخی نیست {name}. بگو چی شده؛ مسخره‌بازی درنمیارم 🤍",
            "اوه... این یکی رو جدی می‌گیرم {name}. حرف بزن، شاید یکم سبک‌تر شی.",
            "جمعش نکن توی خودت کله‌خراب؛ اگه خواستی همون چیزی که اذیتت کرده رو بگو.",
        ],
        "bored": [
            "حوصله‌ات سر رفته چون خودت هیچ کاری نمی‌کنی 😂 بزن «بازی دوز» جمع رو راه بنداز.",
            "بزن «سرگرمی» دیگه، منتظری خود حوصله بیاد در بزنه؟ 😂",
            "«شیپ» رو بزن یکم گروه به هم بریزه، حوصله‌اتم سر نره 😂💞",
        ],
        "love": [
            "گوه نخور که خجالتم می‌دی 😂🤍 منم هواتو دارم {name}.",
            "خودت دوست‌داشتنی‌ای کله‌خراب 😂🤍",
            "باشه بابا، منم دوستت دارم؛ حالا لوس نشو 😂",
        ],
        "join": [
            "به به {name} هم اومد 😂 فقط تو کم بودی، خوش اومدی کله خراب.",
            "{name} رسید 😂 بچه ها جمع کنید خودتونو، یه دردسر جدید اضافه شد. خوش اومدی.",
            "خوش اومدی {name} 😂 قانون اول: اسکل بازی آزاده، ولی زیوو ازت اسکل تره.",
            "اوووه {name} هم پیداش شد 😂 خوش اومدی دیوونه، بیا ببینیم چه گندی می زنی.",
        ],
    },
}


def normalize_speaker_text(text: str) -> str:
    value = (text or "").strip().replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")
    value = re.sub(r"[؟?!！،,؛;:.…]+", " ", value)
    return " ".join(value.lower().split())


def mode_from_label(value: str) -> Optional[str]:
    normalized = normalize_speaker_text(value)
    return SPEAKER_MODE_ALIASES.get(normalized)


def event_from_label(value: str) -> Optional[str]:
    normalized = normalize_speaker_text(value)
    return SPEAKER_EVENT_ALIASES.get(normalized)


def parse_speaker_command(text: str) -> Optional[Dict[str, str]]:
    raw = (text or "").strip().replace("\u200c", " ")
    norm = " ".join(raw.split())
    low = normalize_speaker_text(norm)

    if low in {"سخنگو", "وضعیت سخنگو", "سخنگو وضعیت"}:
        return {"action": "status"}
    if low in {"سخنگو هوشمند", "وضعیت سخنگو هوشمند", "سخنگو هوشمند وضعیت"}:
        return {"action": "ai_status"}
    if low in {"سخنگو هوشمند روشن", "هوش سخنگو روشن", "سخنگو ai روشن"}:
        return {"action": "ai_enabled", "value": "1"}
    if low in {"سخنگو هوشمند خاموش", "هوش سخنگو خاموش", "سخنگو ai خاموش"}:
        return {"action": "ai_enabled", "value": "0"}
    if low in {"سخنگو روشن", "فعال سخنگو", "سخنگو فعال", "سخنگو فعال کن", "فعال کردن سخنگو"}:
        return {"action": "enabled", "value": "1"}
    if low in {"سخنگو خاموش", "غیرفعال سخنگو", "غیر فعال سخنگو", "سخنگو غیرفعال", "سخنگو غیر فعال", "سخنگو خاموش کن"}:
        return {"action": "enabled", "value": "0"}
    if low in {"لیست سخنگو", "لیست پاسخ سخنگو", "لیست پاسخ های سخنگو", "لیست پاسخهای سخنگو"}:
        return {"action": "list"}

    if low.startswith("سخنگو "):
        mode = mode_from_label(low[len("سخنگو "):])
        if mode:
            return {"action": "mode", "mode": mode}

    for prefix, action in (
        ("افزودن سخنگو ", "upsert_trigger"),
        ("اضافه سخنگو ", "upsert_trigger"),
        ("تغییر سخنگو ", "upsert_trigger"),
        ("ویرایش سخنگو ", "upsert_trigger"),
    ):
        if low.startswith(prefix):
            body = norm[len(prefix):].strip()
            if "|" not in body:
                return {"action": "invalid_trigger"}
            trigger, response = (part.strip() for part in body.split("|", 1))
            if not trigger or not response:
                return {"action": "invalid_trigger"}
            return {"action": action, "trigger": trigger, "response": response}

    if low.startswith("حذف سخنگو "):
        trigger = norm[len("حذف سخنگو "):].strip()
        if trigger:
            return {"action": "delete_trigger", "trigger": trigger}

    default_prefixes = (
        "تنظیم پیش فرض سخنگو ",
        "تنظیم پیشفرض سخنگو ",
        "تغییر پیش فرض سخنگو ",
        "تغییر پیشفرض سخنگو ",
    )
    for prefix in default_prefixes:
        if low.startswith(prefix):
            body = norm[len(prefix):].strip()
            if "|" not in body:
                return {"action": "invalid_default"}
            left, response = (part.strip() for part in body.split("|", 1))
            if not left or not response:
                return {"action": "invalid_default"}
            left_norm = normalize_speaker_text(left)
            mode = None
            event_text = left_norm
            for alias, mode_key in sorted(SPEAKER_MODE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
                if left_norm == alias:
                    event_text = ""
                    mode = mode_key
                    break
                if left_norm.startswith(alias + " "):
                    mode = mode_key
                    event_text = left_norm[len(alias):].strip()
                    break
            event = event_from_label(event_text)
            if not event:
                return {"action": "invalid_default"}
            return {"action": "set_default", "mode": mode or "", "event": event, "response": response}

    reset_prefixes = ("ریست پیش فرض سخنگو ", "ریست پیشفرض سخنگو ")
    for prefix in reset_prefixes:
        if low.startswith(prefix):
            body = low[len(prefix):].strip()
            if body in {"همه", "کامل"}:
                return {"action": "reset_defaults", "event": "*", "mode": ""}
            mode = None
            event_text = body
            for alias, mode_key in sorted(SPEAKER_MODE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
                if body.startswith(alias + " "):
                    mode = mode_key
                    event_text = body[len(alias):].strip()
                    break
            event = event_from_label(event_text)
            if event:
                return {"action": "reset_defaults", "event": event, "mode": mode or ""}
            return {"action": "invalid_default"}

    return None


def classify_speaker_event(text: str, *, bot_called: bool = False) -> Optional[str]:
    norm = normalize_speaker_text(text)
    if not norm:
        return None
    if bot_called:
        return "call"
    if norm in {"سلام", "سلاممم", "سلامم", "درود", "های", "hello", "hi", "صبح بخیر", "شب بخیر"}:
        return "hello"
    if norm in {"خوبی", "چطوری", "چه خبر", "حالت چطوره", "اوضاع", "روبه راهی", "خوبی زیوو", "زیوو خوبی"}:
        return "how"
    if norm in {"مرسی", "ممنون", "دمت گرم", "تشکر", "سپاس", "مرسی زیوو", "دمت گرم زیوو"}:
        return "thanks"
    if norm in {"خدافظ", "خداحافظ", "فعلا", "بای", "شب خوش", "تا بعد", "خدافظ زیوو"}:
        return "bye"
    if any(phrase in norm for phrase in ("حوصلم سر رفته", "حوصله ام سر رفته", "حوصله ندارم", "بی حوصلم", "بی حوصله ام")):
        return "bored"
    if any(phrase in norm for phrase in ("ناراحتم", "حالم بده", "دلم گرفته", "گریه کردم", "خیلی غمگینم", "دپم")):
        return "sad"
    if any(phrase in norm for phrase in ("دوستت دارم", "عاشقتم زیوو", "زیوو عاشقتم", "قلبمی")):
        return "love"
    if re.search(r"(?:خخخ+|ههه+|😂|🤣|خندیدم|ترکیدم)", str(text or ""), flags=re.I):
        return "laugh"
    friendly_words = ("عشقی", "قربونت", "فدات", "داداش", "رفیق", "دوست دارم", "باحالی", "دمت گرم", "جونمی")
    if any(word in norm for word in friendly_words):
        return "friendly"
    return None


def trigger_matches(trigger: str, text: str) -> bool:
    trig = normalize_speaker_text(trigger)
    norm = normalize_speaker_text(text)
    if not trig or not norm:
        return False
    if trig == norm:
        return True
    trig_tokens = trig.split()
    text_tokens = norm.split()
    if len(trig_tokens) == 1:
        return trig in text_tokens
    width = len(trig_tokens)
    return any(text_tokens[i:i + width] == trig_tokens for i in range(0, max(0, len(text_tokens) - width + 1)))


def render_speaker_response(template: str, *, name: str, group: str) -> str:
    safe_name = " ".join((name or "رفیق").split())[:40] or "رفیق"
    safe_group = " ".join((group or "گروه").split())[:80] or "گروه"
    result = str(template or "").replace("{name}", safe_name).replace("{group}", safe_group)
    return result[:1200].strip()


def choose_default_response(mode: str, event: str, override: str = "") -> str:
    if override:
        return override
    selected_mode = mode if mode in SPEAKER_MODES else "normal"
    bank = DEFAULT_RESPONSES.get(selected_mode, DEFAULT_RESPONSES["normal"])
    responses = bank.get(event) or DEFAULT_RESPONSES["normal"].get(event) or []
    if not responses:
        return ""
    key = (selected_mode, str(event))
    previous = _LAST_RESPONSE.get(key, "")
    choices = [item for item in responses if item != previous] or list(responses)
    selected = random.choice(choices)
    _LAST_RESPONSE[key] = selected
    return selected
