#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib.util
import os
import re
import sqlite3
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SOCIAL = ROOT / "zivo_social_games.py"
SRC = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.15"' in SRC


def nodes(*names: str) -> list[ast.AST]:
    wanted = set(names)
    result = [
        node for node in TREE.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted
    ]
    missing = wanted - {getattr(node, "name", "") for node in result}
    assert not missing, missing
    return result


def exec_functions(namespace: dict[str, Any], *names: str) -> dict[str, Any]:
    module = ast.Module(body=nodes(*names), type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(MAIN), "exec"), namespace)
    return namespace


# ---------------------------------------------------------------------------
# 1) Pet resolver: every real catalog item must resolve by canonical and by the
# exact breed text shown to users. No new pet is created.
# ---------------------------------------------------------------------------
spec = importlib.util.spec_from_file_location("zivo_social_games_9612_test", SOCIAL)
assert spec and spec.loader
social = importlib.util.module_from_spec(spec)
spec.loader.exec_module(social)
assert len(social.PET_CATALOG) == 30
assert len([v for v in social.PET_ALIASES.values() if v]) == 30
for canonical, item in social.PET_CATALOG.items():
    species, breed, _price = item
    assert social.resolve_pet_catalog_item(canonical) == item
    assert social.resolve_pet_catalog_item(breed) == item, (species, breed)
    assert social.resolve_pet_catalog_item(f"  {species}\u200c{breed}  ") == item
assert social.resolve_pet_catalog_item("مين\u200cكون")[1] == "مین کون"
assert social.resolve_pet_catalog_item("شاه-طوطي")[1] == "شاه طوطی"
assert social.resolve_pet_catalog_item("پت خیالی") is None

with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "social.db"
    social.configure(db, global_owner_id=0, bot_user_ids=())
    # Zero balance is enough to prove buy_pet reached the real catalog item
    # instead of returning the old "breed not found" error.
    for _canonical, (_species, breed, _price) in social.PET_CATALOG.items():
        result = social.buy_pet(90001, breed)
        assert "این نژاد پیدا نشد" not in result, (breed, result)


# ---------------------------------------------------------------------------
# 2) Global origin/profile migration + full staged flow + restart persistence.
# Extract and execute the REAL project functions against a temporary old-schema DB.
# ---------------------------------------------------------------------------
lock_catalog = (
    "تبلیغات", "لینک", "متن", "آیدی", "استیکر", "عکس", "ویدیو", "ویس", "فایل",
    "فایل حجیم", "گیف", "آهنگ", "فحش", "پیام‌های فیلترشده", "متن انگلیسی", "ریپلای",
    "فوروارد", "ویرایش", "ایموجی", "کد هنگی", "نظرسنجی", "شماره تلفن", "عدد", "هشتگ",
)

with tempfile.TemporaryDirectory() as td:
    db_path = Path(td) / "zivo.db"
    con = sqlite3.connect(db_path)
    con.execute(
        """
        CREATE TABLE global_user_profiles (
            user_id INTEGER PRIMARY KEY,
            preferred_name TEXT NOT NULL DEFAULT '',
            nickname TEXT NOT NULL DEFAULT '',
            observed_name TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        "INSERT INTO global_user_profiles VALUES (42,'نام قدیمی','لقب قدیمی','','olduser','t0','t0','t0')"
    )
    con.commit(); con.close()

    def db_connect() -> sqlite3.Connection:
        c = sqlite3.connect(db_path, timeout=5.0)
        c.row_factory = sqlite3.Row
        return c

    init_ns: dict[str, Any] = {
        "db_connect": db_connect,
        "datetime": datetime,
        "timezone": timezone,
        "timedelta": timedelta,
        "LOCK_CATALOG": lock_catalog,
        "LOCK_DEFAULT_MAX_WARNINGS": 3,
        "FILTERED_MESSAGE_LOCK_NAME": lock_catalog[13],
    }
    exec_functions(init_ns, "init_db")
    init_ns["init_db"]()
    init_ns["init_db"]()  # migration must be idempotent across restarts/deploys

    with db_connect() as c:
        cols = {row[1] for row in c.execute("PRAGMA table_info(global_user_profiles)")}
        assert {"age", "origin"}.issubset(cols)
        old = c.execute(
            "SELECT preferred_name,nickname,username,age,origin FROM global_user_profiles WHERE user_id=42"
        ).fetchone()
        assert tuple(old) == ("نام قدیمی", "لقب قدیمی", "olduser", 0, "")
        state_cols = {row[1] for row in c.execute("PRAGMA table_info(global_origin_registration)")}
        assert {"user_id", "stage", "preferred_name", "nickname", "age", "origin", "context_kind", "context_id"}.issubset(state_cols)

    hot: dict[int, tuple[float, Dict[str, Any]]] = {}
    pending: dict[int, tuple[str, int]] = {}
    profile_ns: dict[str, Any] = {
        "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
        "db_connect": db_connect,
        "global_profile_db_connect": db_connect,
        "datetime": datetime, "timezone": timezone, "time": time, "re": re,
        "GLOBAL_PROFILE_CACHE_TTL_SECONDS": 600.0,
        "GLOBAL_PROFILE_TEXT_MAX": 64,
        "_global_user_profile_hot": hot,
        "_global_origin_registration_pending": pending,
        "PERSIAN_ARABIC_TO_ASCII": str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
        ),
    }
    exec_functions(
        profile_ns,
        "safe_int", "normalize_group_command", "normalize_moderation_digits", "_clean_global_profile_text",
        "get_global_user_profile", "_normalize_profile_age",
        "global_origin_registration_context_matches", "start_global_origin_registration",
        "cancel_global_origin_registration", "advance_global_origin_registration", "global_origin_card_text",
        "parse_global_identity_command",
    )

    start = profile_ns["start_global_origin_registration"]
    advance = profile_ns["advance_global_origin_registration"]
    get_profile = profile_ns["get_global_user_profile"]
    card = profile_ns["global_origin_card_text"]
    parse_identity = profile_ns["parse_global_identity_command"]

    assert parse_identity("ثبت اصل") == {"action": "origin_start"}
    assert parse_identity("اصلش") == {"action": "origin_show"}
    assert "1️⃣" in start(42, "group", 100)
    assert advance(42, "علی رضایی", "group", 100)[1]
    assert advance(42, "قهرمان", "group", 100)[1]
    age_msg, handled = advance(42, "۲۶ سال", "group", 100)
    assert handled and "4️⃣" in age_msg
    done_msg, handled = advance(42, "شیرازی", "group", 100)
    assert handled and "اصل سراسری ثبت شد" in done_msg
    p = get_profile(42)
    assert p["preferred_name"] == "علی رضایی" and p["nickname"] == "قهرمان"
    assert int(p["age"]) == 26 and p["origin"] == "شیرازی"
    assert "شیرازی" in card(42, p)

    # The profile is keyed only by user_id; there is no group_id in retrieval.
    # This is the concrete cross-group invariant requested by the feature.
    hot.clear()
    p_group_b = get_profile(42)
    assert p_group_b["origin"] == "شیرازی" and int(p_group_b["age"]) == 26

    # Restart persistence during an unfinished conversation.
    assert "1️⃣" in start(77, "group", 555)
    advance(77, "کاربر تست", "group", 555)
    pending.clear()  # simulate process restart / RAM loss
    with db_connect() as c:
        rows = c.execute("SELECT user_id, context_kind, context_id FROM global_origin_registration").fetchall()
    pending.update({int(r["user_id"]): (str(r["context_kind"]), int(r["context_id"])) for r in rows})
    assert advance(77, "ندارم", "group", 555)[1]
    assert advance(77, "31", "group", 555)[1]
    assert advance(77, "تبریزی", "group", 555)[1]
    hot.clear()
    p77 = get_profile(77)
    assert p77["preferred_name"] == "کاربر تست" and p77["nickname"] == ""
    assert int(p77["age"]) == 31 and p77["origin"] == "تبریزی"


# ---------------------------------------------------------------------------
# 3) Media/file/photo/code wrapper regression using the REAL classifier functions.
# ---------------------------------------------------------------------------
media_ns: dict[str, Any] = {
    "Any": Any, "Dict": Dict, "Optional": Optional,
    "hashlib": hashlib,
}
exec_functions(
    media_ns,
    "safe_int", "safe_message_property", "document_runtime_signature",
    "infer_document_category_hardened", "message_stats_category", "robust_message_category",
    "normalize_group_command", "canonical_content_text", "exact_content_preview", "exact_content_descriptor",
)
category = media_ns["robust_message_category"]
descriptor = media_ns["exact_content_descriptor"]

class Photo:
    def __init__(self, ident: int): self.id = ident
class MessageMediaPhoto:
    def __init__(self, ident: int): self.photo = Photo(ident)
class Document:
    def __init__(self, ident: int, mime: str = "application/pdf"):
        self.id = ident; self.mime_type = mime; self.size = 1234; self.attributes = []
class MessageMediaDocument:
    def __init__(self, ident: int): self.document = Document(ident)
class Inner:
    pass
class Outer:
    def __init__(self, inner: Any): self._message = inner
    # Some wrappers expose False for absent friendly fields; the classifier must
    # continue into the raw message instead of treating False as real media.
    photo = False
    document = False

inner_photo = Inner(); inner_photo.media = MessageMediaPhoto(12345); inner_photo.raw_text = ""
outer_photo = Outer(inner_photo)
assert category(outer_photo) == "photo"
d = descriptor(outer_photo)
assert d and d["content_type"] == "photo" and d["fingerprint"] == "media:photo:12345"

inner_file = Inner(); inner_file.media = MessageMediaDocument(54321); inner_file.raw_text = ""
outer_file = Outer(inner_file)
assert category(outer_file) == "file"
d = descriptor(outer_file)
assert d and d["content_type"] == "file" and d["fingerprint"] == "media:file:54321"

inner_code = Inner(); inner_code.raw_text = "print('zivo')\nfor i in range(3):\n    print(i)"
outer_code = Outer(inner_code)
d = descriptor(outer_code)
assert d and d["content_type"] == "text" and d["fingerprint"].startswith("text:")


# ---------------------------------------------------------------------------
# 4) Cleanup parser + real batch executor contract and performance constant.
# ---------------------------------------------------------------------------
cleanup_ns: dict[str, Any] = {
    "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
    "asyncio": asyncio, "re": re,
    "PERSIAN_ARABIC_TO_ASCII": str.maketrans(
        "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"
    ),
}
exec_functions(cleanup_ns, "normalize_group_command", "normalize_moderation_digits", "safe_int", "parse_cleanup_command", "delete_message_ids_in_batches")
assert cleanup_ns["parse_cleanup_command"]("پاکسازی 250") == {"action": "cleanup_count", "count": 250}
assert cleanup_ns["parse_cleanup_command"]("حذف") == {"action": "delete_reply"}

calls: list[list[int]] = []
async def fake_governed(_group: Any, ids: Any, **_kwargs: Any) -> None:
    calls.append(list(ids))
cleanup_ns["governed_delete_messages"] = fake_governed
cleanup_ns["log"] = type("Log", (), {"warning": staticmethod(lambda *a, **k: None)})()
class Group: id = 1
result = asyncio.run(cleanup_ns["delete_message_ids_in_batches"](Group(), list(range(1, 251))))
assert result == (250, 0), result
assert [len(x) for x in calls] == [100, 100, 50], calls

match = re.search(r'ZIVO_DELETE_RPC_MIN_INTERVAL",\s*"([0-9.]+)"', SRC)
assert match and float(match.group(1)) == 3.0
old_batches_700 = 6 * 4.8
new_batches_700 = 6 * 3.0
assert new_batches_700 < old_batches_700

# Installer must not overwrite the faster delete default with the old 4.80s value.
# During installed-copy validation ROOT is /opt/zivo60, which may contain an
# older installer from a previous release because the transactional installer
# does not deploy itself. Validate the explicit current-release installer when
# the caller provides it; standalone checks keep the historical local fallback.
installer_path = Path(os.environ.get("ZIVO_INSTALLER_UNDER_TEST", str(ROOT / "install_zivo60.sh")))
installer_text = installer_path.read_text(encoding="utf-8")
assert 'ZIVO_DELETE_RPC_MIN_INTERVAL=3.00' in installer_text
assert 'ZIVO_DELETE_RPC_MIN_INTERVAL=4.80' not in installer_text

# The response hot path should query cleanup settings once and then use RAM cache.
with tempfile.TemporaryDirectory() as td:
    hot_db = Path(td) / "hot.db"
    con = sqlite3.connect(hot_db)
    con.execute("CREATE TABLE bot_message_cleanup_settings (group_id INTEGER PRIMARY KEY, enabled INTEGER, warning_seconds INTEGER, welcome_seconds INTEGER, general_seconds INTEGER)")
    con.commit(); con.close()
    connect_calls = 0
    def hot_db_connect() -> sqlite3.Connection:
        nonlocal_holder[0] += 1
        c = sqlite3.connect(hot_db); c.row_factory = sqlite3.Row; return c
    nonlocal_holder = [0]
    cache_ns: dict[str, Any] = {
        "Any": Any, "Dict": Dict, "Tuple": Tuple, "time": time,
        "db_connect": hot_db_connect,
        "_bot_message_cleanup_settings_hot_cache": {},
        "CLEANUP_SETTINGS_CACHE_TTL_SECONDS": 300.0,
    }
    exec_functions(cache_ns, "get_bot_message_cleanup_settings")
    for _ in range(1000):
        state = cache_ns["get_bot_message_cleanup_settings"](123)
        assert state["general_seconds"] == 0
    assert nonlocal_holder[0] == 1, nonlocal_holder[0]

# Existing scheduled cleanup contract remains connected to the same verified
# full-delete function rather than a parallel implementation.
assert "async def scheduled_cleanup_worker" in SRC
assert "await execute_cleanup_schedule(row)" in SRC
schedule_source = ast.get_source_segment(SRC, next(n for n in TREE.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute_cleanup_schedule")) or ""
assert "delete_full_cleanup_batch" in schedule_source and "execute_full_chat_cleanup" in schedule_source

# Exercise the real manual cleanup command with a fake Soroush history/API.
manual_ns: dict[str, Any] = {
    "Any": Any, "Dict": Dict, "List": List, "Optional": Optional, "Tuple": Tuple,
    "asyncio": asyncio,
}
exec_functions(manual_ns, "safe_int", "delete_message_ids_in_batches", "command_cleanup_messages")
manual_calls: list[list[int]] = []
manual_sent: list[str] = []
manual_active: dict[int, int] = {}
class FakeMsg:
    def __init__(self, ident: int, pinned: bool = False): self.id=ident; self.pinned=pinned
class FakeClient:
    async def get_messages(self, _group: Any, *, limit: int, offset_id: int):
        rows = [FakeMsg(i, pinned=(i == 249)) for i in range(offset_id - 1, max(0, offset_id - limit - 1), -1)]
        return rows
manual_ns["client"] = FakeClient()
async def manual_governed(_group: Any, ids: Any, **_kwargs: Any) -> None:
    manual_calls.append(list(ids) if isinstance(ids, (list, tuple)) else [int(ids)])
manual_ns["governed_delete_messages"] = manual_governed
manual_ns["cleanup_actor_check"] = lambda _gid, _uid: (True, "مالک")
manual_ns["command_cleanup_pin_confirmation"] = lambda *a, **k: None
manual_ns["group_cleanup_command_id"] = lambda gid: manual_active.get(int(gid))
manual_ns["_group_cleanup_active"] = manual_active
manual_ns["message_is_pinned"] = lambda msg: bool(getattr(msg, "pinned", False))
manual_ns["save_cleanup_pin_confirmation"] = lambda _gid, _uid, ids, _src: len(ids)
manual_ns["increment_deleted_message_counter"] = lambda *_a, **_k: None
async def manual_send(_group: Any, text: str) -> None: manual_sent.append(text)
manual_ns["send_group_text"] = manual_send
manual_ns["log"] = type("Log", (), {"warning": staticmethod(lambda *a, **k: None), "info": staticmethod(lambda *a, **k: None)})()
class FakeEvent:
    sender_id=1; id=300; is_reply=False
manual_result = asyncio.run(manual_ns["command_cleanup_messages"](FakeEvent(), Group(), 1, {"action":"cleanup_count","count":250}))
assert manual_result is None
assert sum(len(batch) for batch in manual_calls) == 249  # one pinned is protected
assert [len(batch) for batch in manual_calls] == [100, 100, 49]
assert manual_active == {}
assert any("حذف‌شده: 249" in text for text in manual_sent)

# Exercise the real scheduled cleanup executor against a temporary DB.
with tempfile.TemporaryDirectory() as td:
    cleanup_db = Path(td) / "cleanup.db"
    con = sqlite3.connect(cleanup_db)
    con.execute("CREATE TABLE cleanup_schedules (schedule_id INTEGER PRIMARY KEY, enabled INTEGER, next_run_at TEXT, last_result TEXT DEFAULT '', updated_at TEXT DEFAULT '')")
    con.execute("INSERT INTO cleanup_schedules(schedule_id,enabled,next_run_at) VALUES (5,1,'2000-01-01T00:00:00+00:00')")
    con.commit(); con.close()
    def cleanup_db_connect() -> sqlite3.Connection:
        c=sqlite3.connect(cleanup_db); c.row_factory=sqlite3.Row; return c
    auto_ns: dict[str, Any] = {
        "Any": Any, "List": List, "asyncio": asyncio, "sqlite3": sqlite3,
        "datetime": datetime, "timezone": timezone, "timedelta": timedelta, "time": time,
        "db_connect": cleanup_db_connect, "_group_cleanup_active": {},
        "_group_send_probe_retry_after": {},
    }
    exec_functions(auto_ns, "safe_int", "execute_cleanup_schedule")
    class AutoClient:
        async def get_messages(self, _target: Any, *, limit: int, offset_id: int):
            return [FakeMsg(i) for i in range(1, int(limit)+1)]
    auto_ns["client"] = AutoClient()
    auto_ns["get_installation"] = lambda _gid: {"group_id": int(_gid)}
    auto_ns["is_group_bot_enabled"] = lambda _gid: True
    auto_ns["base_bot_role"] = lambda _gid,_uid: "مالک"
    auto_ns["_is_group_inaccessible_error"] = lambda _exc: False
    auto_ns["group_cleanup_is_active"] = lambda _gid: False
    auto_ns["is_group_pro_active_for_actor"] = lambda _gid,_uid: True
    async def resolve_target(_gid: int): return Group()
    auto_ns["resolve_cleanup_schedule_target"] = resolve_target
    auto_ns["message_is_pinned"] = lambda msg: bool(getattr(msg,"pinned",False))
    auto_deleted: list[list[int]] = []
    async def auto_delete(_target: Any, ids: list[int]): auto_deleted.append(list(ids)); return len(ids), 0
    auto_ns["delete_full_cleanup_batch"] = auto_delete
    async def full_cleanup(*_a, **_k): return (0,0,0,[])
    auto_ns["execute_full_chat_cleanup"] = full_cleanup
    auto_ns["increment_deleted_message_counter"] = lambda *_a,**_k: None
    auto_messages: list[str] = []
    async def auto_send(_target: Any, text: str): auto_messages.append(text)
    auto_ns["send_group_text"] = auto_send
    auto_ns["log"] = type("Log", (), {"warning": staticmethod(lambda *a, **k: None), "info": staticmethod(lambda *a, **k: None)})()
    row={"schedule_id":5,"group_id":1,"cleanup_count":250,"created_by":1}
    asyncio.run(auto_ns["execute_cleanup_schedule"](row))
    assert [len(x) for x in auto_deleted] == [100,100,50]
    with cleanup_db_connect() as c:
        last=c.execute("SELECT last_result FROM cleanup_schedules WHERE schedule_id=5").fetchone()[0]
    assert "deleted=250" in last and "failed=0" in last
    assert any("حذف‌شده: 250" in t for t in auto_messages)

print("CHECK ZIVO60.96.12 PERFORMANCE/CLEANUP/PET/ORIGIN/MEDIA: PASS")
print("  pet catalog canonical+breed aliases: 30/30")
print("  global origin migration + staged flow + restart + cross-group: PASS")
print("  nested photo/document + code descriptor: PASS")
print("  manual cleanup 250 + scheduled executor + cleanup hot-cache: PASS")
print("  delete idle spacing: 4.80s -> 3.00s default")
