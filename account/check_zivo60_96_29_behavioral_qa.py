#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional
from datetime import datetime, timezone, timedelta

import zivo_social_games as social

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.29"' in SRC


def node(name: str):
    return next(
        n for n in TREE.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )


def fn_text(name: str) -> str:
    n = node(name)
    lines = SRC.splitlines(True)
    return "".join(lines[n.lineno - 1:n.end_lineno])


def exec_fn(ns: dict[str, Any], name: str) -> None:
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), "exec"), ns)


# ---------------------------------------------------------------------------
# PET: persistence + natural name-call routing + cross-user isolation.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory(prefix="zivo_pet_call_") as td:
    db = Path(td) / "social.db"
    social.configure(db, global_owner_id=9001, bot_user_ids={9999})
    now = social._now()
    with sqlite3.connect(db) as con:
        con.execute(
            "INSERT INTO social_meow_accounts "
            "(user_id,balance,total_earned,total_spent,last_claim_at,created_at,updated_at) "
            "VALUES (30,10000,0,0,0,?,?)",
            (now, now),
        )
        con.commit()

    assert "هاسکی" in social.buy_pet(30, "سگ هاسکی")
    named = social.name_pet(30, "رکس")
    assert "رکس بیا" in named, named

    assert social.parse_social_command("رکس") is None
    assert social.parse_social_command("رکس", user_id=30)["action"] == "pet_call"
    assert social.parse_social_command("رکس", user_id=30)["call"] == "name"
    assert social.parse_social_command("رکس بیا", user_id=30)["call"] == "come"
    assert social.parse_social_command("رکس خوبی؟", user_id=30)["call"] == "how"
    assert social.parse_social_command("رکس چطوری؟", user_id=30)["call"] == "how"
    assert social.parse_social_command("رکس", user_id=31) is None
    assert "رکس" in social.pet_call(30, "come")

    # Restart-like reconfigure clears RAM cache; DB persistence must still route.
    social.configure(db, global_owner_id=9001, bot_user_ids={9999})
    assert social.parse_social_command("رکس بیا", user_id=30)["action"] == "pet_call"

assert "pet_call" in fn_text("command_social_group")
assert "pet_call" in fn_text("command_social_private")
assert "parse_social_command(text, user_id=user_id)" in fn_text("looks_like_priority_group_command")
assert "looks_like_priority_group_command(text, sender_id)" in fn_text("group_event_may_be_command")
assert 'looks_like_priority_group_command(getattr(event, "raw_text", None) or "", sender)' in SRC


# ---------------------------------------------------------------------------
# FORWARD: failed live verification is consumed, but not reported as complete;
# it must persist a durable delete retry and an audit record.
# ---------------------------------------------------------------------------
class FakeLog:
    def __init__(self):
        self.info_rows = []
        self.warning_rows = []
    def info(self, *args, **kwargs):
        self.info_rows.append(args)
    def warning(self, *args, **kwargs):
        self.warning_rows.append(args)


async def run_forward_case(delete_result: bool):
    queued = []
    audits = []
    punishments = []
    notices = []
    fake_log = FakeLog()

    async def delete_live_message_fast(*args, **kwargs):
        assert kwargs.get("verify") is True
        return bool(delete_result)

    async def apply_group_lock_punishment(*args, **kwargs):
        punishments.append((args, kwargs))
        return {"mode": "warning"}

    async def send_lock_violation_result(*args, **kwargs):
        notices.append((args, kwargs))

    ns = {
        "asyncio": asyncio,
        "Any": Any,
        "Optional": Optional,
        "safe_int": lambda value: int(value) if value is not None else None,
        "canonical_anti_spam_group_id": lambda value: int(value),
        "message_is_forwarded": lambda message: True,
        "SELF_USER_ID": 999999,
        "SYSTEM_USER_IDS": set(),
        "get_installation": lambda gid: {"group_id": gid},
        "is_group_bot_enabled": lambda gid: True,
        "lock_user_is_always_exempt": lambda gid, uid: False,
        "group_lock_row": lambda gid, name: {"enabled": 1, "direct_action": "warning"},
        "fast_event_group_target": lambda event: object(),
        "delete_live_message_fast": delete_live_message_fast,
        "queue_live_delete_retry": lambda *a, **kw: queued.append((a, kw)),
        "record_moderation_audit": lambda *a, **kw: audits.append((a, kw)),
        "apply_group_lock_punishment": apply_group_lock_punishment,
        "send_lock_violation_result": send_lock_violation_result,
        "log": fake_log,
    }
    exec_fn(ns, "maybe_enforce_forward_lock_fast")
    event = SimpleNamespace(
        is_private=False,
        chat_id=500,
        sender_id=77,
        id=900,
        message=SimpleNamespace(fwd_from=object()),
        input_sender=None,
    )
    handled = await ns["maybe_enforce_forward_lock_fast"](event, 500)
    return handled, queued, audits, punishments, notices, fake_log


handled, queued, audits, punishments, notices, fake_log = asyncio.run(run_forward_case(False))
assert handled is True  # consumed by moderation; not synonymous with delete success
assert len(queued) == 1 and queued[0][1]["reason"] == "forward_lock"
assert len(audits) == 1 and audits[0][0][3] == "forward_delete_pending"
assert len(punishments) == 1
assert len(fake_log.warning_rows) == 1
assert any("pending-delete" in str(row[0]) for row in fake_log.warning_rows)
assert not any("fast enforced" in str(row[0]) for row in fake_log.info_rows)

handled, queued, audits, punishments, notices, fake_log = asyncio.run(run_forward_case(True))
assert handled is True
assert queued == [] and audits == []
assert len(punishments) == 1
assert any("fast enforced" in str(row[0]) for row in fake_log.info_rows)


# ---------------------------------------------------------------------------
# Durable persistence contract: execute the real queue function against temp DB.
# ---------------------------------------------------------------------------
with tempfile.TemporaryDirectory(prefix="zivo_live_delete_") as td:
    db = Path(td) / "runtime.db"
    with sqlite3.connect(db) as con:
        con.execute(
            """
            CREATE TABLE live_delete_retry_jobs (
                group_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                target_user_id INTEGER NOT NULL DEFAULT 0,
                reason TEXT NOT NULL DEFAULT 'moderation',
                status TEXT NOT NULL DEFAULT 'pending',
                due_at TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(group_id, message_id)
            )
            """
        )
        con.commit()

    @contextmanager
    def db_connect():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            yield con
        finally:
            con.close()

    ns = {
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "db_connect": db_connect,
    }
    exec_fn(ns, "queue_live_delete_retry")
    ns["queue_live_delete_retry"](
        500, 900, target_user_id=77, reason="forward_lock", error="LIVE_VERIFY_PENDING"
    )
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM live_delete_retry_jobs WHERE group_id=500 AND message_id=900").fetchone()
    assert row is not None
    assert row["status"] == "pending" and row["target_user_id"] == 77
    assert row["reason"] == "forward_lock"

worker = fn_text("live_delete_retry_worker")
assert "_filter_message_exists_strict" in worker
assert "governed_delete_messages" in worker
assert "_complete_live_delete_retry" in worker
assert "_reschedule_live_delete_retry" in worker
assert "zivo-live-delete-durable-worker" in SRC

print("CHECK ZIVO60.96.29 BEHAVIORAL QA: PASS")
print("  PET natural name-call + persistence + isolation: PASS")
print("  forward failed-delete pending/audit semantics: PASS")
print("  durable forward delete persistence + verify worker contract: PASS")
