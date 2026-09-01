#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline integration contract for ZIVO 60.96.11 additive features."""

from __future__ import annotations

import ast
import hashlib
import os
import re
from pathlib import Path
from typing import Optional

import zivo_admin_ux as admin_ux
import zivo_market_tools as market_tools


ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SOURCE = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
INSTALLER_PATH = Path(os.environ.get("ZIVO_INSTALLER_UNDER_TEST", str(ROOT / "install_zivo60.sh")))
INSTALLER = INSTALLER_PATH.read_text(encoding="utf-8")


def function_text(name: str) -> str:
    lines = SOURCE.splitlines(True)
    node = next(
        item
        for item in ast.walk(TREE)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return "".join(lines[node.lineno - 1 : node.end_lineno])


# The release is additive and the frozen Persian runtime corpus stays exact.
assert 'VERSION = "zivo60.96.11"' in SOURCE
persian_literals = [
    node.value
    for node in ast.walk(TREE)
    if isinstance(node, ast.Constant)
    and isinstance(node.value, str)
    and any("\u0600" <= char <= "\u06ff" for char in node.value)
]
assert len(persian_literals) >= 3992
assert all(any(x in item for item in persian_literals) for x in ("مالک","ادمین","ویژه","راهنما"))


# Join: one eyes write probe, then the durable full ACTIVE card; never the short guide.
fast_join = function_text("_fast_post_join_write_and_activation")
durable_join = function_text("_process_group_join_notice_job")
promotion = function_text("_promote_pending_group_after_write")
card_queue = function_text("_post_activation_card_task")
for body in (fast_join, durable_join):
    assert 'marker="👀"' in body
    assert "_group_join_notice_complete" in body
    assert "try_auto_activate_pending_group" in body
    assert body.index("try_auto_activate_pending_group") < body.index("_group_join_notice_complete")
    assert "PENDING_ACTIVATION_NOT_READY" in body
    assert "deliver_card_inline=True" in body
    assert "send_group_join_guide_receipt" not in body
assert "deliver_card_inline=True" in promotion
assert promotion.index("try_auto_activate_pending_group") < promotion.index("_group_join_notice_complete")
assert "_activation_card_job_upsert" in card_queue
assert "_process_activation_card_job" in card_queue

activation_gate = function_text("try_auto_activate_pending_group")
assert 'fresh_row["group_notice_probe_sent"]' in activation_gate
assert 'fresh_row["group_notice_sent"]' not in activation_gate

old_card = (
    "╭───〔 🤖 ZIVO ACTIVE 〕───╮\n\n"
    "✨ زیوو با موفقیت روی این گروه فعال شد.\n\n"
    "👑 مالک زیوو\n﹝مشاهده نمایه﹞\n🆔 49145577\n\n"
    "🛡 ادمین‌های شناسایی‌شده\n▫️ ادمین دیگری شناسایی نشد.\n\n"
    "⚙️ وضعیت دسترسی\n✅ عضویت و ارسال پیام زیوو تأیید شد.\n"
    "🛡 سطح گروه: دسترسی ارسال زیوو تأیید شد.\n\n"
    "🔐 قفل‌های پیش‌فرض فعال\n✅ قفل لینک\n✅ قفل آیدی\n"
    "✅ قفل پیام‌های فیلترشده\n✅ قفل فوروارد\n✅ قفل کد هنگی\n\n"
    "📚 راهنما\n▫️ برای دیدن همه دستورات: راهنما\n"
    "▫️ برای مدیریت قفل‌ها: لیست قفل\n\n╰──────────────╯"
)
active_card = admin_ux.normalize_active_card_layout(old_card)
assert active_card.startswith("╭───〔  ZIVO ACTIVE 〕───╮")
assert "زیوو با موفقیت روی این گروه فعال شد." in active_card
assert "ادمین دیگری شناسایی نشد." in active_card
assert "قفل کد هنگی" in active_card
assert "برای مدیریت قفل‌ها: لیست قفل" in active_card
assert all(icon not in active_card for icon in ("🤖", "✨", "👑", "🛡", "⚙️", "🔐", "📚", "✅", "🆔", "▫️"))


# Role targeting: reply, username, numeric ID, and both word orders.
role_cases = {
    "ادمین": ("admin", ""),
    "ادمین @zivo_user": ("admin", "@zivo_user"),
    "@zivo_user ادمین": ("admin", "@zivo_user"),
    "ادمین 49145577": ("admin", "49145577"),
    "49145577 ادمین": ("admin", "49145577"),
    "ویژه @zivo_user": ("special", "@zivo_user"),
    "49145577 ویژه": ("special", "49145577"),
    "معاف 49145577": ("exempt", "49145577"),
    "حذف معافیت @zivo_user": ("remove_exempt", "@zivo_user"),
    "49145577 عزل": ("dismiss", "49145577"),
}
for command, expected in role_cases.items():
    parsed = admin_ux.parse_role_assignment_command(command)
    assert parsed is not None, command
    assert (parsed["action"], parsed["target"]) == expected, command
assert admin_ux.parse_role_assignment_command("ادمین 9223372036854775807") is not None
assert admin_ux.parse_role_assignment_command("ادمین 9223372036854775808") is None
assert admin_ux.parse_role_assignment_command("ادمین 99999999999999999999") is None
router = function_text("_handle_group_commands_impl")
assert "role_assignment_command = parse_role_assignment_command(text)" in router
for call in (
    "command_set_admin", "command_set_special", "command_set_exempt",
    "command_remove_exempt", "command_dismiss_rank",
):
    assert call in router
resolver = function_text("resolve_moderation_target_spec")
membership = function_text("role_target_group_membership_proven")
role_target = function_text("require_role_reply_target")
numeric_reply_parser = function_text("extract_explicit_user_id")
assert "uid > ((1 << 63) - 1)" in resolver
assert "strict_group_member" in resolver
assert "client.get_entity" in resolver
assert "role_target_group_membership_proven" in resolver
assert "GetParticipantRequest" in membership and "client.get_participants" in membership
assert "utils.get_input_channel(group)" in membership
assert "utils.get_input_peer(group)" not in membership
assert "if group_input is not None" in membership
assert "strict_group_member=True" in role_target and "group=group" in role_target
# 60.96.19: explicit ID/username targets retain strict membership proof in
# resolve_moderation_target_spec, while a live reply message from this exact
# group is accepted as membership evidence to avoid Soroush NOT_SUPPORTED.
assert "role_target_group_membership_proven" not in role_target
assert "role target reply proof accepted" in role_target
assert role_target.index("moderation_reply_target") < role_target.index(
    "role target reply proof accepted"
) < role_target.index("return int(target_id)")

numeric_namespace = {
    "Optional": Optional,
    "normalize_group_command": lambda value: str(value or "").strip(),
    "safe_int": lambda value: int(value),
    "re": re,
}
exec(numeric_reply_parser, numeric_namespace)
extract_numeric_id = numeric_namespace["extract_explicit_user_id"]
assert extract_numeric_id("9223372036854775807") == 9223372036854775807
assert extract_numeric_id("9223372036854775808") is None
assert extract_numeric_id("99999999999999999999") is None
assert extract_numeric_id("ID: 9223372036854775808") is None

admin_setter = function_text("command_set_admin")
assert "base_bot_role(int(group_id), int(actor_id)) != BOT_ROLE_OWNER" in admin_setter
for command_name in (
    "command_set_admin", "command_set_special", "command_set_exempt",
    "command_remove_exempt", "command_dismiss_rank",
):
    body = function_text(command_name)
    assert "BOT_ROLE_OWNER" in body or 'target_role == "مالک"' in body, command_name
for mutation_name in (
    "upsert_bot_admin", "upsert_bot_special", "upsert_bot_exemption",
    "remove_bot_exemption", "dismiss_bot_rank",
):
    assert "mark_group_backup_dirty" in function_text(mutation_name), mutation_name


# Voice settings are persistent, manager-gated and supplied to the actual synthesizer.
voice_cases = {
    "صدای ویس زن": ("gender", "female"),
    "صدای ویس مرد": ("gender", "male"),
    "صدای ویس خودکار": ("gender", "auto"),
    "لحن ویس معیار": ("style", "formal"),
    "لحن ویس روان": ("style", "normal"),
    "لحن ویس آرام": ("style", "calm"),
    "لحن ویس پرانرژی": ("style", "energetic"),
    "سرعت ویس آرام": ("speed", "slow"),
    "سرعت ویس عادی": ("speed", "normal"),
    "سرعت ویس تند": ("speed", "fast"),
}
for command, expected in voice_cases.items():
    parsed = admin_ux.parse_voice_settings_command(command)
    assert parsed is not None, command
    assert (parsed["action"], parsed.get("value")) == expected, command
assert "CREATE TABLE IF NOT EXISTS tts_voice_settings" in SOURCE
tts_body = function_text("command_text_to_voice")
assert "get_tts_voice_settings" in tts_body
assert "gender=str(voice_profile.get" in tts_body
assert "style=str(voice_profile.get" in tts_body
assert "speed=str(voice_profile.get" in tts_body


# Calculator/conversion and visual market card are wired to group and private routes.
calculated = market_tools.calculate_expression("۱۱×۱۳")
assert calculated.result == "143"
assert "صورت مسئله" in calculated.response_text() and "پاسخ" in calculated.response_text()
snapshot = {
    "usd_toman": 100_000,
    "eur_toman": 110_000,
    "gbp_toman": 125_000,
    "gold_toman": 7_500_000,
    "source": "TEST",
    "updated_at": "NOW",
}
for request in ("120 دلار", "دلار 120", "25 یورو", "پوند 2", "2 طلا"):
    assert market_tools.parse_conversion_request(request) is not None, request
    converted = market_tools.conversion_text(request, snapshot)
    assert converted and "نتیجه" in converted and "تومان" in converted, request
assert "market_snapshot_data" in function_text("_market_snapshot_async")
assert "render_market_card" in function_text("command_market_card")
assert "has_operator" in function_text("parse_market_utility_command")
assert "command_market_utility" in router
private_body = function_text("process_private_inbound")
assert "parse_market_utility_command" in private_body


# Lock mutations invalidate hot state immediately; bulk changes require confirmation.
for setter in (
    "set_group_lock_enabled",
    "set_group_lock_max_warnings",
    "set_group_lock_auto_ban",
    "set_group_lock_action",
    "set_all_group_lock_max_warnings",
    "set_all_group_lock_auto_ban",
    "set_all_group_locks_enabled",
):
    assert "mark_group_backup_dirty(group_id)" in function_text(setter), setter
lock_cases = {
    "بستن لینک": ("enable_lock", "لینک"),
    "بستن قفل لینک": ("enable_lock", "لینک"),
    "خاموش کردن لینک": ("disable_lock", "لینک"),
    "قفل همه": ("bulk_preview", None),
    "تایید قفل همه": ("bulk_apply", None),
    "باز کردن همه قفل‌ها": ("bulk_preview", None),
    "تایید باز کردن همه قفل‌ها": ("bulk_apply", None),
}
for command, expected in lock_cases.items():
    parsed = admin_ux.parse_quick_lock_command(command)
    assert parsed is not None, command
    assert parsed["action"] == expected[0], command
    if expected[1] is not None:
        assert parsed["raw_name"] == expected[1], command
assert admin_ux.parse_quick_lock_command("بستن گروه") is not None
assert "set_all_group_locks_enabled" in function_text("command_group_lock")
cache_invalidator = function_text("invalidate_group_hot_caches")
for cache_name in (
    "_special_lock_default_hot",
    "_special_lock_override_hot",
    "_special_lock_override_absent_hot",
):
    assert cache_name in cache_invalidator, cache_name


# Installer preserves pre-existing provider/TTS/custom account settings and can
# restore account-env files created or changed by a failed deployment.
assert 'cat > "$ACCOUNT_ENV_DIR/main.env"' not in INSTALLER
assert 'MAIN_ENV_TMP="$(mktemp "$ACCOUNT_ENV_DIR/.main.env.${STAMP}.XXXXXX")"' in INSTALLER
assert "ZIVO_ACCOUNT_KEY|ZIVO_ACCOUNT_LABEL|ZIVO_ACCOUNT_CONTROLLER" in INSTALLER
assert 'mv -f -- "$MAIN_ENV_TMP" "$MAIN_ENV"' in INSTALLER
assert 'account-env-files.nul' in INSTALLER and 'account-env-files.ready' in INSTALLER
assert INSTALLER.index(': > "$ACCOUNT_ENV_MANIFEST_READY"') < INSTALLER.index('MAIN_ENV="$ACCOUNT_ENV_DIR/main.env"')


print("CHECK ZIVO60.96.11 ACTIVE/MARKET/VOICE/ADMIN/LOCKS: PASS")
