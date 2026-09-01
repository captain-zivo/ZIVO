#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
import re
import tempfile
import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
MULTI = ROOT / "zivo_multi_account.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
MSRC = MULTI.read_text(encoding="utf-8")
ast.parse(MSRC)

assert 'VERSION = "zivo60.94.1"' in SRC


def function_source(name: str) -> str:
    node = next(
        item for item in ast.walk(TREE)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    lines = SRC.splitlines(True)
    return "".join(lines[node.lineno - 1:node.end_lineno])


# Every group command and file response inherits the exact source-message reply.
send_message = function_source("send_message")
send_file = function_source("send_file")
public_wrapper = function_source("handle_group_public_instant_command")
group_wrapper = function_source("handle_group_commands")
assert "_group_command_reply_to.get()" in send_message
assert "canonical_anti_spam_group_id(target_id)" in send_message
assert "_group_command_reply_to.get()" in send_file
assert "message_id" in public_wrapper and "_group_command_reply_to.set" in public_wrapper
assert "message_id" in group_wrapper and "_group_command_reply_to.set" in group_wrapper
for sender_name in (
    "send_file_resilient",
    "send_copyable_command_text", "send_stats_sectioned_report",
    "send_box_with_bold_ascii_numbers", "send_group_box",
    "send_group_box_with_mentions", "send_group_text",
    "send_group_text_with_mentions",
):
    assert "active_group_command_reply_id" in function_source(sender_name), sender_name

# Speaker AI/custom/fallback replies retain the triggering message id.
speaker = function_source("maybe_handle_speaker_message")
ai_worker = function_source("speaker_ai_queue_worker")
assert '"source_message_id": int(source_message_id or 0)' in speaker
assert "reply_to=source_message_id" in speaker
assert 'reply_to=safe_int(job.get("source_message_id"))' in ai_worker

# Reproduce the exact server regression: startup used to prime two-field filter
# tuples while the hot matcher unpacked three. The cache now self-heals and the
# startup primer stores three fields from the outset.
cache_node = next(
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "list_filtered_phrases_cached"
)
cache_ns: Dict[str, Any] = {
    "time": time,
    "Tuple": Tuple,
    "List": List,
    "FILTERED_PHRASE_CACHE_TTL": 300.0,
    "_filtered_phrase_cache": {77: (time.monotonic(), (("hello", "HELLO"),))},
    "normalize_filter_abuse_text": lambda value: (str(value), str(value).replace(" ", "")),
}
matcher_node = next(
    node for node in TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "match_filtered_phrase_normalized"
)
cache_ns.update({
    "Optional": Optional,
    "phrase_occurs_in_normalized_text": lambda text, phrase: phrase in text,
})
exec(compile(ast.Module(body=[cache_node, matcher_node], type_ignores=[]), str(MAIN), "exec"), cache_ns)
assert cache_ns["list_filtered_phrases_cached"](77) == (("hello", "HELLO", "hello"),)
assert cache_ns["match_filtered_phrase_normalized"](77, "say hello", "sayhello") == "HELLO"
prime = function_source("prime_hot_runtime_state")
assert "List[Tuple[str, str, str]]" in prime
assert "normalize_filter_abuse_text(phrase_norm)[1]" in prime

# Exercise the actual cleanup schedule parser without importing SPlusthon.
selected_names = {
    "normalize_group_command",
    "normalize_moderation_digits",
    "cleanup_schedule_amount_from_token",
    "parse_cleanup_schedule_command",
    "cleanup_schedule_next_run",
}
selected_nodes = [
    node for node in TREE.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in selected_names
]
schedule_ns: Dict[str, Any] = {
    "re": re,
    "datetime": datetime,
    "timezone": timezone,
    "IRAN_TZ": timezone(timedelta(hours=3, minutes=30)),
    "PERSIAN_ARABIC_TO_ASCII": str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"),
    "Any": Any,
    "Dict": Dict,
    "Optional": Optional,
    "Tuple": Tuple,
}
exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(MAIN), "exec"), schedule_ns)
parse_schedule = schedule_ns["parse_cleanup_schedule_command"]
assert parse_schedule("پاکسازی خودکار هر 1 ساعت 100") == {
    "action": "create", "schedule_kind": "interval", "interval_seconds": 3600,
    "local_time": "", "cleanup_count": 100,
}
assert parse_schedule("هر ۲ ساعت پاکسازی کل")["cleanup_count"] == 0
assert parse_schedule("هر یه ساعت پاکسازی کن")["interval_seconds"] == 3600
assert parse_schedule("هر یک ساعت پاکسازی کن")["cleanup_count"] == 100
assert parse_schedule("پاکسازی خودکار روزانه 03:30 200")["local_time"] == "03:30"
assert parse_schedule("هر شب ساعت 23:05 پاکسازی 700")["cleanup_count"] == 700
assert parse_schedule("حذف پاکسازی خودکار 12") == {"action": "delete", "schedule_id": 12}
assert parse_schedule("پاکسازی خودکار هر 5 دقیقه 100") == {"action": "invalid"}
assert "CREATE TABLE IF NOT EXISTS cleanup_schedules" in SRC
assert "scheduled_cleanup_worker()" in SRC
assert "is_group_pro_active_for_actor(group_id, actor_id)" in function_source("command_cleanup_schedule")

# Special GIF permission bypasses transport aliases and its checks are RAM-cached.
lock_body = function_source("maybe_enforce_group_lock")
assert '_special_lock_default_hot' in SRC and '_special_lock_override_hot' in SRC
assert 'category == "gif"' in lock_body
for alias in ("گیف", "فایل", "ویدیو", "فایل حجیم"):
    assert alias in lock_body

# Closed groups with manually-added ZIVO admins use the admin-safe soft lock.
close_body = function_source("close_group_send_access")
fallback_body = function_source("maybe_enforce_group_close_fallback")
assert "group_has_manual_zivo_admins(group_id)" in close_body
assert "baseline_rights" in close_body and "native_verified=False" in close_body
assert 'role in {"مالک", "ادمین"}' in fallback_body

# Target advertising exposes all accounts and durable coordinated cleanup.
assert '"z:tacct:all"' in SRC
assert "multi_signal_target_batch_reached" in function_source("run_target_growth_campaign_job")
assert "TARGET_REACHED_BY_BATCH" in MSRC
assert 'status="delete_failed"' in function_source("cleanup_target_campaign_banners")
assert "retry_partial_target_campaign_cleanup" in function_source("multi_account_campaign_worker")

spec = importlib.util.spec_from_file_location("zivo_multi_v94_test", MULTI)
multi = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(multi)
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "control.db"
    for key in ("main", "acc2", "acc3"):
        multi.register_account(
            db, account_key=key, label=key, phone="", self_id=1,
            enabled=True, is_controller=(key == "main"),
            session_path=f"{key}.session", db_path=f"{key}.db",
        )
    jobs = multi.create_campaign_jobs(
        db, batch_id="batch-v94", account_keys=["main", "acc2", "acc3"],
        scope="groups", content={"type": "text", "text": "banner"},
        repeat_count=1, interval_seconds=0, telegram_chat_id=1,
        telegram_message_id=2, campaign_mode="target_growth",
        target_group_link="https://splus.ir/example", target_group_id=10,
        target_member_count=500, baseline_member_count=400,
    )
    multi.update_job(db, jobs[1], status="running", sent_banner_count=2)
    changed = multi.signal_target_batch_reached(
        db, batch_id="batch-v94", source_job_id=jobs[0], current_member_count=500,
    )
    assert changed == 2
    running = multi.get_job(db, jobs[1])
    queued = multi.get_job(db, jobs[2])
    assert running["status"] == "running" and running["stop_requested"] == 1
    assert running["last_error"] == "TARGET_REACHED_BY_BATCH"
    assert queued["status"] == "target_reached" and queued["stop_requested"] == 1
    assert multi.recover_running_jobs(db, "acc2") == 1
    assert multi.get_job(db, jobs[1])["status"] == "target_reached_cleanup_partial"

# User-facing help includes every new workflow.
for text in (
    "COMMAND LIST 60.95",
    "پاکسازی خودکار هر 1 ساعت 100",
    "پاکسازی خودکار روزانه 03:30 200",
    "وضعیت پاکسازی خودکار",
    "پاکسازی خودکار خاموش",
    "پاکسازی خودکار فعال",
):
    assert text in SRC, text

print("CHECK ZIVO60.94 REPLY/SCHEDULE/ADMIN/GIF/PANEL/SPEED: PASS")
