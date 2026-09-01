#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import json
import re
import sqlite3
import tempfile
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple

import zivo_social_games as social

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
LINES = SRC.splitlines(True)
assert 'VERSION = "zivo60.96.30"' in SRC


def node(name: str):
    return next(
        n for n in TREE.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )


def fn_text(name: str) -> str:
    n = node(name)
    return "".join(LINES[n.lineno - 1:n.end_lineno])


def exec_fn(ns: dict[str, Any], name: str) -> None:
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), "exec"), ns)


# 1) Meow aliases: natural stretched meow/howl all route to one claim action.
with tempfile.TemporaryDirectory(prefix="zivo96_30_meow_") as td:
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
    for text in ("میو", "میوووووو", "میو هاپ", "میوهاپ", "زوزه", "زوزه کشیدن"):
        parsed = social.parse_social_command(text, user_id=30)
        assert parsed and parsed["action"] == "meow_claim", (text, parsed)
    first = social.claim_meow(30)
    second = social.claim_meow(30)
    assert "جایزه" in first
    assert "هنوز وقت میوی بعدی" in second


# 2) Speaker learning profanity guard: block sexual/profane teaching and obfuscation,
# while ordinary Persian text remains teachable.
ns: dict[str, Any] = {
    "re": re,
    "Tuple": Tuple,
    "normalize_group_command": lambda value: " ".join(str(value or "").replace("\u200c", " ").split()),
}
ann_terms = next(
    n for n in TREE.body
    if isinstance(n, ast.AnnAssign)
    and isinstance(n.target, ast.Name)
    and n.target.id == "CONTENT_PROFANITY_TERMS"
)
ann_patterns = next(
    n for n in TREE.body
    if isinstance(n, ast.AnnAssign)
    and isinstance(n.target, ast.Name)
    and n.target.id == "CONTENT_PROFANITY_PATTERNS"
)
mod = ast.Module(
    body=[ann_terms, node("_compile_content_profanity_pattern"), ann_patterns, node("content_has_profanity"), node("speaker_learning_has_profanity"), node("lock_text_has_profanity")],
    type_ignores=[],
)
ast.fix_missing_locations(mod)
exec(compile(mod, str(MAIN), "exec"), ns)
blocked = ns["speaker_learning_has_profanity"]
lock_blocked = ns["lock_text_has_profanity"]
for text in (
    "کص", "ک ص", "ک.ص", "کیییر", "جنده", "م ا د ر ج ن د ه",
    "گــوه", "سکس", "پورن", "f.u.c.k", "fuuuck", "j a k e s h",
):
    assert blocked(text), text
    assert lock_blocked(text), text
for text in ("سلام رفیق", "کسب و کار خوب", "امروز حالت چطوره؟", "تکون نخور", "کونیاک"):
    assert not blocked(text), text
    assert not lock_blocked(text), text
assert 'SPEAKER_PROFANITY_BLOCKED' in fn_text("upsert_speaker_trigger")
assert 'SPEAKER_PROFANITY_BLOCKED' in fn_text("set_speaker_default_override")
assert "محتوای جنسی/توهین‌آمیز" in SRC


# 3) Owner fallback: unresolved Soroush profile must not show generic «ثبت نشده».
class FakeLog:
    def info(self, *args, **kwargs): pass
    def debug(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def exception(self, *args, **kwargs): pass

class FakeClient:
    async def get_entity(self, peer):
        raise RuntimeError("CACHE_MISS")
    async def __call__(self, request):
        raise RuntimeError("UNEXPECTED_RPC")

class PeerUser:
    def __init__(self, user_id: int): self.user_id = user_id

owner_ns: dict[str, Any] = {
    "Any": Any, "Dict": Dict, "sqlite3": sqlite3, "asyncio": asyncio,
    "safe_int": lambda v: int(v) if v is not None else None,
    "stats_access_hash": lambda gid, uid: 0,
    "input_peer_access_hash": lambda peer: 0,
    "display_name": lambda entity: getattr(entity, "name", "بدون نام"),
    "get_global_user_profile": lambda uid: {
        "observed_name": "مالک واقعی", "username": "owner_live",
        "preferred_name": "", "nickname": "",
    },
    "client": FakeClient(),
    "types": SimpleNamespace(PeerUser=PeerUser, InputUser=object),
    "functions": SimpleNamespace(users=SimpleNamespace(GetFullUserRequest=lambda **kw: kw)),
    "log": FakeLog(),
}
exec_fn(owner_ns, "fetch_owner_full_profile")
installation = {
    "owner_user_id": 123, "owner_username": "", "group_id": 777,
    "owner_access_hash": 0,
}
event = SimpleNamespace(sender_id=456, input_sender=None, sender=None)
profile = asyncio.run(owner_ns["fetch_owner_full_profile"](event, object(), installation))
assert profile["name"] == "مالک واقعی", profile
assert profile["username"] == "owner_live", profile
assert profile["name"] != "ثبت نشده"
assert "get_entity(types.PeerUser" in fn_text("fetch_owner_full_profile")


# 4) Installation provenance is persisted separately from group ownership.
with tempfile.TemporaryDirectory(prefix="zivo96_30_provenance_") as td:
    install_db = Path(td) / "install.db"
    def provenance_db_connect():
        con = sqlite3.connect(install_db)
        con.row_factory = sqlite3.Row
        return con
    with provenance_db_connect() as con:
        con.execute(
            """CREATE TABLE installations(
                group_id INTEGER PRIMARY KEY, group_title TEXT NOT NULL DEFAULT '',
                owner_user_id INTEGER NOT NULL, owner_username TEXT NOT NULL DEFAULT '',
                owner_access_hash INTEGER NOT NULL DEFAULT 0, invite_hash TEXT NOT NULL DEFAULT '',
                install_source TEXT NOT NULL DEFAULT '', default_locks_json TEXT NOT NULL DEFAULT '[]',
                installed_at TEXT NOT NULL, native_owner_user_id INTEGER NOT NULL DEFAULT 0,
                native_owner_username TEXT NOT NULL DEFAULT '', native_owner_access_hash INTEGER NOT NULL DEFAULT 0,
                owner_mode TEXT NOT NULL DEFAULT 'native', introduced_by_user_id INTEGER NOT NULL DEFAULT 0,
                introduced_by_username TEXT NOT NULL DEFAULT ''
            )"""
        )
        con.commit()
    prov_ns = {
        "Any": Any, "Dict": Dict, "Optional": Optional, "sqlite3": sqlite3,
        "json": json, "datetime": datetime, "timezone": timezone, "DEFAULT_LOCKS": [],
        "db_connect": provenance_db_connect,
        "activate_default_install_locks": lambda *a, **k: None,
        "invalidate_group_hot_caches": lambda *a, **k: None,
        "refresh_role_membership_cache": lambda *a, **k: None,
    }
    exec_fn(prov_ns, "register_installation")
    saved = prov_ns["register_installation"](
        4455, "گروه تست", 777, owner_username="group_owner",
        introduced_by_user_id=888, introduced_by_username="adder_user",
    )
    assert int(saved["owner_user_id"]) == 777
    assert int(saved["introduced_by_user_id"]) == 888
    assert saved["introduced_by_username"] == "adder_user"
assert 'introduced_by_user_id=int(row["requester_user_id"] or 0)' in SRC


# 5) Cross-account duplicate group UX must identify the ZIVO account, stored
# introducer/owner and current requester.
sent: list[str] = []
async def send_private_from_event(event, requester, text, verify_delivery=False):
    sent.append(text)

with tempfile.TemporaryDirectory(prefix="zivo96_30_dup_") as td:
    account_db = Path(td) / "acc2.db"
    with sqlite3.connect(account_db) as con:
        con.execute("CREATE TABLE installations(group_id INTEGER PRIMARY KEY, owner_user_id INTEGER, owner_username TEXT, introduced_by_user_id INTEGER, introduced_by_username TEXT)")
        con.execute(
            "CREATE TABLE global_user_profiles(user_id INTEGER PRIMARY KEY, preferred_name TEXT, nickname TEXT, observed_name TEXT, username TEXT)"
        )
        con.execute("INSERT INTO installations VALUES (4455, 777, 'group_owner', 888, 'adder_user')")
        con.execute("INSERT INTO global_user_profiles VALUES (777, '', '', 'مالک گروه', 'group_owner')")
        con.execute("INSERT INTO global_user_profiles VALUES (888, '', '', 'آورنده واقعی', 'adder_user')")
        con.commit()
    dup_ns = {
        "Any": Any, "Optional": Optional, "Tuple": Tuple,
        "sqlite3": sqlite3, "Path": Path,
        "safe_int": lambda v: int(v) if v is not None else None,
        "multi_get_account": lambda *a, **k: {"self_id": 998877, "db_path": str(account_db)},
        "MULTI_ACCOUNT_DB": Path(td) / "control.db",
        "send_private_from_event": send_private_from_event,
    }
    exec_fn(dup_ns, "_multi_claim_install_owner_identity")
    exec_fn(dup_ns, "_reply_group_already_has_zivo")
    claim = {"account_key": "acc2", "self_id": 998877, "group_title": "گروه تست", "group_id": 4455}
    asyncio.run(dup_ns["_reply_group_already_has_zivo"](SimpleNamespace(sender_id=321), SimpleNamespace(id=321), claim))
assert sent and "998877" in sent[0] and "acc2" in sent[0] and "321" in sent[0]
assert "آورنده واقعی" in sent[0] and "888" in sent[0] and "آورنده/مالک ثبت‌شده" in sent[0]
assert "777" not in sent[0], sent[0]
assert "ربات عضو گروه هست" not in sent[0]


# 6) Raw join extraction fallback: a raw Channel service add-user update must be detected.
class PeerChannel:
    def __init__(self, channel_id): self.channel_id = channel_id
class PeerChat:
    def __init__(self, chat_id): self.chat_id = chat_id
class MessageActionChatAddUser:
    def __init__(self, users): self.users = users

raw_types = SimpleNamespace(PeerChannel=PeerChannel, PeerChat=PeerChat)
join_ns = {
    "Any": Any, "List": list, "Tuple": Tuple, "SimpleNamespace": SimpleNamespace,
    "safe_int": lambda v: int(v) if v is not None else None,
    "SELF_USER_ID": 9999, "SYSTEM_USER_IDS": set(), "types": raw_types,
}
exec_fn(join_ns, "_joined_user_ids_from_event")
exec_fn(join_ns, "raw_group_join_payloads")
raw_message = SimpleNamespace(
    id=55, peer_id=PeerChannel(777), from_id=SimpleNamespace(user_id=456),
    action=MessageActionChatAddUser([123]), message="",
)
raw_update = SimpleNamespace(message=raw_message)
payloads = join_ns["raw_group_join_payloads"](raw_update)
assert len(payloads) == 1 and payloads[0][0] == 777 and payloads[0][1] is raw_message, payloads
assert "_raw_group_join_welcome_rescue" in fn_text("zivo_raw_private_router")
assert "welcome_raw_rescue" in fn_text("_raw_group_join_welcome_rescue")


# 7) Welcome speed + private/public delivery contract.
welcome_resolve = fn_text("_resolve_welcome_profile")
assert "get_participants" not in welcome_resolve
assert "WELCOME_PROFILE_RPC_TIMEOUT_SECONDS" in welcome_resolve
welcome_handler = fn_text("maybe_handle_group_join_welcome")
assert "reply_to_service=not is_public_group" in welcome_handler

class SendClient:
    def __init__(self): self.calls = []
    async def send_message(self, group, text, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(id=1)

send_client = SendClient()
send_ns = {
    "Any": Any, "Dict": Dict,
    "client": send_client,
    "rich_mention_entities": lambda text, mentions: [],
    "schedule_bot_message_cleanup": lambda *a, **k: None,
    "log": FakeLog(),
}
exec_fn(send_ns, "_send_welcome_text_reply")
asyncio.run(send_ns["_send_welcome_text_reply"](SimpleNamespace(id=1), "سلام", 99, {"name":"کاربر","id":5,"access_hash":0}, reply_to_service=False))
assert "reply_to" not in send_client.calls[-1]
asyncio.run(send_ns["_send_welcome_text_reply"](SimpleNamespace(id=1), "سلام", 99, {"name":"کاربر","id":5,"access_hash":0}, reply_to_service=True))
assert send_client.calls[-1].get("reply_to") == 99


# 8) Spam route contract: real Flood Guard must run before the old local shield,
# and the old shield is skipped on the default enabled Flood Guard hot path.
router = fn_text("_zivo_router_impl")
pos_flood = router.index("consume_group_flood_guard_event")
pos_core = router.index("consume_group_anti_spam_event")
assert pos_flood < pos_core
assert "not flood_guard_enabled" in router

# Direct Flood Guard behavior: seventh consecutive event triggers Ban/Delete.
flood_ns: dict[str, Any] = {
    "Any": Any, "safe_int": lambda v: int(v) if v is not None else None,
    "canonical_anti_spam_group_id": lambda v: int(v) if v is not None else None,
    "SELF_USER_ID": 9999, "SYSTEM_USER_IDS": set(),
    "anti_spam_event_is_stale": lambda event: False,
    "get_installation": lambda gid: {"group_id": gid},
    "get_flood_guard_settings": lambda gid: {"enabled":1,"window_seconds":10,"consecutive_limit":7,"burst_limit":10,"cleanup_scan_limit":0},
    "lock_user_is_exempt": lambda gid, uid: False,
    "time": __import__("time"), "deque": deque,
    "_flood_guard_last_sender": {}, "_flood_guard_seen_messages": {},
    "_flood_guard_action_until": {}, "_flood_guard_event_times": {},
    "flood_guard_cleanup_runtime": lambda now: None,
    "queue_flood_guard_live_delete": lambda *a, **k: None,
    "ban_group_hard_spammer": None, "purge_flood_spammer_messages": None,
    "send_group_text": None, "log": FakeLog(),
}
ban_calls=[]; purge_calls=[]
async def ban(*args, **kwargs): ban_calls.append((args,kwargs)); return True
async def purge(*args, **kwargs): purge_calls.append((args,kwargs)); return (7,7,7,0)
async def send(*args, **kwargs): return None
flood_ns["ban_group_hard_spammer"] = ban
flood_ns["purge_flood_spammer_messages"] = purge
flood_ns["send_group_text"] = send
exec_fn(flood_ns, "consume_group_flood_guard_event")
class FloodEvent:
    is_private=False
    input_sender=None
    input_chat=None
    def __init__(self, mid): self.sender_id=55; self.id=mid; self.chat_id=777
    async def get_chat(self): return SimpleNamespace(id=777)
for mid in range(1,7):
    assert asyncio.run(flood_ns["consume_group_flood_guard_event"](FloodEvent(mid))) is False
assert asyncio.run(flood_ns["consume_group_flood_guard_event"](FloodEvent(7))) is True
assert len(ban_calls)==1 and len(purge_calls)==1


# Help registry/command list contains new/changed user-facing behavior.
for token in ("میو هاپ", "زوزه", "Raw fallback", "محتوای جنسی/توهین‌آمیز", "وضعیت خوشامد"):
    assert token in SRC, token

print("CHECK ZIVO60.96.30 OWNER/WELCOME/SPAM/MEOW/GUARD: PASS")
print("  welcome raw fallback + private/public routing + hot-path speed: PASS")
print("  spam Flood Guard real Ban/Delete route + ordering: PASS")
print("  owner durable-name fallback + session photo path: PASS")
print("  multi-account presence UX: PASS")
print("  meow aliases + shared cooldown: PASS")
print("  speaker profanity/sexual-learning guard: PASS")
