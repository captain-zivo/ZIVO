#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ZIVO Official Bot v17 for Soroush Plus official Bot Platform.

Runtime architecture:
- Official Bot API: getMe / getUpdates / sendMessage / answerCallbackQuery
- Account control: direct local Unix-domain socket IPC
- Join/control execute inside the selected main/acc2/acc3 process
- No filesystem SQLite bridge is opened by the official bot at runtime
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import signal
import sqlite3
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, Iterator, Optional, Tuple, List
from zoneinfo import ZoneInfo

import requests

from zivo_entertainment import ENTERTAINMENT_COMMANDS, entertainment_response
import zivo_market_tools as market_tools
import zivo_social_games as social_games
from zivo_ipc import DEFAULT_ACCOUNTS as IPC_ACCOUNT_KEYS, request as ipc_request, socket_path as ipc_socket_path

APP_NAME = "ZIVO Official"
VERSION = "zivo-official17"

# User explicitly requested an embedded token for this build.
BOT_TOKEN = "69669557:_Traf8PaLT5rQmxiIKrhQHV7GoXklGjGwsA"

BASE_DIR = Path("/opt/ZIVO_OFFICIAL_BOT17")
LOG_PATH = BASE_DIR / "zivo_official17.log"

PRIVATE_INVITE_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:web\.)?splus\.ir/joingroup/([^/?#\s<>]+)(?:[/?#].*)?$", re.I)
PUBLIC_GROUP_RE = re.compile(r"^(?:https?://)?(?:www\.)?(?:web\.)?splus\.ir/([A-Za-z0-9_]{3,64})(?:[/?#].*)?$", re.I)

API_ROOT = "https://api.splus.ir"
API_BASE = f"{API_ROOT}/bot{BOT_TOKEN}"
GET_ME_URL = f"{API_BASE}/getMe"
GET_UPDATES_URL = f"{API_BASE}/getUpdates"
SEND_MESSAGE_URL = f"{API_BASE}/sendMessage"
ANSWER_CALLBACK_URL = f"{API_BASE}/answerCallbackQuery"

HTTP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": f"{APP_NAME}/{VERSION}",
}

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 35
SEND_TIMEOUT = 20
RECONNECT_MIN_SECONDS = 1.0
RECONNECT_MAX_SECONDS = 30.0

# Verified from the previous ZIVO source. This is the internal ZIVO owner ID,
# not a Soroush native-admin claim.
GLOBAL_OWNER_IDS = {49145577}

HELP_TEXT = """🚀 ZIVO | پنل رسمی مدیریت گروه
━━━━━━━━━━━━━━━━━━
نسخه: zivo-official17 + zivo60.96.48

🔗 اتصال گروه
• روی «اتصال گروه» بزن و لینک را بفرست.
• ZIVO قبل از Join، نام، بیو و تعداد اعضا را از خود سروش بررسی می‌کند.
• سریع‌ترین اکانت سالم پیشنهاد می‌شود و تا تأیید تو هیچ عضویتی انجام نمی‌شود.

🎛 مدیریت گروه
بعد از انتخاب گروه، پنل مدیریت براساس پلن همان گروه ساخته می‌شود و با ارتقای اشتراک قابلیت‌های تازه به همان صفحه اضافه می‌شوند.

💎 اشتراک
پلن، مدت، کد تخفیف، لینک مستقیم درگاه، بررسی پرداخت و صفحه فعال‌سازی همگی داخل همین بات انجام می‌شوند.

🛡 پیوی اکانت‌های اجرایی خاموش است؛ رابط کاربر فقط همین بات رسمی است.

🔋 وضعیت اشتراک
داخل مدیریت هر گروه، روزهای باقی‌مانده + درصد و نوار شارژ اشتراک نمایش داده می‌شود.

🐱 اقتصاد Meow
• انتقال Meow با آیدی عددی، @username یا Forward پیام
• خرید Meow برای خودت یا شخص دیگر؛ حداقل 100 و هر Meow برابر 40 تومان
• Gift Code یک‌بارمصرف ZIVO########
• پرداخت زیبال، کد تخفیف، کارت‌به‌کارت و بررسی پرداخت
• مقصد فقط باید یک‌بار Official ZIVO را Start کرده باشد؛ پیوی اکانت‌های اجرایی لازم نیست.

🧱 قفل‌های گروه
از داخل مدیریت گروه، لیست کامل قفل‌ها را ببین و روشن/خاموش کن. GOLD و DIAMOND تنظیم اخطار اختصاصی و AutoBan هر قفل را هم دارند.

📣 اطلاع‌رسانی
کاربر می‌تواند با «تبلیغات خاموش» دریافت اطلاع‌رسانی Official را متوقف کند. مالک ZIVO می‌تواند Campaign متن/عکس/ویدیو/ویس/فایل را برای Official، پیوی اکانت‌ها، گروه‌ها یا همه شبکه بفرستد.
"""

COMMAND_LIST_TEXT = """📚 ZIVO | دستورات کاربردی
━━━━━━━━━━━━━━━━━━
/start | پنل | راهنما
گروه‌های من | کنترل گروه | خروج کنترل
خرید اشتراک | اشتراک من | خریدهای من
انتقال میو | خرید Meow | کد هدیه Meow | موجودی Meow

در حالت کنترل، فرمان‌های اصلی گروه مستقیم اجرا می‌شوند.
نمونه:
قفل لینک
اسپم فعال
پاکسازی 700
خوشامد فعال
سخنگو روشن
هدف 123456 | بن
پیام 987 | پین
"""

CAPABILITY_STATUS_TEXT = """✨ ZIVO | تفاوت واقعی پلن‌ها
━━━━━━━━━━━━━━━━━━
🆓 FREE — رایگان
• مدیریت پایه کامل: قفل‌ها، ضداسپم، اخطار، سکوت، بن، قوانین، پین و آمار پایه
• تمام قفل‌های رسانه‌ای فعلی و ضد فحش/فیلتر کلمه
• پاکسازی تا 700 پیام
• خوشامد متنی و سخنگوی Normal
• بازی‌ها، Meow، Pet و House
• Meow Luck: 1.00× | Pet: قیمت عادی
🚫 بدون Content Filter، AI، Backup، Anti-Raid حرفه‌ای، Watch List و Group Health

🥈 SILVER — نقره‌ای
• همه FREE
• Content Filter واقعی
• پاکسازی تا 2,000 پیام
• Learning و شخصیت‌های غیر-AI سخنگو
• یک Schedule فعال و پاکسازی زمان‌بندی‌شده محدود
• گزارش آماری پایه بیشتر
• Pet با 10٪ تخفیف | Meow Luck: 1.15×

🥇 GOLD — طلایی
• همه FREE + SILVER
• پاکسازی تا 5,000 پیام + پاکسازی کامل گپ
• رسانه خوشامد: GIF / عکس / Sticker / Media
• گزارش امروز + پرونده کاربران
• Admin Audit
• Backup دستی + Restore + Copy Settings
• Anti-Raid پایه و تنظیم مجازات حرفه‌ای
• AI Speaker محدود با سهمیه روزانه
• Pet با 20٪ تخفیف | Meow Luck: 1.35×

💎 DIAMOND — الماس
• همه قابلیت‌های قبلی
• پاکسازی بدون سقف پلنی با Safe Batch داخلی
• AI کامل و شخصیت اختصاصی
• Auto Moderation
• Watch List و گزارش رفتار کاربران زیرنظر
• Group Health با امتیاز امنیت
• Anti-Raid حرفه‌ای
• گزارش هفتگی
• Auto Backup و Snapshotهای بیشتر
• Pet با 30٪ تخفیف | Meow Luck: 1.60×
• 100 Meow پاداش فعال‌سازی با Anti-Abuse

🔐 این تفاوت‌ها فقط متن نیستند؛ Core 96.46 قبل از اجرای فرمان سطح پلن گروه را بررسی می‌کند.
"""

MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "🔗 اتصال گروه", "callback_data": "bridge:join"}, {"text": "📂 گروه‌های من", "callback_data": "bridge:groups"}],
        [{"text": "🎛 مدیریت گروه", "callback_data": "ctl:current"}, {"text": "💎 خرید / ارتقای پلن", "callback_data": "prem:groups"}],
        [{"text": "🌱 اشتراک‌های من", "callback_data": "prem:subs"}, {"text": "✨ تفاوت پلن‌ها", "callback_data": "menu:capabilities"}],
        [{"text": "🎮 سرگرمی", "callback_data": "menu:fun"}, {"text": "🐾 اقتصاد میو", "callback_data": "menu:economy"}],
        [{"text": "🧰 ابزارها", "callback_data": "menu:tools"}, {"text": "📚 راهنما", "callback_data": "menu:help"}],
        [{"text": "📋 دستورات", "callback_data": "menu:commands"}, {"text": "⚡ پینگ", "callback_data": "menu:ping"}],
    ]
}

REQUIRED_JOIN_MENU = {
    "inline_keyboard": [
        [{"text": "📢 عضویت در ZIVOHELP", "url": "https://splus.ir/ZIVOHELP"}],
        [{"text": "📚 عضویت در ZIVOCMD", "url": "https://splus.ir/ZIVOCMD"}],
        [{"text": "✅ عضو شدم · ادامه", "callback_data": "gate:check"}],
    ]
}

PLAN_UX = {
    "free": {
        "label": "FREE · رایگان", "emoji": "🌱", "cleanup": 700,
        "summary": "مدیریت پایه قدرتمند برای گروه‌های عادی",
        "features": [
            "قفل‌ها و ضداسپم", "اخطار، سکوت و بن", "پاکسازی تا 700 پیام",
            "خوشامد متنی", "سخنگوی Normal", "سرگرمی و اقتصاد پایه",
        ],
    },
    "silver": {
        "label": "SILVER · نقره‌ای", "emoji": "🥈", "cleanup": 2000,
        "summary": "مدیریت روان‌تر، فیلتر محتوا و Automation پایه",
        "features": [
            "همه قابلیت‌های FREE", "فیلتر محتوا", "پاکسازی تا 2000 پیام",
            "پاکسازی زمان‌بندی‌شده", "شخصیت‌های Funny / Chatty / Quiet / Anime",
            "Learning و Custom Q&A سخنگو", "Pet با 10٪ تخفیف و Meow Luck 1.15×",
        ],
    },
    "gold": {
        "label": "GOLD · طلایی", "emoji": "🥇", "cleanup": 5000,
        "summary": "پنل حرفه‌ای مدیریت، گزارش، بکاپ، Anti-Raid و AI",
        "features": [
            "همه قابلیت‌های SILVER", "پاکسازی تا 5000 پیام + پاکسازی کامل",
            "رسانه خوشامد", "گزارش امروز و پرونده کاربران", "Admin Audit",
            "Backup / Restore / Copy Settings", "Anti-Raid", "AI Speaker سهمیه‌دار",
            "مجازات جداگانه هر قفل", "Pet با 20٪ تخفیف و Meow Luck 1.35×",
        ],
    },
    "diamond": {
        "label": "DIAMOND · الماس", "emoji": "💎", "cleanup": 0,
        "summary": "مدیریت هوشمند کامل و بیشترین امکانات امنیتی و اقتصادی",
        "features": [
            "همه قابلیت‌های GOLD", "پاکسازی بدون سقف پلنی با Safe Batch",
            "AI کامل و شخصیت اختصاصی", "Auto Moderation", "Watch List",
            "Group Health", "Anti-Raid حرفه‌ای", "گزارش هفتگی", "Auto Backup",
            "Pet با 30٪ تخفیف و Meow Luck 1.60×", "100 Meow پاداش فعال‌سازی با Anti-Abuse",
        ],
    },
}

PLAN_RANK = {"free": 0, "silver": 1, "gold": 2, "diamond": 3}

PLAN_NEW_FEATURES = {
    "silver": [
        "🧹 سقف پاکسازی از 700 به 2,000 پیام ارتقا پیدا کرد",
        "🧽 فیلتر محتوا برای متن/رسانه ثبت‌شده باز شد",
        "⏱ یک Schedule و پاکسازی زمان‌بندی‌شده فعال شد",
        "🎭 شخصیت‌ها و Learning کامل سخنگو اضافه شد",
        "🐾 تخفیف Pet و Meow Luck بهتر شد",
    ],
    "gold": [
        "🧹 سقف پاکسازی به 5,000 پیام + پاکسازی کامل ارتقا پیدا کرد",
        "📊 گزارش امروز، پرونده کاربران و Admin Audit اضافه شد",
        "💾 Backup / Restore / Copy Settings باز شد",
        "🛡 Anti-Raid و مجازات جداگانه قفل‌ها فعال شد",
        "🧠 AI Speaker سهمیه‌دار و رسانه خوشامد اضافه شد",
        "🐾 اقتصاد Premium سطح GOLD فعال شد",
    ],
    "diamond": [
        "♾ پاکسازی بدون سقف مصنوعی پلن با Safe Batch فعال شد",
        "🧠 AI کامل و Auto Moderation باز شد",
        "👁 Watch List و 🩺 Group Health اضافه شد",
        "🛡 Anti-Raid حرفه‌ای و 📈 گزارش هفتگی فعال شد",
        "♻️ Auto Backup و Snapshotهای حرفه‌ای باز شد",
        "🐱 بیشترین Meow Luck + 100 Meow پاداش یک‌باره فعال شد",
    ],
}


FUN_MENU = {
    "inline_keyboard": [
        [{"text": "😂 جوک", "callback_data": "fun:جوک"}, {"text": "📖 داستان", "callback_data": "fun:داستان"}],
        [{"text": "🔮 فال", "callback_data": "fun:فال"}, {"text": "🧩 معما", "callback_data": "fun:معما"}],
        [{"text": "💡 دانستنی", "callback_data": "fun:دانستنی"}, {"text": "🔥 چالش", "callback_data": "fun:چالش"}],
        [{"text": "🎲 تاس", "callback_data": "fun:تاس"}, {"text": "🪙 شیر یا خط", "callback_data": "fun:شیر یا خط"}],
        [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
    ]
}

TOOLS_MENU = {
    "inline_keyboard": [
        [{"text": "🕒 تاریخ و ساعت", "callback_data": "tool:time"}],
        [{"text": "🔤 فونت", "callback_data": "tool:font"}, {"text": "🧮 ماشین حساب", "callback_data": "tool:calc"}],
        [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
    ]
}

ECONOMY_MENU = {
    "inline_keyboard": [
        [{"text": "🐱 میو", "callback_data": "eco:meow"}, {"text": "💰 موجودی", "callback_data": "eco:profile"}],
        [{"text": "🐾 فروشگاه پت", "callback_data": "eco:petshop"}, {"text": "❤️ پت من", "callback_data": "eco:pet"}],
        [{"text": "🏡 فروشگاه خانه", "callback_data": "eco:houseshop"}, {"text": "🏘 خانه‌های من", "callback_data": "eco:houses"}],
        [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
    ]
}

GROUP_CONTROL_MENU = {
    "inline_keyboard": [
        [{"text": "🔒 قفل لینک", "callback_data": "ctl:q:lock_link"}, {"text": "🔓 باز لینک", "callback_data": "ctl:q:unlock_link"}],
        [{"text": "🛡 ضداسپم روشن", "callback_data": "ctl:q:spam_on"}, {"text": "⛔ ضداسپم خاموش", "callback_data": "ctl:q:spam_off"}],
        [{"text": "📊 وضعیت اسپم", "callback_data": "ctl:q:spam_status"}, {"text": "🧹 پاکسازی اسپم", "callback_data": "ctl:q:spam_cleanup_full"}],
        [{"text": "🗑 پاکسازی 100", "callback_data": "ctl:q:cleanup100"}, {"text": "🗑 پاکسازی 700", "callback_data": "ctl:q:cleanup500"}],
        [{"text": "👋 خوشامد روشن", "callback_data": "ctl:q:welcome_on"}, {"text": "🔕 خوشامد خاموش", "callback_data": "ctl:q:welcome_off"}],
        [{"text": "🗣 سخنگو روشن", "callback_data": "ctl:q:speaker_on"}, {"text": "🤐 سخنگو خاموش", "callback_data": "ctl:q:speaker_off"}],
        [{"text": "🧱 لیست قفل‌ها", "callback_data": "ctl:q:locks"}, {"text": "⌨️ فرمان آزاد", "callback_data": "ctl:raw"}],
        [{"text": "🔁 تغییر گروه", "callback_data": "bridge:groups"}, {"text": "🚪 خروج کنترل", "callback_data": "ctl:exit"}],
        [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
    ]
}

QUICK_CONTROL_COMMANDS = {
    "lock_link": "قفل لینک",
    "unlock_link": "باز لینک",
    "spam_on": "اسپم فعال",
    "spam_off": "اسپم خاموش",
    "spam_status": "تنظیمات اسپم",
    "spam_cleanup_full": "پاکسازی اسپم کامل",
    "cleanup100": "پاکسازی",
    "cleanup500": "پاکسازی 700",
    "welcome_on": "خوشامد فعال",
    "welcome_off": "خوشامد خاموش",
    "speaker_on": "سخنگو روشن",
    "speaker_off": "سخنگو خاموش",
    "locks": "لیست قفل",
    "report_today": "گزارش امروز",
    "report_week": "گزارش هفتگی",
    "group_health": "سلامت گروه",
    "admin_audit": "گزارش ادمین",
    "raid_on": "ضد رید فعال",
    "raid_off": "ضد رید خاموش",
    "auto_mod_on": "مدیریت هوشمند فعال",
    "auto_mod_off": "مدیریت هوشمند خاموش",
    "backup_now": "بکاپ گروه",
    "auto_backup_on": "بکاپ خودکار فعال",
    "backup_status": "وضعیت بکاپ",
    "watch_status": "وضعیت واچ لیست",
    "speaker_funny": "شخصیت سخنگو funny",
    "speaker_anime": "شخصیت سخنگو anime",
    "ai_on": "سخنگو هوشمند روشن",
    "ai_off": "سخنگو هوشمند خاموش",
    "content_filter_help": "راهنما فیلتر محتوا",
    "schedule_status": "وضعیت پاکسازی خودکار",
    "cleanup_full": "پاکسازی کامل گپ",
    "dossier_help": "راهنما پرونده",
    "welcome_media_help": "راهنما رسانه خوشامد",
}


JOKES = (
    "برنامه‌نویس رفت نونوایی، گفت دو تا نون بخر؛ اگر تخم‌مرغ داشت شش تا بخر. با شش تا نون برگشت!",
    "گفتن چرا لپ‌تاپت همیشه خنکه؟ گفت چون همه باگ‌هاش فریز شدن.",
    "برنامه‌نویس گفت امروز زود می‌خوابم؛ بعد فقط یک باگ کوچیک دید!",
)
FACTS = (
    "اولین نسخه عمومی پایتون در سال 1991 منتشر شد.",
    "SQLite یک دیتابیس فایل‌محور است و برای بات‌های سبک و متوسط انتخاب مناسبی است.",
    "SSE برای دریافت یک‌طرفه رویدادهای زنده روی HTTP طراحی شده است.",
)
FORTUNES = (
    "امروز یک کار نیمه‌تمام را جمع می‌کنی و ذهنت سبک‌تر می‌شود.",
    "یک تصمیم کوچک، مسیر بزرگ‌تری را برایت روشن می‌کند.",
    "خبر خوب از جایی می‌رسد که انتظارش را کمتر داری.",
)


IRAN_TZ = ZoneInfo("Asia/Tehran")
JALALI_MONTH_NAMES: Tuple[str, ...] = ("فروردین","اردیبهشت","خرداد","تیر","مرداد","شهریور","مهر","آبان","آذر","دی","بهمن","اسفند")
PERSIAN_WEEKDAYS: Tuple[str, ...] = ("دوشنبه","سه‌شنبه","چهارشنبه","پنجشنبه","جمعه","شنبه","یکشنبه")
FONT_TEXT_MAX_CHARS = 120

def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    month_offsets = (0,31,59,90,120,151,181,212,243,273,304,334)
    if gy > 1600:
        jy = 979; gy -= 1600
    else:
        jy = 0; gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365*gy + (gy2+3)//4 - (gy2+99)//100 + (gy2+399)//400 - 80 + gd + month_offsets[gm-1]
    jy += 33*(days//12053); days %= 12053
    jy += 4*(days//1461); days %= 1461
    if days > 365:
        jy += (days-1)//365; days = (days-1)%365
    if days < 186:
        jm = 1 + days//31; jd = 1 + days%31
    else:
        jm = 7 + (days-186)//30; jd = 1 + (days-186)%30
    return jy, jm, jd

def iran_datetime(value: Optional[datetime] = None) -> datetime:
    if value is None:
        return datetime.now(IRAN_TZ)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(IRAN_TZ)

def iran_utc_offset_text(value: datetime) -> str:
    offset = value.utcoffset()
    if offset is None: return "UTC+03:30"
    minutes = int(offset.total_seconds()//60); sign = "+" if minutes >= 0 else "-"; minutes = abs(minutes)
    h,m = divmod(minutes,60); return f"UTC{sign}{h:02d}:{m:02d}"

def iran_date_time_text(value: Optional[datetime] = None) -> str:
    local = iran_datetime(value); jy,jm,jd = gregorian_to_jalali(local.year, local.month, local.day)
    return (f"ZIVO | زمان ایران\n━━━━━━━━━━━━━━━━━━\n{PERSIAN_WEEKDAYS[local.weekday()]}، {jd} {JALALI_MONTH_NAMES[jm-1]} {jy}\n"
            f"{jy:04d}/{jm:02d}/{jd:02d}\nساعت: {local:%H:%M:%S}\nAsia/Tehran | {iran_utc_offset_text(local)}\nمیلادی: {local:%Y/%m/%d}")

def _font_linear_map(upper_start: int, lower_start: int, digit_start: Optional[int]=None) -> Dict[int,str]:
    mapping: Dict[int,str] = {}
    for i,ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"): mapping[ord(ch)] = chr(upper_start+i)
    for i,ch in enumerate("abcdefghijklmnopqrstuvwxyz"): mapping[ord(ch)] = chr(lower_start+i)
    if digit_start is not None:
        for i,ch in enumerate("0123456789"): mapping[ord(ch)] = chr(digit_start+i)
    return mapping

FONT_STYLE_MAPS = (
    _font_linear_map(0x1D400,0x1D41A,0x1D7CE), _font_linear_map(0x1D5A0,0x1D5BA,0x1D7E2),
    _font_linear_map(0x1D5D4,0x1D5EE,0x1D7EC), _font_linear_map(0x1D608,0x1D622),
    _font_linear_map(0x1D63C,0x1D656), _font_linear_map(0x1D670,0x1D68A,0x1D7F6),
    _font_linear_map(0xFF21,0xFF41,0xFF10),
)
FONT_STYLE_WRAPPERS = (("𓆩 "," 𓆪"),("『 "," 』"),("꧁ "," ꧂"),("༺ "," ༻"),("✦ "," ✦"),("♛ "," ♛"),("⫷ "," ⫸"))

def _font_circled(text: str) -> str:
    out=[]
    for ch in text:
        if "A" <= ch <= "Z": out.append(chr(0x24B6+ord(ch)-ord("A")))
        elif "a" <= ch <= "z": out.append(chr(0x24D0+ord(ch)-ord("a")))
        elif ch == "0": out.append("⓪")
        elif "1" <= ch <= "9": out.append(chr(0x2460+ord(ch)-ord("1")))
        else: out.append(ch)
    return "".join(out)

def _font_combining(text: str, mark: str) -> str:
    return "".join(ch+mark if not ch.isspace() else ch for ch in text)

def font_style_variants(text: str) -> Tuple[str,...]:
    value = str(text or "").strip(); variants=[]
    for mapping,wrapper in zip(FONT_STYLE_MAPS,FONT_STYLE_WRAPPERS): variants.append(f"{wrapper[0]}{value.translate(mapping)}{wrapper[1]}")
    variants += [f"★彡 {_font_circled(value)} 彡★", f"〆 {_font_combining(value, chr(0x0332))} 〆", f"乂 {_font_combining(value, chr(0x0336))} 乂", "• "+"  •  ".join(list(value))+" •", f"☬ 【{value}】 ☬"]
    return tuple(variants[:12])

def font_response(text: str) -> str:
    value = str(text or "").strip()
    if not value: return "بعد از «فونت» متن را بنویس. نمونه: فونت zivo"
    if len(value) > FONT_TEXT_MAX_CHARS: return f"متن فونت حداکثر {FONT_TEXT_MAX_CHARS} نویسه باشد."
    lines=["ZIVO | 12 FONT STYLES","━━━━━━━━━━━━━━━━━━"]
    lines.extend(f"{i:02d}  {v}" for i,v in enumerate(font_style_variants(value),1))
    return "\n".join(lines)

def _setup_logging() -> logging.Logger:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("zivo_official5")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


log = _setup_logging()


def normalize_text(value: Any) -> str:
    text = str(value or "").strip()
    text = text.replace("ي", "ی").replace("ك", "ک")
    text = re.sub(r"[\u200c\u200d\ufeff]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(int(value))
    return str(value).strip()


def parse_group_link(text: str) -> Optional[Tuple[str, str]]:
    value = normalize_text(text).strip()
    m = PRIVATE_INVITE_RE.fullmatch(value)
    if m:
        return ("invite", str(m.group(1) or "").strip())
    m = PUBLIC_GROUP_RE.fullmatch(value)
    if m:
        username = str(m.group(1) or "").strip().lstrip("@")
        if username.casefold() != "joingroup":
            return ("public", username)
    return None


@dataclass(frozen=True)
class IncomingMessage:
    raw: Dict[str, Any]
    sender_id: str
    chat_id: str
    message_id: str
    body: str
    message_type: str

    @property
    def is_text(self) -> bool:
        return self.message_type.upper() in {"", "TEXT", "MESSAGE", "TEXT_MESSAGE"} and bool(self.body)


@dataclass(frozen=True)
class IncomingCallback:
    raw: Dict[str, Any]
    callback_id: str
    sender_id: str
    chat_id: str
    message_id: str
    data: str


def normalize_callback(raw: Any) -> Optional[IncomingCallback]:
    if not isinstance(raw, dict):
        return None
    cb = raw.get("callback_query")
    if not isinstance(cb, dict):
        return None
    sender_obj = cb.get("from") if isinstance(cb.get("from"), dict) else {}
    message_obj = cb.get("message") if isinstance(cb.get("message"), dict) else {}
    chat_obj = message_obj.get("chat") if isinstance(message_obj.get("chat"), dict) else {}
    sender_id = safe_id(sender_obj.get("id"))
    chat_id = safe_id(chat_obj.get("id")) or sender_id
    callback_id = safe_id(cb.get("id"))
    data = normalize_text(cb.get("data"))
    message_id = safe_id(message_obj.get("message_id"))
    if not callback_id or not sender_id or not chat_id or not data:
        return None
    return IncomingCallback(
        raw=raw,
        callback_id=callback_id,
        sender_id=sender_id,
        chat_id=chat_id,
        message_id=message_id,
        data=data,
    )


def _first_present(mapping: Dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        value = mapping.get(name)
        if value not in (None, ""):
            return value
    return None


def normalize_event(raw: Any) -> Optional[IncomingMessage]:
    """Normalize current Soroush+ Bot API Update/Message objects.

    Current official Bot API follows an Update envelope with `update_id` and
    an optional `message` object. The message contains `from`, `chat`,
    `message_id`, and `text` fields, matching the documented Bot API model.
    A small legacy fallback is kept only for already-normalized test payloads.
    """
    if not isinstance(raw, dict):
        return None

    payload = raw.get("message") if isinstance(raw.get("message"), dict) else raw

    sender_obj = payload.get("from")
    if isinstance(sender_obj, dict):
        sender = sender_obj.get("id")
    else:
        sender = _first_present(payload, ("sender", "senderId", "sender_id", "userId", "user_id", "from"))

    chat_obj = payload.get("chat")
    if isinstance(chat_obj, dict):
        chat = chat_obj.get("id")
    else:
        chat = _first_present(
            payload,
            ("conversationId", "conversation_id", "chatId", "chat_id", "roomId", "room_id", "to"),
        )

    body = _first_present(payload, ("text", "body", "messageText", "message_text", "content"))
    msg_type = _first_present(payload, ("type", "messageType", "message_type")) or ""
    msg_id = _first_present(payload, ("message_id", "messageId", "id"))

    if chat in (None, ""):
        chat = sender

    sender_id = safe_id(sender)
    chat_id = safe_id(chat)
    if not sender_id and not chat_id:
        return None

    return IncomingMessage(
        raw=raw,
        sender_id=sender_id,
        chat_id=chat_id or sender_id,
        message_id=safe_id(msg_id),
        body=normalize_text(body),
        message_type=normalize_text(msg_type),
    )


class Store:
    def __init__(self, path: Optional[Path] = None) -> None:
        # Official16 deliberately keeps UI/session state in memory. Persistent
        # group ownership and command state live inside each account process.
        # This removes SQLite filesystem failures from the official Bot API path.
        self.path = Path(":memory:")
        self._lock = threading.RLock()
        self._con = sqlite3.connect(":memory:", check_same_thread=False, timeout=15)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA synchronous=OFF")
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        return self._con

    def _init_schema(self) -> None:
        with self._lock, self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_stats (
                    user_id TEXT PRIMARY KEY,
                    messages INTEGER NOT NULL DEFAULT 0,
                    commands INTEGER NOT NULL DEFAULT 0,
                    last_seen INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS word_filters (
                    chat_id TEXT NOT NULL,
                    word TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, word)
                );
                CREATE TABLE IF NOT EXISTS warnings (
                    chat_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bot_contacts (
                    user_id TEXT PRIMARY KEY,
                    chat_id TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    first_name TEXT NOT NULL DEFAULT '',
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS official_user_gate (
                    user_id TEXT PRIMARY KEY,
                    required INTEGER NOT NULL DEFAULT 1,
                    passed INTEGER NOT NULL DEFAULT 0,
                    prompt_sent INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bridge_requests (
                    job_id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    target_account TEXT NOT NULL,
                    link_kind TEXT NOT NULL,
                    link_value TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at INTEGER NOT NULL,
                    notified_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_bridge_requests_notify ON bridge_requests(notified_at, job_id);
                CREATE TABLE IF NOT EXISTS managed_groups (
                    user_id TEXT NOT NULL,
                    group_id INTEGER NOT NULL,
                    account_key TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    member_count INTEGER NOT NULL DEFAULT -1,
                    joined_at INTEGER NOT NULL,
                    PRIMARY KEY(user_id, group_id)
                );
                CREATE TABLE IF NOT EXISTS pending_group_links (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    link_kind TEXT NOT NULL,
                    link_value TEXT NOT NULL,
                    selected_account TEXT NOT NULL DEFAULT '',
                    preview_title TEXT NOT NULL DEFAULT '',
                    preview_about TEXT NOT NULL DEFAULT '',
                    preview_member_count INTEGER NOT NULL DEFAULT -1,
                    preview_group_id INTEGER NOT NULL DEFAULT 0,
                    preview_latency_ms REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'waiting_confirm',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pending_group_links_user ON pending_group_links(user_id,status,request_id);
                CREATE TABLE IF NOT EXISTS premium_ui_state (
                    user_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL DEFAULT '',
                    order_id INTEGER NOT NULL DEFAULT 0,
                    group_id INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_control_state (
                    user_id TEXT PRIMARY KEY,
                    active_group_id INTEGER NOT NULL DEFAULT 0,
                    mode TEXT NOT NULL DEFAULT '',
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS remote_requests (
                    job_id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    group_id INTEGER NOT NULL,
                    account_key TEXT NOT NULL,
                    command_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at INTEGER NOT NULL,
                    notified_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_remote_requests_notify ON remote_requests(notified_at,job_id);
                """
            )

    def observe(self, message: IncomingMessage, command: bool) -> None:
        now = int(time.time())
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO user_stats(user_id, messages, commands, last_seen)
                VALUES(?, 1, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    messages=messages+1,
                    commands=commands+excluded.commands,
                    last_seen=excluded.last_seen
                """,
                (message.sender_id, 1 if command else 0, now),
            )
            con.execute(
                "INSERT INTO events(sender_id, chat_id, message_type, created_at) VALUES(?,?,?,?)",
                (message.sender_id, message.chat_id, message.message_type or "TEXT", now),
            )

    def stats(self, user_id: str) -> Dict[str, int]:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT messages, commands FROM user_stats WHERE user_id=?", (user_id,)).fetchone()
        return {"messages": int(row["messages"]), "commands": int(row["commands"])} if row else {"messages": 0, "commands": 0}

    def remember_contact(self, message: IncomingMessage) -> None:
        if not message.sender_id or not message.chat_id or message.sender_id != message.chat_id:
            return
        payload = message.raw.get("message") if isinstance(message.raw.get("message"), dict) else message.raw
        sender = payload.get("from") if isinstance(payload.get("from"), dict) else {}
        chat = payload.get("chat") if isinstance(payload.get("chat"), dict) else {}
        username = str(sender.get("username") or chat.get("username") or "").strip()
        first_name = str(sender.get("first_name") or chat.get("first_name") or "").strip()
        now = int(time.time())
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO bot_contacts(user_id,chat_id,username,first_name,first_seen,last_seen)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    chat_id=excluded.chat_id, username=excluded.username, first_name=excluded.first_name,
                    last_seen=excluded.last_seen
                """,
                (message.sender_id, message.chat_id, username, first_name, now, now),
            )

    def contact(self, user_id: str) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute("SELECT * FROM bot_contacts WHERE user_id=?", (str(user_id),)).fetchone()

    def contacts(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute("SELECT * FROM bot_contacts ORDER BY last_seen DESC LIMIT ?", (int(limit),)).fetchall()

    def gate_state(self, user_id: str) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute("SELECT * FROM official_user_gate WHERE user_id=?", (str(user_id),)).fetchone()

    def require_gate(self, user_id: str) -> None:
        with self._lock, self._connect() as con:
            con.execute("INSERT INTO official_user_gate(user_id,required,passed,prompt_sent,updated_at) VALUES(?,1,0,1,?) ON CONFLICT(user_id) DO UPDATE SET required=1,prompt_sent=1,updated_at=excluded.updated_at", (str(user_id), int(time.time())))

    def pass_gate(self, user_id: str) -> None:
        with self._lock, self._connect() as con:
            con.execute("INSERT INTO official_user_gate(user_id,required,passed,prompt_sent,updated_at) VALUES(?,1,1,1,?) ON CONFLICT(user_id) DO UPDATE SET passed=1,updated_at=excluded.updated_at", (str(user_id), int(time.time())))

    def gate_pending(self, user_id: str) -> bool:
        row = self.gate_state(user_id)
        return bool(row is not None and int(row["required"] or 0) and not int(row["passed"] or 0))

    def add_bridge_request(self, *, job_id: int, user_id: str, chat_id: str, target_account: str, link_kind: str, link_value: str) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO bridge_requests(job_id,user_id,chat_id,target_account,link_kind,link_value,status,created_at,notified_at) VALUES(?,?,?,?,?,?,'queued',?,0)",
                (int(job_id), str(user_id), str(chat_id), str(target_account), str(link_kind), str(link_value), int(time.time())),
            )

    def pending_bridge_requests(self) -> list[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute("SELECT * FROM bridge_requests WHERE notified_at=0 ORDER BY job_id").fetchall()

    def mark_bridge_notified(self, job_id: int, status: str) -> None:
        with self._lock, self._connect() as con:
            con.execute("UPDATE bridge_requests SET status=?, notified_at=? WHERE job_id=?", (str(status), int(time.time()), int(job_id)))

    def has_active_bridge_request(self, user_id: str) -> bool:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT 1 FROM bridge_requests WHERE user_id=? AND notified_at=0 LIMIT 1", (str(user_id),)).fetchone()
        return row is not None

    def add_managed_group(self, *, user_id: str, group_id: int, account_key: str, title: str, member_count: int) -> None:
        if int(group_id or 0) <= 0:
            return
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO managed_groups(user_id,group_id,account_key,title,member_count,joined_at) VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id,group_id) DO UPDATE SET account_key=excluded.account_key,title=excluded.title,member_count=excluded.member_count
                """,
                (str(user_id), int(group_id), str(account_key), str(title), int(member_count), int(time.time())),
            )

    def managed_groups(self, user_id: str) -> list[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute("SELECT * FROM managed_groups WHERE user_id=? ORDER BY joined_at DESC", (str(user_id),)).fetchall()

    def all_managed_groups(self) -> list[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute(
                "SELECT * FROM managed_groups ORDER BY joined_at DESC"
            ).fetchall()

    def managed_group(self, user_id: str, group_id: int, *, owner_override: bool = False) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as con:
            if owner_override:
                return con.execute(
                    "SELECT * FROM managed_groups WHERE group_id=? ORDER BY joined_at DESC LIMIT 1",
                    (int(group_id),),
                ).fetchone()
            return con.execute(
                "SELECT * FROM managed_groups WHERE user_id=? AND group_id=? LIMIT 1",
                (str(user_id), int(group_id)),
            ).fetchone()

    def create_pending_group_link(
        self, *, user_id: str, chat_id: str, link_kind: str, link_value: str,
        selected_account: str = "", preview_title: str = "", preview_about: str = "",
        preview_member_count: int = -1, preview_group_id: int = 0, preview_latency_ms: float = 0.0,
    ) -> int:
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE pending_group_links SET status='superseded' WHERE user_id=? AND status IN ('waiting_confirm','waiting_account')",
                (str(user_id),),
            )
            cur = con.execute(
                """INSERT INTO pending_group_links(
                    user_id,chat_id,link_kind,link_value,selected_account,preview_title,preview_about,
                    preview_member_count,preview_group_id,preview_latency_ms,status,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,'waiting_confirm',?)""",
                (
                    str(user_id), str(chat_id), str(link_kind), str(link_value), str(selected_account),
                    str(preview_title)[:200], str(preview_about)[:1000], int(preview_member_count),
                    int(preview_group_id), float(preview_latency_ms), int(time.time()),
                ),
            )
            return int(cur.lastrowid)

    def pending_group_link(self, request_id: int, user_id: str) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute(
                "SELECT * FROM pending_group_links WHERE request_id=? AND user_id=? LIMIT 1",
                (int(request_id), str(user_id)),
            ).fetchone()

    def update_pending_group_link(self, request_id: int, *, account_key: Optional[str] = None, status: Optional[str] = None) -> None:
        fields = []
        params: list[Any] = []
        if account_key is not None:
            fields.append("selected_account=?"); params.append(str(account_key))
        if status is not None:
            fields.append("status=?"); params.append(str(status))
        if not fields:
            return
        params.append(int(request_id))
        with self._lock, self._connect() as con:
            con.execute(f"UPDATE pending_group_links SET {','.join(fields)} WHERE request_id=?", params)

    def set_premium_ui_state(self, user_id: str, *, stage: str = "", order_id: int = 0, group_id: int = 0) -> None:
        with self._lock, self._connect() as con:
            if not stage:
                con.execute("DELETE FROM premium_ui_state WHERE user_id=?", (str(user_id),))
                return
            con.execute(
                """INSERT INTO premium_ui_state(user_id,stage,order_id,group_id,updated_at) VALUES(?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET stage=excluded.stage,order_id=excluded.order_id,group_id=excluded.group_id,updated_at=excluded.updated_at""",
                (str(user_id), str(stage), int(order_id), int(group_id), int(time.time())),
            )

    def premium_ui_state(self, user_id: str) -> Dict[str, Any]:
        with self._lock, self._connect() as con:
            row = con.execute("SELECT stage,order_id,group_id FROM premium_ui_state WHERE user_id=?", (str(user_id),)).fetchone()
        if row is None:
            return {"stage": "", "order_id": 0, "group_id": 0}
        return {"stage": str(row["stage"] or ""), "order_id": int(row["order_id"] or 0), "group_id": int(row["group_id"] or 0)}

    def set_control_state(self, user_id: str, *, active_group_id: Optional[int] = None, mode: Optional[str] = None) -> None:
        current = self.control_state(user_id)
        gid = int(active_group_id if active_group_id is not None else current.get("active_group_id", 0))
        current_mode = str(mode if mode is not None else current.get("mode", ""))
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO user_control_state(user_id,active_group_id,mode,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                    active_group_id=excluded.active_group_id,
                    mode=excluded.mode,
                    updated_at=excluded.updated_at
                """,
                (str(user_id), gid, current_mode, int(time.time())),
            )

    def control_state(self, user_id: str) -> Dict[str, Any]:
        with self._lock, self._connect() as con:
            row = con.execute(
                "SELECT active_group_id,mode FROM user_control_state WHERE user_id=?",
                (str(user_id),),
            ).fetchone()
        if row is None:
            return {"active_group_id": 0, "mode": ""}
        return {"active_group_id": int(row["active_group_id"] or 0), "mode": str(row["mode"] or "")}

    def add_remote_request(self, *, job_id: int, user_id: str, chat_id: str, group_id: int, account_key: str, command_text: str) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO remote_requests(
                    job_id,user_id,chat_id,group_id,account_key,command_text,status,created_at,notified_at
                ) VALUES(?,?,?,?,?,?, 'queued', ?, 0)
                """,
                (int(job_id), str(user_id), str(chat_id), int(group_id), str(account_key), str(command_text)[:2000], int(time.time())),
            )

    def pending_remote_requests(self) -> list[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute(
                "SELECT * FROM remote_requests WHERE notified_at=0 ORDER BY job_id"
            ).fetchall()

    def mark_remote_notified(self, job_id: int, status: str) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE remote_requests SET status=?, notified_at=? WHERE job_id=?",
                (str(status), int(time.time()), int(job_id)),
            )

    def add_filter(self, chat_id: str, word: str, created_by: str) -> bool:
        word = normalize_text(word).casefold()
        if not word:
            return False
        with self._lock, self._connect() as con:
            cur = con.execute(
                "INSERT OR IGNORE INTO word_filters(chat_id, word, created_by, created_at) VALUES(?,?,?,?)",
                (chat_id, word, created_by, int(time.time())),
            )
            return cur.rowcount > 0

    def remove_filter(self, chat_id: str, word: str) -> bool:
        word = normalize_text(word).casefold()
        with self._lock, self._connect() as con:
            cur = con.execute("DELETE FROM word_filters WHERE chat_id=? AND word=?", (chat_id, word))
            return cur.rowcount > 0

    def reset_filters(self, chat_id: str) -> int:
        with self._lock, self._connect() as con:
            cur = con.execute("DELETE FROM word_filters WHERE chat_id=?", (chat_id,))
            return int(cur.rowcount or 0)

    def filters(self, chat_id: str) -> list[str]:
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT word FROM word_filters WHERE chat_id=? ORDER BY word", (chat_id,)).fetchall()
        return [str(row["word"]) for row in rows]

    def matched_filter(self, chat_id: str, text: str) -> Optional[str]:
        low = normalize_text(text).casefold()
        for word in self.filters(chat_id):
            if word and word in low:
                return word
        return None

    def warn(self, chat_id: str, user_id: str) -> int:
        now = int(time.time())
        with self._lock, self._connect() as con:
            con.execute(
                """
                INSERT INTO warnings(chat_id, user_id, count, updated_at)
                VALUES(?,?,1,?)
                ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    count=count+1,
                    updated_at=excluded.updated_at
                """,
                (chat_id, user_id, now),
            )
            row = con.execute("SELECT count FROM warnings WHERE chat_id=? AND user_id=?", (chat_id, user_id)).fetchone()
        return int(row["count"])


class SoroushOfficialTransport:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HTTP_HEADERS)
        self.offset = 0

    @staticmethod
    def _json(response: requests.Response) -> Dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"non-json API response: {response.text[:300]!r}") from exc
        if not isinstance(data, dict):
            raise RuntimeError(f"unexpected API response type: {type(data).__name__}")
        return data

    def get_me(self) -> Dict[str, Any]:
        response = self.session.get(GET_ME_URL, timeout=(CONNECT_TIMEOUT, SEND_TIMEOUT))
        log.info("getMe HTTP | status=%s", response.status_code)
        response.raise_for_status()
        data = self._json(response)
        if data.get("ok") is False:
            raise RuntimeError(f"getMe rejected: {data!r}")
        result = data.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"getMe missing result: {data!r}")
        return result

    def send_text(self, to: str, body: str, reply_markup: Optional[Dict[str, Any]] = None) -> requests.Response:
        payload: Dict[str, Any] = {"chat_id": to, "text": body}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self.session.post(SEND_MESSAGE_URL, json=payload, timeout=(CONNECT_TIMEOUT, SEND_TIMEOUT))
        log.info("sendMessage HTTP | status=%s chat_id=%s keyboard=%s", response.status_code, to, bool(reply_markup))
        if not response.ok:
            log.error("sendMessage rejected | status=%s body=%r", response.status_code, response.text[:500])
        response.raise_for_status()
        data = self._json(response)
        if data.get("ok") is False:
            raise RuntimeError(f"sendMessage rejected: {data!r}")
        return response

    def answer_callback(self, callback_id: str, text: str = "") -> bool:
        payload: Dict[str, Any] = {"callback_query_id": callback_id}
        if text:
            payload["text"] = text[:180]
        try:
            response = self.session.post(ANSWER_CALLBACK_URL, json=payload, timeout=(CONNECT_TIMEOUT, SEND_TIMEOUT))
            log.info("answerCallbackQuery HTTP | status=%s callback_id=%s", response.status_code, callback_id)
            if not response.ok:
                log.error("answerCallbackQuery rejected | status=%s body=%r", response.status_code, response.text[:500])
                return False
            data = self._json(response)
            return data.get("ok") is not False
        except Exception as exc:
            log.warning("answerCallbackQuery failed | callback_id=%s | %s", callback_id, exc)
            return False

    def iter_events(self, stop_event: threading.Event) -> Iterator[Dict[str, Any]]:
        while not stop_event.is_set():
            params: Dict[str, Any] = {"timeout": 25}
            if self.offset > 0:
                params["offset"] = self.offset
            response = self.session.get(
                GET_UPDATES_URL,
                params=params,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            log.info("getUpdates HTTP | status=%s offset=%s", response.status_code, self.offset)
            response.raise_for_status()
            data = self._json(response)
            if data.get("ok") is False:
                raise RuntimeError(f"getUpdates rejected: {data!r}")
            updates = data.get("result", [])
            if not isinstance(updates, list):
                raise RuntimeError(f"getUpdates result is not a list: {data!r}")
            for update in updates:
                if stop_event.is_set():
                    return
                if not isinstance(update, dict):
                    continue
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    self.offset = max(self.offset, update_id + 1)
                msg = update.get("message") if isinstance(update.get("message"), dict) else {}
                cb = update.get("callback_query") if isinstance(update.get("callback_query"), dict) else {}
                if cb:
                    frm = cb.get("from") if isinstance(cb.get("from"), dict) else {}
                    cb_msg = cb.get("message") if isinstance(cb.get("message"), dict) else {}
                    cb_chat = cb_msg.get("chat") if isinstance(cb_msg.get("chat"), dict) else {}
                    log.info(
                        "callback received | update_id=%s callback_id=%s from=%s chat=%s data=%r",
                        update_id, cb.get("id", ""), frm.get("id", ""), cb_chat.get("id", ""), cb.get("data", ""),
                    )
                else:
                    frm = msg.get("from") if isinstance(msg.get("from"), dict) else {}
                    log.info(
                        "update received | update_id=%s message_id=%s from=%s chat=%s",
                        update_id,
                        msg.get("message_id", ""),
                        frm.get("id", ""),
                        (msg.get("chat") or {}).get("id", "") if isinstance(msg.get("chat"), dict) else "",
                    )
                yield update


class BotCore:
    def __init__(self, store: Store, transport: Optional[SoroushOfficialTransport]) -> None:
        self.store = store
        self.transport = transport
        self._spam: Dict[tuple[str, str], Deque[float]] = defaultdict(deque)
        self._payment_watch: Dict[int, Dict[str, Any]] = {}
        self._payment_watch_lock = threading.RLock()
        self._admin_state: Dict[str, Dict[str, Any]] = {}
        self._official_campaign_lock = threading.RLock()
        self._official_campaign: Dict[str, Any] = {"running": False, "sent": 0, "failed": 0, "total": 0, "started_at": 0.0}

    @staticmethod
    def _is_owner(sender_id: str) -> bool:
        try:
            return int(sender_id) in GLOBAL_OWNER_IDS
        except (TypeError, ValueError):
            return False

    def _send(self, chat_id: str, body: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
        if self.transport is None:
            return
        try:
            self.transport.send_text(chat_id, body[:3900], reply_markup=reply_markup)
        except Exception as exc:
            log.error("send failed | chat=%s | %s", chat_id, exc)

    def _membership_gate_text(self, *, failed: bool = False) -> str:
        if failed:
            return (
                "📢 عضویت در کانال‌های رسمی ZIVO\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "برای اینکه آموزش‌ها، نسخه‌های جدید و فرمان‌های آماده رو از دست ندی، عضویت در دو کانال رسمی ZIVO رو کامل کن.\n\n"
                "📢 ZIVOHELP — خبر نسخه‌ها و اطلاعیه‌ها\n"
                "📚 ZIVOCMD — آموزش، نمونه فرمان و راهنما\n\n"
                "اگر همین الان عضو شدی، چند ثانیه صبر کن و بعد روی «✅ ادامه» بزن."
            )
        return (
            "👋 به ZIVO خوش اومدی\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ZIVO مرکز مدیریت هوشمند گروه‌های سروش+ه؛ قفل و ضداسپم، پاکسازی، گزارش، Backup، AI، Anti-Raid و اقتصاد میو رو یک‌جا و مرتب در اختیارت می‌ذاره.\n\n"
            "قبل از ورود به پنل، دو کانال رسمی ZIVO رو داشته باش تا آموزش قابلیت‌ها و خبر آپدیت‌ها رو از دست ندی:\n"
            "📢 ZIVOHELP — اطلاعیه و نسخه‌های جدید\n"
            "📚 ZIVOCMD — آموزش و فرمان‌های آماده\n\n"
            "بعد از عضویت روی «✅ عضو شدم · ادامه» بزن."
        )

    def _send_membership_gate(self, chat_id: str, *, failed: bool = False) -> str:
        text = self._membership_gate_text(failed=failed)
        self._send(chat_id, text, reply_markup=REQUIRED_JOIN_MENU if not failed else {
            "inline_keyboard": [
                [{"text": "📢 ZIVOHELP", "url": "https://splus.ir/ZIVOHELP"}, {"text": "📚 ZIVOCMD", "url": "https://splus.ir/ZIVOCMD"}],
                [{"text": "✅ ادامه", "callback_data": "menu:home"}],
            ]
        })
        return text

    def _complete_soft_gate(self, user_id: str, chat_id: str) -> str:
        self.store.pass_gate(user_id)
        try:
            self._ipc("main", {"op": "official_gate", "action": "pass", "requester_user_id": int(user_id)}, timeout=5.0)
        except Exception as exc:
            log.warning("persistent official soft gate pass failed | user=%s | %s: %s", user_id, type(exc).__name__, exc)
        text = self._membership_gate_text(failed=True)
        self._send(chat_id, text, reply_markup={
            "inline_keyboard": [
                [{"text": "📢 ZIVOHELP", "url": "https://splus.ir/ZIVOHELP"}, {"text": "📚 ZIVOCMD", "url": "https://splus.ir/ZIVOCMD"}],
                [{"text": "✅ ادامه", "callback_data": "menu:home"}],
            ]
        })
        return text

    def _check_membership_gate(self, user_id: str, chat_id: str) -> str:
        # Official16 intentionally uses a two-touch soft onboarding reminder.
        # No hard membership RPC is required: first contact shows the invitation,
        # the next interaction opens the panel permanently for that user.
        return self._complete_soft_gate(user_id, chat_id)

    def _premium_status_for_group(self, user_id: str, group_id: int) -> Dict[str, Any]:
        try:
            result = self._ipc("main", {
                "op": "premium", "action": "status",
                "requester_user_id": int(user_id), "group_id": int(group_id),
            }, timeout=5.0)
            if result.get("ok"):
                sub = dict(result.get("subscription") or {})
                plan = str(sub.get("plan") or "free").strip().lower()
                if plan not in PLAN_UX:
                    plan = "free"
                return {"ok": True, "plan": plan, "label": PLAN_UX[plan]["label"], "subscription": sub}
        except Exception as exc:
            log.warning("premium status unavailable | user=%s group=%s | %s: %s", user_id, group_id, type(exc).__name__, exc)
        return {"ok": False, "plan": "free", "label": PLAN_UX["free"]["label"], "subscription": {"plan": "free"}}

    def _active_plan_state(self, user_id: str) -> Dict[str, Any]:
        active = self._active_group(user_id)
        if active is None:
            return {"ok": False, "plan": "free", "label": PLAN_UX["free"]["label"]}
        return self._premium_status_for_group(user_id, int(active.get("group_id") or 0))

    @staticmethod
    def _parse_iso(value: Any) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def _subscription_meter(self, subscription: Dict[str, Any]) -> str:
        plan = str(subscription.get("plan") or "free").lower()
        if plan == "free":
            return "🔋 FREE · بدون تاریخ انقضا"
        start = self._parse_iso(subscription.get("started_at") or subscription.get("effective_started_at"))
        end = self._parse_iso(subscription.get("expires_at") or subscription.get("effective_expires_at"))
        now = datetime.now(timezone.utc)
        if end is None:
            return "🔋 اشتراک فعال · بدون تاریخ پایان ثبت‌شده"
        remaining_seconds = max(0.0, (end - now).total_seconds())
        remaining_days = max(0, int((remaining_seconds + 86399) // 86400))
        if remaining_seconds <= 0:
            return "🪫 🔴 اشتراک تمام شده\n🟥🟥🟥🟥🟥🟥🟥🟥🟥🟥  0٪"
        if start is None or end <= start:
            pct = 100
        else:
            total = max(1.0, (end - start).total_seconds())
            pct = max(0, min(100, int(round((remaining_seconds / total) * 100))))
        filled = max(1, min(10, int((pct + 9) // 10)))
        bar = "🟩" * filled + "⬜" * (10 - filled)
        return f"🔋 {remaining_days} روز باقی‌مانده\n{bar}  {pct}٪"

    def _group_control_menu(self, user_id: str) -> Dict[str, Any]:
        active = self._active_group(user_id)
        if active is None:
            return self._groups_menu(user_id)
        plan = str(self._active_plan_state(user_id).get("plan") or "free")
        rank = PLAN_RANK.get(plan, 0)
        rows: list[list[dict[str, str]]] = [
            [{"text": "🔒 قفل لینک", "callback_data": "ctl:q:lock_link"}, {"text": "🔓 باز لینک", "callback_data": "ctl:q:unlock_link"}],
            [{"text": "🛡 ضداسپم روشن", "callback_data": "ctl:q:spam_on"}, {"text": "⛔ ضداسپم خاموش", "callback_data": "ctl:q:spam_off"}],
            [{"text": "📊 وضعیت اسپم", "callback_data": "ctl:q:spam_status"}, {"text": "🧹 پاکسازی اسپم", "callback_data": "ctl:q:spam_cleanup_full"}],
        ]
        if plan == "free":
            rows.append([{"text": "🗑 حذف 300", "callback_data": "ctl:cleanup:300"}, {"text": "🗑 حذف 700", "callback_data": "ctl:cleanup:700"}])
        elif plan == "silver":
            rows.append([{"text": "🗑 حذف 700", "callback_data": "ctl:cleanup:700"}, {"text": "🗑 حذف 2,000", "callback_data": "ctl:cleanup:2000"}])
        elif plan == "gold":
            rows.append([{"text": "🗑 حذف 2,000", "callback_data": "ctl:cleanup:2000"}, {"text": "🗑 حذف 5,000", "callback_data": "ctl:cleanup:5000"}])
            rows.append([{"text": "🧹 پاکسازی کامل", "callback_data": "ctl:q:cleanup_full"}])
        else:
            rows.append([{"text": "🗑 حذف 5,000", "callback_data": "ctl:cleanup:5000"}, {"text": "♾ پاکسازی کامل", "callback_data": "ctl:q:cleanup_full"}])
        rows.extend([
            [{"text": "👋 خوشامد روشن", "callback_data": "ctl:q:welcome_on"}, {"text": "🔕 خوشامد خاموش", "callback_data": "ctl:q:welcome_off"}],
            [{"text": "🗣 سخنگو روشن", "callback_data": "ctl:q:speaker_on"}, {"text": "🤐 سخنگو خاموش", "callback_data": "ctl:q:speaker_off"}],
        ])
        if rank >= 1:
            rows.extend([
                [{"text": "🧽 فیلتر محتوا", "callback_data": "ctl:q:content_filter_help"}, {"text": "⏱ پاکسازی زمان‌بندی", "callback_data": "ctl:q:schedule_status"}],
                [{"text": "😄 Funny", "callback_data": "ctl:q:speaker_funny"}, {"text": "🎭 Anime", "callback_data": "ctl:q:speaker_anime"}],
            ])
        if rank >= 2:
            rows.extend([
                [{"text": "📊 گزارش امروز", "callback_data": "ctl:q:report_today"}, {"text": "🧾 Admin Audit", "callback_data": "ctl:q:admin_audit"}],
                [{"text": "💾 بکاپ", "callback_data": "ctl:q:backup_now"}, {"text": "📦 وضعیت بکاپ", "callback_data": "ctl:q:backup_status"}],
                [{"text": "🛡 Anti-Raid روشن", "callback_data": "ctl:q:raid_on"}, {"text": "🔕 Anti-Raid خاموش", "callback_data": "ctl:q:raid_off"}],
                [{"text": "🧠 AI روشن", "callback_data": "ctl:q:ai_on"}, {"text": "🧠 AI خاموش", "callback_data": "ctl:q:ai_off"}],
                [{"text": "👤 پرونده کاربر", "callback_data": "ctl:q:dossier_help"}, {"text": "🖼 رسانه خوشامد", "callback_data": "ctl:q:welcome_media_help"}],
            ])
        if rank >= 3:
            rows.extend([
                [{"text": "📈 گزارش هفتگی", "callback_data": "ctl:q:report_week"}, {"text": "🩺 سلامت گروه", "callback_data": "ctl:q:group_health"}],
                [{"text": "🧠 Auto Mod روشن", "callback_data": "ctl:q:auto_mod_on"}, {"text": "🧠 Auto Mod خاموش", "callback_data": "ctl:q:auto_mod_off"}],
                [{"text": "♻️ Auto Backup", "callback_data": "ctl:q:auto_backup_on"}, {"text": "👁 Watch List", "callback_data": "ctl:q:watch_status"}],
            ])
        rows.extend([
            [{"text": "✨ امکانات فعال این گروه", "callback_data": "ctl:features"}, {"text": "💎 ارتقای پلن", "callback_data": f"prem:g:{int(active.get('group_id') or 0)}"}],
            [{"text": "🧱 لیست قفل‌ها", "callback_data": "ctl:q:locks"}, {"text": "⌨️ فرمان آزاد", "callback_data": "ctl:raw"}],
            [{"text": "🔁 تغییر گروه", "callback_data": "bridge:groups"}, {"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
        ])
        return {"inline_keyboard": rows}

    def _plan_features_text(self, user_id: str) -> str:
        active = self._active_group(user_id)
        if active is None:
            return "گروه فعالی انتخاب نشده."
        state = self._active_plan_state(user_id)
        plan = str(state.get("plan") or "free")
        cfg = PLAN_UX[plan]
        lines = [
            f"{cfg['emoji']} امکانات فعال همین گروه",
            "━━━━━━━━━━━━━━━━━━",
            f"🏷 {active.get('title') or active.get('group_id')}",
            f"💎 پلن: {cfg['label']}",
            f"📝 {cfg['summary']}",
            "",
        ]
        lines.extend(f"• {item}" for item in cfg["features"])
        lines.extend(["", "تمام دکمه‌های پنل مدیریت براساس همین پلن ساخته می‌شن؛ قابلیت قفل‌شده داخل مدیریت این گروه نمایش داده نمی‌شه."])
        return "\n".join(lines)

    def _send_plan_features(self, user_id: str, chat_id: str) -> str:
        text = self._plan_features_text(user_id)
        self._send(chat_id, text, reply_markup=self._group_control_menu(user_id))
        return text

    def _send_premium_tools_menu(self, user_id: str, chat_id: str) -> str:
        # Compatibility route: Official16 merged the old premium center into the
        # active group's dynamic management panel.
        return self._send_control_panel(user_id, chat_id)

    def _main_menu_for(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        rows = [list(row) for row in MAIN_MENU.get("inline_keyboard", [])]
        if user_id is not None and self._is_owner(str(user_id)):
            rows.insert(0, [{"text": "👑 پنل ادمین ZIVO", "callback_data": "admin:home"}])
        return {"inline_keyboard": rows}

    def _admin_home(self, user_id: str, chat_id: str) -> str:
        if not self._is_owner(user_id):
            return "این بخش فقط برای مالک اصلی ZIVO است."
        text = (
            "👑 پنل ادمین ZIVO\n━━━━━━━━━━━━━━━━━━\n"
            "📣 تبلیغات و اطلاع‌رسانی\n"
            "ارسال به کاربران بات رسمی یا پیوی‌های واقعی main/acc2/acc3 با صف Campaign، Dedup و Rate Limit.\n\n"
            "👥 مخاطبان\n"
            "آمار کاربران بات و پیوی‌های شناخته‌شده هر اکانت.\n\n"
            "🔄 اسکن پیوی‌ها\n"
            "Full Dialog Inventory تمام پیوی‌های عادی و آرشیوشده را بدون سقف ثابت به‌روزرسانی می‌کند."
        )
        markup={"inline_keyboard":[
            [{"text":"📣 تبلیغات","callback_data":"admin:ads"},{"text":"👥 مخاطبان","callback_data":"admin:audience"}],
            [{"text":"🔄 اسکن کامل پیوی‌ها","callback_data":"admin:inventory"},{"text":"📊 وضعیت ارسال","callback_data":"admin:status"}],
            [{"text":"🏠 پنل اصلی","callback_data":"menu:home"}],
        ]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _admin_audience(self, user_id: str, chat_id: str) -> str:
        try:
            result=self._ipc("main",{"op":"official_admin","action":"audience","requester_user_id":int(user_id)},timeout=8.0)
        except Exception as exc:
            result={"ok":False,"error":f"{type(exc).__name__}: {exc}"}
        if not result.get("ok"):
            text=f"❌ دریافت آمار مخاطبان ناموفق بود: {result.get('error') or 'FAILED'}"
        else:
            official=dict(result.get("official") or {}); network=dict(result.get("account_network") or {})
            lines=["👥 مخاطبان ZIVO","━━━━━━━━━━━━━━━━━━",
                   f"🤖 کاربران بات رسمی: {int(official.get('enabled') or 0):,}",
                   f"💬 پیوی‌های اکانت‌های ZIVO: {int(network.get('private_enabled') or 0):,}",
                   f"🚫 انصراف از تبلیغات: {int(network.get('private_disabled') or 0)+int(official.get('disabled') or 0):,}",
                   f"📡 Campaign فعال: {int(result.get('active_campaigns') or 0)}",""]
            for row in result.get("accounts") or []:
                lines.append(f"• {row.get('account_key')}: {int(row.get('private_count') or 0):,} پیوی · {int(row.get('groups_count') or 0):,} گروه · {row.get('status') or '-'}")
            lines.append("\nℹ️ ارسال پیوی اکانت‌ها هنگام شروع Campaign دوباره Live Dialog Scan می‌شود؛ بنابراین فقط به عدد Cache تکیه نمی‌کند.")
            text="\n".join(lines)
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"🔄 اسکن کامل پیوی‌ها","callback_data":"admin:inventory"}],[{"text":"📣 تبلیغات","callback_data":"admin:ads"},{"text":"↩️ ادمین","callback_data":"admin:home"}]]}); return text

    def _admin_ads_menu(self, user_id: str, chat_id: str) -> str:
        text=("📣 تبلیغات ZIVO\n━━━━━━━━━━━━━━━━━━\nمقصد ارسال را انتخاب کن.\n\n🤖 کاربران بات رسمی: فقط افرادی که قبلاً پیوی Official را باز کرده‌اند.\n💬 پیوی اکانت‌ها: Full Dialog Scan روی main/acc2/acc3، با حذف Bot/Deleted، Dedup و رعایت انصراف تبلیغات.\n🌐 هر دو: هر دو مسیر هم‌زمان اجرا می‌شوند.")
        markup={"inline_keyboard":[
            [{"text":"🤖 کاربران بات رسمی","callback_data":"admin:adscope:official"}],
            [{"text":"💬 پیوی اکانت‌های ZIVO","callback_data":"admin:adscope:accounts"}],
            [{"text":"🌐 هر دو مسیر","callback_data":"admin:adscope:all"}],
            [{"text":"↩️ پنل ادمین","callback_data":"admin:home"}],
        ]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _admin_begin_ad(self, user_id: str, chat_id: str, scope: str) -> str:
        self._admin_state[str(user_id)]={"stage":"ad_text","scope":scope}
        text="✍️ متن تبلیغ یا اطلاعیه را بفرست.\n\nبعد از دریافت، پیش‌نمایش و دکمه تأیید نمایش داده می‌شود.\nحداکثر 3500 کاراکتر."
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"❌ لغو","callback_data":"admin:home"}]]}); return text

    def _admin_ad_preview(self, user_id: str, chat_id: str, body: str) -> str:
        state=self._admin_state.setdefault(str(user_id),{})
        state.update({"stage":"ad_confirm","text":body[:3500]})
        scope=state.get("scope") or "official"
        label={"official":"کاربران بات رسمی","accounts":"پیوی اکانت‌های ZIVO","all":"هر دو مسیر"}.get(scope,scope)
        text=f"📣 پیش‌نمایش ارسال\n━━━━━━━━━━━━━━━━━━\n🎯 مقصد: {label}\n\n{body[:3000]}\n\nاگر متن درسته تأیید کن."
        markup={"inline_keyboard":[[{"text":"✅ شروع ارسال","callback_data":"admin:adsend"}],[{"text":"✏️ ویرایش متن","callback_data":f"admin:adscope:{scope}"},{"text":"❌ لغو","callback_data":"admin:home"}]]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _official_broadcast_worker(self, user_ids: List[int], body: str) -> None:
        with self._official_campaign_lock:
            self._official_campaign={"running":True,"sent":0,"failed":0,"total":len(user_ids),"started_at":time.time()}
        for uid in user_ids:
            try:
                if self.transport is None:
                    raise RuntimeError("TRANSPORT_UNAVAILABLE")
                self.transport.send_text(str(uid),body[:3900])
                with self._official_campaign_lock: self._official_campaign["sent"]+=1
            except Exception:
                with self._official_campaign_lock: self._official_campaign["failed"]+=1
            time.sleep(0.12)
        with self._official_campaign_lock: self._official_campaign["running"]=False

    def _admin_send_ad(self, user_id: str, chat_id: str) -> str:
        state=dict(self._admin_state.get(str(user_id)) or {})
        body=str(state.get("text") or "").strip(); scope=str(state.get("scope") or "official")
        if not body:
            return self._admin_ads_menu(user_id,chat_id)
        pieces=[]
        if scope in {"accounts","all"}:
            try:
                result=self._ipc("main",{"op":"official_admin","action":"campaign_create","requester_user_id":int(user_id),"text":body},timeout=8.0)
            except Exception as exc:
                result={"ok":False,"error":f"{type(exc).__name__}: {exc}"}
            if result.get("ok"):
                state["batch_id"]=str(result.get("batch_id") or ""); pieces.append(f"💬 صف پیوی اکانت‌ها ساخته شد · {len(result.get('job_ids') or [])} Worker")
            else:
                pieces.append(f"❌ صف پیوی اکانت‌ها: {result.get('error') or 'FAILED'}")
        if scope in {"official","all"}:
            try:
                result=self._ipc("main",{"op":"official_admin","action":"official_users","requester_user_id":int(user_id)},timeout=8.0)
                ids=[int(x) for x in result.get("user_ids") or [] if int(x)>0] if result.get("ok") else []
            except Exception:
                ids=[]
            if ids:
                threading.Thread(target=self._official_broadcast_worker,args=(ids,body),daemon=True,name="zivo-official17-broadcast").start()
                pieces.append(f"🤖 ارسال بات رسمی شروع شد · {len(ids):,} مخاطب")
            else:
                pieces.append("🤖 کاربر واجد ارسال در بات رسمی پیدا نشد")
        self._admin_state[str(user_id)]=state
        text="✅ کمپین ثبت شد\n━━━━━━━━━━━━━━━━━━\n"+"\n".join(pieces)+"\n\nاز «📊 وضعیت ارسال» پیشرفت را ببین."
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"📊 وضعیت ارسال","callback_data":"admin:status"}],[{"text":"👑 پنل ادمین","callback_data":"admin:home"}]]}); return text

    def _admin_campaign_status(self, user_id: str, chat_id: str) -> str:
        state=self._admin_state.get(str(user_id)) or {}; batch_id=str(state.get("batch_id") or "")
        with self._official_campaign_lock: local=dict(self._official_campaign)
        lines=["📊 وضعیت ارسال ZIVO","━━━━━━━━━━━━━━━━━━",f"🤖 بات رسمی: {'در حال ارسال' if local.get('running') else 'آماده'} · موفق {int(local.get('sent') or 0):,} · ناموفق {int(local.get('failed') or 0):,} · کل {int(local.get('total') or 0):,}"]
        if batch_id:
            try: result=self._ipc("main",{"op":"official_admin","action":"campaign_status","requester_user_id":int(user_id),"batch_id":batch_id},timeout=8.0)
            except Exception: result={"ok":False}
            if result.get("ok"):
                jobs=result.get("jobs") or []; lines.append("\n💬 پیوی اکانت‌ها:")
                for row in jobs:
                    lines.append(f"• {row.get('account_key')} · {row.get('status')} · {int(row.get('success_count') or 0):,}/{int(row.get('total_targets') or 0):,} · خطا {int(row.get('failure_count') or 0):,}")
        text="\n".join(lines)
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"🔄 بروزرسانی","callback_data":"admin:status"}],[{"text":"👑 پنل ادمین","callback_data":"admin:home"}]]}); return text

    def _send_main_menu(self, chat_id: str, user_id: Optional[str] = None) -> str:
        text = (
            "⚡ ZIVO | مدیریت هوشمند گروه‌های سروش+\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "ZIVO ساخته شده تا مدیریت گروه از چندین فرمان پراکنده تبدیل بشه به یک پنل تمیز، سریع و قابل‌فهم.\n\n"
            "🛡 امنیت و مدیریت\n"
            "قفل‌ها، ضداسپم، فیلتر، اخطار، سکوت، بن و پاکسازی\n\n"
            "🤖 هوشمندسازی\n"
            "سخنگو، AI، گزارش، Backup، Anti-Raid و Auto Moderation\n\n"
            "🎮 جامعه و اقتصاد\n"
            "سرگرمی، Meow، Pet و House\n\n"
            "💎 هر گروه پلن خودش رو داره\n"
            "وقتی SILVER / GOLD / DIAMOND برای یک گروه فعال می‌کنی، قابلیت‌های جدید مستقیماً به «🎛 مدیریت گروه» همان گروه اضافه می‌شن؛ پنل جداگانه و گیج‌کننده‌ای وجود نداره.\n\n"
            "🔗 گروه جدید داری؟ «اتصال گروه»\n"
            "📂 قبلاً وصلش کردی؟ «گروه‌های من»"
        )
        self._send(chat_id, text, reply_markup=self._main_menu_for(user_id))
        return text

    def _send_fun_menu(self, chat_id: str) -> str:
        text = "🎮 سرگرمی ZIVO\n━━━━━━━━━━━━━━━━━━\nیه گزینه انتخاب کن 👇"
        self._send(chat_id, text, reply_markup=FUN_MENU)
        return text

    def _send_tools_menu(self, chat_id: str) -> str:
        text = "🧰 ابزارهای ZIVO\n━━━━━━━━━━━━━━━━━━\nابزار موردنظرت رو انتخاب کن 👇"
        self._send(chat_id, text, reply_markup=TOOLS_MENU)
        return text

    def _send_economy_menu(self, chat_id: str) -> str:
        text = "🐾 دنیای میو ZIVO\n━━━━━━━━━━━━━━━━━━\nموجودی، پت و خونه‌هات از همین‌جا 👇"
        self._send(chat_id, text, reply_markup=ECONOMY_MENU)
        return text

    @staticmethod
    def _ipc(account_key: str, payload: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Any]:
        return ipc_request(account_key, payload, timeout=timeout)

    @staticmethod
    def _speed_label(latency_ms: float, rank: int = 0) -> str:
        if rank == 0:
            return "⚡ سریع‌ترین پیشنهاد ZIVO"
        if latency_ms <= 8:
            return "🚀 فوق‌سریع"
        if latency_ms <= 20:
            return "⚡ خیلی سریع"
        if latency_ms <= 60:
            return "✅ سریع"
        return "🟢 آماده"

    def _account_rows(self) -> list[Dict[str, Any]]:
        rows: list[Dict[str, Any]] = []
        for key in IPC_ACCOUNT_KEYS:
            started = time.monotonic()
            try:
                data = self._ipc(key, {"op": "status"}, timeout=1.5)
            except Exception as exc:
                log.info("account socket offline | account=%s | %s: %s", key, type(exc).__name__, exc)
                continue
            latency_ms = round((time.monotonic() - started) * 1000.0, 1)
            if not data.get("ok"):
                continue
            rows.append({
                "account_key": str(data.get("account_key") or key),
                "label": str(data.get("account_label") or key),
                "enabled": 1 if data.get("enabled") else 0,
                "self_id": int(data.get("self_id") or 0),
                "status": "online" if data.get("connected") else "offline",
                "last_heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "groups_count": int(data.get("groups_count") or 0),
                "socket": str(ipc_socket_path(key)),
                "latency_ms": latency_ms,
            })
        rows.sort(key=lambda r: (0 if int(r.get("enabled") or 0) and r.get("status") == "online" and int(r.get("self_id") or 0) > 0 else 1, float(r.get("latency_ms") or 99999)))
        for idx, row in enumerate(rows):
            row["speed_label"] = self._speed_label(float(row.get("latency_ms") or 99999), idx)
            row["recommended"] = idx == 0 and int(row.get("enabled") or 0) and row.get("status") == "online" and int(row.get("self_id") or 0) > 0
        return rows

    def _account_status_text(self, *, detailed: bool = False) -> str:
        rows = self._account_rows()
        if not rows:
            return "🔴 هیچ اکانت اجرایی ZIVO در دسترس نیست. سرویس‌های main / acc2 / acc3 را بررسی کن."
        usable = [r for r in rows if int(r.get("enabled") or 0) and r.get("status") == "online" and int(r.get("self_id") or 0) > 0]
        if not usable:
            return "🟠 اکانت‌ها پاسخ می‌دهند اما هیچ‌کدام الان آماده Join نیستند."
        best = usable[0]
        lines = [
            "⚡ وضعیت اکانت‌های اجرایی",
            "━━━━━━━━━━━━━━━━━━",
            f"پیشنهاد ZIVO: {best['label']} ({best['account_key']})",
            f"سرعت پاسخ داخلی: {best['latency_ms']} ms",
            "",
        ]
        for idx, row in enumerate(usable):
            lines.append(f"{'🥇' if idx == 0 else '•'} {row['label']} ({row['account_key']}) — {self._speed_label(float(row.get('latency_ms') or 99999), idx)} — {row['latency_ms']} ms")
        if detailed:
            lines.append("")
            lines.append("🔧 جزئیات فنی فقط برای مالک نمایش داده شد؛ تعداد گروه‌ها در رابط کاربر نمایش داده نمی‌شود.")
        return "\n".join(lines)

    def _persist_managed_group(self, *, user_id: str, group_id: int, account_key: str, title: str, member_count: int) -> None:
        gid = int(group_id or 0)
        if gid <= 0:
            return
        self.store.add_managed_group(
            user_id=str(user_id), group_id=gid, account_key=str(account_key or "main"),
            title=str(title or ""), member_count=int(member_count if member_count is not None else -1),
        )
        try:
            self._ipc("main", {
                "op": "official_group_access", "action": "add",
                "requester_user_id": int(user_id), "group_id": gid,
                "account_key": str(account_key or "main"), "title": str(title or ""),
                "member_count": int(member_count if member_count is not None else -1),
            }, timeout=5.0)
        except Exception as exc:
            log.warning("official managed-group persist deferred | user=%s group=%s account=%s | %s: %s", user_id, gid, account_key, type(exc).__name__, exc)

    def _managed_rows_for_user(self, user_id: str) -> list[Dict[str, Any]]:
        uid = int(user_id or 0)
        owner = self._is_owner(user_id)
        merged: Dict[int, Dict[str, Any]] = {}

        # First restore groups explicitly granted/claimed through the Official bot.
        # This survives Official restarts because the authoritative mapping lives
        # in the shared Account Core DB, not only in Official's local UI cache.
        try:
            persisted = self._ipc("main", {
                "op": "official_group_access", "action": "list",
                "requester_user_id": uid,
            }, timeout=4.0)
        except Exception:
            persisted = {}
        for item in persisted.get("groups") or []:
            if not isinstance(item, dict):
                continue
            gid = int(item.get("group_id") or 0)
            if gid <= 0:
                continue
            merged[gid] = {
                "user_id": str(user_id), "group_id": gid,
                "account_key": str(item.get("account_key") or "main"),
                "title": str(item.get("title") or ""),
                "member_count": int(item.get("member_count") if item.get("member_count") is not None else -1),
            }

        # Reconcile live/installed groups exposed by every execution account.
        for key in IPC_ACCOUNT_KEYS:
            try:
                data = self._ipc(key, {"op": "groups", "requester_user_id": uid, "owner_override": owner}, timeout=2.5)
            except Exception:
                continue
            for item in data.get("groups") or []:
                if not isinstance(item, dict):
                    continue
                gid = int(item.get("group_id") or 0)
                if gid <= 0:
                    continue
                row = {
                    "user_id": str(user_id), "group_id": gid,
                    "account_key": str(item.get("account_key") or key),
                    "title": str(item.get("title") or ""),
                    "member_count": int(item.get("member_count") if item.get("member_count") is not None else -1),
                }
                merged[gid] = row
                self._persist_managed_group(
                    user_id=str(user_id), group_id=gid, account_key=row["account_key"],
                    title=row["title"], member_count=row["member_count"],
                )

        # Local cache is a last-resort UI fallback if the IPC was temporarily down.
        for item in self.store.managed_groups(str(user_id)):
            gid = int(item["group_id"] or 0)
            if gid <= 0 or gid in merged:
                continue
            merged[gid] = {
                "user_id": str(user_id), "group_id": gid,
                "account_key": str(item["account_key"] or "main"),
                "title": str(item["title"] or ""),
                "member_count": int(item["member_count"] if item["member_count"] is not None else -1),
            }
        return list(merged.values())

    def _my_groups_text(self, user_id: str) -> str:
        rows = self._managed_rows_for_user(user_id)
        if not rows:
            return (
                "🧩 گروه‌های من\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "هنوز گروهی به پنلت وصل نشده.\n\n"
                "از «🔗 اتصال گروه» شروع کن؛ قبل از Join مشخصات گروه را بهت نشان می‌دهم."
            )
        state = self.store.control_state(user_id)
        active = int(state.get("active_group_id") or 0)
        lines = ["🧩 گروه‌های قابل کنترل", "━━━━━━━━━━━━━━━━━━"]
        for row in rows[:30]:
            gid = int(row["group_id"])
            marker = "  ✅ فعال" if gid == active else ""
            lines.append(f"• {row['title'] or 'بدون نام'}{marker}")
        lines.extend(["", "👇 گروه موردنظرت را از دکمه‌ها انتخاب کن."])
        return "\n".join(lines)

    def _groups_menu(self, user_id: str) -> Dict[str, Any]:
        rows = self._managed_rows_for_user(user_id)
        keyboard: list[list[Dict[str, str]]] = []
        for row in rows[:20]:
            gid = int(row["group_id"] or 0)
            if gid <= 0:
                continue
            title = str(row["title"] or f"گروه {gid}")[:30]
            keyboard.append([{"text": f"🎛 {title}", "callback_data": f"ctl:group:{gid}"}])
        keyboard.append([{"text": "🔗 اتصال گروه جدید", "callback_data": "bridge:join"}])
        keyboard.append([{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}])
        return {"inline_keyboard": keyboard}

    def _send_groups_menu(self, user_id: str, chat_id: str) -> str:
        text = self._my_groups_text(user_id)
        self._send(chat_id, text, reply_markup=self._groups_menu(user_id))
        return text

    @staticmethod
    def _full_group_link(kind: str, value: str) -> str:
        if str(kind) == "invite":
            return f"https://splus.ir/joingroup/{str(value).strip()}"
        return f"https://splus.ir/{str(value).strip().lstrip('@')}"

    def _account_selection_markup(self, request_id: int, candidates: list[Dict[str, Any]]) -> Dict[str, Any]:
        keyboard: list[list[Dict[str, str]]] = []
        for idx, row in enumerate(candidates[:12]):
            key = str(row.get("account_key") or "").strip().lower()
            if not key:
                continue
            label = str(row.get("label") or key)
            latency = float(row.get("latency_ms") or 0)
            badge = "🥇" if idx == 0 else "⚡"
            keyboard.append([
                {"text": f"{badge} {label} · {latency:g} ms", "callback_data": f"bridge:pick:{int(request_id)}:{key}"}
            ])
        keyboard.append([{"text": "↩️ برگشت به پیش‌نمایش", "callback_data": f"bridge:preview:{int(request_id)}"}])
        keyboard.append([{"text": "❌ لغو اتصال", "callback_data": f"bridge:cancel:{int(request_id)}"}])
        return {"inline_keyboard": keyboard}

    def _group_preview_markup(self, request_id: int) -> Dict[str, Any]:
        return {"inline_keyboard": [
            [{"text": "✅ تأیید اتصال", "callback_data": f"bridge:confirm:{int(request_id)}"}],
            [{"text": "⚡ تغییر اکانت", "callback_data": f"bridge:accounts:{int(request_id)}"}, {"text": "❌ لغو", "callback_data": f"bridge:cancel:{int(request_id)}"}],
            [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
        ]}

    def _group_preview_text(self, pending: sqlite3.Row) -> str:
        title = str(pending["preview_title"] or "اطلاعات نامشخص")
        about = str(pending["preview_about"] or "تنظیم نشده").strip()
        if len(about) > 420:
            about = about[:417] + "..."
        members = int(pending["preview_member_count"] or -1)
        count_text = f"{members:,}" if members >= 0 else "دریافت نشد"
        account = str(pending["selected_account"] or "—")
        latency = float(pending["preview_latency_ms"] or 0)
        link = self._full_group_link(str(pending["link_kind"]), str(pending["link_value"]))
        return (
            "🔎 گروه شناسایی شد\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🏷 نام: {title}\n"
            f"👥 اعضا: {count_text}\n"
            f"📝 بیو: {about}\n"
            f"🔗 لینک: {link}\n\n"
            f"⚡ اکانت پیشنهادی: {account}\n"
            f"⏱ پاسخ داخلی: {latency:g} ms\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "اگر همین گروه است، «✅ تأیید اتصال» را بزن.\n"
            "تا قبل از تأیید، هیچ اکانتی عضو گروه نمی‌شود."
        )

    def _existing_group_markup(self, request_id: int) -> Dict[str, Any]:
        return {"inline_keyboard": [
            [{"text": "🔄 بررسی دسترسی من", "callback_data": f"bridge:claim:{int(request_id)}"}],
            [{"text": "❌ لغو", "callback_data": f"bridge:cancel:{int(request_id)}"}, {"text": "🏠 پنل", "callback_data": "menu:home"}],
        ]}

    def _register_existing_group(self, *, user_id: str, chat_id: str, account_key: str, probe: Dict[str, Any]) -> str:
        gid = int(probe.get("group_id") or 0)
        title = str(probe.get("title") or f"گروه {gid}")
        count = int(probe.get("member_count") if probe.get("member_count") is not None else -1)
        self._persist_managed_group(user_id=user_id, group_id=gid, account_key=account_key, title=title, member_count=count)
        self.store.set_control_state(user_id, active_group_id=gid, mode="")
        text = (
            "✅ این گروه از قبل به ZIVO متصل بود\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🏷 {title}\n"
            + (f"👥 {count:,} عضو\n" if count >= 0 else "")
            + f"🤖 اکانت اجرایی موجود: {account_key}\n\n"
            "ZIVO اکانت جدیدی وارد گروه نکرد. همان اکانتی که از قبل داخل گروه بود به پنل تو اضافه شد.\n"
            "از همین حالا می‌تونی گروه رو کنترل کنی یا براش اشتراک بخری."
        )
        self._send(chat_id, text, reply_markup={"inline_keyboard": [
            [{"text": "🎛 کنترل همین گروه", "callback_data": "ctl:current"}, {"text": "💎 خرید اشتراک", "callback_data": f"prem:g:{gid}"}],
            [{"text": "✨ تفاوت پلن‌ها", "callback_data": "menu:capabilities"}],
            [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
        ]})
        return text

    def _begin_group_link(self, message: IncomingMessage, kind: str, value: str) -> str:
        if message.chat_id != message.sender_id:
            text = "🔐 برای امنیت، لینک گروه را فقط در پیوی همین بات بفرست."
            self._send(message.chat_id, text)
            return text
        candidates = [row for row in self._account_rows() if int(row.get("enabled") or 0) and row.get("status") == "online" and int(row.get("self_id") or 0) > 0]
        if not candidates:
            text = "🔴 الان هیچ اکانت اجرایی آماده اتصال نیست. چند لحظه بعد دوباره امتحان کن."
            self._send(message.chat_id, text, reply_markup=MAIN_MENU)
            return text

        probes: list[tuple[Dict[str, Any], Dict[str, Any]]] = []
        for row in candidates:
            try:
                probe = self._ipc(str(row["account_key"]), {
                    "op": "inspect_link", "link_kind": kind, "link_value": value,
                    "requester_user_id": int(message.sender_id),
                }, timeout=12.0)
            except Exception:
                continue
            if probe.get("ok"):
                probes.append((row, probe))

        # Rule 96.46: if ANY ZIVO account is already inside this group, never
        # join a second account. Reuse the existing account instead.
        existing = next(((row, probe) for row, probe in probes if probe.get("already_member") and probe.get("requester_can_control")), None)
        if existing is not None:
            row, probe = existing
            return self._register_existing_group(
                user_id=message.sender_id, chat_id=message.chat_id,
                account_key=str(row.get("account_key") or "main"), probe=probe,
            )

        existing_unverified = next(((row, probe) for row, probe in probes if probe.get("already_member")), None)
        if existing_unverified is not None:
            row, probe = existing_unverified
            request_id = self.store.create_pending_group_link(
                user_id=message.sender_id, chat_id=message.chat_id, link_kind=kind, link_value=value,
                selected_account=str(row.get("account_key") or "main"),
                preview_title=str(probe.get("title") or "گروه"), preview_about=str(probe.get("about") or ""),
                preview_member_count=int(probe.get("member_count") if probe.get("member_count") is not None else -1),
                preview_group_id=int(probe.get("group_id") or 0), preview_latency_ms=float(row.get("latency_ms") or 0),
            )
            self.store.update_pending_group_link(request_id, status="existing_unverified")
            text = (
                "ℹ️ ZIVO از قبل داخل این گروه است\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🏷 {probe.get('title') or 'گروه'}\n"
                f"🤖 اکانت موجود: {row.get('account_key')}\n\n"
                "برای جلوگیری از ورود چند اکانت، اکانت دیگری Join نمی‌شود.\n"
                "اما هنوز مالک/ادمین بودن حساب شما برای کنترل این گروه از سروش تأیید نشده.\n\n"
                "اگر مالک یا ادمین گروه هستی، چند ثانیه صبر کن و «🔄 بررسی دسترسی من» را بزن."
            )
            self._send(message.chat_id, text, reply_markup=self._existing_group_markup(request_id))
            return text

        inspect_result: Dict[str, Any] = probes[0][1] if probes else {}
        inspect_account = probes[0][0] if probes else candidates[0]
        request_id = self.store.create_pending_group_link(
            user_id=message.sender_id,
            chat_id=message.chat_id,
            link_kind=kind,
            link_value=value,
            selected_account=str(inspect_account.get("account_key") or candidates[0]["account_key"]),
            preview_title=str(inspect_result.get("title") or "اطلاعات پیش از عضویت محدود است"),
            preview_about=str(inspect_result.get("about") or ""),
            preview_member_count=int(inspect_result.get("member_count") if inspect_result.get("member_count") is not None else -1),
            preview_group_id=int(inspect_result.get("group_id") or 0),
            preview_latency_ms=float(inspect_account.get("latency_ms") or 0),
        )
        pending = self.store.pending_group_link(request_id, message.sender_id)
        assert pending is not None
        text = self._group_preview_text(pending)
        if not inspect_result.get("ok"):
            text += "\n\nℹ️ سروش جزئیات این لینک خصوصی را قبل از عضویت محدود کرده؛ خود لینک قابل تأیید است."
        self._send(message.chat_id, text, reply_markup=self._group_preview_markup(request_id))
        log.info("official group preview | request=%s user=%s kind=%s account=%s inspect_ok=%s", request_id, message.sender_id, kind, pending["selected_account"], bool(inspect_result.get("ok")))
        return text

    def _claim_existing_group(self, callback: IncomingCallback, request_id: int) -> str:
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        if pending is None or str(pending["status"] or "") != "existing_unverified":
            text = "⌛ این بررسی دیگر فعال نیست؛ لینک گروه را دوباره بفرست."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        key = str(pending["selected_account"] or "main")
        try:
            probe = self._ipc(key, {
                "op": "inspect_link", "link_kind": str(pending["link_kind"]), "link_value": str(pending["link_value"]),
                "requester_user_id": int(callback.sender_id),
            }, timeout=15.0)
        except Exception:
            probe = {}
        if probe.get("ok") and probe.get("already_member") and probe.get("requester_can_control"):
            self.store.update_pending_group_link(request_id, status="claimed")
            return self._register_existing_group(user_id=callback.sender_id, chat_id=callback.chat_id, account_key=key, probe=probe)
        text = (
            "⛔ هنوز دسترسی مدیریتی شما تأیید نشد.\n"
            "اگر همین الان ادمین شدی یا دسترسی‌ها تغییر کرده، چند ثانیه صبر کن و دوباره بررسی کن.\n"
            "ZIVO برای امنیت، تا تأیید مالک/ادمین بودن کنترل گروه را واگذار نمی‌کند."
        )
        self._send(callback.chat_id, text, reply_markup=self._existing_group_markup(request_id))
        return text

    def _show_group_preview(self, callback: IncomingCallback, request_id: int) -> str:
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        if pending is None or str(pending["status"] or "") not in {"waiting_confirm", "waiting_account"}:
            text = "⌛ این درخواست دیگر فعال نیست. لینک را دوباره بفرست."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        self.store.update_pending_group_link(request_id, status="waiting_confirm")
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        assert pending is not None
        text = self._group_preview_text(pending)
        self._send(callback.chat_id, text, reply_markup=self._group_preview_markup(request_id))
        return text

    def _show_account_choices(self, callback: IncomingCallback, request_id: int) -> str:
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        if pending is None or str(pending["status"] or "") not in {"waiting_confirm", "waiting_account"}:
            text = "⌛ درخواست اتصال منقضی شده."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        candidates = [row for row in self._account_rows() if int(row.get("enabled") or 0) and row.get("status") == "online" and int(row.get("self_id") or 0) > 0]
        if not candidates:
            text = "🔴 هیچ اکانت آماده‌ای پیدا نشد."
            self._send(callback.chat_id, text, reply_markup=self._group_preview_markup(request_id))
            return text
        self.store.update_pending_group_link(request_id, status="waiting_account")
        lines = [
            "⚡ انتخاب اکانت اجرایی",
            "━━━━━━━━━━━━━━━━━━",
            "ZIVO سرعت پاسخ واقعی هر اکانت را اندازه گرفته.",
            "اکانت اول پیشنهاد خودکار ZIVO است.", "",
        ]
        for idx, row in enumerate(candidates):
            lines.append(f"{'🥇' if idx == 0 else '•'} {row['label']} ({row['account_key']}) — {row['latency_ms']} ms")
        text = "\n".join(lines)
        self._send(callback.chat_id, text, reply_markup=self._account_selection_markup(request_id, candidates))
        return text

    def _select_join_account(self, callback: IncomingCallback, request_id: int, account_key: str) -> str:
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        if pending is None or str(pending["status"] or "") not in {"waiting_confirm", "waiting_account"}:
            text = "⌛ این درخواست منقضی شده."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        key = str(account_key or "").strip().lower()
        rows = {str(r.get("account_key") or "").lower(): r for r in self._account_rows()}
        row = rows.get(key)
        if row is None or not int(row.get("enabled") or 0) or row.get("status") != "online":
            text = "🔴 این اکانت الان آماده نیست؛ یکی دیگر را انتخاب کن."
            self._send(callback.chat_id, text, reply_markup=self._account_selection_markup(request_id, list(rows.values())))
            return text
        self.store.update_pending_group_link(request_id, account_key=key, status="waiting_confirm")
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        assert pending is not None
        text = self._group_preview_text(pending).replace(f"⏱ پاسخ داخلی: {float(pending['preview_latency_ms'] or 0):g} ms", f"⏱ پاسخ داخلی فعلی: {float(row.get('latency_ms') or 0):g} ms")
        self._send(callback.chat_id, text, reply_markup=self._group_preview_markup(request_id))
        return text

    def _cancel_group_join(self, callback: IncomingCallback, request_id: int) -> str:
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        if pending is not None:
            self.store.update_pending_group_link(request_id, status="cancelled")
        text = "❌ اتصال لغو شد. هیچ اکانتی عضو گروه نشد."
        self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
        return text

    def _confirm_group_join(self, callback: IncomingCallback, request_id: int) -> str:
        pending = self.store.pending_group_link(request_id, callback.sender_id)
        if pending is None or str(pending["status"] or "") != "waiting_confirm":
            text = "⌛ این درخواست آماده تأیید نیست. لینک را دوباره بفرست."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        key = str(pending["selected_account"] or "").strip().lower()
        if not key:
            return self._show_account_choices(callback, request_id)
        self.store.update_pending_group_link(request_id, status="joining")
        title = str(pending["preview_title"] or "گروه")
        self._send(callback.chat_id, f"⏳ اتصال امن ZIVO در حال انجامه…\n━━━━━━━━━━━━━━━━━━\n🏷 گروه: {title}\n⚡ اکانت انتخاب‌شده: {key}\n\nدر حال تأیید عضویت، دسترسی ارسال و آماده‌سازی کنترل گروه هستم.", reply_markup={"inline_keyboard": [[{"text": "⏳ در حال اتصال…", "callback_data": "noop"}]]})
        started = time.monotonic()
        try:
            result = self._ipc(key, {
                "op": "join",
                "requester_user_id": int(callback.sender_id),
                "source_message_id": int(callback.message_id or 0),
                "link_kind": str(pending["link_kind"]),
                "link_value": str(pending["link_value"]),
            }, timeout=55.0)
        except Exception as exc:
            self.store.update_pending_group_link(request_id, status="waiting_confirm")
            text = f"❌ اتصال انجام نشد.\nجزئیات: {type(exc).__name__}: {exc}"
            self._send(callback.chat_id, text, reply_markup=self._group_preview_markup(request_id))
            return text
        elapsed = round((time.monotonic() - started) * 1000.0, 1)
        code = str(result.get("result_code") or result.get("status") or "failed")
        gid = int(result.get("group_id") or 0)
        joined_title = str(result.get("title") or title)
        count = int(result.get("member_count") or pending["preview_member_count"] or -1)
        can_manage = bool(result.get("joined_now")) or bool(result.get("requester_can_control"))
        if result.get("ok") and gid > 0 and can_manage:
            self.store.update_pending_group_link(request_id, status="joined")
            self._persist_managed_group(user_id=callback.sender_id, group_id=gid, account_key=key, title=joined_title, member_count=count)
            self.store.set_control_state(callback.sender_id, active_group_id=gid, mode="")
            if code == "joined_full":
                access = "✅ دسترسی کامل مدیریتی آماده است"
            elif code == "joined_basic":
                access = "🟡 اتصال انجام شد؛ برای بن/پین/سکوت، اکانت را ادمین کامل کن"
            elif code == "already":
                access = "ℹ️ اکانت از قبل داخل گروه بود"
            else:
                access = "✅ عضویت تأیید شد"
            text = (
                "🎉 اتصال ZIVO با موفقیت انجام شد\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🏷 {joined_title or gid}\n"
            )
            if count >= 0:
                text += f"👥 {count:,} عضو\n"
            text += f"⚡ اکانت اجرایی: {key}\n{access}\n⏱ زمان اتصال: {result.get('elapsed_ms', elapsed)} ms\n━━━━━━━━━━━━━━━━━━\nحالا می‌تونی کنترل گروه یا خرید اشتراک رو باز کنی."
            markup = {"inline_keyboard": [
                [{"text": "🎛 کنترل گروه", "callback_data": "ctl:current"}, {"text": "💎 خرید اشتراک", "callback_data": f"prem:g:{gid}"}],
                [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}],
            ]}
            self._send(callback.chat_id, text, reply_markup=markup)
            log.info("official direct join PASS | account=%s group=%s code=%s elapsed_ms=%s", key, gid, code, result.get("elapsed_ms", elapsed))
            return text
        if result.get("ok") and gid > 0 and not can_manage:
            self.store.update_pending_group_link(request_id, status="existing_unverified")
            text = (
                "🔐 این گروه از قبل به ZIVO متصل است\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🏷 {joined_title or gid}\n"
                f"🤖 اکانت موجود: {key}\n\n"
                "برای جلوگیری از ورود اکانت دوم، Join جدید انجام نشد.\n"
                "اما مالک/ادمین بودن حساب شما هنوز تأیید نشده؛ تا تأیید، گروه به پنل کنترل اضافه نمی‌شود."
            )
            self._send(callback.chat_id, text, reply_markup=self._existing_group_markup(request_id))
            return text
        self.store.update_pending_group_link(request_id, status="waiting_confirm")
        err = str(result.get("error") or "JOIN_FAILED")[:600]
        text = f"❌ عضویت انجام نشد.\nکد: {code}\nجزئیات: {err}\n⏱ {result.get('elapsed_ms', elapsed)} ms"
        self._send(callback.chat_id, text, reply_markup=self._group_preview_markup(request_id))
        return text

    def _active_group(self, user_id: str) -> Optional[Dict[str, Any]]:
        state = self.store.control_state(user_id)
        gid = int(state.get("active_group_id") or 0)
        if gid <= 0:
            return None
        row = self.store.managed_group(user_id, gid, owner_override=self._is_owner(user_id))
        if row is not None:
            return dict(row)
        for item in self._managed_rows_for_user(user_id):
            if int(item.get("group_id") or 0) == gid:
                return item
        return None

    def _control_panel_text(self, user_id: str) -> str:
        row = self._active_group(user_id)
        if row is None:
            return "گروه فعالی انتخاب نشده. اول «گروه‌های من» را باز و یک گروه انتخاب کن."
        state = self._active_plan_state(user_id)
        plan = str(state.get("plan") or "free")
        cfg = PLAN_UX[plan]
        cleanup_text = "بدون سقف پلنی" if not cfg.get("cleanup") else f"تا {int(cfg['cleanup']):,} پیام"
        meter = self._subscription_meter(dict(state.get("subscription") or {}))
        return (
            "🎛 مدیریت گروه\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🏷 {row['title'] or 'بدون نام'}\n"
            f"{cfg['emoji']} پلن فعال: {cfg['label']}\n"
            f"🧹 سقف پاکسازی: {cleanup_text}\n"
            f"⚡ اکانت اجرایی: {row['account_key']}\n"
            f"{meter}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "دکمه‌های پایین فقط قابلیت‌هایی هستن که همین الان برای این گروه فعالن. با ارتقای پلن، امکانات جدید همین‌جا اضافه می‌شن."
        )

    def _send_control_panel(self, user_id: str, chat_id: str) -> str:
        text = self._control_panel_text(user_id)
        markup = self._group_control_menu(user_id) if self._active_group(user_id) is not None else self._groups_menu(user_id)
        self._send(chat_id, text, reply_markup=markup)
        return text

    @staticmethod
    def _parse_remote_target(text: str) -> Tuple[str, int, int]:
        value = normalize_text(text)
        m = re.fullmatch(r"هدف\s+(\d+)\s*\|\s*(.+)", value, flags=re.DOTALL)
        if m:
            return str(m.group(2)).strip(), int(m.group(1)), 0
        m = re.fullmatch(r"پیام\s+(\d+)\s*\|\s*(.+)", value, flags=re.DOTALL)
        if m:
            return str(m.group(2)).strip(), 0, int(m.group(1))
        return value, 0, 0

    def _queue_remote_command(self, *, user_id: str, chat_id: str, command_text: str) -> str:
        row = self._active_group(user_id)
        if row is None:
            return "گروه فعالی انتخاب نشده. از «گروه‌های من» یک گروه انتخاب کن."
        command, target_user_id, target_message_id = self._parse_remote_target(command_text)
        if not command:
            return "فرمان خالی است."
        account = str(row["account_key"])
        started = time.monotonic()
        try:
            result = self._ipc(account, {
                "op": "control",
                "requester_user_id": int(user_id),
                "group_id": int(row["group_id"]),
                "command_text": command,
                "target_user_id": int(target_user_id),
                "target_message_id": int(target_message_id),
            }, timeout=35.0)
        except Exception as exc:
            log.warning("direct control socket failed | account=%s group=%s | %s: %s", account, row["group_id"], type(exc).__name__, exc)
            return f"اجرای مستقیم فرمان ناموفق بود: {type(exc).__name__}: {exc}"
        elapsed = result.get("elapsed_ms", round((time.monotonic() - started) * 1000.0, 1))
        if result.get("ok"):
            return f"اجرا شد.\nاکانت: {account}\nگروه: {int(row['group_id'])}\nنتیجه: {str(result.get('result_text') or 'OK')[:1500]}\nزمان: {elapsed} ms"
        code = str(result.get("result_code") or "FAILED")
        err = str(result.get("error") or result.get("result_text") or "اجرای فرمان ناموفق بود")[:900]
        return f"فرمان اجرا نشد.\nاکانت: {account}\nکد: {code}\nجزئیات: {err}\nزمان: {elapsed} ms"

    def poll_bridge_jobs(self, sender: Optional[SoroushOfficialTransport] = None) -> int:
        return 0

    def poll_remote_jobs(self, sender: Optional[SoroushOfficialTransport] = None) -> int:
        return 0

    def handle_callback(self, raw: Dict[str, Any]) -> Optional[str]:
        callback = normalize_callback(raw)
        if callback is None:
            return None
        data = callback.data.casefold()
        if self.transport is not None:
            self.transport.answer_callback(callback.callback_id)

        if data == "noop":
            return None

        if data == "gate:check":
            return self._check_membership_gate(callback.sender_id, callback.chat_id)
        if data.startswith("admin:"):
            if not self._is_owner(callback.sender_id):
                text="این بخش فقط برای مالک اصلی ZIVO است."; self._send(callback.chat_id,text); return text
            if data == "admin:home": return self._admin_home(callback.sender_id, callback.chat_id)
            if data == "admin:ads": return self._admin_ads_menu(callback.sender_id, callback.chat_id)
            if data == "admin:audience": return self._admin_audience(callback.sender_id, callback.chat_id)
            if data == "admin:inventory":
                result=self._ipc("main",{"op":"official_admin","action":"inventory_refresh","requester_user_id":int(callback.sender_id)},timeout=8.0)
                text="🔄 اسکن کامل پیوی‌ها درخواست شد.\nاکانت‌ها: "+", ".join(result.get("requested_accounts") or [])+"\n\nاسکن Low Priority است و بدون ایجاد فشار روی پیام‌های زنده انجام می‌شود." if result.get("ok") else f"❌ درخواست اسکن ناموفق: {result.get('error') or 'FAILED'}"
                self._send(callback.chat_id,text,reply_markup={"inline_keyboard":[[{"text":"👥 مخاطبان","callback_data":"admin:audience"}],[{"text":"👑 پنل ادمین","callback_data":"admin:home"}]]}); return text
            if data == "admin:status": return self._admin_campaign_status(callback.sender_id, callback.chat_id)
            m=re.fullmatch(r"admin:adscope:(official|accounts|all)",data)
            if m: return self._admin_begin_ad(callback.sender_id, callback.chat_id, m.group(1))
            if data == "admin:adsend": return self._admin_send_ad(callback.sender_id, callback.chat_id)
        if not self._is_owner(callback.sender_id) and self.store.gate_pending(callback.sender_id):
            return self._complete_soft_gate(callback.sender_id, callback.chat_id)

        m = re.fullmatch(r"bridge:claim:(\d+)", data)
        if m:
            return self._claim_existing_group(callback, int(m.group(1)))

        if data.startswith("bridge:pick:"):
            parts = callback.data.split(":", 3)
            if len(parts) == 4 and parts[2].isdigit():
                return self._select_join_account(callback, int(parts[2]), parts[3])
            return None
        m = re.fullmatch(r"bridge:confirm:(\d+)", data)
        if m:
            return self._confirm_group_join(callback, int(m.group(1)))
        m = re.fullmatch(r"bridge:accounts:(\d+)", data)
        if m:
            return self._show_account_choices(callback, int(m.group(1)))
        m = re.fullmatch(r"bridge:preview:(\d+)", data)
        if m:
            return self._show_group_preview(callback, int(m.group(1)))
        m = re.fullmatch(r"bridge:cancel:(\d+)", data)
        if m:
            return self._cancel_group_join(callback, int(m.group(1)))
        if data.startswith("ctl:group:"):
            try:
                gid = int(callback.data.rsplit(":", 1)[1])
            except Exception:
                return None
            row = next((item for item in self._managed_rows_for_user(callback.sender_id) if int(item.get("group_id") or 0) == gid), None)
            if row is None:
                text = "این گروه در پنل قابل کنترل تو ثبت نشده است."
                self._send(callback.chat_id, text, reply_markup=self._groups_menu(callback.sender_id))
                return text
            self.store.set_control_state(callback.sender_id, active_group_id=gid, mode="")
            return self._send_control_panel(callback.sender_id, callback.chat_id)
        if data == "ctl:current":
            return self._send_control_panel(callback.sender_id, callback.chat_id)
        if data == "ctl:raw":
            if self._active_group(callback.sender_id) is None:
                return self._send_groups_menu(callback.sender_id, callback.chat_id)
            self.store.set_control_state(callback.sender_id, mode="remote")
            text = (
                "حالت فرمان آزاد فعال شد. هر متن بعدی به Router واقعی گروه ارسال می‌شود.\n"
                "برای فرمان‌های ریپلای‌محور:\nهدف 123456 | بن\nپیام 987 | پین\n\nبرای خروج بنویس: خروج کنترل"
            )
            self._send(callback.chat_id, text, reply_markup=self._group_control_menu(callback.sender_id))
            return text
        if data == "ctl:exit":
            self.store.set_control_state(callback.sender_id, mode="")
            text = "حالت فرمان آزاد بسته شد. گروه فعال در پنل حفظ شد."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        if data == "ctl:features":
            return self._send_plan_features(callback.sender_id, callback.chat_id)
        m = re.fullmatch(r"ctl:cleanup:(300|700|2000|5000)", data)
        if m:
            text = self._queue_remote_command(user_id=callback.sender_id, chat_id=callback.chat_id, command_text=f"پاکسازی {int(m.group(1))}")
            self._send(callback.chat_id, text, reply_markup=self._group_control_menu(callback.sender_id))
            return text
        if data.startswith("ctl:q:"):
            key = callback.data.split(":", 2)[2]
            command = QUICK_CONTROL_COMMANDS.get(key)
            if command is None:
                return None
            text = self._queue_remote_command(
                user_id=callback.sender_id, chat_id=callback.chat_id, command_text=command
            )
            self._send(callback.chat_id, text, reply_markup=self._group_control_menu(callback.sender_id))
            return text

        if data == "prem:groups":
            return self._premium_groups_menu(callback.sender_id, callback.chat_id)
        if data == "prem:subs":
            return self._premium_my_subscriptions(callback.sender_id, callback.chat_id)
        if data == "prem:history":
            return self._premium_history(callback.sender_id, callback.chat_id)
        m = re.fullmatch(r"prem:g:(\d+)", data)
        if m:
            return self._premium_group_menu(callback.sender_id, callback.chat_id, int(m.group(1)))
        m = re.fullmatch(r"prem:p:(\d+):([sgd])", data)
        if m:
            return self._premium_duration_menu(callback.sender_id, callback.chat_id, int(m.group(1)), self._premium_plan_long(m.group(2)))
        m = re.fullmatch(r"prem:o:(\d+):([sgd]):(30|60|90)", data)
        if m:
            return self._premium_create_order(callback.sender_id, callback.chat_id, int(m.group(1)), self._premium_plan_long(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"prem:checkout:(\d+)", data)
        if m:
            self.store.set_premium_ui_state(callback.sender_id, stage="checkout", order_id=int(m.group(1)))
            return self._premium_checkout(callback.sender_id, callback.chat_id, int(m.group(1)))
        m = re.fullmatch(r"prem:coupon:(\d+)", data)
        if m:
            return self._premium_request_coupon(callback.sender_id, callback.chat_id, int(m.group(1)))
        m = re.fullmatch(r"prem:check:(\d+)", data)
        if m:
            return self._premium_check_payment(callback.sender_id, callback.chat_id, int(m.group(1)))
        m = re.fullmatch(r"prem:cancel:(\d+)", data)
        if m:
            return self._premium_cancel(callback.sender_id, callback.chat_id, int(m.group(1)))
        m = re.fullmatch(r"prem:([wzc]):(\d+)", data)
        if m:
            method = {"w": "wallet", "z": "zibal", "c": "card"}[m.group(1)]
            return self._premium_pay(callback.sender_id, callback.chat_id, int(m.group(2)), method)

        if data == "menu:home":
            return self._send_main_menu(callback.chat_id, callback.sender_id)
        if data == "menu:help":
            self._send(callback.chat_id, HELP_TEXT, reply_markup=MAIN_MENU)
            return HELP_TEXT
        if data == "menu:capabilities":
            if self._active_group(callback.sender_id) is not None:
                return self._send_plan_features(callback.sender_id, callback.chat_id)
            self._send(callback.chat_id, CAPABILITY_STATUS_TEXT, reply_markup=MAIN_MENU)
            return CAPABILITY_STATUS_TEXT
        if data == "menu:commands":
            self._send(callback.chat_id, COMMAND_LIST_TEXT, reply_markup=MAIN_MENU)
            return COMMAND_LIST_TEXT
        if data == "menu:stats":
            stats = self.store.stats(callback.sender_id)
            text = f"آمار ZIVO\nپیام‌ها: {stats['messages']}\nفرمان‌ها: {stats['commands']}"
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        if data == "menu:id":
            text = f"شناسه فرستنده: {callback.sender_id}\nشناسه گفتگو: {callback.chat_id}"
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        if data == "menu:ping":
            text = "PONG | هسته ZIVO در حال اجراست."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        if data == "menu:premiumtools":
            return self._send_premium_tools_menu(callback.sender_id, callback.chat_id)
        if data == "menu:fun":
            return self._send_fun_menu(callback.chat_id)
        if data == "menu:tools":
            return self._send_tools_menu(callback.chat_id)
        if data == "menu:economy":
            return self._send_economy_menu(callback.chat_id)
        if data == "bridge:join":
            self.store.set_control_state(callback.sender_id, mode="await_group_link")
            text = (
                "🔗 اتصال گروه جدید\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "لینک گروهت رو همین‌جا بفرست.\n\n"
                "✅ لینک خصوصی: splus.ir/joingroup/...\n"
                "✅ لینک عمومی: splus.ir/username\n\n"
                "بعد از ارسال، اول مشخصات گروه رو نشون می‌دم و فقط بعد از تأیید خودت Join انجام می‌شه."
            )
            self._send(callback.chat_id, text, reply_markup={"inline_keyboard": [[{"text": "❌ لغو", "callback_data": "menu:home"}]]}); return text
        if data == "bridge:groups":
            return self._send_groups_menu(callback.sender_id, callback.chat_id)
        if data.startswith("fun:"):
            command = callback.data.split(":", 1)[1]
            text = entertainment_response(command, f"{callback.chat_id}:{callback.sender_id}")
            self._send(callback.chat_id, text, reply_markup=FUN_MENU)
            return text
        if data == "tool:time":
            text = iran_date_time_text(); self._send(callback.chat_id, text, reply_markup=TOOLS_MENU); return text
        if data == "tool:font":
            text = "برای ساخت 12 استایل بنویس: فونت zivo"; self._send(callback.chat_id, text, reply_markup=TOOLS_MENU); return text
        if data == "tool:calc":
            text = "عبارت را مستقیم بفرست؛ نمونه: (25+5)/3 یا 11*13"; self._send(callback.chat_id, text, reply_markup=TOOLS_MENU); return text
        if data == "eco:meow":
            text = self._social_private(callback.sender_id, "میو"); self._send(callback.chat_id, text, reply_markup=ECONOMY_MENU); return text
        if data == "eco:profile":
            text = self._social_private(callback.sender_id, "موجودی میو"); self._send(callback.chat_id, text, reply_markup=ECONOMY_MENU); return text
        if data == "eco:petshop":
            text = self._social_private(callback.sender_id, "فروشگاه پت"); self._send(callback.chat_id, text, reply_markup=ECONOMY_MENU); return text
        if data == "eco:pet":
            text = self._social_private(callback.sender_id, "پت من"); self._send(callback.chat_id, text, reply_markup=ECONOMY_MENU); return text
        if data == "eco:houseshop":
            text = self._social_private(callback.sender_id, "فروشگاه خانه"); self._send(callback.chat_id, text, reply_markup=ECONOMY_MENU); return text
        if data == "eco:houses":
            text = self._social_private(callback.sender_id, "خانه های من"); self._send(callback.chat_id, text, reply_markup=ECONOMY_MENU); return text

        return None

    def _social_private(self, user_id: str, command_text: str) -> str:
        active = self._active_group(user_id)
        premium_group_id = int(active.get("group_id") or 0) if active is not None else 0
        try:
            result = self._ipc("main", {"op": "social", "requester_user_id": int(user_id), "group_id": premium_group_id, "command_text": str(command_text)}, timeout=12.0)
        except Exception as exc:
            return f"اجرای اقتصاد/سرگرمی خصوصی ناموفق بود: {type(exc).__name__}: {exc}"
        if result.get("ok"):
            return str(result.get("result_text") or "OK")
        return f"فرمان خصوصی اجرا نشد: {result.get('error') or 'FAILED'}"

    @staticmethod
    def _premium_plan_short(plan: str) -> str:
        return {"silver": "s", "gold": "g", "diamond": "d"}.get(str(plan or ""), "")

    @staticmethod
    def _premium_plan_long(code: str) -> str:
        return {"s": "silver", "g": "gold", "d": "diamond"}.get(str(code or ""), "")

    def _premium_group_row(self, user_id: str, group_id: int) -> Optional[Dict[str, Any]]:
        return next((r for r in self._managed_rows_for_user(user_id) if int(r.get("group_id") or 0) == int(group_id)), None)

    def _premium_catalog(self, user_id: str) -> Dict[str, Any]:
        try:
            result = self._ipc("main", {"op": "premium", "action": "catalog", "requester_user_id": int(user_id)}, timeout=6.0)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return result

    def _premium_groups_menu(self, user_id: str, chat_id: str) -> str:
        rows = self._managed_rows_for_user(user_id)
        if not rows:
            text = (
                "💎 خرید اشتراک ZIVO\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "هنوز گروهی به پنلت وصل نشده.\n\n"
                "اول گروهت رو وصل کن؛ بعد می‌تونی پلن اشتراکش رو همین‌جا انتخاب کنی."
            )
            markup = {"inline_keyboard": [[{"text": "🔗 اتصال گروه", "callback_data": "bridge:join"}], [{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}]]}
            self._send(chat_id, text, reply_markup=markup)
            return text
        buttons = []
        for row in rows[:20]:
            gid = int(row.get("group_id") or 0)
            title = str(row.get("title") or f"گروه {gid}")[:30]
            buttons.append([{"text": f"💎 {title}", "callback_data": f"prem:g:{gid}"}])
        buttons.append([{"text": "🌱 اشتراک من", "callback_data": "prem:subs"}, {"text": "🧾 خریدهای من", "callback_data": "prem:history"}])
        buttons.append([{"text": "🏠 پنل اصلی", "callback_data": "menu:home"}])
        text = "💎 خرید اشتراک ZIVO\n━━━━━━━━━━━━━━━━━━\nاشتراک برای کدوم گروه فعال بشه؟ 👇"
        self._send(chat_id, text, reply_markup={"inline_keyboard": buttons})
        return text

    def _premium_group_menu(self, user_id: str, chat_id: str, group_id: int) -> str:
        row = self._premium_group_row(user_id, group_id)
        if row is None:
            text = "🔐 این گروه در پنل قابل‌کنترل تو نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        catalog = self._premium_catalog(user_id)
        if not catalog.get("ok"):
            text = "🟠 سرویس اشتراک الان پاسخ نمی‌ده. کمی بعد دوباره امتحان کن."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        try:
            status = self._ipc("main", {"op": "premium", "action": "status", "requester_user_id": int(user_id), "group_id": int(group_id)}, timeout=5.0)
        except Exception:
            status = {"ok": True, "subscription": {"plan": "free", "status": "active"}, "plan_label": "رایگان"}
        sub = status.get("subscription") or {}
        current = str(status.get("plan_label") or sub.get("plan") or "رایگان")
        text = (
            "💎 انتخاب پلن\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🏷 گروه: {row.get('title') or group_id}\n"
            f"🌱 پلن فعلی: {current}\n\n"
            "پلنی که می‌خوای رو انتخاب کن 👇"
        )
        markup = {"inline_keyboard": [
            [{"text": "🥈 نقره‌ای", "callback_data": f"prem:p:{group_id}:s"}],
            [{"text": "🥇 طلایی", "callback_data": f"prem:p:{group_id}:g"}],
            [{"text": "💎 الماس", "callback_data": f"prem:p:{group_id}:d"}],
            [{"text": "✨ مقایسه قابلیت‌ها", "callback_data": "menu:capabilities"}],
            [{"text": "↩️ انتخاب گروه", "callback_data": "prem:groups"}],
        ]}
        self._send(chat_id, text, reply_markup=markup)
        return text

    def _premium_duration_menu(self, user_id: str, chat_id: str, group_id: int, plan: str) -> str:
        row = self._premium_group_row(user_id, group_id)
        if row is None:
            text = "🔐 این گروه قابل خرید نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        catalog = self._premium_catalog(user_id)
        plan_row = next((x for x in catalog.get("plans") or [] if str(x.get("plan") or "") == plan), None)
        if not plan_row:
            text = "🟠 قیمت این پلن الان در دسترس نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        pcode = self._premium_plan_short(plan)
        label = str(plan_row.get("label") or plan)
        lines = ["🗓 انتخاب مدت اشتراک", "━━━━━━━━━━━━━━━━━━", f"🏷 {row.get('title') or group_id}", f"💎 پلن: {label}", "", "مدت رو انتخاب کن:"]
        buttons = []
        for price in plan_row.get("prices") or []:
            days = int(price.get("duration_days") or 0)
            months = {30: "۱ ماهه", 60: "۲ ماهه", 90: "۳ ماهه"}.get(days, f"{days} روزه")
            amount = str(price.get("money_toman") or price.get("money_rial") or "")
            buttons.append([{"text": f"📅 {months} · {amount}", "callback_data": f"prem:o:{group_id}:{pcode}:{days}"}])
        buttons.append([{"text": "↩️ تغییر پلن", "callback_data": f"prem:g:{group_id}"}])
        self._send(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons})
        return "\n".join(lines)

    @staticmethod
    def _order_status_fa(status: str) -> str:
        return {
            "created": "آماده پرداخت",
            "gateway_pending": "در انتظار نتیجه درگاه",
            "activated": "فعال‌شده",
            "cancelled": "لغوشده",
            "rejected": "ردشده",
            "verify_failed": "نیازمند بررسی دوباره",
            "gateway_returned": "پرداخت تکمیل نشده",
            "amount_mismatch": "اختلاف مبلغ",
        }.get(str(status or ""), str(status or "در حال بررسی"))

    def _premium_checkout_markup(self, order: Dict[str, Any], *, wallet_balance: int = 0, payment: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        oid = int(order.get("order_id") or 0)
        gid = int(order.get("group_id") or 0)
        amount = int(order.get("amount_rial") or 0)
        status = str(order.get("status") or "")
        payment = payment or {}
        buttons: list[list[Dict[str, str]]] = []
        if status == "activated":
            buttons.append([{"text": "✅ اشتراک فعال است", "callback_data": "prem:subs"}])
        elif status == "cancelled":
            buttons.append([{"text": "💎 ساخت سفارش جدید", "callback_data": f"prem:g:{gid}"}])
        else:
            if wallet_balance >= amount and amount > 0:
                buttons.append([{"text": "👛 پرداخت با کیف پول", "callback_data": f"prem:w:{oid}"}])
            if payment.get("zibal_enabled") or int(order.get("zibal_track_id") or 0) > 0:
                buttons.append([{"text": "💳 پرداخت آنلاین زیبال", "callback_data": f"prem:z:{oid}"}])
            if payment.get("card_enabled"):
                buttons.append([{"text": "💳 کارت‌به‌کارت", "callback_data": f"prem:c:{oid}"}])
            buttons.append([{"text": "🎟 کد تخفیف", "callback_data": f"prem:coupon:{oid}"}, {"text": "🔄 چک پرداخت", "callback_data": f"prem:check:{oid}"}])
            buttons.append([{"text": "❌ لغو سفارش", "callback_data": f"prem:cancel:{oid}"}])
        buttons.append([{"text": "↩️ تغییر پلن", "callback_data": f"prem:g:{gid}"}, {"text": "🏠 پنل", "callback_data": "menu:home"}])
        return {"inline_keyboard": buttons}

    def _premium_checkout_text(self, order: Dict[str, Any], *, wallet_balance: int = 0) -> str:
        original = int(order.get("original_amount_rial") or order.get("amount_rial") or 0)
        amount = int(order.get("amount_rial") or 0)
        discount = int(order.get("discount_rial") or 0)
        code = str(order.get("discount_code") or "")
        status = self._order_status_fa(str(order.get("status") or ""))
        lines = [
            "🧾 صفحه پرداخت ZIVO",
            "━━━━━━━━━━━━━━━━━━",
            f"🔖 کد سفارش: {order.get('order_code') or order.get('order_id')}",
            f"🏷 گروه: {order.get('group_title') or order.get('group_id')}",
            f"💎 پلن: {str(order.get('plan') or '').upper()}",
            f"🗓 مدت: {int(order.get('duration_days') or 0)} روز",
            "",
        ]
        if discount > 0:
            lines.extend([f"💵 مبلغ اصلی: {original:,} ریال", f"🎟 تخفیف {code}: −{discount:,} ریال", f"✅ مبلغ نهایی: {amount:,} ریال"])
        else:
            lines.append(f"💵 مبلغ قابل پرداخت: {amount:,} ریال")
        lines.extend([f"👛 کیف پول: {int(wallet_balance):,} ریال", f"📌 وضعیت: {status}", "━━━━━━━━━━━━━━━━━━", "می‌تونی پرداخت کنی، کد تخفیف بزنی، پرداخت رو چک کنی یا سفارش رو لغو کنی."])
        return "\n".join(lines)

    def _premium_checkout(self, user_id: str, chat_id: str, order_id: int) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "order", "requester_user_id": int(user_id), "order_ref": int(order_id)}, timeout=6.0)
        except Exception:
            text = "🟠 اطلاعات سفارش الان در دسترس نیست. دوباره امتحان کن."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if not result.get("ok"):
            text = "🟠 این سفارش پیدا نشد یا متعلق به این حساب نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        order = result.get("order") or {}
        text = self._premium_checkout_text(order, wallet_balance=int(result.get("wallet_balance") or 0))
        self._send(chat_id, text, reply_markup=self._premium_checkout_markup(order, wallet_balance=int(result.get("wallet_balance") or 0), payment=result.get("payment") or {}))
        return text

    def _premium_create_order(self, user_id: str, chat_id: str, group_id: int, plan: str, days: int) -> str:
        row = self._premium_group_row(user_id, group_id)
        if row is None:
            text = "🔐 این گروه برای خرید در دسترس نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        try:
            result = self._ipc("main", {
                "op": "premium", "action": "create_order", "requester_user_id": int(user_id),
                "group_id": int(group_id), "group_title": str(row.get("title") or f"گروه {group_id}"),
                "plan": plan, "duration_days": int(days),
            }, timeout=8.0)
        except Exception:
            text = "🟠 ساخت سفارش انجام نشد. دوباره امتحان کن."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if not result.get("ok"):
            text = f"🟠 سفارش ساخته نشد: {result.get('error') or 'FAILED'}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        order = result.get("order") or {}
        oid = int(order.get("order_id") or 0)
        self.store.set_premium_ui_state(user_id, stage="checkout", order_id=oid, group_id=group_id)
        return self._premium_checkout(user_id, chat_id, oid)

    def _premium_success_page(self, user_id: str, chat_id: str, order: Dict[str, Any], order_id: int) -> str:
        gid = int(order.get("group_id") or 0)
        if gid > 0 and self._premium_group_row(user_id, gid) is not None:
            self.store.set_control_state(user_id, active_group_id=gid, mode="")
        plan = str(order.get("plan") or "free").strip().lower()
        if plan not in PLAN_UX:
            plan = "free"
        cfg = PLAN_UX[plan]
        title = str(order.get("group_title") or (f"گروه {gid}" if gid else "گروه ZIVO"))
        duration_days = int(order.get("duration_days") or 0)
        months = max(1, round(duration_days / 30)) if duration_days > 0 else 0
        code = str(order.get("order_code") or order_id)
        unlocked = PLAN_NEW_FEATURES.get(plan, [])
        lines = [
            "🎉 پرداخت موفق بود · پلن فعال شد",
            "━━━━━━━━━━━━━━━━━━",
            f"🏷 گروه: {title}",
            f"{cfg['emoji']} پلن فعال: {cfg['label']}",
        ]
        if months:
            lines.append(f"📅 مدت اشتراک: {months} ماه")
        lines.extend([
            f"🔖 کد سفارش: {code}",
            "✅ وضعیت: فعال و آماده استفاده",
            "━━━━━━━━━━━━━━━━━━",
            "✨ قابلیت‌هایی که همین الان به مدیریت این گروه اضافه شدند:",
        ])
        if unlocked:
            lines.extend(f"{item}" for item in unlocked)
        else:
            lines.append("🌱 قابلیت‌های پایه FREE برای گروه فعال هستند.")
        lines.extend([
            "",
            "از این لحظه لازم نیست وارد بخش جداگانه‌ای بشی؛ دکمه «🎛 مدیریت گروه» همین گروه با امکانات پلن جدید بازطراحی شده.",
        ])
        text = "\n".join(lines)
        markup = {"inline_keyboard": [
            [{"text": f"🎛 مدیریت گروه · {cfg['label']}", "callback_data": "ctl:current"}],
            [{"text": "✨ دیدن امکانات فعال", "callback_data": "ctl:features"}, {"text": "🌱 اشتراک من", "callback_data": "prem:subs"}],
            [{"text": "🧾 خرید / تمدید دوباره", "callback_data": f"prem:g:{gid}"}, {"text": "🏠 صفحه اصلی", "callback_data": "menu:home"}],
        ]}
        self._send(chat_id, text, reply_markup=markup)
        return text

    def _watch_payment(self, user_id: str, chat_id: str, order_id: int) -> None:
        with self._payment_watch_lock:
            self._payment_watch[int(order_id)] = {"user_id": str(user_id), "chat_id": str(chat_id), "next_check": 0.0, "created": time.monotonic()}

    def poll_payment_watch(self) -> int:
        now = time.monotonic()
        with self._payment_watch_lock:
            items = list(self._payment_watch.items())
        notified = 0
        for oid, meta in items:
            if now < float(meta.get("next_check") or 0):
                continue
            if now - float(meta.get("created") or now) > 1800:
                with self._payment_watch_lock:
                    self._payment_watch.pop(oid, None)
                continue
            try:
                result = self._ipc("main", {"op": "premium", "action": "order", "requester_user_id": int(meta["user_id"]), "order_ref": int(oid)}, timeout=4.0)
            except Exception:
                result = {}
            order = result.get("order") or {}
            status = str(order.get("status") or "")
            if status == "activated":
                self._premium_success_page(str(meta["user_id"]), str(meta["chat_id"]), order, int(oid))
                with self._payment_watch_lock:
                    self._payment_watch.pop(oid, None)
                notified += 1
            elif status in {"cancelled", "rejected"}:
                with self._payment_watch_lock:
                    self._payment_watch.pop(oid, None)
            else:
                with self._payment_watch_lock:
                    if oid in self._payment_watch:
                        self._payment_watch[oid]["next_check"] = now + 2.5
        return notified

    def _premium_pay(self, user_id: str, chat_id: str, order_id: int, method: str) -> str:
        action = {"wallet": "wallet_pay", "zibal": "zibal", "card": "card"}.get(method, "order")
        try:
            result = self._ipc("main", {"op": "premium", "action": action, "requester_user_id": int(user_id), "order_ref": int(order_id)}, timeout=20.0)
        except Exception:
            text = "🟠 عملیات پرداخت به سرویس نرسید. دوباره امتحان کن."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        order = result.get("order") or {}
        code = str(order.get("order_code") or order_id)
        if method == "wallet":
            if result.get("ok") and result.get("activated"):
                return self._premium_success_page(user_id, chat_id, order, order_id)
            text = f"👛 موجودی کیف پول برای این پرداخت کافی نیست.\nموجودی: {int(result.get('wallet_balance') or 0):,} ریال"
            self._send(chat_id, text, reply_markup=self._premium_checkout_markup(order, wallet_balance=int(result.get("wallet_balance") or 0), payment={}))
            return text
        if method == "zibal":
            if result.get("ok") and result.get("payment_url"):
                self._watch_payment(user_id, chat_id, order_id)
                text = (
                    "💳 صفحه پرداخت آماده شد\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🔖 سفارش: {code}\n"
                    f"💵 مبلغ: {int(order.get('amount_rial') or 0):,} ریال\n\n"
                    f"🔗 لینک پرداخت:\n{result.get('payment_url')}\n\n"
                    "روی دکمه ورود به درگاه بزن. بعد از پرداخت به ZIVO برگرد؛ نتیجه خودکار بررسی می‌شه و صفحه فعال‌سازی مخصوص همان گروه نمایش داده می‌شه. اگر پیام نیومد، «🔄 چک پرداخت» رو بزن."
                )
                payment_url = str(result.get("payment_url") or "")
                self._send(chat_id, text, reply_markup={"inline_keyboard": [
                    [{"text": "💳 پرداخت آنلاین — ورود به درگاه", "url": payment_url}],
                    [{"text": "🔄 چک پرداخت", "callback_data": f"prem:check:{order_id}"}, {"text": "🎟 کد تخفیف", "callback_data": f"prem:coupon:{order_id}"}],
                    [{"text": "❌ لغو سفارش", "callback_data": f"prem:cancel:{order_id}"}],
                    [{"text": "🏠 پنل", "callback_data": "menu:home"}],
                ]})
                return text
            text = f"🟠 درگاه ساخته نشد: {result.get('error') or 'FAILED'}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if result.get("ok") and result.get("manual_receipt_required"):
            text = (
                "💳 کارت‌به‌کارت\n━━━━━━━━━━━━━━━━━━\n"
                f"🔖 سفارش: {code}\n"
                f"💳 کارت: {result.get('card_number') or '—'}\n"
                f"👤 به نام: {result.get('card_holder') or '—'}\n"
                f"💵 مبلغ: {result.get('money_rial') or order.get('amount_rial')}\n\n"
                "بعد از پرداخت، کد سفارش و رسید را برای پشتیبانی بفرست."
            )
        else:
            text = "🟠 کارت‌به‌کارت الان فعال نیست."
        self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "🔄 چک پرداخت", "callback_data": f"prem:check:{order_id}"}], [{"text": "🏠 پنل", "callback_data": "menu:home"}]]})
        return text

    def _premium_check_payment(self, user_id: str, chat_id: str, order_id: int) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "check_payment", "requester_user_id": int(user_id), "order_ref": int(order_id)}, timeout=20.0)
        except Exception:
            text = "🟠 بررسی پرداخت انجام نشد. چند ثانیه بعد دوباره بزن."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        order = result.get("order") or {}
        if result.get("ok") and result.get("activated"):
            with self._payment_watch_lock:
                self._payment_watch.pop(int(order_id), None)
            return self._premium_success_page(user_id, chat_id, order, order_id)
        if result.get("ok") and result.get("pending"):
            text = "⏳ هنوز پرداخت تأیید نشده. اگر همین الان پرداخت کردی چند ثانیه صبر کن و دوباره «چک پرداخت» رو بزن."
            self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "🔄 چک دوباره", "callback_data": f"prem:check:{order_id}"}], [{"text": "🧾 برگشت به سفارش", "callback_data": f"prem:checkout:{order_id}"}]]})
            return text
        text = f"🟠 پرداخت تأیید نشد: {result.get('error') or result.get('message') or 'FAILED'}"
        self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "🧾 سفارش", "callback_data": f"prem:checkout:{order_id}"}], [{"text": "🏠 پنل", "callback_data": "menu:home"}]]})
        return text

    def _premium_request_coupon(self, user_id: str, chat_id: str, order_id: int) -> str:
        self.store.set_premium_ui_state(user_id, stage="coupon", order_id=order_id)
        text = "🎟 کد تخفیف داری؟\n━━━━━━━━━━━━━━━━━━\nکد رو همین‌جا به‌صورت یک پیام بفرست.\nبرای برگشت بنویس: لغو"
        self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "↩️ برگشت به سفارش", "callback_data": f"prem:checkout:{order_id}"}]]})
        return text

    def _premium_apply_coupon(self, user_id: str, chat_id: str, order_id: int, code: str) -> str:
        if normalize_text(code).casefold() in {"لغو", "cancel"}:
            self.store.set_premium_ui_state(user_id, stage="")
            return self._premium_checkout(user_id, chat_id, order_id)
        try:
            result = self._ipc("main", {"op": "premium", "action": "discount_apply", "requester_user_id": int(user_id), "order_ref": int(order_id), "code": str(code)}, timeout=6.0)
        except Exception:
            result = {"ok": False, "error": "SERVICE_UNAVAILABLE"}
        self.store.set_premium_ui_state(user_id, stage="")
        if not result.get("ok"):
            err = str(result.get("error") or "INVALID")
            friendly = {
                "DISCOUNT_CODE_NOT_FOUND": "این کد تخفیف معتبر نیست.",
                "DISCOUNT_ORDER_LOCKED": "بعد از شروع پرداخت، مبلغ سفارش قابل تغییر نیست.",
            }.get(err, "کد تخفیف اعمال نشد.")
            text = f"🎟 {friendly}"
            self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "🧾 برگشت به سفارش", "callback_data": f"prem:checkout:{order_id}"}]]})
            return text
        order = result.get("order") or {}
        text = f"✅ کد تخفیف اعمال شد.\n🎟 {order.get('discount_code')}\n💸 تخفیف: {int(order.get('discount_rial') or 0):,} ریال\n✅ مبلغ جدید: {int(order.get('amount_rial') or 0):,} ریال"
        self._send(chat_id, text, reply_markup=self._premium_checkout_markup(order, wallet_balance=int(result.get("wallet_balance") or 0), payment=self._premium_catalog(user_id).get("payment") or {}))
        return text

    def _premium_cancel(self, user_id: str, chat_id: str, order_id: int) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "cancel", "requester_user_id": int(user_id), "order_ref": int(order_id)}, timeout=6.0)
        except Exception:
            result = {"ok": False, "error": "SERVICE_UNAVAILABLE"}
        if result.get("ok"):
            self.store.set_premium_ui_state(user_id, stage="")
            with self._payment_watch_lock:
                self._payment_watch.pop(int(order_id), None)
            text = "❌ سفارش لغو شد. هیچ مبلغی از کیف پول کم نشد و اشتراکی فعال نشد."
            self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "💎 خرید اشتراک جدید", "callback_data": "prem:groups"}], [{"text": "🏠 پنل", "callback_data": "menu:home"}]]})
            return text
        text = f"🟠 سفارش لغو نشد: {result.get('error') or 'FAILED'}"
        self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "🧾 برگشت به سفارش", "callback_data": f"prem:checkout:{order_id}"}]]})
        return text

    def _premium_my_subscriptions(self, user_id: str, chat_id: str) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "my_subscriptions", "requester_user_id": int(user_id)}, timeout=6.0)
        except Exception:
            result = {"ok": True, "subscriptions": []}
        rows = result.get("subscriptions") or []
        if not rows:
            text = (
                "🌱 اشتراک من\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "پلن فعلی: رایگان\n\n"
                "هیچ اشتراک پولی فعالی نداری؛ این خطا نیست. امکانات رایگان ZIVO همچنان فعاله.\n"
                "اگر امکانات بیشتر می‌خوای، پلن‌ها رو ببین 👇"
            )
            self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "💎 دیدن پلن‌ها", "callback_data": "prem:groups"}], [{"text": "✨ مقایسه قابلیت‌ها", "callback_data": "menu:capabilities"}], [{"text": "🏠 پنل", "callback_data": "menu:home"}]]})
            return text
        lines = ["🌟 اشتراک‌های فعال من", "━━━━━━━━━━━━━━━━━━"]
        for row in rows[:20]:
            plan = str(row.get("effective_plan") or row.get("plan") or "free").upper()
            meter = self._subscription_meter(dict(row))
            lines.append(f"✅ {row.get('group_title') or row.get('group_id')}\n   💎 {plan}\n   {meter.replace(chr(10), chr(10)+'   ')}")
        text = "\n".join(lines)
        self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "💎 خرید/تمدید", "callback_data": "prem:groups"}], [{"text": "🏠 پنل", "callback_data": "menu:home"}]]})
        return text

    def _premium_history(self, user_id: str, chat_id: str) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "history", "requester_user_id": int(user_id)}, timeout=6.0)
        except Exception:
            result = {"ok": True, "orders": []}
        rows = result.get("orders") or []
        lines = ["🧾 خریدهای من", "━━━━━━━━━━━━━━━━━━"]
        if not rows:
            lines.append("هنوز سفارشی ثبت نکردی.")
        else:
            for row in rows[:12]:
                lines.append(f"• {row.get('order_code') or row.get('order_id')} · {row.get('group_title') or row.get('group_id')} · {str(row.get('plan') or '').upper()} · {self._order_status_fa(str(row.get('status') or ''))}")
        text = "\n".join(lines)
        self._send(chat_id, text, reply_markup={"inline_keyboard": [[{"text": "💎 خرید اشتراک", "callback_data": "prem:groups"}], [{"text": "🏠 پنل", "callback_data": "menu:home"}]]})
        return text

    def _spam_triggered(self, message: IncomingMessage) -> bool:
        now = time.monotonic()
        key = (message.chat_id, message.sender_id)
        q = self._spam[key]
        q.append(now)
        while q and now - q[0] > 6.0:
            q.popleft()
        return len(q) >= 7

    def handle(self, raw: Dict[str, Any]) -> Optional[str]:
        message = normalize_event(raw)
        if message is None or not message.is_text:
            return None

        text = message.body
        low = text.casefold()
        commandish = low.startswith("/") or low.split(" ", 1)[0] in {
            "شروع", "راهنما", "لیست", "پنل", "پینگ", "نسخه", "شناسه", "آمار", "جوک", "فال", "دانستنی",
            "داستان", "چالش", "معما", "جواب", "حقیقت", "جرئت", "تاس", "سکه", "شیر", "شانس",
            "تاریخ", "زمان", "وقت", "ساعت", "فونت", "میو", "موجودی", "فروشگاه", "خرید", "پت", "خانه", "بازار",
            "فیلتر", "حذف", "ریست", "وضعیت", "اکانت", "اکانت‌ها", "کاربران", "پیام", "گروه‌های", "اشتراک", "پلن", "پلن‌ها", "خریدهای",
        }
        contact_before = self.store.contact(message.sender_id) if message.chat_id == message.sender_id else None
        self.store.observe(message, command=commandish)
        self.store.remember_contact(message)

        if message.chat_id == message.sender_id and not self._is_owner(message.sender_id):
            gate_state = self.store.gate_state(message.sender_id)
            if contact_before is None and gate_state is None:
                persistent = {}
                try:
                    pres = self._ipc("main", {"op": "official_gate", "action": "status", "requester_user_id": int(message.sender_id)}, timeout=5.0)
                    persistent = pres.get("state") or {} if pres.get("ok") else {}
                except Exception:
                    persistent = {}
                # A user who already owns/controls a ZIVO group is necessarily an
                # existing user from before this onboarding gate. Seed them as
                # passed so upgrades never lock established customers out.
                if not persistent.get("seen"):
                    try:
                        if self._managed_rows_for_user(message.sender_id):
                            self._ipc("main", {"op": "official_gate", "action": "pass", "requester_user_id": int(message.sender_id)}, timeout=5.0)
                            persistent = {"seen": True, "membership_passed": True}
                    except Exception:
                        pass
                if persistent.get("membership_passed"):
                    self.store.pass_gate(message.sender_id)
                elif persistent.get("seen"):
                    self.store.require_gate(message.sender_id)
                    return self._complete_soft_gate(message.sender_id, message.chat_id)
                else:
                    try:
                        self._ipc("main", {"op": "official_gate", "action": "seen", "requester_user_id": int(message.sender_id)}, timeout=5.0)
                    except Exception:
                        pass
                    self.store.require_gate(message.sender_id)
                    return self._send_membership_gate(message.chat_id, failed=False)
            if self.store.gate_pending(message.sender_id):
                return self._complete_soft_gate(message.sender_id, message.chat_id)

        if self._is_owner(message.sender_id):
            admin_state=self._admin_state.get(str(message.sender_id)) or {}
            if str(admin_state.get("stage") or "") == "ad_text":
                if not text.strip():
                    return None
                return self._admin_ad_preview(message.sender_id, message.chat_id, text.strip())
            if low in {"پنل ادمین", "ادمین", "تبلیغات بات"}:
                return self._admin_home(message.sender_id, message.chat_id)

        if low in {"تبلیغات خاموش", "دریافت تبلیغات خاموش"}:
            try: self._ipc("main",{"op":"official_admin_user","action":"broadcast_off","requester_user_id":int(message.sender_id)},timeout=5.0)
            except Exception: pass
            response="✅ دریافت پیام‌های اطلاع‌رسانی بات رسمی برایت غیرفعال شد."; self._send(message.chat_id,response); return response
        if low in {"تبلیغات روشن", "دریافت تبلیغات روشن"}:
            try: self._ipc("main",{"op":"official_admin_user","action":"broadcast_on","requester_user_id":int(message.sender_id)},timeout=5.0)
            except Exception: pass
            response="✅ دریافت پیام‌های اطلاع‌رسانی بات رسمی برایت فعال شد."; self._send(message.chat_id,response); return response

        group_link = parse_group_link(text)
        if group_link is not None:
            return self._begin_group_link(message, group_link[0], group_link[1])

        if low in {"/start", "start", "شروع", "شروع کار", "ربات", "پنل", "/panel"}:
            self.store.set_premium_ui_state(message.sender_id, stage="")
            self.store.set_control_state(message.sender_id, mode="")
            return self._send_main_menu(message.chat_id, message.sender_id)

        premium_state = self.store.premium_ui_state(message.sender_id)
        if message.chat_id == message.sender_id and str(premium_state.get("stage") or "") == "coupon" and int(premium_state.get("order_id") or 0) > 0:
            return self._premium_apply_coupon(message.sender_id, message.chat_id, int(premium_state["order_id"]), text)

        if low in {"خروج کنترل", "پایان کنترل", "بستن کنترل"}:
            self.store.set_control_state(message.sender_id, mode="")
            response = "حالت فرمان آزاد بسته شد. گروه فعال در پنل حفظ شد."
            self._send(message.chat_id, response, reply_markup=MAIN_MENU)
            return response

        if low in {"کنترل گروه", "کنترل"}:
            if self._active_group(message.sender_id) is None:
                return self._send_groups_menu(message.sender_id, message.chat_id)
            self.store.set_control_state(message.sender_id, mode="remote")
            response = self._send_control_panel(message.sender_id, message.chat_id)
            return response

        state = self.store.control_state(message.sender_id)
        if (
            message.chat_id == message.sender_id
            and str(state.get("mode") or "") == "remote"
            and int(state.get("active_group_id") or 0) > 0
        ):
            response = self._queue_remote_command(
                user_id=message.sender_id, chat_id=message.chat_id, command_text=text
            )
            self._send(message.chat_id, response, reply_markup=self._group_control_menu(message.sender_id))
            return response

        if low in {"خرید اشتراک", "اشتراک", "پلن ها", "پلن‌ها", "پلنها"}:
            return self._premium_groups_menu(message.sender_id, message.chat_id)
        if low in {"اشتراک من", "اشتراک های من", "اشتراک‌های من"}:
            return self._premium_my_subscriptions(message.sender_id, message.chat_id)
        if low in {"خریدهای من", "تراکنش های من", "تراکنش‌های من"}:
            return self._premium_history(message.sender_id, message.chat_id)

        response = self._route_command(message)
        if response is not None:
            self._send(message.chat_id, response)
            return response

        matched = self.store.matched_filter(message.chat_id, text)
        if matched:
            count = self.store.warn(message.chat_id, message.sender_id)
            response = f"پیام شامل عبارت فیلترشده «{matched}» بود. اخطار داخلی ZIVO: {count}"
            self._send(message.chat_id, response)
            return response

        if self._spam_triggered(message):
            response = "ارسال پیام خیلی سریع تشخیص داده شد. کمی آهسته‌تر پیام بفرست."
            self._send(message.chat_id, response)
            return response

        return None

    def _route_command(self, message: IncomingMessage) -> Optional[str]:
        text = message.body
        low = text.casefold()

        if low in {"/start", "start", "شروع", "شروع کار", "ربات"}:
            return f"ZIVO رسمی فعاله.\nنسخه: {VERSION}\nبرای دستورات: راهنما"
        if low in {"راهنما", "/help", "help"}:
            return HELP_TEXT
        if low in {"لیست دستورات", "دستورات"}:
            return COMMAND_LIST_TEXT
        if low in {"پینگ", "/ping", "ping"}:
            return "PONG | هسته ZIVO در حال اجراست."
        if low in {"نسخه", "/version", "version"}:
            return VERSION
        if low in {"شناسه", "آیدی من", "ایدی من", "/id"}:
            return f"شناسه فرستنده: {message.sender_id}\nشناسه گفتگو: {message.chat_id}"
        if low in {"آمار من", "/stats"}:
            stats = self.store.stats(message.sender_id)
            return f"آمار ZIVO\nپیام‌ها: {stats['messages']}\nفرمان‌ها: {stats['commands']}"
        if low in {"تاریخ", "زمان", "وقت", "ساعت"}:
            return iran_date_time_text()
        if low == "فونت":
            return font_response("")
        if low.startswith("فونت "):
            return font_response(text[5:].strip())

        calc = market_tools.arithmetic_response(text)
        if calc is not None:
            return calc

        if text in ENTERTAINMENT_COMMANDS:
            return entertainment_response(text, f"{message.chat_id}:{message.sender_id}")

        # Lightweight candidate detection only. Do NOT call parse_social_command
        # here: pet-name resolution can open the account SQLite database. All
        # social/economy parsing and mutations belong to the account process.
        social_head = low.split(maxsplit=1)[0] if low else ""
        social_candidate = (
            social_head in social_games.SOCIAL_COMMAND_HEADS
            or bool(re.fullmatch(r"میو{1,24}", low))
            or low in {"آوو", "آووو", "آوووو", "اَووو", "زوزه", "زوزه بکش", "زوزه کشیدن"}
        )
        if social_candidate:
            try:
                result = self._ipc("main", {"op": "social", "requester_user_id": int(message.sender_id), "command_text": text}, timeout=12.0)
            except Exception as exc:
                return f"اجرای اقتصاد/سرگرمی خصوصی ناموفق بود: {type(exc).__name__}: {exc}"
            if result.get("ok"):
                return str(result.get("result_text") or "OK")
            if str(result.get("error") or "") != "SOCIAL_COMMAND_UNKNOWN":
                return f"فرمان خصوصی اجرا نشد: {result.get('error') or 'FAILED'}"

        if low in {"گروه‌های من", "گروه های من", "گروههای من"}:
            return self._my_groups_text(message.sender_id)
        if low in {"وضعیت اتصال", "وضعیت اکانت", "وضعیت اکانت‌ها", "وضعیت اکانت ها"}:
            return self._account_status_text(detailed=self._is_owner(message.sender_id))
        if low in {"اکانت‌ها", "اکانت ها"}:
            if not self._is_owner(message.sender_id):
                return self._account_status_text(detailed=False)
            return self._account_status_text(detailed=True)
        match = re.fullmatch(r"اکانت\s+([A-Za-z0-9_-]+)\s+(فعال|روشن|خاموش|غیرفعال)", text, flags=re.IGNORECASE)
        if match:
            if not self._is_owner(message.sender_id):
                return "این کنترل فقط برای مالک اصلی ZIVO است."
            key = str(match.group(1)).strip().lower()
            enabled = match.group(2) in {"فعال", "روشن"}
            rows = {str(r["account_key"] or "").strip().lower(): r for r in self._account_rows()}
            if key not in rows:
                return f"اکانت {key} از مسیر Socket در دسترس نیست."
            try:
                result = self._ipc(key, {"op": "set_enabled", "requester_user_id": int(message.sender_id), "enabled": enabled}, timeout=3.0)
            except Exception as exc:
                return f"تغییر وضعیت اکانت ناموفق بود: {type(exc).__name__}: {exc}"
            if not result.get("ok"):
                return f"تغییر وضعیت اکانت رد شد: {result.get('error') or 'FAILED'}"
            return f"اکانت {key} {'فعال' if enabled else 'خاموش'} شد. سرویس اکانت Stop نمی‌شود."
        if low == "کاربران بات":
            if not self._is_owner(message.sender_id):
                return "این بخش فقط برای مالک اصلی ZIVO است."
            rows = self.store.contacts(30)
            lines = [f"کاربران خصوصی شناخته‌شده: {len(rows)}"]
            for row in rows:
                label = str(row["username"] or row["first_name"] or "-")
                lines.append(f"• {row['user_id']} | {label}")
            return "\n".join(lines)
        match = re.fullmatch(r"پیام\s+کاربر\s+(\d+)\s+(.+)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            if not self._is_owner(message.sender_id):
                return "این بخش فقط برای مالک اصلی ZIVO است."
            uid = str(match.group(1))
            body = str(match.group(2)).strip()
            contact = self.store.contact(uid)
            if contact is None:
                return "این کاربر هنوز در پیوی بات ثبت نشده و chat_id قابل‌اعتماد نداریم."
            self._send(str(contact["chat_id"]), body)
            return f"پیام برای کاربر {uid} ارسال شد."

        m = re.fullmatch(r"ساخت\s+کد\s+تخفیف\s+([A-Za-z0-9_-]{2,32})\s+(\d{1,2})", text, flags=re.IGNORECASE)
        if m:
            if not self._is_owner(message.sender_id):
                return "این دستور فقط برای مالک اصلی ZIVO است."
            result = self._ipc("main", {"op": "premium", "action": "discount_set", "requester_user_id": int(message.sender_id), "code": m.group(1), "percent": int(m.group(2))}, timeout=5.0)
            if not result.get("ok"):
                return f"ساخت کد انجام نشد: {result.get('error') or 'FAILED'}"
            row = result.get("discount") or {}
            return f"🎟 کد تخفیف ساخته شد\nکد: {row.get('code')}\nمقدار: {row.get('percent')}٪"

        m = re.fullmatch(r"حذف\s+کد\s+تخفیف\s+([A-Za-z0-9_-]{2,32})", text, flags=re.IGNORECASE)
        if m:
            if not self._is_owner(message.sender_id):
                return "این دستور فقط برای مالک اصلی ZIVO است."
            result = self._ipc("main", {"op": "premium", "action": "discount_remove", "requester_user_id": int(message.sender_id), "code": m.group(1)}, timeout=5.0)
            return "✅ کد حذف شد." if result.get("removed") else "کد پیدا نشد."

        if low in {"لیست کد تخفیف", "لیست کدهای تخفیف"}:
            if not self._is_owner(message.sender_id):
                return "این دستور فقط برای مالک اصلی ZIVO است."
            result = self._ipc("main", {"op": "premium", "action": "discount_list", "requester_user_id": int(message.sender_id)}, timeout=5.0)
            rows = result.get("discounts") or []
            return "🎟 کدهای تخفیف\n" + ("\n".join(f"• {r.get('code')} — {r.get('percent')}٪" for r in rows) if rows else "هیچ کدی تعریف نشده.")

        if low in {"وضعیت api", "وضعیت ای پی آی", "وضعیت ایپیای"}:
            return "Transport فعال: getMe + getUpdates(Long Polling) + sendMessage + Callback. قابلیت‌های خصوصی موج اول از ZIVO 60.96.39.4 منتقل شده‌اند."
        if low in {"وضعیت قابلیت‌ها", "وضعیت قابلیت ها"}:
            return CAPABILITY_STATUS_TEXT

        match = re.fullmatch(r"فیلتر(?:\s+کلمه)?\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            word = normalize_text(match.group(1))
            if len(word) > 80:
                return "عبارت فیلتر خیلی بلند است."
            created = self.store.add_filter(message.chat_id, word, message.sender_id)
            return f"فیلتر «{word}» {'اضافه شد' if created else 'از قبل وجود داشت'}."

        match = re.fullmatch(r"حذف\s+فیلتر\s+(.+)", text, flags=re.IGNORECASE)
        if match:
            word = normalize_text(match.group(1))
            removed = self.store.remove_filter(message.chat_id, word)
            return f"فیلتر «{word}» {'حذف شد' if removed else 'پیدا نشد'}."

        if low == "لیست فیلتر":
            words = self.store.filters(message.chat_id)
            if not words:
                return "لیست فیلتر خالی است."
            return "فیلترهای این گفتگو:\n" + "\n".join(f"- {word}" for word in words[:100])

        if low == "ریست فیلتر":
            removed = self.store.reset_filters(message.chat_id)
            return f"{removed} فیلتر پاک شد."

        return None


# ---------------------------------------------------------------------------
# Official17 extensions: Meow commerce, rich campaign, and lock-control UX.
# Kept as subclasses so the stable Official16 join/premium/group flows remain
# untouched while the new surfaces are easy to audit independently.
# ---------------------------------------------------------------------------

class SoroushOfficialTransport(SoroushOfficialTransport):
    MEDIA_ENDPOINTS = {
        "photo": f"{API_BASE}/sendPhoto",
        "video": f"{API_BASE}/sendVideo",
        "voice": f"{API_BASE}/sendVoice",
        "document": f"{API_BASE}/sendDocument",
    }

    def send_media(self, to: str, item: Dict[str, Any], caption: str = "") -> requests.Response:
        kind = str(item.get("type") or "document").strip().lower()
        endpoint = self.MEDIA_ENDPOINTS.get(kind, self.MEDIA_ENDPOINTS["document"])
        media_key = kind if kind in {"photo", "video", "voice"} else "document"
        value = str(item.get("file_id") or item.get("url") or item.get("file_path") or "").strip()
        if not value:
            raise RuntimeError("OFFICIAL_MEDIA_FILE_ID_MISSING")
        payload: Dict[str, Any] = {"chat_id": str(to), media_key: value}
        if caption:
            payload["caption"] = str(caption)[:3500]
        response = self.session.post(endpoint, json=payload, timeout=(CONNECT_TIMEOUT, SEND_TIMEOUT))
        log.info("send%s HTTP | status=%s chat_id=%s", kind.title(), response.status_code, to)
        response.raise_for_status()
        data = self._json(response)
        if data.get("ok") is False:
            raise RuntimeError(f"send{kind.title()} rejected: {data!r}")
        return response

    def download_media_item(self, item: Dict[str, Any], destination: Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        direct = str(item.get("url") or item.get("file_url") or "").strip()
        candidates: List[str] = []
        if direct.startswith("http://") or direct.startswith("https://"):
            candidates.append(direct)
        file_path = str(item.get("file_path") or "").strip()
        file_id = str(item.get("file_id") or "").strip()
        if not file_path and file_id:
            try:
                r = self.session.get(f"{API_BASE}/getFile", params={"file_id": file_id}, timeout=(CONNECT_TIMEOUT, SEND_TIMEOUT))
                if r.ok:
                    data = self._json(r)
                    result = data.get("result") if isinstance(data.get("result"), dict) else {}
                    file_path = str(result.get("file_path") or result.get("path") or "").strip()
            except Exception as exc:
                log.warning("official getFile failed | %s: %s", type(exc).__name__, exc)
        if file_path:
            candidates.extend([
                f"{API_ROOT}/file/bot{BOT_TOKEN}/{file_path.lstrip('/')}",
                f"{API_BASE}/file/{file_path.lstrip('/')}",
            ])
        last_error = "MEDIA_DOWNLOAD_SOURCE_UNAVAILABLE"
        for url in candidates:
            try:
                r = self.session.get(url, timeout=(CONNECT_TIMEOUT, 60), stream=True)
                if not r.ok:
                    last_error = f"HTTP_{r.status_code}"
                    continue
                with destination.open("wb") as f:
                    for chunk in r.iter_content(1024 * 256):
                        if chunk:
                            f.write(chunk)
                if destination.is_file() and destination.stat().st_size > 0:
                    return destination
            except Exception as exc:
                last_error = f"{type(exc).__name__}:{exc}"
        raise RuntimeError(last_error)


class BotCore(BotCore):
    MEOW_MIN_BUY = 100
    MEOW_UNIT_TOMAN = 40
    MEOW_UNIT_RIAL = 400
    ADMIN_MEDIA_DIR = Path("/opt/zivo60/official_campaign_media")

    def __init__(self, store: Store, transport: Optional[SoroushOfficialTransport]) -> None:
        super().__init__(store, transport)
        self._meow_state: Dict[str, Dict[str, Any]] = {}

    # ----- common identity/media helpers -----
    @staticmethod
    def _raw_message(raw: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        msg = raw.get("message")
        return msg if isinstance(msg, dict) else raw

    @classmethod
    def _sender_meta(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        msg = cls._raw_message(raw)
        obj = msg.get("from") if isinstance(msg.get("from"), dict) else {}
        return {
            "id": safe_id(obj.get("id")),
            "username": str(obj.get("username") or "").strip().lstrip("@"),
            "first_name": str(obj.get("first_name") or obj.get("name") or "").strip(),
        }

    @classmethod
    def _forwarded_user_reference(cls, raw: Dict[str, Any]) -> str:
        msg = cls._raw_message(raw)
        candidates: List[Any] = [msg.get("forward_from"), msg.get("forwardFrom"), msg.get("forward")]
        origin = msg.get("forward_origin") or msg.get("forwardOrigin")
        if isinstance(origin, dict):
            candidates.extend([origin.get("sender_user"), origin.get("from"), origin.get("sender")])
        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            uid = safe_id(obj.get("id") or obj.get("user_id") or obj.get("userId"))
            if uid:
                return uid
            username = str(obj.get("username") or "").strip().lstrip("@")
            if username:
                return "@" + username
        return ""

    @classmethod
    def _incoming_media(cls, raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg = cls._raw_message(raw)
        caption = normalize_text(msg.get("caption") or msg.get("text") or "")
        photos = msg.get("photo")
        if isinstance(photos, list) and photos:
            p = photos[-1] if isinstance(photos[-1], dict) else {}
            fid = safe_id(p.get("file_id") or p.get("fileId") or p.get("id"))
            if fid:
                return {"type":"photo","file_id":fid,"text":caption,"file_path":str(p.get("file_path") or ""),"url":str(p.get("url") or "")}
        for key, kind in (("voice","voice"),("video","video"),("document","document"),("audio","document"),("animation","video")):
            obj = msg.get(key)
            if isinstance(obj, dict):
                fid = safe_id(obj.get("file_id") or obj.get("fileId") or obj.get("id"))
                if fid:
                    return {"type":kind,"file_id":fid,"text":caption,"file_name":str(obj.get("file_name") or ""),"file_path":str(obj.get("file_path") or ""),"url":str(obj.get("url") or "")}
        attachment = msg.get("attachment") or msg.get("media")
        if isinstance(attachment, dict):
            kind = str(attachment.get("type") or "document").lower()
            if kind not in {"photo","video","voice","document"}: kind="document"
            fid=safe_id(attachment.get("file_id") or attachment.get("fileId") or attachment.get("id"))
            if fid:
                return {"type":kind,"file_id":fid,"text":caption,"file_name":str(attachment.get("file_name") or ""),"file_path":str(attachment.get("file_path") or ""),"url":str(attachment.get("url") or "")}
        return None

    def _remember_official_identity(self, raw: Dict[str, Any], user_id: str) -> None:
        meta=self._sender_meta(raw)
        try:
            self._ipc("main", {"op":"official_gate","action":"seen","requester_user_id":int(user_id),"username":meta.get("username"),"first_name":meta.get("first_name")}, timeout=4.0)
        except Exception:
            pass

    def _economy_markup17(self) -> Dict[str, Any]:
        return {"inline_keyboard":[
            [{"text":"🐱 دریافت Meow","callback_data":"eco:meow"},{"text":"💰 موجودی Meow","callback_data":"eco:profile"}],
            [{"text":"🔁 انتقال Meow","callback_data":"meow:transfer"},{"text":"🛒 خرید Meow","callback_data":"meow:buy"}],
            [{"text":"🎁 کد هدیه Meow","callback_data":"meow:gift"}],
            [{"text":"🐾 فروشگاه Pet","callback_data":"eco:petshop"},{"text":"❤️ Pet من","callback_data":"eco:pet"}],
            [{"text":"🏡 فروشگاه خانه","callback_data":"eco:houseshop"},{"text":"🏘 خانه‌های من","callback_data":"eco:houses"}],
            [{"text":"🏠 پنل اصلی","callback_data":"menu:home"}],
        ]}

    def _send_economy_menu(self, chat_id: str) -> str:
        text=("🐱 اقتصاد Meow ZIVO\n━━━━━━━━━━━━━━━━━━\n"
              "Meow را بگیر، انتقال بده، مستقیم بخر یا برای دوستت شارژ کن.\n"
              "Gift Code هم می‌تونی بسازی و به هرکسی بدی.\n\n"
              "🔐 برای دریافت انتقال/خرید هدیه، مقصد فقط باید یک‌بار بات رسمی ZIVO را Start کرده باشد؛ پیوی اکانت‌های اجرایی لازم نیست.")
        self._send(chat_id,text,reply_markup=self._economy_markup17()); return text

    def _target_label(self, row: Dict[str, Any]) -> str:
        uid=int(row.get("user_id") or row.get("id") or 0); name=str(row.get("first_name") or "").strip(); username=str(row.get("username") or "").strip().lstrip("@")
        bits=[]
        if name: bits.append(name)
        if username: bits.append("@"+username)
        bits.append(str(uid))
        return " · ".join(bits)

    def _resolve_target_from_raw(self, user_id: str, raw: Dict[str, Any], body: str) -> Dict[str, Any]:
        ref=self._forwarded_user_reference(raw) or normalize_text(body).strip()
        if not ref:
            return {"ok":False,"error":"TARGET_REFERENCE_EMPTY"}
        try:
            return self._ipc("main",{"op":"meow_commerce","action":"resolve_target","requester_user_id":int(user_id),"reference":ref},timeout=6.0)
        except Exception as exc:
            return {"ok":False,"error":f"{type(exc).__name__}:{exc}"}

    def _official_not_started_text(self) -> str:
        return ("⛔ این کاربر هنوز بات رسمی ZIVO را Start نکرده.\n\n"
                "ازش بخواه وارد بات رسمی ZIVO بشه و /start بزنه. بهتره کانال‌های ZIVOHELP و ZIVOCMD رو هم داشته باشه؛ بعد دوباره همین عملیات رو انجام بده.\n\n"
                "ℹ️ لازم نیست پیوی هیچ‌کدوم از اکانت‌های main / acc2 / acc3 رو باز کنه.")

    # ----- Meow transfer / buy / gift code -----
    def _meow_transfer_start(self,user_id:str,chat_id:str)->str:
        self._meow_state[user_id]={"stage":"transfer_amount","kind":"transfer"}
        text="🔁 انتقال Meow\n━━━━━━━━━━━━━━━━━━\nتعداد Meow برای انتقال رو بفرست.\nحداقل انتقال: 20 Meow\n\nبرای لغو بنویس: لغو"
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"❌ لغو","callback_data":"meow:cancel"}]]}); return text

    def _meow_buy_start(self,user_id:str,chat_id:str)->str:
        self._meow_state[user_id]={"stage":"buy_who","kind":"purchase"}
        text=("🛒 خرید Meow\n━━━━━━━━━━━━━━━━━━\n"
              "هر 1 Meow = 40 تومان\nحداقل خرید = 100 Meow\n\nبرای چه کسی می‌خوای شارژ کنی؟")
        markup={"inline_keyboard":[[{"text":"👤 برای خودم","callback_data":"meow:buy:self"},{"text":"🎁 برای شخص دیگر","callback_data":"meow:buy:other"}],[{"text":"❌ لغو","callback_data":"meow:cancel"}]]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _meow_gift_menu(self,user_id:str,chat_id:str)->str:
        text=("🎁 کد هدیه Meow\n━━━━━━━━━━━━━━━━━━\n"
              "کد هدیه یک‌بارمصرفه و هرکس واردش کنه، مقدار Meow مستقیم به حساب رسمی ZIVO اون شخص اضافه می‌شه.\n\n"
              "کدهای جدید با ZIVO شروع می‌شن و 8 رقم دارن.")
        markup={"inline_keyboard":[[{"text":"🎟 وارد کردن کد هدیه","callback_data":"meow:gift:redeem"}],[{"text":"🛍 خرید کد هدیه","callback_data":"meow:gift:buy"}],[{"text":"↩️ اقتصاد Meow","callback_data":"menu:economy"}]]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _meow_amount_preview(self,user_id:str,chat_id:str,state:Dict[str,Any])->str:
        amount=int(state.get("amount") or 0); rial=amount*self.MEOW_UNIT_RIAL; toman=amount*self.MEOW_UNIT_TOMAN
        target=state.get("target") or {}; who="کد هدیه" if state.get("kind")=="gift" else self._target_label(target)
        text=("🧾 پیش‌فاکتور Meow\n━━━━━━━━━━━━━━━━━━\n"
              f"🐱 تعداد: {amount:,} Meow\n🎯 مقصد: {who}\n"
              f"💵 قیمت واحد: {self.MEOW_UNIT_TOMAN:,} تومان\n"
              f"💰 مبلغ کل: {toman:,} تومان\n💳 معادل: {rial:,} ریال\n\n"
              "اگر تعداد و مقصد درسته، تأیید کن.")
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"✅ تأیید مقدار","callback_data":"meow:amount:confirm"}],[{"text":"❌ لغو","callback_data":"meow:cancel"}]]}); return text

    def _meow_create_order(self,user_id:str,chat_id:str)->str:
        st=self._meow_state.get(user_id) or {}; amount=int(st.get("amount") or 0); kind=st.get("kind")
        if amount < self.MEOW_MIN_BUY: return self._send_economy_menu(chat_id)
        action="create_meow_gift_order" if kind=="gift" else "create_meow_order"
        payload={"op":"premium","action":action,"requester_user_id":int(user_id),"meow_amount":amount}
        if kind!="gift": payload["target_user_id"]=int((st.get("target") or {}).get("user_id") or 0)
        try: res=self._ipc("main",payload,timeout=8.0)
        except Exception as exc: res={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
        if not res.get("ok"):
            text=f"❌ سفارش ساخته نشد: {res.get('error') or 'FAILED'}"; self._send(chat_id,text,reply_markup=self._economy_markup17()); return text
        order=res.get("order") or {}; oid=int(order.get("order_id") or 0)
        st.update({"stage":"coupon_choice","order_id":oid,"order":order}); self._meow_state[user_id]=st
        text=("🎟 کد تخفیف داری؟\n━━━━━━━━━━━━━━━━━━\n"
              f"🐱 {amount:,} Meow\n💰 مبلغ اولیه: {int(order.get('amount_rial') or 0):,} ریال\n\n"
              "اگه کد داری واردش کن؛ اگه نداری مستقیم ادامه بده.")
        markup={"inline_keyboard":[[{"text":"🎟 کد تخفیف دارم","callback_data":"meow:coupon:yes"}],[{"text":"➡️ ادامه بدون تخفیف","callback_data":"meow:coupon:skip"}],[{"text":"❌ لغو سفارش","callback_data":f"meow:order:cancel:{oid}"}]]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _meow_final_preview(self,user_id:str,chat_id:str)->str:
        st=self._meow_state.get(user_id) or {}; oid=int(st.get("order_id") or 0)
        try: res=self._ipc("main",{"op":"premium","action":"order","requester_user_id":int(user_id),"order_ref":oid},timeout=6.0)
        except Exception: res={}
        order=res.get("order") or st.get("order") or {}; st["order"]=order; st["stage"]="final_confirm"; self._meow_state[user_id]=st
        original=int(order.get("original_amount_rial") or order.get("amount_rial") or 0); final=int(order.get("amount_rial") or 0); pct=int(order.get("discount_percent") or 0)
        lines=["✅ جمع‌بندی نهایی سفارش","━━━━━━━━━━━━━━━━━━",f"🐱 تعداد: {int(order.get('meow_amount') or st.get('amount') or 0):,} Meow",f"💵 مبلغ اولیه: {original:,} ریال"]
        if pct: lines += [f"🎟 تخفیف: {pct}٪",f"💚 مبلغ بعد تخفیف: {final:,} ریال"]
        else: lines += ["🎟 تخفیف: ندارد",f"💳 مبلغ پرداخت: {final:,} ریال"]
        lines += ["","برای رفتن به صفحه پرداخت تأیید کن."]
        self._send(chat_id,"\n".join(lines),reply_markup={"inline_keyboard":[[{"text":"✅ تأیید و رفتن به پرداخت","callback_data":"meow:final:confirm"}],[{"text":"❌ لغو","callback_data":f"meow:order:cancel:{oid}"}]]}); return "\n".join(lines)

    def _meow_payment_page(self,user_id:str,chat_id:str,order_id:int)->str:
        try: z=self._ipc("main",{"op":"premium","action":"zibal","requester_user_id":int(user_id),"order_ref":int(order_id)},timeout=20.0)
        except Exception as exc: z={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
        order=z.get("order") or {}; url=str(z.get("payment_url") or "")
        self._watch_payment(user_id,chat_id,order_id)
        lines=["💳 پرداخت Meow","━━━━━━━━━━━━━━━━━━",f"🔖 سفارش: {order.get('order_code') or order_id}",f"🐱 تعداد: {int(order.get('meow_amount') or 0):,} Meow",f"💰 مبلغ: {int(order.get('amount_rial') or 0):,} ریال","","بعد از پرداخت برگرد و «🔄 بررسی پرداخت» رو بزن؛ ZIVO هم به‌صورت خودکار وضعیت رو بررسی می‌کنه."]
        rows=[]
        if url: rows.append([{"text":"💳 ورود مستقیم به درگاه","url":url}])
        rows.append([{"text":"💳 کارت‌به‌کارت","callback_data":f"meow:card:{order_id}"}])
        rows.append([{"text":"🔄 بررسی پرداخت","callback_data":f"meow:check:{order_id}"}])
        rows.append([{"text":"❌ لغو سفارش","callback_data":f"meow:order:cancel:{order_id}"}])
        self._send(chat_id,"\n".join(lines),reply_markup={"inline_keyboard":rows}); return "\n".join(lines)

    def _meow_card_page(self,user_id:str,chat_id:str,order_id:int)->str:
        try: res=self._ipc("main",{"op":"premium","action":"card","requester_user_id":int(user_id),"order_ref":int(order_id)},timeout=8.0)
        except Exception: res={"ok":False}
        if not res.get("ok"):
            text="🟠 کارت‌به‌کارت الان فعال نیست."; self._send(chat_id,text); return text
        card=str(res.get("card_number") or ""); rial=int(res.get("amount_rial") or 0)
        st=self._meow_state.setdefault(user_id,{}); st.update({"card_number":card,"card_amount_rial":rial,"order_id":order_id})
        text=f"💳 کارت‌به‌کارت Meow\n━━━━━━━━━━━━━━━━━━\n💳 کارت: {card}\n👤 به نام: {res.get('card_holder') or '—'}\n💵 مبلغ: {rial:,} ریال\n\nبرای کپی راحت، روی یکی از دکمه‌های پایین بزن تا مقدار به‌تنهایی برات ارسال بشه."
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"📋 شماره کارت","callback_data":"meow:copy:card"},{"text":"📋 مبلغ ریال","callback_data":"meow:copy:amount"}],[{"text":"🔄 بررسی پرداخت","callback_data":f"meow:check:{order_id}"}],[{"text":"❌ لغو","callback_data":f"meow:order:cancel:{order_id}"}]]}); return text

    def _meow_success(self,user_id:str,chat_id:str,order:Dict[str,Any],order_id:int)->str:
        kind=str(order.get("order_kind") or ""); amount=int(order.get("meow_amount") or 0)
        if kind=="meow_gift_code":
            code=str(order.get("gift_code") or "")
            text=("🎉 پرداخت موفق بود · کد هدیه ساخته شد\n━━━━━━━━━━━━━━━━━━\n"
                  f"🐱 اعتبار: {amount:,} Meow\n🎁 کد هدیه:\n{code}\n\n"
                  "این کد یک‌بار مصرفه. هرکس در ZIVO واردش کنه، Meow همون لحظه به حسابش اضافه می‌شه.")
            self._meow_state[user_id]={"gift_code":code}
            markup={"inline_keyboard":[[{"text":"📋 نمایش کد برای کپی","callback_data":"meow:copy:gift"}],[{"text":"🎁 کدهای هدیه","callback_data":"meow:gift"},{"text":"🐱 اقتصاد Meow","callback_data":"menu:economy"}],[{"text":"🏠 پنل اصلی","callback_data":"menu:home"}]]}
        else:
            target=int(order.get("target_user_id") or 0); self_target=target==int(user_id)
            text=("🎉 پرداخت موفق بود · Meow شارژ شد\n━━━━━━━━━━━━━━━━━━\n"
                  f"🐱 مقدار: {amount:,} Meow\n🎯 مقصد: {'حساب خودت' if self_target else target}\n"
                  f"🔖 سفارش: {order.get('order_code') or order_id}\n\n✅ شارژ با موفقیت انجام شد.")
            markup={"inline_keyboard":[[{"text":"💰 موجودی Meow","callback_data":"eco:profile"},{"text":"🔁 انتقال Meow","callback_data":"meow:transfer"}],[{"text":"🏠 پنل اصلی","callback_data":"menu:home"}]]}
        self._send(chat_id,text,reply_markup=markup); return text

    # ----- locks -----
    def _locks_page(self,user_id:str,chat_id:str,page:int=0)->str:
        row=self._active_group(user_id)
        if row is None: return self._send_groups_menu(user_id,chat_id)
        try: res=self._ipc(str(row.get("account_key") or "main"),{"op":"official_group_locks","action":"list","requester_user_id":int(user_id),"group_id":int(row.get("group_id") or 0)},timeout=8.0)
        except Exception as exc: res={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
        if not res.get("ok"):
            text=f"❌ دریافت قفل‌ها ناموفق بود: {res.get('error') or 'FAILED'}"; self._send(chat_id,text); return text
        locks=list(res.get("locks") or []); per=6; pages=max(1,(len(locks)+per-1)//per); page=max(0,min(pages-1,int(page))); chunk=locks[page*per:(page+1)*per]
        lines=["🧱 مدیریت قفل‌های گروه","━━━━━━━━━━━━━━━━━━",f"🏷 {row.get('title') or 'گروه'}",f"📄 صفحه {page+1}/{pages}",""]
        rows=[]
        for item in chunk:
            on=bool(item.get("enabled")); name=str(item.get("name") or ""); lines.append(f"{'🟢' if on else '⚪️'} {name} · اخطار {int(item.get('max_warnings') or 3)} · AutoBan {'ON' if item.get('auto_ban') else 'OFF'}")
            rows.append([{"text":f"{'🔓 خاموش' if on else '🔒 روشن'} · {name}","callback_data":f"locks:t:{page}:{name}"}])
            if res.get("advanced_allowed"):
                rows.append([{"text":"➖ اخطار","callback_data":f"locks:w:-1:{page}:{name}"},{"text":"➕ اخطار","callback_data":f"locks:w:1:{page}:{name}"},{"text":"🚫 AutoBan" if item.get('auto_ban') else "✅ AutoBan","callback_data":f"locks:b:{page}:{name}"}])
        nav=[]
        if page>0: nav.append({"text":"⬅️ قبلی","callback_data":f"locks:p:{page-1}"})
        if page<pages-1: nav.append({"text":"بعدی ➡️","callback_data":f"locks:p:{page+1}"})
        if nav: rows.append(nav)
        if not res.get("advanced_allowed"): lines.extend(["","💎 تنظیم اخطار اختصاصی و AutoBan هر قفل از GOLD به بالا فعال می‌شه."])
        rows.append([{"text":"🎛 مدیریت گروه","callback_data":"ctl:current"}])
        text="\n".join(lines); self._send(chat_id,text,reply_markup={"inline_keyboard":rows}); return text

    def _lock_action(self,user_id:str,chat_id:str,action:str,name:str,page:int,delta:int=0)->str:
        row=self._active_group(user_id)
        if row is None: return self._send_groups_menu(user_id,chat_id)
        payload={"op":"official_group_locks","action":action,"requester_user_id":int(user_id),"group_id":int(row.get("group_id") or 0),"lock_name":name}
        if delta: payload["delta"]=delta
        try: res=self._ipc(str(row.get("account_key") or "main"),payload,timeout=8.0)
        except Exception as exc: res={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
        if not res.get("ok"):
            if res.get("error")=="GOLD_REQUIRED_FOR_PER_LOCK_PUNISHMENT": text="💎 تنظیم اخطار و AutoBan اختصاصی هر قفل از GOLD به بالا فعاله."
            else: text=f"❌ تغییر قفل انجام نشد: {res.get('error') or 'FAILED'}"
            self._send(chat_id,text); return text
        return self._locks_page(user_id,chat_id,page)

    # ----- richer admin campaigns -----
    def _admin_ads_menu(self,user_id:str,chat_id:str)->str:
        text=("📣 تبلیغات ZIVO\n━━━━━━━━━━━━━━━━━━\n"
              "مقصد رو انتخاب کن. برای مسیر اکانت‌ها می‌تونی فقط پیوی‌ها، فقط گروه‌ها یا هر دو رو هدف بگیری؛ بعد هم main / acc2 / acc3 یا همه اکانت‌ها رو انتخاب کنی.\n\n"
              "محتوا می‌تونه متن، عکس، دو عکس، ویدیو، ویس، فایل یا ترکیب متن+رسانه باشه (تا 4 بخش پشت‌سرهم).")
        markup={"inline_keyboard":[
            [{"text":"🤖 کاربران بات رسمی","callback_data":"admin:adscope:official"}],
            [{"text":"💬 پیوی اکانت‌ها","callback_data":"admin:adscope:private"},{"text":"👥 گروه‌ها","callback_data":"admin:adscope:groups"}],
            [{"text":"💬+👥 پیوی و گروه","callback_data":"admin:adscope:both"}],
            [{"text":"🌐 همه شبکه ZIVO","callback_data":"admin:adscope:all"}],
            [{"text":"↩️ پنل ادمین","callback_data":"admin:home"}],
        ]}; self._send(chat_id,text,reply_markup=markup); return text

    def _admin_account_select(self,user_id:str,chat_id:str,scope:str)->str:
        self._admin_state[user_id]={"stage":"ad_account","scope":scope,"items":[]}
        text="⚡ اکانت‌های ارسال\n━━━━━━━━━━━━━━━━━━\nکدوم اکانت‌های اجرایی در Campaign شرکت کنن؟"
        markup={"inline_keyboard":[[{"text":"1️⃣ main","callback_data":"admin:adacct:main"},{"text":"2️⃣ acc2","callback_data":"admin:adacct:acc2"}],[{"text":"3️⃣ acc3","callback_data":"admin:adacct:acc3"},{"text":"🌐 همه اکانت‌ها","callback_data":"admin:adacct:all"}],[{"text":"❌ لغو","callback_data":"admin:home"}]]}
        self._send(chat_id,text,reply_markup=markup); return text

    def _admin_begin_collect(self,user_id:str,chat_id:str,scope:str,account_keys:List[str])->str:
        self._admin_state[user_id]={"stage":"ad_collect","scope":scope,"account_keys":account_keys,"items":[]}
        text=("🧩 ساخت تبلیغ چندرسانه‌ای\n━━━━━━━━━━━━━━━━━━\n"
              "حالا محتوا رو بفرست؛ هر پیام یک بخش از تبلیغه.\n"
              "پشتیبانی: متن، عکس، ویدیو، ویس و فایل. می‌تونی مثلاً «متن + دو عکس» یا «ویس + متن» بفرستی.\n\n"
              "حداکثر 4 بخش. وقتی تموم شد روی «✅ پایان و پیش‌نمایش» بزن.")
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"✅ پایان و پیش‌نمایش","callback_data":"admin:adpreview"}],[{"text":"🗑 پاک کردن بخش‌ها","callback_data":"admin:adclear"},{"text":"❌ لغو","callback_data":"admin:home"}]]}); return text

    def _admin_add_part(self,user_id:str,chat_id:str,raw:Dict[str,Any],body:str)->str:
        st=self._admin_state.get(user_id) or {}; items=list(st.get("items") or [])
        if len(items)>=4:
            text="حداکثر 4 بخش برای هر تبلیغ قابل ثبت است. الان پیش‌نمایش رو باز کن."; self._send(chat_id,text); return text
        media=self._incoming_media(raw)
        if media: item=media
        elif normalize_text(body).strip(): item={"type":"text","text":normalize_text(body).strip()[:3500]}
        else: return ""
        items.append(item); st["items"]=items; self._admin_state[user_id]=st
        labels={"text":"متن","photo":"عکس","video":"ویدیو","voice":"ویس","document":"فایل"}
        text=f"✅ بخش {len(items)} ثبت شد · {labels.get(item.get('type'),'رسانه')}\nمی‌تونی بخش بعدی رو بفرستی یا پیش‌نمایش رو باز کنی."
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"✅ پایان و پیش‌نمایش","callback_data":"admin:adpreview"}],[{"text":"🗑 شروع دوباره","callback_data":"admin:adclear"}]]}); return text

    def _admin_parts_preview(self,user_id:str,chat_id:str)->str:
        st=self._admin_state.get(user_id) or {}; items=list(st.get("items") or [])
        if not items:
            text="هنوز محتوایی ثبت نشده."; self._send(chat_id,text); return text
        scope=str(st.get("scope") or "official"); keys=st.get("account_keys") or []
        labels={"official":"کاربران بات رسمی","private":"پیوی اکانت‌ها","groups":"گروه‌ها","both":"پیوی+گروه","all":"کل شبکه"}
        lines=["📣 پیش‌نمایش Campaign","━━━━━━━━━━━━━━━━━━",f"🎯 مقصد: {labels.get(scope,scope)}",f"⚡ اکانت‌ها: {', '.join(keys) if keys else '—'}","",f"🧩 تعداد بخش‌ها: {len(items)}"]
        for i,item in enumerate(items,1):
            kind=str(item.get("type") or "text"); summary=(str(item.get("text") or "").replace("\n"," ")[:80] or kind)
            lines.append(f"{i}. {kind} · {summary}")
        lines.extend(["","با تأیید، بخش‌ها به همین ترتیب ارسال می‌شن."])
        text="\n".join(lines); self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"✅ شروع ارسال","callback_data":"admin:adsend17"}],[{"text":"✏️ ادامه ویرایش","callback_data":"admin:adcontinue"},{"text":"❌ لغو","callback_data":"admin:home"}]]}); return text

    def _official_broadcast_worker17(self,user_ids:List[int],items:List[Dict[str,Any]])->None:
        with self._official_campaign_lock: self._official_campaign={"running":True,"sent":0,"failed":0,"total":len(user_ids),"started_at":time.time()}
        for uid in user_ids:
            ok=True
            for item in items:
                try:
                    if self.transport is None: raise RuntimeError("TRANSPORT_UNAVAILABLE")
                    if item.get("type")=="text": self.transport.send_text(str(uid),str(item.get("text") or "")[:3900])
                    else: self.transport.send_media(str(uid),item,str(item.get("text") or ""))
                    time.sleep(0.08)
                except Exception: ok=False; break
            with self._official_campaign_lock:
                self._official_campaign["sent" if ok else "failed"] += 1
            time.sleep(0.12)
        with self._official_campaign_lock: self._official_campaign["running"]=False

    def _admin_send_parts(self,user_id:str,chat_id:str)->str:
        st=self._admin_state.get(user_id) or {}; scope=str(st.get("scope") or "official"); items=list(st.get("items") or []); keys=list(st.get("account_keys") or [])
        if not items: return self._admin_ads_menu(user_id,chat_id)
        pieces=[]; batch_ids=[]
        account_scope = "both" if scope=="all" else scope
        if scope in {"private","groups","both","all"}:
            self.ADMIN_MEDIA_DIR.mkdir(parents=True,exist_ok=True)
            for idx,item in enumerate(items,1):
                content=dict(item)
                if content.get("type")!="text":
                    if self.transport is None: pieces.append("❌ دانلود رسانه: Transport unavailable"); continue
                    ext={"photo":".jpg","video":".mp4","voice":".ogg","document":".bin"}.get(str(content.get("type")),".bin")
                    fname=str(content.get("file_name") or "");
                    if fname and Path(fname).suffix: ext=Path(fname).suffix[:12]
                    dest=self.ADMIN_MEDIA_DIR/f"official17_{int(time.time())}_{idx}_{random.randint(1000,9999)}{ext}"
                    try: self.transport.download_media_item(content,dest); content={"type":content.get("type"),"text":content.get("text") or "","path":str(dest)}
                    except Exception as exc: pieces.append(f"❌ بخش {idx} رسانه: {type(exc).__name__}"); continue
                try: res=self._ipc("main",{"op":"official_admin","action":"campaign_create","requester_user_id":int(user_id),"scope":account_scope,"account_keys":keys,"content":content},timeout=10.0)
                except Exception as exc: res={"ok":False,"error":f"{type(exc).__name__}:{exc}"}
                if res.get("ok"): batch_ids.append(str(res.get("batch_id") or ""))
                else: pieces.append(f"❌ بخش {idx}: {res.get('error') or 'FAILED'}")
            if batch_ids: pieces.append(f"📡 Campaign اکانت‌ها: {len(batch_ids)} بخش در صف")
        if scope in {"official","all"}:
            try: r=self._ipc("main",{"op":"official_admin","action":"official_users","requester_user_id":int(user_id)},timeout=8.0); ids=[int(x) for x in r.get("user_ids") or [] if int(x)>0]
            except Exception: ids=[]
            if ids:
                threading.Thread(target=self._official_broadcast_worker17,args=(ids,items),daemon=True,name="zivo-official17-broadcast").start(); pieces.append(f"🤖 Official: شروع ارسال به {len(ids):,} کاربر")
            else: pieces.append("🤖 Official: مخاطب فعالی پیدا نشد")
        st.update({"stage":"ad_running","batch_ids":batch_ids}); self._admin_state[user_id]=st
        text="✅ Campaign شروع شد\n━━━━━━━━━━━━━━━━━━\n"+"\n".join(pieces)
        self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"📊 وضعیت ارسال","callback_data":"admin:status"}],[{"text":"👑 پنل ادمین","callback_data":"admin:home"}]]}); return text

    def _admin_campaign_status(self,user_id:str,chat_id:str)->str:
        st=self._admin_state.get(user_id) or {}; bids=list(st.get("batch_ids") or []); old=str(st.get("batch_id") or "")
        with self._official_campaign_lock: local=dict(self._official_campaign)
        lines=["📊 وضعیت ارسال ZIVO","━━━━━━━━━━━━━━━━━━",f"🤖 Official: {'در حال ارسال' if local.get('running') else 'آماده'} · موفق {int(local.get('sent') or 0):,} · ناموفق {int(local.get('failed') or 0):,} / {int(local.get('total') or 0):,}"]
        if bids or old:
            try: res=self._ipc("main",{"op":"official_admin","action":"campaign_status","requester_user_id":int(user_id),"batch_ids":bids,"batch_id":old},timeout=8.0)
            except Exception: res={"ok":False}
            if res.get("ok"):
                lines.append("\n📡 Account Campaigns:")
                for r in res.get("jobs") or []: lines.append(f"• {r.get('account_key')} · {r.get('scope')} · {r.get('content_type')} · {r.get('status')} · {int(r.get('success_count') or 0):,}/{int(r.get('total_targets') or 0):,}")
        text="\n".join(lines); self._send(chat_id,text,reply_markup={"inline_keyboard":[[{"text":"🔄 بروزرسانی","callback_data":"admin:status"}],[{"text":"👑 پنل ادمین","callback_data":"admin:home"}]]}); return text

    # ----- event/callback routing -----
    def handle_callback(self,raw:Dict[str,Any])->Optional[str]:
        cb=normalize_callback(raw)
        if cb is None: return None
        d=cb.data
        low=d.casefold()
        # answer only for callbacks handled here; super answers the others.
        def ack():
            if self.transport is not None: self.transport.answer_callback(cb.callback_id)
        if low in {"eco:meow","eco:profile","eco:petshop","eco:pet","eco:houseshop","eco:houses"}:
            ack(); uid=cb.sender_id; chat=cb.chat_id
            command={"eco:meow":"میو","eco:profile":"موجودی میو","eco:petshop":"فروشگاه پت","eco:pet":"پت من","eco:houseshop":"فروشگاه خانه","eco:houses":"خانه های من"}[low]
            text=self._social_private(uid,command); self._send(chat,text,reply_markup=self._economy_markup17()); return text
        if low.startswith("meow:"):
            ack(); uid=cb.sender_id; chat=cb.chat_id
            if low=="meow:transfer": return self._meow_transfer_start(uid,chat)
            if low=="meow:buy": return self._meow_buy_start(uid,chat)
            if low=="meow:gift": return self._meow_gift_menu(uid,chat)
            if low=="meow:cancel": self._meow_state.pop(uid,None); self._ipc("main",{"op":"meow_commerce","action":"transfer_cancel","requester_user_id":int(uid)},timeout=4.0); return self._send_economy_menu(chat)
            if low=="meow:buy:self":
                r=self._ipc("main",{"op":"meow_commerce","action":"resolve_target","requester_user_id":int(uid),"reference":int(uid)},timeout=5.0)
                if not r.get("ok"):
                    try: self._ipc("main",{"op":"official_gate","action":"seen","requester_user_id":int(uid)},timeout=4.0)
                    except Exception: pass
                    r=self._ipc("main",{"op":"meow_commerce","action":"resolve_target","requester_user_id":int(uid),"reference":int(uid)},timeout=5.0)
                self._meow_state[uid]={"stage":"buy_amount","kind":"purchase","target":r.get("user") or {"user_id":int(uid)}}; text="🐱 تعداد Meow رو وارد کن. حداقل خرید 100 تاست."; self._send(chat,text); return text
            if low=="meow:buy:other": self._meow_state[uid]={"stage":"buy_target","kind":"purchase"}; text="🎯 گیرنده رو مشخص کن:\n• آیدی عددی\n• @username\n• یا پیام اون شخص رو برای ZIVO فوروارد کن\n\nگیرنده باید قبلاً بات رسمی ZIVO رو Start کرده باشه."; self._send(chat,text); return text
            if low=="meow:gift:redeem": self._meow_state[uid]={"stage":"gift_redeem","kind":"redeem"}; text="🎟 کد هدیه رو بفرست. نمونه: ZIVO12345678"; self._send(chat,text); return text
            if low=="meow:gift:buy": self._meow_state[uid]={"stage":"gift_amount","kind":"gift"}; text="🎁 چند Meow داخل کد هدیه می‌خوای؟ حداقل 100 Meow."; self._send(chat,text); return text
            if low=="meow:amount:confirm": return self._meow_create_order(uid,chat)
            if low=="meow:coupon:yes": self._meow_state.setdefault(uid,{})["stage"]="coupon_input"; text="🎟 کد تخفیف رو بفرست."; self._send(chat,text); return text
            if low=="meow:coupon:skip": return self._meow_final_preview(uid,chat)
            if low=="meow:final:confirm": return self._meow_payment_page(uid,chat,int((self._meow_state.get(uid) or {}).get("order_id") or 0))
            if low.startswith("meow:pay:zibal:"): return self._meow_payment_page(uid,chat,int(d.rsplit(":",1)[1]))
            m=re.fullmatch(r"meow:card:(\d+)",low)
            if m: return self._meow_card_page(uid,chat,int(m.group(1)))
            m=re.fullmatch(r"meow:check:(\d+)",low)
            if m:
                oid=int(m.group(1)); res=self._ipc("main",{"op":"premium","action":"check_payment","requester_user_id":int(uid),"order_ref":oid},timeout=20.0); order=res.get("order") or {}
                if res.get("ok") and res.get("activated"): return self._meow_success(uid,chat,order,oid)
                text="⏳ پرداخت هنوز تأیید نشده. اگر تازه پرداخت کردی چند ثانیه صبر کن و دوباره بررسی کن."; self._send(chat,text,reply_markup={"inline_keyboard":[[{"text":"🔄 بررسی دوباره","callback_data":f"meow:check:{oid}"}]]}); return text
            m=re.fullmatch(r"meow:order:cancel:(\d+)",low)
            if m:
                self._ipc("main",{"op":"premium","action":"cancel","requester_user_id":int(uid),"order_ref":int(m.group(1))},timeout=6.0); self._meow_state.pop(uid,None); text="✅ سفارش لغو شد."; self._send(chat,text,reply_markup=self._economy_markup17()); return text
            if low=="meow:copy:card": text=str((self._meow_state.get(uid) or {}).get("card_number") or ""); self._send(chat,text); return text
            if low=="meow:copy:amount": text=str((self._meow_state.get(uid) or {}).get("card_amount_rial") or ""); self._send(chat,text); return text
            if low=="meow:copy:gift": text=str((self._meow_state.get(uid) or {}).get("gift_code") or ""); self._send(chat,text); return text
            if low=="meow:transfer:confirm":
                res=self._ipc("main",{"op":"meow_commerce","action":"transfer_confirm","requester_user_id":int(uid)},timeout=6.0)
                if not res.get("ok"): text=f"❌ انتقال انجام نشد: {res.get('error') or 'FAILED'}"; self._send(chat,text); return text
                tr=res.get("transfer") or {}; target=int(tr.get("recipient_id") or 0); sender=self._sender_meta(raw)
                try:
                    sr=self._ipc("main",{"op":"meow_commerce","action":"resolve_target","requester_user_id":int(uid),"reference":int(uid)},timeout=4.0)
                    sender_label=self._target_label(sr.get("user") or {"user_id":int(uid)}) if sr.get("ok") else uid
                except Exception:
                    sender_label=uid
                text=f"✅ انتقال انجام شد\n🐱 ارسال: {int(tr.get('amount') or 0):,}\n🏦 مالیات: {int(tr.get('tax') or 0):,}\n📥 دریافتی مقصد: {int(tr.get('net_amount') or 0):,}\n💰 موجودی تو: {int(tr.get('sender_balance_after') or 0):,}"
                self._send(chat,text,reply_markup=self._economy_markup17())
                if target and self.transport is not None:
                    try: self.transport.send_text(str(target),f"🎁 Meow دریافت کردی!\n━━━━━━━━━━━━━━━━━━\n👤 از طرف: {sender_label} ({uid})\n🐱 مقدار دریافتی: {int(tr.get('net_amount') or 0):,} Meow\n🏦 مالیات انتقال: {int(tr.get('tax') or 0):,}")
                    except Exception: pass
                self._meow_state.pop(uid,None); return text
            return None
        if low.startswith("locks:"):
            ack(); uid=cb.sender_id; chat=cb.chat_id
            if low=="locks:list": return self._locks_page(uid,chat,0)
            m=re.fullmatch(r"locks:p:(\d+)",low)
            if m: return self._locks_page(uid,chat,int(m.group(1)))
            m=re.fullmatch(r"locks:t:(\d+):(.+)",d,re.I)
            if m: return self._lock_action(uid,chat,"toggle",m.group(2),int(m.group(1)))
            m=re.fullmatch(r"locks:w:(-?\d+):(\d+):(.+)",d,re.I)
            if m: return self._lock_action(uid,chat,"warning_delta",m.group(3),int(m.group(2)),int(m.group(1)))
            m=re.fullmatch(r"locks:b:(\d+):(.+)",d,re.I)
            if m: return self._lock_action(uid,chat,"autoban_toggle",m.group(2),int(m.group(1)))
            return None
        if low.startswith("admin:") and self._is_owner(cb.sender_id):
            if low.startswith("admin:adscope:"):
                ack(); scope=low.rsplit(":",1)[1]
                if scope=="official": return self._admin_begin_collect(cb.sender_id,cb.chat_id,"official",[])
                if scope in {"private","groups","both","all"}: return self._admin_account_select(cb.sender_id,cb.chat_id,scope)
            if low.startswith("admin:adacct:"):
                ack(); choice=low.rsplit(":",1)[1]; st=self._admin_state.get(cb.sender_id) or {}; scope=str(st.get("scope") or "private"); keys=list(IPC_ACCOUNT_KEYS) if choice=="all" else [choice]; return self._admin_begin_collect(cb.sender_id,cb.chat_id,scope,keys)
            if low=="admin:adpreview": ack(); return self._admin_parts_preview(cb.sender_id,cb.chat_id)
            if low=="admin:adclear": ack(); st=self._admin_state.get(cb.sender_id) or {}; return self._admin_begin_collect(cb.sender_id,cb.chat_id,str(st.get("scope") or "official"),list(st.get("account_keys") or []))
            if low=="admin:adcontinue": ack(); st=self._admin_state.get(cb.sender_id) or {}; st["stage"]="ad_collect"; self._admin_state[cb.sender_id]=st; text="✍️ بخش بعدی رو بفرست."; self._send(cb.chat_id,text); return text
            if low=="admin:adsend17": ack(); return self._admin_send_parts(cb.sender_id,cb.chat_id)
        if low=="ctl:q:locks":
            ack(); return self._locks_page(cb.sender_id,cb.chat_id,0)
        return super().handle_callback(raw)

    def handle(self,raw:Dict[str,Any])->Optional[str]:
        msg=normalize_event(raw); rawmsg=self._raw_message(raw)
        sender=safe_id((rawmsg.get("from") or {}).get("id") if isinstance(rawmsg.get("from"),dict) else "") or (msg.sender_id if msg else "")
        chat=safe_id((rawmsg.get("chat") or {}).get("id") if isinstance(rawmsg.get("chat"),dict) else "") or (msg.chat_id if msg else sender)
        body=normalize_text(rawmsg.get("text") or rawmsg.get("caption") or (msg.body if msg else ""))
        # Keep the inherited two-touch onboarding order intact; identity is persisted by that flow.
        # Owner media/text collection must work even when normalize_event marks it non-text.
        if sender and self._is_owner(sender):
            st=self._admin_state.get(sender) or {}
            if str(st.get("stage") or "")=="ad_collect": return self._admin_add_part(sender,chat,raw,body)
        # Meow target/coupon/amount/gift stages accept forwarded/media envelope too.
        if sender and chat==sender:
            st=self._meow_state.get(sender) or {}; stage=str(st.get("stage") or "")
            if stage:
                low=body.casefold().strip()
                if low in {"لغو","cancel"}: self._meow_state.pop(sender,None); return self._send_economy_menu(chat)
                if stage=="transfer_amount":
                    try: amount=int(normalize_text(body).replace(",","").replace("٬","").strip())
                    except Exception: amount=0
                    if amount<20: text="حداقل انتقال 20 Meow است. یک عدد معتبر بفرست."; self._send(chat,text); return text
                    st.update({"amount":amount,"stage":"transfer_target"}); self._meow_state[sender]=st; text="🎯 مقصد رو بفرست: آیدی عددی، @username یا پیامش رو فوروارد کن."; self._send(chat,text); return text
                if stage in {"transfer_target","buy_target"}:
                    res=self._resolve_target_from_raw(sender,raw,body)
                    if not res.get("ok"): text=self._official_not_started_text(); self._send(chat,text); return text
                    target=res.get("user") or {}; st["target"]=target
                    if stage=="transfer_target":
                        try: p=self._ipc("main",{"op":"meow_commerce","action":"transfer_prepare","requester_user_id":int(sender),"target_user_id":int(target.get('user_id') or 0),"meow_amount":int(st.get('amount') or 0)},timeout=6.0)
                        except Exception as exc: p={"ok":False,"error":str(exc)}
                        if not p.get("ok"): text=f"❌ انتقال آماده نشد: {p.get('error') or 'FAILED'}"; self._send(chat,text); return text
                        tr=p.get("transfer") or {}; st["stage"]="transfer_confirm"; self._meow_state[sender]=st
                        text=f"🔁 تأیید انتقال\n━━━━━━━━━━━━━━━━━━\n🎯 {self._target_label(target)}\n🐱 ارسال: {int(tr.get('amount') or 0):,}\n🏦 مالیات 2٪: {int(tr.get('tax') or 0):,}\n📥 دریافتی مقصد: {int(tr.get('net_amount') or 0):,}\n💰 موجودی فعلی تو: {int(tr.get('sender_balance') or 0):,}\n\nانتقال انجام بشه؟"
                        self._send(chat,text,reply_markup={"inline_keyboard":[[{"text":"✅ بله، انتقال بده","callback_data":"meow:transfer:confirm"}],[{"text":"❌ لغو","callback_data":"meow:cancel"}]]}); return text
                    st["stage"]="buy_amount"; self._meow_state[sender]=st; text=f"✅ مقصد: {self._target_label(target)}\n\nحالا تعداد Meow رو بفرست. حداقل 100 تا."; self._send(chat,text); return text
                if stage in {"buy_amount","gift_amount"}:
                    try: amount=int(normalize_text(body).replace(",","").replace("٬","").strip())
                    except Exception: amount=0
                    if amount<self.MEOW_MIN_BUY: text="⛔ خرید کمتر از 100 Meow ممکن نیست. یک عدد 100 یا بیشتر بفرست."; self._send(chat,text); return text
                    if stage=="gift_amount": st["kind"]="gift"
                    st.update({"amount":amount,"stage":"amount_confirm"}); self._meow_state[sender]=st; return self._meow_amount_preview(sender,chat,st)
                if stage=="coupon_input":
                    oid=int(st.get("order_id") or 0)
                    try: r=self._ipc("main",{"op":"premium","action":"discount_apply","requester_user_id":int(sender),"order_ref":oid,"code":body.strip()},timeout=6.0)
                    except Exception as exc: r={"ok":False,"error":str(exc)}
                    if not r.get("ok"): text=f"❌ کد تخفیف اعمال نشد: {r.get('error') or 'نامعتبر'}\nدوباره کد رو بفرست یا «لغو» بنویس."; self._send(chat,text); return text
                    st["order"]=r.get("order") or {}; self._meow_state[sender]=st; return self._meow_final_preview(sender,chat)
                if stage=="gift_redeem":
                    try: r=self._ipc("main",{"op":"meow_commerce","action":"gift_redeem","requester_user_id":int(sender),"code":body.strip()},timeout=6.0)
                    except Exception as exc: r={"ok":False,"error":str(exc)}
                    self._meow_state.pop(sender,None)
                    if not r.get("ok"): text=f"❌ کد هدیه قابل استفاده نیست: {r.get('error') or 'INVALID'}"; self._send(chat,text,reply_markup=self._economy_markup17()); return text
                    g=r.get("gift") or {}; creator=int(g.get("creator_user_id") or 0)
                    try: cr=self._ipc("main",{"op":"meow_commerce","action":"resolve_target","requester_user_id":int(sender),"reference":creator},timeout=4.0); creator_label=self._target_label(cr.get("user") or {"user_id":creator}) if creator else str(creator)
                    except Exception: creator_label=str(creator)
                    text=f"🎉 کد هدیه استفاده شد\n━━━━━━━━━━━━━━━━━━\n🎁 کد: {g.get('code')}\n🐱 دریافت کردی: {int(g.get('meow_amount') or 0):,} Meow\n👤 سازنده کد: {creator_label}\n💰 موجودی جدید: {int(g.get('balance_after') or 0):,}"
                    self._send(chat,text,reply_markup=self._economy_markup17()); return text
        return super().handle(raw)

    def _premium_success_page(self,user_id:str,chat_id:str,order:Dict[str,Any],order_id:int)->str:
        if str(order.get("order_kind") or "") in {"meow_purchase","meow_gift_code"}: return self._meow_success(user_id,chat_id,order,order_id)
        return super()._premium_success_page(user_id,chat_id,order,order_id)

    def poll_payment_watch(self)->int:
        count=super().poll_payment_watch()
        # Deliver purchase/gift-code notifications from the controller DB.
        try: res=self._ipc("main",{"op":"meow_commerce","action":"notifications","requester_user_id":int(next(iter(GLOBAL_OWNER_IDS)))},timeout=4.0)
        except Exception: res={}
        for n in res.get("notifications") or []:
            nid=int(n.get("notification_id") or 0); uid=int(n.get("user_id") or 0); success=False
            try:
                if uid>0 and self.transport is not None: self.transport.send_text(str(uid),str(n.get("text") or "")[:3900]); success=True
            except Exception: success=False
            try: self._ipc("main",{"op":"meow_commerce","action":"notification_finish","requester_user_id":int(next(iter(GLOBAL_OWNER_IDS))),"notification_id":nid,"success":success},timeout=3.0)
            except Exception: pass
        return count


class ZivoOfficialApp:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.transport = SoroushOfficialTransport()
        self.store = Store()
        self.core = BotCore(self.store, self.transport)
        self._payment_thread: Optional[threading.Thread] = None

    def request_stop(self, *_: Any) -> None:
        self.stop_event.set()

    def _payment_watch_loop(self) -> None:
        while not self.stop_event.wait(2.0):
            try:
                self.core.poll_payment_watch()
            except Exception:
                log.exception("payment watcher failed")

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        self._payment_thread = threading.Thread(target=self._payment_watch_loop, name="zivo-payment-watch", daemon=True)
        self._payment_thread.start()
        log.info("startup | app=%s version=%s transport=official-bot-api bridge=unix-socket-direct ux=meow-commerce-media-lock-admin-v17", APP_NAME, VERSION)
        log.info("runtime paths | pid=%s core=%s state=memory ipc_accounts=%s", os.getpid(), Path(__file__).resolve(), ",".join(IPC_ACCOUNT_KEYS))
        me = self.transport.get_me()
        log.info("bot authenticated | id=%s username=%s name=%s", me.get("id", ""), me.get("username", ""), me.get("first_name", me.get("name", "")))
        rows = self.core._account_rows()
        log.info("account IPC discovery | online=%s/%s sockets=%s", len(rows), len(IPC_ACCOUNT_KEYS), ",".join(str(ipc_socket_path(k)) for k in IPC_ACCOUNT_KEYS))
        delay = RECONNECT_MIN_SECONDS
        while not self.stop_event.is_set():
            try:
                log.info("starting official getUpdates long polling")
                for raw in self.transport.iter_events(self.stop_event):
                    if self.stop_event.is_set():
                        break
                    try:
                        if isinstance(raw.get("callback_query"), dict):
                            self.core.handle_callback(raw)
                        else:
                            self.core.handle(raw)
                    except Exception:
                        log.exception("event handling failed")
                delay = RECONNECT_MIN_SECONDS
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                log.warning("Bot API polling error | %s | retry=%.1fs", exc, delay)
                self.stop_event.wait(delay)
                delay = min(RECONNECT_MAX_SECONDS, delay * 2.0)
        try:
            self.transport.session.close()
        except Exception:
            pass
        if self._payment_thread is not None and self._payment_thread.is_alive():
            self._payment_thread.join(timeout=3.0)
        log.info("shutdown complete")


def main() -> None:
    ZivoOfficialApp().run()


if __name__ == "__main__":
    main()
