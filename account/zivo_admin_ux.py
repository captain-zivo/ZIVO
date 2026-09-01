#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZIVO 60.96.11 additive administration and help UX.

This module intentionally owns the new Persian copy so the long-lived protected
runtime text in zivo60.py remains byte-identical.  It contains no database or
transport code and is therefore straightforward to test in isolation.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TARGET_RE = re.compile(r"(?:@[A-Za-z0-9_.]{3,64}|[A-Za-z][A-Za-z0-9_.]{2,63}|[0-9۰-۹٠-٩]{5,20})")
_SQLITE_INT64_MAX = (1 << 63) - 1

VOICE_SETTINGS_COPY_LABEL = "صدای ویس"
VOICE_SETTINGS_COPY_ALIASES: Dict[str, str] = {
    "ویس": "voice",
    "صدا": "voice",
    "صدای ویس": "voice",
    "تنظیم ویس": "voice",
    "voice": "voice",
}


def _normalize(value: Any) -> str:
    text = str(value or "").replace("\u200c", " ").replace("ي", "ی").replace("ك", "ک")
    return " ".join(text.split()).strip()


def _valid_role_target(value: str) -> bool:
    if not _TARGET_RE.fullmatch(value):
        return False
    ascii_value = value.translate(_PERSIAN_DIGITS)
    if ascii_value.isdigit():
        try:
            return 0 < int(ascii_value) <= _SQLITE_INT64_MAX
        except (TypeError, ValueError, OverflowError):
            return False
    return True


def parse_role_assignment_command(value: Any) -> Optional[Dict[str, str]]:
    """Parse role changes with reply, username or numeric ID in either order."""
    text = _normalize(value)
    if not text:
        return None

    action_aliases: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
        ("remove_exempt", ("حذف معافیت", "حذف معاف")),
        ("admin", ("تنظیم ادمین", "ادمین")),
        ("special", ("تنظیم ویژه", "ویژه")),
        ("exempt", ("تنظیم معاف", "معاف")),
        ("dismiss", ("عزل",)),
    )
    for action, aliases in action_aliases:
        for alias in aliases:
            if text == alias:
                return {"action": action, "target": "", "command": alias}

            prefix = alias + " "
            if text.startswith(prefix):
                target = text[len(prefix):].strip()
                if _valid_role_target(target):
                    return {"action": action, "target": target, "command": alias}

            suffix = " " + alias
            if text.endswith(suffix):
                target = text[:-len(suffix)].strip()
                if _valid_role_target(target):
                    return {"action": action, "target": target, "command": alias}
    return None


def role_target_usage(command: str) -> str:
    label = _normalize(command) or "ادمین"
    return (
        "👤 ZIVO | انتخاب کاربر\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "یکی از این روش‌ها را استفاده کن:\n\n"
        f"۱) روی پیام کاربر ریپلای کن و بنویس: {label}\n"
        f"۲) {label} @username\n"
        f"۳) @username {label}\n"
        f"۴) {label} 49123456\n"
        f"۵) 49123456 {label}\n\n"
        "آیدی عددی یا یوزرنیم باید متعلق به یک کاربر واقعی باشد."
    )


def role_target_unresolved(target: str) -> str:
    shown = _normalize(target)[:80] or "نامشخص"
    return (
        "❌ کاربر مقصد پیدا نشد.\n"
        f"مقدار دریافت‌شده: {shown}\n\n"
        "اگر آیدی عددی با دسترسی ناقص بود، یک‌بار روی پیام همان کاربر ریپلای کن تا زیوو اطلاعاتش را ذخیره کند."
    )


def role_system_target_denied() -> str:
    return "❌ این دستور روی حساب زیوو یا حساب سیستمی قابل اجرا نیست."


def manager_role_allowed(role: Any) -> bool:
    return _normalize(role) in {"مالک", "ادمین"}


def _plain_activation_block(value: Any) -> str:
    cleaned: List[str] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        line = re.sub(r"^(?:✨|👑|▫️|🛡|⚙️|🔐|📚|✅|🆔|➕)\s*", "", line)
        cleaned.append(line)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


def build_active_card(
    owner_block: Any,
    admins_block: Any,
    access_block: Any,
    locks_block: Any,
) -> str:
    """Build the exact plain ZIVO ACTIVE layout requested for link joins."""
    return (
        "╭───〔  ZIVO ACTIVE 〕───╮\n\n"
        "زیوو با موفقیت روی این گروه فعال شد.\n\n"
        f"{_plain_activation_block(owner_block)}\n\n"
        "ادمین‌های شناسایی‌شده\n"
        f"{_plain_activation_block(admins_block)}\n\n"
        "وضعیت دسترسی\n"
        f"{_plain_activation_block(access_block)}\n\n"
        "قفل‌های پیش‌فرض فعال\n"
        f"{_plain_activation_block(locks_block)}\n\n"
        "راهنما\n"
        "برای دیدن همه دستورات: راهنما\n"
        "برای مدیریت قفل‌ها: لیست قفل\n\n"
        "╰──────────────╯"
    )


def normalize_active_card_layout(value: Any) -> str:
    text = str(value or "")
    if "ZIVO ACTIVE" not in text:
        return text
    lines: List[str] = []
    for index, raw_line in enumerate(text.splitlines()):
        line = raw_line.strip()
        if "ZIVO ACTIVE" in line:
            line = "╭───〔  ZIVO ACTIVE 〕───╮"
        elif line != "╰──────────────╯":
            line = re.sub(r"^(?:✨|👑|▫️|🛡|⚙️|🔐|📚|✅|🆔|➕)\s*", "", line)
        lines.append(line)
    return "\n".join(lines)


def parse_voice_settings_command(value: Any) -> Optional[Dict[str, str]]:
    text = _normalize(value)
    aliases: Dict[str, Dict[str, str]] = {
        "تنظیمات ویس": {"action": "status"},
        "وضعیت ویس": {"action": "status"},
        "وضعیت صدای ویس": {"action": "status"},
        "صدای ویس زن": {"action": "gender", "value": "female"},
        "تنظیم صدای ویس زن": {"action": "gender", "value": "female"},
        "صدای ویس مرد": {"action": "gender", "value": "male"},
        "تنظیم صدای ویس مرد": {"action": "gender", "value": "male"},
        "صدای ویس خودکار": {"action": "gender", "value": "auto"},
        "تنظیم صدای ویس خودکار": {"action": "gender", "value": "auto"},
        "لحن ویس معیار": {"action": "style", "value": "formal"},
        "لحن ویس رسمی": {"action": "style", "value": "formal"},
        "لحن ویس روان": {"action": "style", "value": "normal"},
        "لحن ویس محاوره ای": {"action": "style", "value": "normal"},
        "لحن ویس محاوره‌ای": {"action": "style", "value": "normal"},
        "لحن ویس آرام": {"action": "style", "value": "calm"},
        "لحن ویس پرانرژی": {"action": "style", "value": "energetic"},
        "لحن ویس تهرانی": {"action": "unsupported_accent", "value": "tehran"},
        "لحن ویس اصفهانی": {"action": "unsupported_accent", "value": "isfahan"},
        "سرعت ویس آرام": {"action": "speed", "value": "slow"},
        "سرعت ویس عادی": {"action": "speed", "value": "normal"},
        "سرعت ویس تند": {"action": "speed", "value": "fast"},
        "ریست تنظیمات ویس": {"action": "reset"},
        "بازنشانی تنظیمات ویس": {"action": "reset"},
    }
    return dict(aliases[text]) if text in aliases else None


def voice_settings_permission_denied() -> str:
    return "⛔ تنظیم صدای ویس فقط برای مالک و ادمین‌های زیوو فعال است."


def voice_accent_unavailable() -> str:
    return (
        "🎙 موتور فعلی صدای فارسی، لهجهٔ شهری واقعی و قابل‌اعتماد برای تهران یا اصفهان ندارد؛ "
        "برای جلوگیری از صدای مصنوعی یا تمسخرآمیز تنظیم تغییر نکرد.\n"
        "می‌توانی از «لحن ویس روان» یا «لحن ویس معیار» استفاده کنی."
    )


def voice_settings_text(profile: Dict[str, Any], changed: bool = False) -> str:
    gender = {"female": "زن", "male": "مرد", "auto": "خودکار"}.get(
        str(profile.get("gender") or "auto"), "خودکار"
    )
    style_key = str(profile.get("style") or "normal")
    style = {
        "normal": "روان و طبیعی",
        "formal": "فارسی معیار و رسمی",
        "calm": "آرام و ملایم",
        "energetic": "پرانرژی",
    }.get(style_key, "روان و طبیعی")
    speed_map = {"slow": "آرام", "fast": "تند", "normal": "عادی"}
    speed = speed_map.get(str(profile.get("speed") or "normal"), "عادی")
    headline = "✅ تنظیم ذخیره شد." if changed else "⚙️ تنظیم فعلی گروه"
    return (
        "🎙 ZIVO | مرکز تنظیم ویس\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{headline}\n"
        f"👤 صدا: {gender}\n"
        f"🗣 لحن: {style}\n"
        f"⏱ سرعت: {speed}\n\n"
        "فرمان‌های سریع:\n"
        "⌁ صدای ویس زن\n"
        "⌁ صدای ویس مرد\n"
        "⌁ صدای ویس خودکار\n"
        "⌁ لحن ویس معیار\n"
        "⌁ لحن ویس روان\n"
        "⌁ لحن ویس آرام | پرانرژی\n"
        "⌁ سرعت ویس آرام | عادی | تند\n"
        "⌁ ریست تنظیمات ویس\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "این تنظیم برای ویس تمام کاربران همین گروه اجرا می‌شود."
    )


def parse_quick_lock_command(value: Any) -> Optional[Dict[str, Any]]:
    text = _normalize(value)
    bulk: Dict[str, Dict[str, Any]] = {
        "قفل همه": {"action": "bulk_preview", "enabled": True},
        "بستن همه قفل ها": {"action": "bulk_preview", "enabled": True},
        "بستن همه قفل‌ها": {"action": "bulk_preview", "enabled": True},
        "بازکردن همه": {"action": "bulk_preview", "enabled": False},
        "باز کردن همه": {"action": "bulk_preview", "enabled": False},
        "بازکردن همه قفل ها": {"action": "bulk_preview", "enabled": False},
        "بازکردن همه قفل‌ها": {"action": "bulk_preview", "enabled": False},
        "باز کردن همه قفل ها": {"action": "bulk_preview", "enabled": False},
        "باز کردن همه قفل‌ها": {"action": "bulk_preview", "enabled": False},
        "تایید قفل همه": {"action": "bulk_apply", "enabled": True},
        "تأیید قفل همه": {"action": "bulk_apply", "enabled": True},
        "تایید بازکردن همه": {"action": "bulk_apply", "enabled": False},
        "تأیید بازکردن همه": {"action": "bulk_apply", "enabled": False},
        "تایید بازکردن همه قفل ها": {"action": "bulk_apply", "enabled": False},
        "تأیید بازکردن همه قفل‌ها": {"action": "bulk_apply", "enabled": False},
        "تایید باز کردن همه قفل ها": {"action": "bulk_apply", "enabled": False},
        "تایید باز کردن همه قفل‌ها": {"action": "bulk_apply", "enabled": False},
        "تأیید باز کردن همه قفل ها": {"action": "bulk_apply", "enabled": False},
        "تأیید باز کردن همه قفل‌ها": {"action": "bulk_apply", "enabled": False},
    }
    if text in bulk:
        return dict(bulk[text])

    for prefix, action in (
        ("بستن قفل ", "enable_lock"),
        ("بستن ", "enable_lock"),
        ("روشن کردن قفل ", "enable_lock"),
        ("روشن کردن ", "enable_lock"),
        ("خاموش کردن قفل ", "disable_lock"),
        ("خاموش کردن ", "disable_lock"),
    ):
        if text.startswith(prefix) and text[len(prefix):].strip():
            return {"action": action, "raw_name": text[len(prefix):].strip()}
    return None


def bulk_lock_confirmation(enabled: bool) -> str:
    if enabled:
        command = "تایید قفل همه"
        operation = "روشن‌شدن همه قفل‌ها"
    else:
        command = "تایید بازکردن همه قفل ها"
        operation = "خاموش‌شدن همه قفل‌ها"
    return (
        "⚠️ ZIVO | تأیید تغییر گروهی قفل‌ها\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"درخواست: {operation}\n"
        "این تغییر روی تمام انواع پیام و محتوای گروه اثر می‌گذارد.\n\n"
        f"اگر مطمئنی دقیقاً بنویس: {command}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "تا قبل از تأیید هیچ تنظیمی تغییر نکرده است."
    )


def bulk_lock_result(enabled: bool, count: int, actor_role: str) -> str:
    return (
        "✅ ZIVO | تغییر گروهی قفل‌ها انجام شد\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🎖 اجراکننده: {actor_role}\n"
        f"🔐 تعداد قفل‌های به‌روزشده: {int(count)}\n"
        f"⚙️ وضعیت جدید: {'همه روشن' if enabled else 'همه خاموش'}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "برای بررسی دوباره بنویس: لیست قفل"
    )


def lock_center_text(items: Sequence[Dict[str, Any]]) -> str:
    active = [item for item in items if bool(item.get("enabled"))]
    inactive = [item for item in items if not bool(item.get("enabled"))]
    lines: List[str] = [
        "🔐 ZIVO | مرکز مدیریت قفل‌ها",
        "━━━━━━━━━━━━━━━━━━",
        f"✅ فعال: {len(active)}  |  ⭕ خاموش: {len(inactive)}  |  کل: {len(items)}",
        "",
        "✅ قفل‌های فعال",
    ]
    if active:
        for item in active:
            lines.append(
                f"• {item['name']}  |  اخطار {int(item.get('max_warnings') or 0)}  |  "
                f"بن {'روشن' if item.get('auto_ban') else 'خاموش'}  |  {item.get('punishment') or 'اخطار'}"
            )
    else:
        lines.append("• هیچ قفلی روشن نیست.")
    lines.extend(("", "⭕ قفل‌های خاموش"))
    if inactive:
        lines.append("• " + "، ".join(str(item["name"]) for item in inactive))
    else:
        lines.append("• همه قفل‌ها روشن هستند.")
    lines.extend((
        "",
        "⚡ مدیریت سریع",
        "⌁ بستن لینک  ← روشن‌کردن قفل",
        "⌁ بازکردن لینک  ← خاموش‌کردن قفل",
        "⌁ وضعیت قفل لینک  ← جزئیات کامل",
        "⌁ قفل همه  ← پیش‌نمایش روشن‌کردن همه",
        "⌁ بازکردن همه  ← پیش‌نمایش خاموش‌کردن همه",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "تغییر گروهی فقط پس از فرمان تأیید انجام می‌شود.",
    ))
    return "\n".join(lines)[:3900]


EXTRA_CAPABILITY_REGISTRY: Tuple[Dict[str, Any], ...] = (
    {
        "key": "market_calculator",
        "icon": "💱",
        "title": "بازار تصویری و محاسبه‌گر",
        "description": "کارت تصویری نرخ بازار، تبدیل دلار/یورو/پوند/طلای ۱۸ عیار به تومان و محاسبه امن عبارت‌های ریاضی.",
        "help_command": "راهنما محاسبه و ارز",
        "help_aliases": ("راهنما محاسبه و ارز", "راهنما تبدیل ارز", "راهنما ماشین حساب"),
        "command_details": (
            ("قیمت دلار و طلا", "قیمت‌های زنده را همراه کارت تصویری و روند واقعی منبع نمایش می‌دهد."),
            ("120 دلار", "ارزش مقدار نوشته‌شده را با نرخ زنده به تومان محاسبه می‌کند؛ «دلار 120» هم پذیرفته می‌شود."),
            ("25 یورو", "یورو را به تومان تبدیل می‌کند؛ پوند نیز با همین ساختار پشتیبانی می‌شود."),
            ("2 طلا", "ارزش دو گرم طلای ۱۸ عیار را با نرخ زنده محاسبه می‌کند."),
            ("11*13", "صورت مسئله و جواب را بدون اجرای کد یا eval نمایش می‌دهد."),
        ),
        "notes": ("اگر منبع نمودار واقعی در دسترس نباشد، زیوو نمودار ساختگی نمی‌سازد و پاسخ متنی معتبر را نگه می‌دارد.",),
    },
    {
        "key": "voice_profiles",
        "icon": "🎙",
        "title": "تنظیم صدای ویس",
        "description": "مالک و ادمین صدای زن یا مرد، لحن معیار یا روان و سرعت خواندن ویس‌های گروه را تعیین می‌کنند.",
        "help_command": "راهنما تنظیم ویس",
        "help_aliases": ("راهنما تنظیم ویس", "راهنما صدای ویس"),
        "command_details": (
            ("وضعیت صدای ویس", "تنظیم فعال همین گروه را نشان می‌دهد."),
            ("صدای ویس زن", "صدای فارسی زن را برای ویس‌های گروه انتخاب می‌کند."),
            ("صدای ویس مرد", "صدای فارسی مرد را برای ویس‌های گروه انتخاب می‌کند."),
            ("لحن ویس معیار", "خوانش رسمی و فارسی معیار را فعال می‌کند."),
            ("لحن ویس روان", "خوانش روان‌تر و محاوره‌ای را فعال می‌کند."),
            ("سرعت ویس آرام", "سرعت خواندن را تنظیم می‌کند؛ «عادی» و «تند» هم فعال‌اند."),
        ),
        "notes": ("موتور فعلی لهجه واقعی تهران یا اصفهان ندارد؛ زیوو به‌جای تقلید غیرقابل‌اعتماد، فارسی معیار یا روان ارائه می‌کند.",),
    },
    {
        "key": "role_targeting",
        "icon": "🎖",
        "title": "مقام‌دهی آسان",
        "description": "تعیین ادمین، ویژه و معاف با ریپلای، یوزرنیم یا آیدی عددی و با هر دو ترتیب فرمان.",
        "help_command": "راهنما مقام دهی آسان",
        "help_aliases": ("راهنما مقام دهی آسان", "راهنما ادمین با آیدی"),
        "command_details": (
            ("ادمین @username", "مالک، کاربر را با یوزرنیم ادمین زیوو می‌کند."),
            ("@username ویژه", "مالک یا ادمین، کاربر را با ترتیب معکوس ویژه می‌کند."),
            ("ادمین 49123456", "مقام را با آیدی عددی تنظیم می‌کند."),
            ("49123456 عزل", "مقام کاربر را طبق سلسله‌مراتب دسترسی حذف می‌کند."),
        ),
    },
    {
        "key": "lock_center",
        "icon": "🔐",
        "title": "مرکز سریع قفل‌ها",
        "description": "نمایش خواناتر قفل‌های روشن و خاموش، فرمان‌های طبیعی بستن/بازکردن و تغییر گروهی دارای تأیید.",
        "help_command": "راهنما مرکز قفل",
        "help_aliases": ("راهنما مرکز قفل", "راهنما قفل سریع"),
        "command_details": (
            ("لیست قفل", "مرکز مدیریتی خوانا با قفل‌های فعال، خاموش و فرمان‌های سریع را باز می‌کند."),
            ("بستن لینک", "قفل لینک را روشن می‌کند؛ «قفل لینک» همچنان فعال است."),
            ("بازکردن لینک", "قفل لینک را خاموش می‌کند."),
            ("قفل همه", "پیش‌نمایش روشن‌کردن همه قفل‌ها را نشان می‌دهد و بدون تأیید چیزی عوض نمی‌شود."),
            ("بازکردن همه", "پیش‌نمایش خاموش‌کردن همه قفل‌ها را نشان می‌دهد و تأیید جدا لازم دارد."),
        ),
    },
)


EXTRA_COMMAND_HEADS = frozenset({
    "صدای", "لحن", "سرعت", "ریست", "بازنشانی", "بستن", "روشن", "خاموش",
    "تایید", "تأیید", "دلار", "یورو", "پوند", "طلا",
})


def append_command_list(text: str, commands: Iterable[str]) -> Tuple[str, List[str]]:
    extra = (
        "\n\n✨ فرمان‌های تازه\n"
        "⌁ قیمت دلار و طلا | 120 دلار | یورو 25 | 2 طلا\n"
        "⌁ 11*13 | (25+5)/3\n"
        "⌁ وضعیت صدای ویس | صدای ویس زن | صدای ویس مرد\n"
        "⌁ لحن ویس معیار | لحن ویس روان | سرعت ویس عادی\n"
        "⌁ ادمین @username | @username ویژه | ادمین 49123456\n"
        "⌁ بستن لینک | بازکردن لینک | قفل همه | بازکردن همه"
    )
    new_commands = list(commands) + [
        "120 دلار", "یورو 25", "11*13", "وضعیت صدای ویس", "صدای ویس زن",
        "صدای ویس مرد", "لحن ویس روان", "ادمین @username", "@username ویژه",
        "بستن لینک", "بازکردن همه",
    ]
    marker = "\n━━━━━━━━━━━━━━━━━━\n"
    if marker in text:
        head, tail = text.rsplit(marker, 1)
        return head + extra + marker + tail, new_commands
    return text + extra, new_commands
