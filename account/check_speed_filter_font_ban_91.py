#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / "zivo60.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)
LINES = SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC


def fn(name: str) -> str:
    node = next(
        x for x in ast.walk(TREE)
        if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == name
    )
    return "".join(LINES[node.lineno - 1:node.end_lineno])


# 1) Group hot path: disabled locks must not run their classifiers; ordinary chatter
# must not enter the full command parser unless it resembles a documented command.
detect = fn("detect_lock_violations")
lock_guard = fn("maybe_enforce_group_lock")
command_gate = fn("group_event_may_be_command")
router = fn("_zivo_router_impl")
assert "enabled_locks" in detect and "wanted" in detect
assert "enabled_lock_names" in lock_guard
assert "match_filtered_guard_text" in lock_guard
assert "group_lock_rows(group_id)" in lock_guard
assert "looks_like_priority_group_command" in command_gate
assert "_tag_session" in command_gate and "allow_short=True" in command_gate
assert "command_candidate_hot" in router and "group_event_may_be_command" in router
cleanup_busy = fn("consume_cleanup_busy_group_event")
assert "group_cleanup_is_active" in cleanup_busy and "event.get_chat" not in cleanup_busy
warn_settings = fn("get_manual_warning_settings")
warn_count = fn("manual_warning_count")
repeat_level = fn("warning_repeat_level")
exact_count = fn("exact_content_filter_count")
assert "_manual_warning_settings_hot_cache" in warn_settings
assert "_manual_warning_count_hot_cache" in warn_count
assert "_warning_repeat_level_hot_cache" in repeat_level
assert "_exact_content_filter_count_hot_cache" in exact_count
assert "exact_content_filter_count(group_id) <= 0" in fn("maybe_enforce_exact_content_filter")
assert "GROUP_INSTALL_ROUTER_COMMANDS" in router
assert "performance-hotpath=enabled-locks+enabled-lock-set-cache+command-gate+filter-single-normalize+filter-precomputed-matchers+warning-cache+warning-ceiling+lock-notice-coalesce+exact-filter-presence+zero-rpc-cleanup" in SRC

# 2) Fixed filter is intentionally scoped to bio-check evasions, with manual filters
# and the other moderation locks remaining separate.
assert 'filter-history=recent100+verified-delete+evasion-normalize+biocheck-safe' in SRC
assign = next(
    n for n in TREE.body
    if (
        isinstance(n, ast.AnnAssign)
        and isinstance(n.target, ast.Name)
        and n.target.id == "FILTER_BUILTIN_COMPACT_PATTERNS"
    )
)
filter_block = ast.get_source_segment(SRC, assign) or ""
for token in ("بیوچک", "چکبیو", "biocheck", "checkbio"):
    assert token in filter_block, token
for broad in ("ممبرواقعی", "تبادلممبر", "دوستیابی", "joinmygroup", "جوینکانال"):
    assert broad not in filter_block, broad
assert 'filter_safety_key = "zivo60.90-filter-autoban-safe-default"' in SRC
assert '"پیام‌های فیلترشده": False' in SRC

# 3) Font command: execute the isolated pure transformation/parser functions and
# require exactly twelve distinct outputs for Latin and Persian input.
selected = []
for n in TREE.body:
    if isinstance(n, ast.FunctionDef) and n.name in {
        "_font_linear_map", "_font_circled", "_font_combining",
        "font_style_variants", "parse_font_command",
    }:
        selected.append(n)
mini = compile(ast.Module(body=selected, type_ignores=[]), "<font90>", "exec")
ns: Dict[str, Any] = {
    "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
    "FONT_TEXT_MAX_CHARS": 120,
    "normalize_group_command": lambda value: " ".join(str(value or "").replace("\u200c", " ").split()),
}
exec(mini, ns)
linear = ns["_font_linear_map"]
ns["FONT_STYLE_MAPS"] = (
    linear(0x1D400, 0x1D41A, 0x1D7CE),
    linear(0x1D5A0, 0x1D5BA, 0x1D7E2),
    linear(0x1D5D4, 0x1D5EE, 0x1D7EC),
    linear(0x1D608, 0x1D622, None),
    linear(0x1D63C, 0x1D656, None),
    linear(0x1D670, 0x1D68A, 0x1D7F6),
    linear(0xFF21, 0xFF41, 0xFF10),
)
ns["FONT_STYLE_WRAPPERS"] = (
    ("𓆩 ", " 𓆪"), ("『 ", " 』"), ("꧁ ", " ꧂"), ("༺ ", " ༻"),
    ("✦ ", " ✦"), ("♛ ", " ♛"), ("⫷ ", " ⫸"),
)
for sample in ("Zivo60", "سلام"):
    variants = ns["font_style_variants"](sample)
    assert len(variants) == 12, (sample, len(variants))
    assert len(set(variants)) == 12, sample
assert ns["parse_font_command"]("فونت zivo") == {"text": "zivo", "error": None}
assert ns["parse_font_command"]("فونت") == {"text": "", "error": "missing"}
assert ns["parse_font_command"]("سلام") is None
assert ns["parse_font_command"]("فونت " + "x" * 121)["error"] == "too_long"

# All three user-facing command paths and help registry must expose the feature.
assert '"key": "font_styles"' in SRC and '"help_command": "راهنما فونت"' in SRC
for function_name in ("handle_group_public_instant_command", "handle_group_commands", "process_private_inbound"):
    implementation_name = {
        "handle_group_public_instant_command": "_handle_group_public_instant_command_impl",
        "handle_group_commands": "_handle_group_commands_impl",
    }.get(function_name, function_name)
    body = fn(implementation_name)
    assert "parse_font_command" in body and "command_font" in body, function_name

# 4) Bulk ban cleanup must be a real on-platform release with bounded concurrency,
# warning reset and cleanup only after the platform release marks rows inactive.
bulk = fn("release_all_active_bans")
audit = fn("command_ban_audit")
assert "asyncio.Semaphore(BAN_BULK_RELEASE_CONCURRENCY)" in bulk
assert "release_zivo_ban" in bulk and 'source="bulk_cleanup"' in bulk
assert "reset_manual_warning" in bulk
assert "return_exceptions=True" in bulk
assert "banned = 0 AND muted = 0" in bulk
assert "release_all_active_bans" in audit
assert 'ban-tools=direct-unban+list-cleanup+bulk-release' in SRC
for alias in ("پاکسازی لیست بن ها", "پاکسازی کامل بن ها", "پاکسازی همه بن ها"):
    assert alias in SRC, alias

print("CHECK ZIVO60.91 SPEED/FILTER/FONT/BAN: PASS")
print("  group hot-path gate: PASS")
print("  conservative fixed filter: PASS")
print("  font 12 distinct styles: PASS")
print("  real bulk unban contract: PASS")
