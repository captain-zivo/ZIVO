#!/usr/bin/env python3
from __future__ import annotations

import ast
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
LINES = SRC.splitlines(True)

assert 'VERSION = "zivo60.96.31"' in SRC

def node(name: str):
    return next(
        n for n in TREE.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )

def fn_text(name: str) -> str:
    n = node(name)
    return "".join(LINES[n.lineno - 1:n.end_lineno])

def exec_fn(ns: dict, name: str) -> None:
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), "exec"), ns)

# 1) Transport circuit must not restart a healthy connection just because
# auto-reconnect happened more than three times with no pending pressure.
ns = {
    "TRANSPORT_PENDING_WARN": 32,
    "TRANSPORT_PENDING_CIRCUIT": 96,
    "TRANSPORT_PENDING_IMMEDIATE": 180,
    "TRANSPORT_RECONNECT_MAX": 3,
    "TRANSPORT_STAGNANT_SECONDS": 20.0,
}
exec_fn(ns, "transport_reconnect_should_restart")
exec_fn(ns, "transport_stuck_should_restart")
assert ns["transport_reconnect_should_restart"](0, 4) is False
assert ns["transport_reconnect_should_restart"](20, 8) is False
assert ns["transport_reconnect_should_restart"](40, 4) is True
assert ns["transport_reconnect_should_restart"](96, 1) is True

# Old live failure was pending=37 + stagnant=20s -> unnecessary restart.
assert ns["transport_stuck_should_restart"](37, 9, 20) is False
assert ns["transport_stuck_should_restart"](63, 50, 120) is False
assert ns["transport_stuck_should_restart"](64, 1, 30) is True
assert ns["transport_stuck_should_restart"](96, 3, 1) is True
assert ns["transport_stuck_should_restart"](180, 1, 0) is True

# 2) NOT_SUPPORTED GetParticipant must create an account-local capability
# backoff so the same guaranteed-failing RPC isn't repeated across groups.
requester = fn_text("_verified_requester_admin_from_group")
assert "_direct_participant_not_supported_until" in requester
assert "DIRECT_PARTICIPANT_NOT_SUPPORTED_BACKOFF_SECONDS" in requester
assert "requester_direct_not_supported_backoff" in requester
assert '"NOT_SUPPORTED" in upper' in requester

# 3) Hard no-write/private errors must create a 5-minute group send backoff.
send_text = fn_text("send_group_text")
send_mentions = fn_text("send_group_text_with_mentions")
assert 'globals().get("_group_send_hard_backoff_active")' in send_text
assert 'globals().get("_mark_group_send_hard_backoff")' in send_text
assert 'globals().get("_group_send_hard_backoff_active")' in send_mentions
assert 'globals().get("_mark_group_send_hard_backoff")' in send_mentions
assert "CHAT_WRITE_FORBIDDEN_BACKOFF" in send_text

# Plain-text formatting restriction must remain eligible for rich fallback,
# and must not be treated as a hard inaccessible group.
hard_error = fn_text("_is_group_hard_unavailable_error")
assert "CHATSENDPLAINFORBIDDEN" not in hard_error
assert "CHATWRITEFORBIDDEN" in hard_error
assert "CHANNELPRIVATE" in hard_error

# 4) Durable delete retry is background work and must yield when live delete
# circuit or transport pressure is active.
durable = fn_text("live_delete_retry_worker")
assert "live_delete_circuit_is_open()" in durable
assert "_transport_pending_request_count(client) >= TRANSPORT_PENDING_WARN" in durable

# 5) Background group-close repair must use long backoff on permissions.
close_worker = fn_text("process_group_close_schedules")
assert "retry_seconds = 600.0 if permission_failure" in close_worker

# 6) Health circuit explicitly closes cached aiohttp session before exit.
health = fn_text("transport_health_worker")
assert "await close_websocket_cache()" in health

print("CHECK ZIVO60.96.31 LIVE TRANSPORT RELIABILITY: PASS")
print("  healthy reconnect storm no longer forces restart: PASS")
print("  pending=37/stagnant=20 false-positive circuit fixed: PASS")
print("  NOT_SUPPORTED participant RPC capability backoff: PASS")
print("  inaccessible group send backoff: PASS")
print("  durable delete pressure deferral: PASS")
print("  group-close permission backoff: PASS")
