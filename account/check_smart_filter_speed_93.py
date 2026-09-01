#!/usr/bin/env python3
from __future__ import annotations
import ast, hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC)
assert 'VERSION = "zivo60.93"' in SRC

# Persian runtime baseline, intentionally advanced for the v60.95 social UI.
p=[n.value for n in ast.walk(TREE) if isinstance(n,ast.Constant) and isinstance(n.value,str) and any('\u0600'<=c<='\u06ff' for c in n.value)]
assert len(p)>=3992, len(p)
assert all(any(x in item for item in p) for x in ('مالک','ادمین','ویژه','راهنما'))

def fn(name: str) -> str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    lines=SRC.splitlines(True)
    return ''.join(lines[node.lineno-1:node.end_lineno])

# Filter matcher has short-phrase safety and avoids per-message phrase normalization.
matcher=fn('match_filtered_phrase_normalized')
assert 'compact_len <= 2' in matcher
assert 'compact_len < 6' in matcher
assert 'phrase_compact in compact_text' in matcher
assert 'normalize_filter_abuse_text(phrase_norm)' not in matcher
cache=fn('list_filtered_phrases_cached')
assert 'normalize_filter_abuse_text(row["phrase_norm"])[1]' in cache

# Filtered-message lock cannot become a permanent-ban false positive.
punish=fn('apply_group_lock_punishment')
assert 'lock_name == FILTERED_MESSAGE_LOCK_NAME' in punish
assert 'action_mode = "warning"' in punish
assert 'auto_ban = False' in punish
assert 'zivo60.93-smart-filter-strong-lock-autoban' in SRC

# Strong lock defaults and current-install migration exist without broadening soft locks.
assert 'for _strong_lock_index in (0, 1, 3, 12, 19)' in SRC
assert 'tuple(LOCK_CATALOG[index] for index in (16, 12, 19, 0, 1, 3))' in SRC

# Busy-group hot path no longer allocates enabled-lock set / lock dict copy per message.
rows=fn('group_lock_rows')
assert 'return cached[1]' in rows
assert 'return dict(cached[1])' not in rows
enabled=fn('enabled_group_lock_names')
assert '_group_enabled_lock_names_hot_cache' in enabled
hot=fn('maybe_enforce_group_lock')
assert 'enabled_group_lock_names(group_id, rows=lock_rows)' in hot
assert 'enabled_lock_names = {' not in hot

# Ban cleanup router remains before numeric cleanup.
pos_ban=SRC.index('if ban_audit_command is not None:')
pos_cleanup=SRC.index('if cleanup_command is not None:', pos_ban)
assert pos_ban < pos_cleanup

print('CHECK ZIVO60.93 SMART FILTER + STRONG WARNING BAN + GROUP HOT PATH: PASS')
