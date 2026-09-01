#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
LINES = SRC.splitlines(True)
assert 'VERSION = "zivo60.96.32"' in SRC


def node(name: str):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def exec_fn(ns: dict[str, Any], name: str) -> None:
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), "exec"), ns)


class Log:
    def info(self, *a, **k): pass
    def warning(self, *a, **k): pass
    def debug(self, *a, **k): pass


def make_db(path: Path):
    def connect():
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        return con
    with connect() as con:
        con.executescript("""
        CREATE TABLE installations(
            group_id INTEGER PRIMARY KEY,
            owner_user_id INTEGER NOT NULL DEFAULT 0,
            owner_username TEXT NOT NULL DEFAULT '',
            owner_access_hash INTEGER NOT NULL DEFAULT 0,
            native_owner_user_id INTEGER NOT NULL DEFAULT 0,
            native_owner_username TEXT NOT NULL DEFAULT '',
            native_owner_access_hash INTEGER NOT NULL DEFAULT 0,
            owner_mode TEXT NOT NULL DEFAULT 'runtime'
        );
        CREATE TABLE bot_admins(group_id INTEGER, user_id INTEGER);
        CREATE TABLE bot_specials(group_id INTEGER, user_id INTEGER);
        CREATE TABLE special_lock_overrides(group_id INTEGER, user_id INTEGER);
        """)
        con.commit()
    return connect


# 1) Existing proven native-owner metadata must repair owner=0 without any live RPC.
with tempfile.TemporaryDirectory(prefix="zivo96_32_owner_native_") as td:
    connect = make_db(Path(td) / "db.sqlite")
    with connect() as con:
        con.execute(
            "INSERT INTO installations VALUES (23086873,0,'',0,68123456,'native_owner',987654321,'runtime')"
        )
        con.commit()

    def get_installation(gid):
        with connect() as con:
            return con.execute("SELECT * FROM installations WHERE group_id=?", (int(gid),)).fetchone()

    async def should_not_scan(group):
        raise AssertionError("live creator scan should not run when native metadata exists")

    ns = {
        "Any": Any, "sqlite3": sqlite3, "asyncio": asyncio,
        "db_connect": connect,
        "invalidate_group_hot_caches": lambda *a, **k: None,
        "refresh_role_membership_cache": lambda *a, **k: None,
        "get_installation": get_installation,
        "get_real_owner_recovery_cache": lambda gid: None,
        "find_group_creator": should_not_scan,
        "queue_global_profile_observation": lambda *a, **k: None,
        "safe_int": lambda v: int(v) if v is not None else None,
        "log": Log(),
    }
    exec_fn(ns, "reclaim_bot_ownership_for_real_group_owner")
    exec_fn(ns, "recover_owner_placeholder_for_display")
    row = get_installation(23086873)
    repaired = asyncio.run(ns["recover_owner_placeholder_for_display"](SimpleNamespace(), SimpleNamespace(id=23086873), 23086873, row))
    assert int(repaired["owner_user_id"]) == 68123456, dict(repaired)
    assert repaired["owner_username"] == "native_owner"
    assert int(repaired["owner_access_hash"]) == 987654321
    assert repaired["owner_mode"] == "native"


# 2) If metadata is empty, a real live creator must be persisted and returned.
with tempfile.TemporaryDirectory(prefix="zivo96_32_owner_live_") as td:
    connect = make_db(Path(td) / "db.sqlite")
    with connect() as con:
        con.execute("INSERT INTO installations VALUES (4455,0,'',0,0,'',0,'runtime')")
        con.commit()

    def get_installation(gid):
        with connect() as con:
            return con.execute("SELECT * FROM installations WHERE group_id=?", (int(gid),)).fetchone()

    observed: list[int] = []
    async def find_creator(group):
        return SimpleNamespace(id=778899, username="real_owner", access_hash=112233, first_name="مالک واقعی", last_name="")

    ns = {
        "Any": Any, "sqlite3": sqlite3, "asyncio": asyncio,
        "db_connect": connect,
        "invalidate_group_hot_caches": lambda *a, **k: None,
        "refresh_role_membership_cache": lambda *a, **k: None,
        "get_installation": get_installation,
        "get_real_owner_recovery_cache": lambda gid: None,
        "find_group_creator": find_creator,
        "queue_global_profile_observation": lambda uid, **kw: observed.append(int(uid)),
        "safe_int": lambda v: int(v) if v is not None else None,
        "log": Log(),
    }
    exec_fn(ns, "reclaim_bot_ownership_for_real_group_owner")
    exec_fn(ns, "recover_owner_placeholder_for_display")
    row = get_installation(4455)
    repaired = asyncio.run(ns["recover_owner_placeholder_for_display"](SimpleNamespace(), SimpleNamespace(id=4455), 4455, row))
    assert int(repaired["owner_user_id"]) == 778899, dict(repaired)
    assert repaired["owner_username"] == "real_owner"
    assert int(repaired["owner_access_hash"]) == 112233
    assert observed == [778899]


# 3) command_show_owner must never build/send a profile card for owner id 0.
sent: list[str] = []
async def fake_recover(event, group, group_id, installation): return installation
async def fake_send(group, text, **kw): sent.append(text)
async def forbidden_fetch(*a, **k): raise AssertionError("zero owner must not reach profile builder")
async def forbidden_card(*a, **k): raise AssertionError("zero owner must not reach owner card")

ns = {
    "Any": Any, "sqlite3": sqlite3,
    "recover_owner_placeholder_for_display": fake_recover,
    "send_group_text": fake_send,
    "fetch_owner_full_profile": forbidden_fetch,
    "send_owner_profile_card": forbidden_card,
    "log": Log(),
}
exec_fn(ns, "command_show_owner")
asyncio.run(ns["command_show_owner"](SimpleNamespace(), object(), 99, {"owner_user_id": 0}))
assert sent and "مالک گروه هنوز از سروش قابل بازیابی نیست" in sent[0], sent
assert "owner card blocked zero placeholder" in SRC
assert "recover_owner_placeholder_for_display" in SRC

print("CHECK ZIVO60.96.32 OWNER ZERO RECOVERY: PASS")
print("  owner=0 + proven native metadata -> durable repair: PASS")
print("  owner=0 + live creator -> durable repair: PASS")
print("  owner=0 can never render a fake owner card: PASS")
