#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.35"' in SRC


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


# 1) A local owner=0 placeholder must recover durable native-owner proof from
# another account DB instead of forcing a fragile live creator RPC.
with tempfile.TemporaryDirectory(prefix="zivo96_35_owner_cross_") as td:
    td = Path(td)
    local = td / "main.db"
    donor = td / "acc2.db"

    schema = """
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
    """
    for path in (local, donor):
        con = sqlite3.connect(path)
        con.executescript(schema)
        con.commit(); con.close()

    con = sqlite3.connect(local)
    con.execute("INSERT INTO installations VALUES (7001,0,'',0,0,'',0,'runtime')")
    con.commit(); con.close()
    con = sqlite3.connect(donor)
    con.execute("INSERT INTO installations VALUES (7001,991122,'old',123,991122,'real_owner',998877,'native')")
    con.commit(); con.close()

    def connect():
        con = sqlite3.connect(local)
        con.row_factory = sqlite3.Row
        return con

    def get_installation(gid):
        with connect() as con:
            return con.execute("SELECT * FROM installations WHERE group_id=?", (int(gid),)).fetchone()

    async def no_live_scan(group):
        raise AssertionError("cross-account durable owner proof should win before live RPC")

    ns: dict[str, Any] = {
        "Any": Any, "Dict": Dict, "Optional": Optional,
        "Path": Path, "sqlite3": sqlite3, "asyncio": asyncio,
        "DB_PATH": local, "ACCOUNT_KEY": "main",
        "_legacy_group_account_sources": lambda gid: [("main", str(local)), ("acc2", str(donor))],
        "db_connect": connect,
        "invalidate_group_hot_caches": lambda *a, **k: None,
        "refresh_role_membership_cache": lambda *a, **k: None,
        "get_installation": get_installation,
        "get_real_owner_recovery_cache": lambda gid: None,
        "find_group_creator": no_live_scan,
        "queue_global_profile_observation": lambda *a, **k: None,
        "safe_int": lambda v: int(v) if v is not None else None,
        "log": Log(),
    }
    exec_fn(ns, "legacy_cross_account_owner_hint")
    exec_fn(ns, "reclaim_bot_ownership_for_real_group_owner")
    exec_fn(ns, "recover_owner_placeholder_for_display")
    row = get_installation(7001)
    fixed = asyncio.run(ns["recover_owner_placeholder_for_display"](SimpleNamespace(), SimpleNamespace(id=7001), 7001, row))
    assert int(fixed["owner_user_id"]) == 991122, dict(fixed)
    assert fixed["owner_username"] == "real_owner"
    assert int(fixed["owner_access_hash"]) == 998877


# 2) Never trust a donor's temporary executive owner when native-owner proof is absent.
with tempfile.TemporaryDirectory(prefix="zivo96_35_owner_exec_") as td:
    td = Path(td)
    local = td / "main.db"; donor = td / "acc3.db"
    for path in (local, donor):
        con = sqlite3.connect(path)
        con.execute("""CREATE TABLE installations(
            group_id INTEGER PRIMARY KEY, owner_user_id INTEGER, owner_username TEXT,
            owner_access_hash INTEGER, native_owner_user_id INTEGER,
            native_owner_username TEXT, native_owner_access_hash INTEGER, owner_mode TEXT)""")
        con.commit(); con.close()
    con = sqlite3.connect(donor)
    con.execute("INSERT INTO installations VALUES (7002,555,'exec',444,0,'',0,'executive')")
    con.commit(); con.close()
    ns = {
        "Any": Any, "Dict": Dict, "Optional": Optional, "Path": Path, "sqlite3": sqlite3,
        "DB_PATH": local, "ACCOUNT_KEY": "main",
        "_legacy_group_account_sources": lambda gid: [("main", str(local)), ("acc3", str(donor))],
        "log": Log(),
    }
    exec_fn(ns, "legacy_cross_account_owner_hint")
    assert ns["legacy_cross_account_owner_hint"](7002) is None


# 3) Group-like proxy entities must use an admin-filtered fallback; an unfiltered
# member scan is not reliable in groups with more than 200 members.
class FakeChannel: pass
class FakeChat: pass
class FakeCreator:
    def __init__(self, user_id: int): self.user_id = user_id
class FakeChatCreator(FakeCreator): pass

creator = SimpleNamespace(id=778811, username="creator_proxy", access_hash=332211)
creator.participant = FakeCreator(778811)

async def fake_get_admins(group):
    return [creator]

class Client:
    async def get_participants(self, *a, **k):
        raise AssertionError("unfiltered member scan should not run after filtered creator is found")
    def __call__(self, *a, **k):
        raise AssertionError("direct Channel/Chat RPC should not run for proxy entity")

fake_types = SimpleNamespace(
    Channel=FakeChannel, Chat=FakeChat,
    ChannelParticipantCreator=FakeCreator,
    ChatParticipantCreator=FakeChatCreator,
)
ns = {
    "Any": Any, "Optional": Optional, "asyncio": asyncio,
    "types": fake_types, "client": Client(), "get_admins": fake_get_admins,
    "safe_int": lambda v: int(v) if v is not None else None,
    "participant_user_id": lambda p: int(getattr(p, "user_id", 0) or 0) or None,
    "log": Log(),
}
exec_fn(ns, "find_group_creator")
proxy_group = SimpleNamespace(id=8800, megagroup=True, broadcast=False)
found = asyncio.run(ns["find_group_creator"](proxy_group))
assert int(found.id) == 778811

# 4) The old owner=0 safety contract and user-facing no-fake-card behavior must remain.
assert "owner card blocked zero placeholder" in SRC
assert "source=filtered_admin_fallback" in SRC
assert "source=cross_account_" in SRC

print("CHECK ZIVO60.96.35 OWNER MULTIGROUP RECOVERY: PASS")
print("  owner=0 + sibling-account native proof -> durable repair: PASS")
print("  temporary executive donor is not trusted as native owner: PASS")
print("  proxy/group-like entity -> filtered admin creator fallback: PASS")
print("  zero-owner fake-card safety preserved: PASS")
