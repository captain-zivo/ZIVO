#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
SRC_PATH = ROOT / "zivo60.py"
SRC = SRC_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SRC)

m = re.search(r'VERSION = "zivo60\.96\.(\d+)"', SRC)
assert m and int(m.group(1)) >= 34, m.group(0) if m else "missing version"


def fn(name: str) -> str:
    node = next(
        n for n in ast.walk(TREE)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    return ast.get_source_segment(SRC, node) or ""

# Parser: bare cleanup is now a useful safe default; explicit counts remain exact.
parse_ns: Dict[str, Any] = {
    "re": re,
    "Dict": Dict,
    "Optional": Optional,
    "normalize_group_command": lambda s: " ".join(str(s or "").split()),
    "normalize_moderation_digits": lambda s: s,
}
exec(fn("parse_cleanup_command"), parse_ns)
parse = parse_ns["parse_cleanup_command"]
assert parse("پاکسازی") == {"action": "cleanup_count", "count": 100}
assert parse("پاکسازی پیام‌ها") == {"action": "cleanup_count", "count": 100}
assert parse("پاکسازی 250") == {"action": "cleanup_count", "count": 250}
assert parse("حذف 50") == {"action": "cleanup_count", "count": 50}

# Retry/verify behavior: the first delete times out after actually deleting 60/100.
# Verification must keep only the 40 live ids and retry exactly those.
class TimeoutDelete(Exception):
    pass

calls: List[List[int]] = []
live = set(range(1, 101))

async def governed(_group: Any, ids: Any, **_kwargs: Any) -> None:
    batch = [int(x) for x in ids]
    calls.append(batch)
    if len(calls) == 1:
        for mid in batch[:60]:
            live.discard(mid)
        raise TimeoutDelete("simulated shielded timeout")
    for mid in batch:
        live.discard(mid)

async def verifier(_group: Any, ids: List[int]) -> Dict[int, object]:
    return {int(mid): object() for mid in ids if int(mid) in live}

class Log:
    def warning(self, *a: Any, **k: Any) -> None: pass
    def info(self, *a: Any, **k: Any) -> None: pass

retry_ns: Dict[str, Any] = {
    "Any": Any,
    "List": List,
    "Tuple": Tuple,
    "Optional": Optional,
    "BaseException": BaseException,
    "asyncio": asyncio,
    "governed_delete_messages": governed,
    "cleanup_resolve_message_ids": verifier,
    "cleanup_error_is_permission": lambda exc: False,
    "cleanup_retry_wait_seconds": lambda exc, attempt: 0.01,
    "log": Log(),
}
exec(fn("delete_message_ids_in_batches"), retry_ns)
result = asyncio.run(retry_ns["delete_message_ids_in_batches"](type("G", (), {"id": 1})(), list(range(1, 101))))
assert result == (100, 0), result
assert [len(x) for x in calls] == [100, 40], calls
assert not live, live

# Permission failure must not spin three retries.
perm_calls: List[List[int]] = []
class PermissionDenied(Exception):
    pass
async def denied(_group: Any, ids: Any, **_kwargs: Any) -> None:
    perm_calls.append([int(x) for x in ids])
    raise PermissionDenied("CHAT_ADMIN_REQUIRED")
async def unavailable_verify(_group: Any, ids: List[int]) -> Dict[int, object]:
    raise RuntimeError("verify unavailable")
perm_ns: Dict[str, Any] = {
    "Any": Any, "List": List, "Tuple": Tuple, "Optional": Optional,
    "BaseException": BaseException, "asyncio": asyncio,
    "governed_delete_messages": denied,
    "cleanup_resolve_message_ids": unavailable_verify,
    "cleanup_error_is_permission": lambda exc: isinstance(exc, PermissionDenied),
    "cleanup_retry_wait_seconds": lambda exc, attempt: 0.01,
    "log": Log(),
}
exec(fn("delete_message_ids_in_batches"), perm_ns)
perm_result = asyncio.run(perm_ns["delete_message_ids_in_batches"](type("G", (), {"id": 2})(), [1,2,3,4]))
assert perm_result == (0, 4), perm_result
assert len(perm_calls) == 1, perm_calls

# Command UX must acknowledge start before potentially slow history/delete work.
command_src = fn("command_cleanup_messages")
assert "پاکسازی شروع شد" in command_src
assert "حذف و بررسی نتیجه در حال انجامه" in command_src

# Help must expose the new bare command rather than hiding it.
assert '("پاکسازی", "پاکسازی سریع پیش\u200cفرض' in SRC or '("پاکسازی", "پاکسازی سریع پیش‌فرض' in SRC

# Existing full cleanup remains separate and protected.
assert 'if text == "پاکسازی گپ":' in fn("parse_cleanup_command")
assert '"action": "full_cleanup"' in fn("parse_full_cleanup_command")

print("CHECK ZIVO60.96.34 CLEANUP RELIABILITY: PASS")
print("  bare پاکسازی -> safe default 100: PASS")
print("  timeout late-delete verify + retry remaining only: PASS")
print("  permission failure no retry storm: PASS")
print("  immediate cleanup-start UX: PASS")
print("  full-cleanup route separation preserved: PASS")
