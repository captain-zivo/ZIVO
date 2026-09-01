#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""ZIVO Official Bot v12 for Soroush Plus official Bot Platform.

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
VERSION = "zivo-official12"

# User explicitly requested an embedded token for this build.
BOT_TOKEN = "69669557:_Traf8PaLT5rQmxiIKrhQHV7GoXklGjGwsA"

BASE_DIR = Path("/opt/ZIVO_OFFICIAL_BOT12")
LOG_PATH = BASE_DIR / "zivo_official12.log"

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

HELP_TEXT = """ZIVO | پنل رسمی کنترل اکانت‌بات‌ها
━━━━━━━━━━━━━━━━━━
نسخه: zivo-official12 + zivo60.96.44

اتصال گروه
1) لینک splus.ir/joingroup/... یا لینک عمومی گروه را بفرست.
2) main / acc2 / acc3 آنلاین نمایش داده می‌شوند.
3) اکانت انتخابی همان لحظه با Unix Socket مستقیم Join را اجرا می‌کند.
4) بعد از Join گروه را از «گروه‌های من» انتخاب و کنترل کن.

کنترل گروه
فرمان‌ها مستقیم داخل Router اصلی همان Account اجرا می‌شوند؛ Poll/Notifier/SQLite واسط وجود ندارد.
قفل لینک | باز لینک | لیست قفل
اسپم فعال | اسپم خاموش | پاکسازی اسپم کامل
پاکسازی | پاکسازی 500
خوشامد فعال | سخنگو روشن | قوانین | راهنما و سایر فرمان‌های اصلی

خرید اشتراک
از دکمه «خرید اشتراک» گروه را انتخاب کن، پلن و مدت را بزن و سپس پرداخت با کیف پول یا زیبال را انجام بده.
اشتراک روی همان group_id فعال می‌شود و Premium Engine اصلی ZIVO استفاده می‌شود.

فرمان‌های هدف‌دار
هدف 123456 | بن
هدف 123456 | سکوت
هدف 123456 | اخطار
پیام 987 | پین
پیام 987 | حذف

پیوی خود Accountها در حالت Official-only خاموش است؛ رابط کاربر همین بات رسمی است.
"""

COMMAND_LIST_TEXT = """ZIVO | لیست دستورات رسمی
━━━━━━━━━━━━━━━━━━
/start | پنل | راهنما | لیست دستورات
گروه‌های من | وضعیت اتصال | کنترل گروه | خروج کنترل
خرید اشتراک | اشتراک من | خریدهای من | کیف پول

در حالت کنترل، تمام فرمان‌های Group Router اصلی قابل ارسال‌اند.
هدف [user_id] | [فرمان]
پیام [message_id] | [فرمان]

نمونه:
هدف 123456 | بن
پیام 987 | پین
پاکسازی 500
قفل لینک
اسپم فعال
خوشامد فعال
سخنگو روشن
"""

CAPABILITY_STATUS_TEXT = """ZIVO | وضعیت Official12 + Account 96.44
━━━━━━━━━━━━━━━━━━
- Official Bot API: getUpdates/sendMessage/Callback
- Direct Unix Socket: Official -> main/acc2/acc3
- Join مستقیم بدون SQLite bridge و بدون Poll notifier
- کنترل مستقیم Group Router اصلی
- Social/Meow خصوصی از Account IPC
- خرید اشتراک داخل بات رسمی
- Premium Engine مشترک: Silver/Gold/Diamond، کیف پول، زیبال، وضعیت و تاریخچه سفارش
- فیلتر محتوا: Snapshot جدیدترین 100 پیام
- Bio Guard سخت‌گیرانه ضد دورزدن
- پیوی Accountها در Official-only غیرفعال
"""

MAIN_MENU = {
    "inline_keyboard": [
        [{"text": "اتصال گروه", "callback_data": "bridge:join"}, {"text": "گروه‌های من", "callback_data": "bridge:groups"}],
        [{"text": "کنترل گروه", "callback_data": "ctl:current"}, {"text": "راهنما", "callback_data": "menu:help"}],
        [{"text": "قابلیت‌ها", "callback_data": "menu:capabilities"}, {"text": "لیست دستورات", "callback_data": "menu:commands"}],
        [{"text": "سرگرمی", "callback_data": "menu:fun"}, {"text": "ابزارها", "callback_data": "menu:tools"}],
        [{"text": "خرید اشتراک", "callback_data": "prem:groups"}, {"text": "اشتراک من", "callback_data": "prem:subs"}],
        [{"text": "اقتصاد میو", "callback_data": "menu:economy"}, {"text": "آمار من", "callback_data": "menu:stats"}],
        [{"text": "شناسه", "callback_data": "menu:id"}, {"text": "پینگ", "callback_data": "menu:ping"}],
    ]
}

FUN_MENU = {
    "inline_keyboard": [
        [{"text": "جوک", "callback_data": "fun:جوک"}, {"text": "داستان", "callback_data": "fun:داستان"}],
        [{"text": "فال", "callback_data": "fun:فال"}, {"text": "معما", "callback_data": "fun:معما"}],
        [{"text": "دانستنی", "callback_data": "fun:دانستنی"}, {"text": "چالش", "callback_data": "fun:چالش"}],
        [{"text": "تاس", "callback_data": "fun:تاس"}, {"text": "شیر یا خط", "callback_data": "fun:شیر یا خط"}],
        [{"text": "بازگشت", "callback_data": "menu:home"}],
    ]
}

TOOLS_MENU = {
    "inline_keyboard": [
        [{"text": "تاریخ و ساعت", "callback_data": "tool:time"}],
        [{"text": "راهنمای فونت", "callback_data": "tool:font"}, {"text": "ماشین حساب", "callback_data": "tool:calc"}],
        [{"text": "بازگشت", "callback_data": "menu:home"}],
    ]
}

ECONOMY_MENU = {
    "inline_keyboard": [
        [{"text": "میو", "callback_data": "eco:meow"}, {"text": "موجودی", "callback_data": "eco:profile"}],
        [{"text": "فروشگاه پت", "callback_data": "eco:petshop"}, {"text": "پت من", "callback_data": "eco:pet"}],
        [{"text": "فروشگاه خانه", "callback_data": "eco:houseshop"}, {"text": "خانه‌های من", "callback_data": "eco:houses"}],
        [{"text": "بازگشت", "callback_data": "menu:home"}],
    ]
}

GROUP_CONTROL_MENU = {
    "inline_keyboard": [
        [{"text": "قفل لینک", "callback_data": "ctl:q:lock_link"}, {"text": "باز لینک", "callback_data": "ctl:q:unlock_link"}],
        [{"text": "ضداسپم روشن", "callback_data": "ctl:q:spam_on"}, {"text": "ضداسپم خاموش", "callback_data": "ctl:q:spam_off"}],
        [{"text": "وضعیت اسپم", "callback_data": "ctl:q:spam_status"}, {"text": "پاکسازی اسپم کامل", "callback_data": "ctl:q:spam_cleanup_full"}],
        [{"text": "پاکسازی 100", "callback_data": "ctl:q:cleanup100"}, {"text": "پاکسازی 500", "callback_data": "ctl:q:cleanup500"}],
        [{"text": "خوشامد روشن", "callback_data": "ctl:q:welcome_on"}, {"text": "خوشامد خاموش", "callback_data": "ctl:q:welcome_off"}],
        [{"text": "سخنگو روشن", "callback_data": "ctl:q:speaker_on"}, {"text": "سخنگو خاموش", "callback_data": "ctl:q:speaker_off"}],
        [{"text": "لیست قفل‌ها", "callback_data": "ctl:q:locks"}, {"text": "فرمان آزاد", "callback_data": "ctl:raw"}],
        [{"text": "تغییر گروه", "callback_data": "bridge:groups"}, {"text": "خروج کنترل", "callback_data": "ctl:exit"}],
        [{"text": "پنل اصلی", "callback_data": "menu:home"}],
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
    "cleanup500": "پاکسازی 500",
    "welcome_on": "خوشامد فعال",
    "welcome_off": "خوشامد خاموش",
    "speaker_on": "سخنگو روشن",
    "speaker_off": "سخنگو خاموش",
    "locks": "لیست قفل",
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
        # Official12 deliberately keeps UI/session state in memory. Persistent
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
                    status TEXT NOT NULL DEFAULT 'waiting_account',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pending_group_links_user ON pending_group_links(user_id,status,request_id);
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

    def create_pending_group_link(self, *, user_id: str, chat_id: str, link_kind: str, link_value: str) -> int:
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE pending_group_links SET status='superseded' WHERE user_id=? AND status='waiting_account'",
                (str(user_id),),
            )
            cur = con.execute(
                "INSERT INTO pending_group_links(user_id,chat_id,link_kind,link_value,status,created_at) VALUES(?,?,?,?, 'waiting_account', ?)",
                (str(user_id), str(chat_id), str(link_kind), str(link_value), int(time.time())),
            )
            return int(cur.lastrowid)

    def pending_group_link(self, request_id: int, user_id: str) -> Optional[sqlite3.Row]:
        with self._lock, self._connect() as con:
            return con.execute(
                "SELECT * FROM pending_group_links WHERE request_id=? AND user_id=? LIMIT 1",
                (int(request_id), str(user_id)),
            ).fetchone()

    def mark_pending_group_link_selected(self, request_id: int, account_key: str) -> None:
        with self._lock, self._connect() as con:
            con.execute(
                "UPDATE pending_group_links SET selected_account=?, status='queued' WHERE request_id=?",
                (str(account_key), int(request_id)),
            )

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

    def _send_main_menu(self, chat_id: str) -> str:
        text = f"ZIVO رسمی فعاله.\nنسخه: {VERSION}\nاز پنل زیر انتخاب کن:"
        self._send(chat_id, text, reply_markup=MAIN_MENU)
        return text

    def _send_fun_menu(self, chat_id: str) -> str:
        text = "بخش سرگرمی ZIVO — یکی را انتخاب کن:"
        self._send(chat_id, text, reply_markup=FUN_MENU)
        return text

    def _send_tools_menu(self, chat_id: str) -> str:
        text = "ابزارهای منتقل‌شده از ZIVO 60.96.39.4"
        self._send(chat_id, text, reply_markup=TOOLS_MENU)
        return text

    def _send_economy_menu(self, chat_id: str) -> str:
        text = "اقتصاد میو، پت و خانه"
        self._send(chat_id, text, reply_markup=ECONOMY_MENU)
        return text

    @staticmethod
    def _ipc(account_key: str, payload: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Any]:
        return ipc_request(account_key, payload, timeout=timeout)

    def _account_rows(self) -> list[Dict[str, Any]]:
        rows: list[Dict[str, Any]] = []
        for key in IPC_ACCOUNT_KEYS:
            try:
                data = self._ipc(key, {"op": "status"}, timeout=1.5)
            except Exception as exc:
                log.info("account socket offline | account=%s | %s: %s", key, type(exc).__name__, exc)
                continue
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
            })
        return rows

    def _account_status_text(self, *, detailed: bool = False) -> str:
        rows = self._account_rows()
        if not rows:
            return "هیچ اکانت ZIVO از مسیر Socket مستقیم در دسترس نیست."
        now = datetime.now(timezone.utc)
        lines = ["ZIVO | وضعیت اکانت‌بات‌ها", "━━━━━━━━━━━━━━━━━━"]
        online = 0
        for row in rows:
            status = str(row["status"] or "")
            heartbeat = str(row["last_heartbeat_at"] or "")
            fresh = False
            if heartbeat:
                try:
                    dt = datetime.fromisoformat(heartbeat)
                    if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                    fresh = (now - dt).total_seconds() <= 45
                except Exception:
                    fresh = False
            usable = bool(int(row["enabled"] or 0)) and status == "online" and fresh and int(row["self_id"] or 0) != 0
            online += int(usable)
            if detailed:
                lines.append(
                    f"{'ONLINE' if usable else 'OFFLINE'} | {row['account_key']} | {row['label'] or '-'} | "
                    f"enabled={int(row['enabled'] or 0)} | groups={int(row['groups_count'] or 0)} | status={status or '-'}"
                )
        if not detailed:
            lines.append(f"اکانت ثبت‌شده: {len(rows)}")
            lines.append(f"اکانت آماده Join: {online}")
        return "\n".join(lines)

    def _managed_rows_for_user(self, user_id: str) -> list[Dict[str, Any]]:
        uid = int(user_id or 0)
        owner = self._is_owner(user_id)
        merged: Dict[int, Dict[str, Any]] = {}
        for key in IPC_ACCOUNT_KEYS:
            try:
                data = self._ipc(key, {"op": "groups", "requester_user_id": uid, "owner_override": owner}, timeout=2.5)
            except Exception:
                continue
            for item in data.get("groups") or []:
                if not isinstance(item, dict):
                    continue
                gid = int(item.get("group_id") or 0)
                if gid <= 0 or gid in merged:
                    continue
                row = {
                    "user_id": str(user_id), "group_id": gid,
                    "account_key": str(item.get("account_key") or key),
                    "title": str(item.get("title") or ""),
                    "member_count": int(item.get("member_count") or -1),
                }
                merged[gid] = row
                self.store.add_managed_group(
                    user_id=str(user_id), group_id=gid, account_key=row["account_key"],
                    title=row["title"], member_count=row["member_count"],
                )
        return list(merged.values())

    def _my_groups_text(self, user_id: str) -> str:
        rows = self._managed_rows_for_user(user_id)
        if not rows:
            return "هنوز گروهی از طریق این بات برایت ثبت نشده است."
        state = self.store.control_state(user_id)
        active = int(state.get("active_group_id") or 0)
        lines = ["ZIVO | گروه‌های قابل کنترل", "━━━━━━━━━━━━━━━━━━"]
        for row in rows[:30]:
            gid = int(row["group_id"])
            count = int(row["member_count"] or -1)
            suffix = f" | اعضا: {count}" if count >= 0 else ""
            marker = " ← فعال" if gid == active else ""
            lines.append(f"• {row['title'] or 'بدون نام'} | id={gid} | account={row['account_key']}{suffix}{marker}")
        lines.append("برای انتخاب، از دکمه‌های «گروه‌های من» استفاده کن.")
        return "\n".join(lines)

    def _groups_menu(self, user_id: str) -> Dict[str, Any]:
        rows = self._managed_rows_for_user(user_id)
        keyboard: list[list[Dict[str, str]]] = []
        for row in rows[:20]:
            gid = int(row["group_id"] or 0)
            if gid <= 0:
                continue
            title = str(row["title"] or f"گروه {gid}")[:28]
            account = str(row["account_key"] or "?")
            keyboard.append([{"text": f"{title} | {account}", "callback_data": f"ctl:group:{gid}"}])
        keyboard.append([{"text": "پنل اصلی", "callback_data": "menu:home"}])
        return {"inline_keyboard": keyboard}

    def _send_groups_menu(self, user_id: str, chat_id: str) -> str:
        text = self._my_groups_text(user_id)
        self._send(chat_id, text, reply_markup=self._groups_menu(user_id))
        return text

    def _account_selection_markup(self, request_id: int, candidates: list[sqlite3.Row]) -> Dict[str, Any]:
        keyboard: list[list[Dict[str, str]]] = []
        for row in candidates[:12]:
            key = str(row["account_key"] or "").strip().lower()
            if not key:
                continue
            label = str(row["label"] or key)
            groups_count = int(row["groups_count"] or 0)
            keyboard.append([
                {"text": f"{label} ({key}) | {groups_count} گروه", "callback_data": f"bridge:pick:{int(request_id)}:{key}"}
            ])
        keyboard.append([{"text": "لغو", "callback_data": "menu:home"}])
        return {"inline_keyboard": keyboard}

    def _begin_group_link(self, message: IncomingMessage, kind: str, value: str) -> str:
        if message.chat_id != message.sender_id:
            text = "برای امنیت، لینک گروه را فقط در پیوی همین بات بفرست."
            self._send(message.chat_id, text)
            return text
        candidates = [row for row in self._account_rows() if int(row.get("enabled") or 0) and row.get("status") == "online" and int(row.get("self_id") or 0) > 0]
        if not candidates:
            text = "هیچ اکانت ZIVO از مسیر مستقیم Socket آنلاین نیست. سرویس‌های main/acc2/acc3 را بررسی کن."
            self._send(message.chat_id, text)
            return text
        request_id = self.store.create_pending_group_link(
            user_id=message.sender_id, chat_id=message.chat_id,
            link_kind=kind, link_value=value,
        )
        lines = ["لینک دریافت شد. اکانت اجرایی را انتخاب کن:", f"کد: {request_id}", "━━━━━━━━━━━━━━━━━━"]
        for row in candidates:
            lines.append(f"• {row['account_key']} | {row['label']} | گروه‌ها: {int(row['groups_count'])}")
        text = "\n".join(lines)
        self._send(message.chat_id, text, reply_markup=self._account_selection_markup(request_id, candidates))
        log.info("official socket awaiting account choice | request=%s user=%s kind=%s", request_id, message.sender_id, kind)
        return text

    def _select_join_account(self, callback: IncomingCallback, request_id: int, account_key: str) -> str:
        pending = self.store.pending_group_link(int(request_id), callback.sender_id)
        if pending is None or str(pending["status"] or "") != "waiting_account":
            text = "این درخواست منقضی یا قبلاً استفاده شده است."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        key = str(account_key or "").strip().lower()
        try:
            status = self._ipc(key, {"op": "status"}, timeout=1.5)
        except Exception as exc:
            text = f"اکانت {key} در دسترس نیست: {type(exc).__name__}"
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        if not status.get("ok") or not status.get("connected") or not status.get("enabled"):
            text = f"اکانت {key} الان آماده Join نیست."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        self.store.mark_pending_group_link_selected(int(request_id), key)
        self._send(callback.chat_id, f"در حال Join مستقیم با {key} ...", reply_markup=MAIN_MENU)
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
            log.warning("direct join socket failed | account=%s | %s: %s", key, type(exc).__name__, exc)
            text = f"Join مستقیم ناموفق شد.\nاکانت: {key}\nخطا: {type(exc).__name__}: {exc}"
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        elapsed = round((time.monotonic() - started) * 1000.0, 1)
        code = str(result.get("result_code") or result.get("status") or "failed")
        gid = int(result.get("group_id") or 0)
        title = str(result.get("title") or "")
        count = int(result.get("member_count") or -1)
        if result.get("ok") and gid > 0:
            self.store.add_managed_group(user_id=callback.sender_id, group_id=gid, account_key=key, title=title, member_count=count)
            self.store.set_control_state(callback.sender_id, active_group_id=gid, mode="")
            if code == "joined_full":
                head = "عضویت انجام شد؛ دسترسی FULL آماده است."
            elif code == "joined_basic":
                head = "عضویت انجام شد؛ حالت BASIC آماده است. برای بن/پین/سکوت اکانت را ادمین کن."
            elif code == "joined_pending":
                head = "اکانت عضو شد ولی دسترسی نوشتن هنوز تأیید نشده است."
            elif code == "already":
                head = "اکانت از قبل عضو این گروه بود."
            else:
                head = f"Join انجام شد: {code}"
            text = f"{head}\nگروه: {title or gid}\nID: {gid}\nاکانت: {key}\nزمان پاسخ: {result.get('elapsed_ms', elapsed)} ms"
            self._send(callback.chat_id, text, reply_markup=GROUP_CONTROL_MENU)
            log.info("official direct join PASS | account=%s group=%s code=%s elapsed_ms=%s", key, gid, code, result.get("elapsed_ms", elapsed))
            return text
        err = str(result.get("error") or "JOIN_FAILED")[:600]
        text = f"عضویت انجام نشد.\nاکانت: {key}\nکد: {code}\nخطا: {err}\nزمان: {result.get('elapsed_ms', elapsed)} ms"
        self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
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
        return (
            "ZIVO | کنترل گروه\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"گروه: {row['title'] or 'بدون نام'}\n"
            f"ID: {int(row['group_id'])}\n"
            f"اکانت اجرایی: {row['account_key']}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "فرمان‌های سریع پایین یا «فرمان آزاد» را انتخاب کن."
        )

    def _send_control_panel(self, user_id: str, chat_id: str) -> str:
        text = self._control_panel_text(user_id)
        markup = GROUP_CONTROL_MENU if self._active_group(user_id) is not None else self._groups_menu(user_id)
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

        if data.startswith("bridge:pick:"):
            parts = callback.data.split(":", 3)
            if len(parts) == 4 and parts[2].isdigit():
                return self._select_join_account(callback, int(parts[2]), parts[3])
            return None
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
            self._send(callback.chat_id, text, reply_markup=GROUP_CONTROL_MENU)
            return text
        if data == "ctl:exit":
            self.store.set_control_state(callback.sender_id, mode="")
            text = "حالت فرمان آزاد بسته شد. گروه فعال در پنل حفظ شد."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU)
            return text
        if data.startswith("ctl:q:"):
            key = callback.data.split(":", 2)[2]
            command = QUICK_CONTROL_COMMANDS.get(key)
            if command is None:
                return None
            text = self._queue_remote_command(
                user_id=callback.sender_id, chat_id=callback.chat_id, command_text=command
            )
            self._send(callback.chat_id, text, reply_markup=GROUP_CONTROL_MENU)
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
        m = re.fullmatch(r"prem:o:(\d+):([sgd]):(30|60|90)", data)
        if m:
            return self._premium_create_order(callback.sender_id, callback.chat_id, int(m.group(1)), self._premium_plan_long(m.group(2)), int(m.group(3)))
        m = re.fullmatch(r"prem:([wzc]):(\d+)", data)
        if m:
            method = {"w": "wallet", "z": "zibal", "c": "card"}[m.group(1)]
            return self._premium_pay(callback.sender_id, callback.chat_id, int(m.group(2)), method)

        if data == "menu:home":
            return self._send_main_menu(callback.chat_id)
        if data == "menu:help":
            self._send(callback.chat_id, HELP_TEXT, reply_markup=MAIN_MENU)
            return HELP_TEXT
        if data == "menu:capabilities":
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
        if data == "menu:fun":
            return self._send_fun_menu(callback.chat_id)
        if data == "menu:tools":
            return self._send_tools_menu(callback.chat_id)
        if data == "menu:economy":
            return self._send_economy_menu(callback.chat_id)
        if data == "bridge:join":
            text = "لینک خصوصی splus.ir/joingroup/... یا لینک عمومی splus.ir/username گروه را همین‌جا بفرست."
            self._send(callback.chat_id, text, reply_markup=MAIN_MENU); return text
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
        try:
            result = self._ipc("main", {"op": "social", "requester_user_id": int(user_id), "command_text": str(command_text)}, timeout=12.0)
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

    def _premium_groups_menu(self, user_id: str, chat_id: str) -> str:
        rows = self._managed_rows_for_user(user_id)
        if not rows:
            text = "برای خرید اشتراک اول یک گروه را با ZIVO متصل کن."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        buttons = []
        for row in rows[:20]:
            gid = int(row.get("group_id") or 0)
            title = str(row.get("title") or f"گروه {gid}")[:28]
            buttons.append([{"text": title, "callback_data": f"prem:g:{gid}"}])
        buttons.append([{"text": "بازگشت", "callback_data": "menu:home"}])
        text = "ZIVO | خرید اشتراک\n━━━━━━━━━━━━━━━━━━\nگروهی که اشتراک برای آن فعال شود را انتخاب کن:"
        self._send(chat_id, text, reply_markup={"inline_keyboard": buttons})
        return text

    def _premium_group_menu(self, user_id: str, chat_id: str, group_id: int) -> str:
        row = next((r for r in self._managed_rows_for_user(user_id) if int(r.get("group_id") or 0) == int(group_id)), None)
        if row is None:
            text = "این گروه در فهرست گروه‌های قابل‌کنترل تو نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        try:
            catalog = self._ipc("main", {"op": "premium", "action": "catalog", "requester_user_id": int(user_id)}, timeout=5.0)
            status = self._ipc("main", {"op": "premium", "action": "status", "requester_user_id": int(user_id), "group_id": int(group_id)}, timeout=5.0)
        except Exception as exc:
            text = f"سرویس اشتراک در دسترس نیست: {type(exc).__name__}: {exc}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if not catalog.get("ok"):
            text = f"سرویس اشتراک آماده نیست: {catalog.get('error') or 'FAILED'}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        sub = status.get("subscription") or {}
        lines = [
            "ZIVO | انتخاب پلن",
            "━━━━━━━━━━━━━━━━━━",
            f"گروه: {row.get('title') or group_id}",
            f"پلن فعلی: {status.get('plan_label') or sub.get('plan') or 'رایگان'}",
            f"وضعیت: {sub.get('status') or 'active'}",
            "",
            "پلن و مدت را انتخاب کن:",
        ]
        buttons = []
        for plan in catalog.get("plans") or []:
            pcode = self._premium_plan_short(str(plan.get("plan") or ""))
            if not pcode:
                continue
            label = str(plan.get("label") or plan.get("plan") or "")
            for price in plan.get("prices") or []:
                days = int(price.get("duration_days") or 0)
                months = {30: 1, 60: 2, 90: 3}.get(days, days)
                amount = str(price.get("money_toman") or price.get("money_rial") or "")
                buttons.append([{"text": f"{label} | {months} ماه | {amount}", "callback_data": f"prem:o:{group_id}:{pcode}:{days}"}])
        buttons.append([{"text": "خریدهای من", "callback_data": "prem:history"}, {"text": "بازگشت", "callback_data": "prem:groups"}])
        self._send(chat_id, "\n".join(lines), reply_markup={"inline_keyboard": buttons})
        return "\n".join(lines)

    def _premium_create_order(self, user_id: str, chat_id: str, group_id: int, plan: str, days: int) -> str:
        row = next((r for r in self._managed_rows_for_user(user_id) if int(r.get("group_id") or 0) == int(group_id)), None)
        if row is None:
            text = "گروه برای این کاربر قابل خرید نیست."
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        try:
            result = self._ipc("main", {
                "op": "premium", "action": "create_order", "requester_user_id": int(user_id),
                "group_id": int(group_id), "group_title": str(row.get("title") or f"گروه {group_id}"),
                "plan": plan, "duration_days": int(days),
            }, timeout=8.0)
        except Exception as exc:
            text = f"ساخت سفارش ناموفق بود: {type(exc).__name__}: {exc}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if not result.get("ok"):
            text = f"سفارش ساخته نشد: {result.get('error') or 'FAILED'}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        order = result.get("order") or {}
        oid = int(order.get("order_id") or 0)
        code = str(order.get("order_code") or oid)
        wallet = int(result.get("wallet_balance") or 0)
        amount = int(order.get("amount_rial") or 0)
        text = (
            "ZIVO | سفارش ساخته شد\n━━━━━━━━━━━━━━━━━━\n"
            f"کد سفارش: {code}\n"
            f"گروه: {row.get('title') or group_id}\n"
            f"پلن: {result.get('plan_label') or plan}\n"
            f"مدت: {result.get('duration_label') or days}\n"
            f"مبلغ: {result.get('money_rial') or amount}\n"
            f"کیف پول: {wallet:,} ریال\n\n"
            "روش پرداخت را انتخاب کن."
        )
        buttons = []
        if wallet >= amount and amount > 0:
            buttons.append([{"text": "پرداخت با کیف پول", "callback_data": f"prem:w:{oid}"}])
        if result.get("zibal_enabled"):
            buttons.append([{"text": "پرداخت آنلاین زیبال", "callback_data": f"prem:z:{oid}"}])
        if result.get("card_enabled"):
            buttons.append([{"text": "کارت‌به‌کارت", "callback_data": f"prem:c:{oid}"}])
        buttons.append([{"text": "بازگشت به پلن‌ها", "callback_data": f"prem:g:{group_id}"}])
        if not buttons[:-1]:
            text += "\n\nهیچ روش پرداخت فعالی روی پنل تنظیم نشده است."
        self._send(chat_id, text, reply_markup={"inline_keyboard": buttons})
        return text

    def _premium_pay(self, user_id: str, chat_id: str, order_id: int, method: str) -> str:
        action = {"wallet": "wallet_pay", "zibal": "zibal", "card": "card"}.get(method, "order")
        try:
            result = self._ipc("main", {"op": "premium", "action": action, "requester_user_id": int(user_id), "order_ref": int(order_id)}, timeout=20.0)
        except Exception as exc:
            text = f"پرداخت اجرا نشد: {type(exc).__name__}: {exc}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        order = result.get("order") or {}
        code = str(order.get("order_code") or order_id)
        if method == "wallet":
            if result.get("ok") and result.get("activated"):
                sub = result.get("subscription") or {}
                text = f"پرداخت کیف پول موفق شد.\nکد: {code}\nاشتراک فعال شد: {sub.get('plan') or order.get('plan')}\nگروه: {order.get('group_title') or order.get('group_id')}"
            else:
                text = f"پرداخت کیف پول انجام نشد.\nکد: {code}\nخطا: {result.get('error') or 'FAILED'}\nموجودی: {int(result.get('wallet_balance') or 0):,} ریال"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if method == "zibal":
            if result.get("ok") and result.get("payment_url"):
                text = f"درگاه زیبال آماده است.\nکد سفارش: {code}\nمبلغ: {int(order.get('amount_rial') or 0):,} ریال\n\nلینک پرداخت:\n{result.get('payment_url')}\n\nبعد از پرداخت، Callback اصلی ZIVO تراکنش را Verify و اشتراک را فعال می‌کند."
            else:
                text = f"درگاه ساخته نشد.\nکد: {code}\nخطا: {result.get('error') or 'FAILED'}"
            self._send(chat_id, text, reply_markup=MAIN_MENU)
            return text
        if result.get("ok") and result.get("manual_receipt_required"):
            text = (
                "ZIVO | کارت‌به‌کارت\n━━━━━━━━━━━━━━━━━━\n"
                f"کد سفارش: {code}\nکارت: {result.get('card_number') or '—'}\n"
                f"به نام: {result.get('card_holder') or '—'}\nمبلغ: {result.get('money_rial') or order.get('amount_rial')}\n\n"
                "مسیر دریافت عکس رسید در Bot API رسمی هنوز Live-verified نشده؛ بنابراین این نسخه رسید را جعلی ثبت نمی‌کند. کد سفارش را همراه رسید برای پشتیبانی بفرست."
            )
        else:
            text = f"کارت‌به‌کارت آماده نیست: {result.get('error') or 'FAILED'}"
        self._send(chat_id, text, reply_markup=MAIN_MENU)
        return text

    def _premium_my_subscriptions(self, user_id: str, chat_id: str) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "my_subscriptions", "requester_user_id": int(user_id)}, timeout=6.0)
        except Exception as exc:
            text = f"خواندن اشتراک‌ها ناموفق بود: {type(exc).__name__}: {exc}"
            self._send(chat_id, text, reply_markup=MAIN_MENU); return text
        rows = result.get("subscriptions") or []
        lines = ["ZIVO | اشتراک‌های من", "━━━━━━━━━━━━━━━━━━"]
        if not rows:
            lines.append("اشتراک فعالی به نام این کاربر ثبت نشده است.")
        else:
            for row in rows[:20]:
                plan = row.get("effective_plan") or row.get("plan") or "free"
                status = row.get("effective_status") or row.get("status") or "active"
                lines.append(f"• {row.get('group_title') or row.get('group_id')} | {plan} | {status} | {row.get('effective_expires_at') or row.get('expires_at') or 'دائمی'}")
        text = "\n".join(lines)
        self._send(chat_id, text, reply_markup=MAIN_MENU); return text

    def _premium_history(self, user_id: str, chat_id: str) -> str:
        try:
            result = self._ipc("main", {"op": "premium", "action": "history", "requester_user_id": int(user_id)}, timeout=6.0)
        except Exception as exc:
            text = f"خواندن خریدها ناموفق بود: {type(exc).__name__}: {exc}"
            self._send(chat_id, text, reply_markup=MAIN_MENU); return text
        rows = result.get("orders") or []
        lines = ["ZIVO | خریدهای من", "━━━━━━━━━━━━━━━━━━"]
        if not rows:
            lines.append("هنوز سفارشی ثبت نشده است.")
        else:
            for row in rows[:15]:
                lines.append(f"• {row.get('order_code') or row.get('order_id')} | {row.get('group_title') or row.get('group_id')} | {row.get('plan')} | {row.get('status')} | {int(row.get('amount_rial') or 0):,} ریال")
        text = "\n".join(lines)
        self._send(chat_id, text, reply_markup=MAIN_MENU); return text

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
        self.store.observe(message, command=commandish)
        self.store.remember_contact(message)

        group_link = parse_group_link(text)
        if group_link is not None:
            return self._begin_group_link(message, group_link[0], group_link[1])

        if low in {"/start", "start", "شروع", "شروع کار", "ربات", "پنل", "/panel"}:
            return self._send_main_menu(message.chat_id)

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
            self._send(message.chat_id, response, reply_markup=GROUP_CONTROL_MENU)
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


class ZivoOfficialApp:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.transport = SoroushOfficialTransport()
        self.store = Store()
        self.core = BotCore(self.store, self.transport)

    def request_stop(self, *_: Any) -> None:
        self.stop_event.set()

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.request_stop)
        signal.signal(signal.SIGINT, self.request_stop)
        log.info("startup | app=%s version=%s transport=official-bot-api bridge=unix-socket-direct", APP_NAME, VERSION)
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
        log.info("shutdown complete")


def main() -> None:
    ZivoOfficialApp().run()


if __name__ == "__main__":
    main()
