#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / "zivo60.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
NAMES = {
    "register_installation",
    "_group_lifecycle_upsert_in_connection",
    "_activation_card_job_upsert_in_connection",
    "_activation_card_job_upsert",
    "_activation_card_ensure_job_from_installation",
    "_activation_card_repair_missing_jobs",
    "_activation_card_jobs_due",
    "_activation_card_complete",
    "_activation_card_resolve_group",
    "resolve_group_lifecycle_target",
    "_post_activation_card_task",
}


class QuietLog:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass

    def warning(self, *args: Any, **kwargs: Any) -> None:
        pass

    def debug(self, *args: Any, **kwargs: Any) -> None:
        pass


def extracted_namespace(db_path: Path) -> Dict[str, Any]:
    nodes = [node for node in TREE.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in NAMES]
    module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))

    @contextmanager
    def db_connect():
        con = sqlite3.connect(db_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    namespace: Dict[str, Any] = {
        "Any": Any,
        "Dict": Dict,
        "List": List,
        "Optional": Optional,
        "sqlite3": sqlite3,
        "asyncio": asyncio,
        "datetime": datetime,
        "timezone": timezone,
        "json": json,
        "DEFAULT_LOCKS": [],
        "ACTIVATION_CARD_BATCH_MAX": 8,
        "db_connect": db_connect,
        "activate_default_install_locks": lambda *args: None,
        "invalidate_group_hot_caches": lambda *args: None,
        "refresh_role_membership_cache": lambda *args: None,
        "_installation_hot_cache": {},
        "_activation_card_entity_cache": {},
        "_activation_card_wakeup": None,
        "log": QuietLog(),
    }
    exec(compile(module, "<activation-card-recovery>", "exec"), namespace)
    return namespace


def create_schema(db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as con:
        con.executescript(
            """
            CREATE TABLE installations (
                group_id INTEGER PRIMARY KEY,
                group_title TEXT NOT NULL DEFAULT '',
                owner_user_id INTEGER NOT NULL,
                owner_username TEXT NOT NULL DEFAULT '',
                owner_access_hash INTEGER NOT NULL DEFAULT 0,
                invite_hash TEXT NOT NULL DEFAULT '',
                install_source TEXT NOT NULL DEFAULT '',
                default_locks_json TEXT NOT NULL DEFAULT '[]',
                installed_at TEXT NOT NULL,
                native_owner_user_id INTEGER NOT NULL DEFAULT 0,
                native_owner_username TEXT NOT NULL DEFAULT '',
                native_owner_access_hash INTEGER NOT NULL DEFAULT 0,
                owner_mode TEXT NOT NULL DEFAULT 'native',
                activation_card_state TEXT NOT NULL DEFAULT 'legacy',
                activation_card_delivered_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE pending_group_activations (
                group_id INTEGER PRIMARY KEY,
                group_notice_sent INTEGER NOT NULL DEFAULT 0,
                group_notice_sent_at TEXT NOT NULL DEFAULT '',
                group_notice_last_error TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE activation_card_jobs (
                group_id INTEGER PRIMARY KEY,
                owner_id INTEGER NOT NULL,
                owner_access_hash INTEGER NOT NULL DEFAULT 0,
                native_owner_id INTEGER NOT NULL DEFAULT 0,
                native_owner_available INTEGER NOT NULL DEFAULT 0,
                owner_mode TEXT NOT NULL DEFAULT 'native',
                probe_sent INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL,
                last_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE group_lifecycle (
                group_id INTEGER PRIMARY KEY,
                group_title TEXT NOT NULL DEFAULT '',
                peer_kind TEXT NOT NULL DEFAULT 'channel',
                group_access_hash INTEGER NOT NULL DEFAULT 0,
                activated_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        con.commit()


def pending_row(db_path: Path, group_id: int) -> None:
    with closing(sqlite3.connect(db_path)) as con:
        con.execute(
            "INSERT INTO pending_group_activations(group_id, updated_at) VALUES (?, '')",
            (group_id,),
        )
        con.commit()


def scalar(db_path: Path, sql: str, args: tuple[Any, ...] = ()) -> Any:
    with closing(sqlite3.connect(db_path)) as con:
        row = con.execute(sql, args).fetchone()
    return None if row is None else row[0]


def test_atomic_register_and_repair(namespace: Dict[str, Any], db_path: Path) -> None:
    register = namespace["register_installation"]
    pending_row(db_path, 7001)
    card = {
        "owner_id": 41,
        "owner_access_hash": 51,
        "native_owner_id": 61,
        "native_owner_available": True,
        "owner_mode": "native",
        "probe_already_sent": True,
        "group_title": "g",
        "peer_kind": "channel",
        "group_access_hash": 7001001,
    }
    row = register(7001, "g", 41, owner_access_hash=51, activation_card=card)
    assert int(row["group_id"]) == 7001
    assert scalar(db_path, "SELECT activation_card_state FROM installations WHERE group_id=7001") == "queued"
    assert scalar(db_path, "SELECT COUNT(*) FROM activation_card_jobs WHERE group_id=7001") == 1
    assert scalar(db_path, "SELECT group_notice_sent FROM pending_group_activations WHERE group_id=7001") == 1
    assert scalar(db_path, "SELECT peer_kind FROM group_lifecycle WHERE group_id=7001") == "channel"
    assert scalar(db_path, "SELECT group_access_hash FROM group_lifecycle WHERE group_id=7001") == 7001001

    original = namespace["_activation_card_job_upsert_in_connection"]

    def fail_upsert(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("INJECTED_QUEUE_FAILURE")

    namespace["_activation_card_job_upsert_in_connection"] = fail_upsert
    pending_row(db_path, 7002)
    try:
        register(7002, "g2", 42, activation_card=card)
    except RuntimeError as exc:
        assert "INJECTED_QUEUE_FAILURE" in str(exc)
    else:
        raise AssertionError("queue failure must abort registration")
    finally:
        namespace["_activation_card_job_upsert_in_connection"] = original
    assert scalar(db_path, "SELECT COUNT(*) FROM installations WHERE group_id=7002") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM activation_card_jobs WHERE group_id=7002") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM group_lifecycle WHERE group_id=7002") == 0
    assert scalar(db_path, "SELECT group_notice_sent FROM pending_group_activations WHERE group_id=7002") == 0

    original_lifecycle = namespace["_group_lifecycle_upsert_in_connection"]

    def fail_lifecycle(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("INJECTED_LIFECYCLE_FAILURE")

    namespace["_group_lifecycle_upsert_in_connection"] = fail_lifecycle
    pending_row(db_path, 7003)
    try:
        register(7003, "g3", 43, activation_card=card)
    except RuntimeError as exc:
        assert "INJECTED_LIFECYCLE_FAILURE" in str(exc)
    else:
        raise AssertionError("lifecycle failure must abort installation and card job")
    finally:
        namespace["_group_lifecycle_upsert_in_connection"] = original_lifecycle
    assert scalar(db_path, "SELECT COUNT(*) FROM installations WHERE group_id=7003") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM activation_card_jobs WHERE group_id=7003") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM group_lifecycle WHERE group_id=7003") == 0
    assert scalar(db_path, "SELECT group_notice_sent FROM pending_group_activations WHERE group_id=7003") == 0

    with closing(sqlite3.connect(db_path)) as con:
        con.execute("DELETE FROM activation_card_jobs WHERE group_id=7001")
        con.commit()
    state = namespace["_activation_card_ensure_job_from_installation"](7001)
    assert state == "queued"
    assert scalar(db_path, "SELECT COUNT(*) FROM activation_card_jobs WHERE group_id=7001") == 1

    namespace["_activation_card_complete"](7001)
    assert scalar(db_path, "SELECT activation_card_state FROM installations WHERE group_id=7001") == "delivered"
    assert scalar(db_path, "SELECT activation_card_delivered_at FROM installations WHERE group_id=7001")
    assert scalar(db_path, "SELECT COUNT(*) FROM activation_card_jobs WHERE group_id=7001") == 0
    assert namespace["_activation_card_repair_missing_jobs"]() == 0


def test_crash_after_register_before_mark(db_path: Path) -> None:
    """A fresh process must resolve the queued card without pending state."""
    create_schema(db_path)
    assert scalar(db_path, "SELECT COUNT(*) FROM pending_group_activations") == 0
    assert scalar(db_path, "SELECT COUNT(*) FROM group_lifecycle") == 0

    before_crash = extracted_namespace(db_path)
    card = {
        "owner_id": 91,
        "owner_access_hash": 92,
        "native_owner_id": 93,
        "native_owner_available": True,
        "owner_mode": "native",
        "probe_already_sent": True,
        "group_title": "crash-safe-group",
        "peer_kind": "channel",
        "group_access_hash": 940001,
    }
    before_crash["register_installation"](
        9001, "crash-safe-group", 91,
        owner_access_hash=92,
        native_owner_user_id=93,
        activation_card=card,
    )

    # Simulate a hard crash here: mark_group_activated was never called and
    # there is no pending row or in-memory entity cache to rescue the job.
    assert scalar(db_path, "SELECT COUNT(*) FROM pending_group_activations") == 0
    assert scalar(db_path, "SELECT activation_card_state FROM installations WHERE group_id=9001") == "queued"
    assert scalar(db_path, "SELECT COUNT(*) FROM activation_card_jobs WHERE group_id=9001") == 1
    assert scalar(db_path, "SELECT group_title FROM group_lifecycle WHERE group_id=9001") == "crash-safe-group"
    assert scalar(db_path, "SELECT peer_kind FROM group_lifecycle WHERE group_id=9001") == "channel"
    assert scalar(db_path, "SELECT group_access_hash FROM group_lifecycle WHERE group_id=9001") == 940001

    after_restart = extracted_namespace(db_path)

    class InputPeerChannel:
        def __init__(self, channel_id: int, access_hash: int) -> None:
            self.channel_id = int(channel_id)
            self.access_hash = int(access_hash)

    class InputPeerChat:
        def __init__(self, chat_id: int) -> None:
            self.chat_id = int(chat_id)

    class RestartClient:
        async def get_entity(self, target: Any) -> Dict[str, Any]:
            assert isinstance(target, InputPeerChannel)
            assert target.channel_id == 9001
            assert target.access_hash == 940001
            return {
                "runtime_group": True,
                "id": target.channel_id,
                "peer_kind": "channel",
                "access_hash": target.access_hash,
            }

    after_restart["types"] = SimpleNamespace(
        InputPeerChannel=InputPeerChannel,
        InputPeerChat=InputPeerChat,
    )
    after_restart["client"] = RestartClient()
    after_restart["is_group_entity"] = (
        lambda value: isinstance(value, dict) and bool(value.get("runtime_group"))
    )
    due = after_restart["_activation_card_jobs_due"]()
    assert [int(job["group_id"]) for job in due] == [9001]
    resolved = asyncio.run(after_restart["_activation_card_resolve_group"](9001))
    assert resolved is not None
    assert resolved["id"] == 9001
    assert resolved["peer_kind"] == "channel"
    assert resolved["access_hash"] == 940001


def test_queue_or_delivery_result(namespace: Dict[str, Any]) -> None:
    async def total_failure() -> None:
        namespace["_activation_card_job_upsert"] = lambda *args: (_ for _ in ()).throw(RuntimeError("db down"))

        async def send_failure(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("send down")

        namespace["send_default_join_message"] = send_failure
        namespace["probe_group_send_access"] = send_failure
        result = await namespace["_post_activation_card_task"](
            object(), 8001, 1, 0, 0, False, "native", probe_already_sent=True
        )
        assert result is False

    async def durable_queue() -> None:
        calls: List[int] = []
        namespace["_activation_card_job_upsert"] = lambda group_id, *args: calls.append(int(group_id))
        namespace["_activation_card_job_row"] = lambda group_id: {"group_id": int(group_id)}

        async def keep_queued(job: Dict[str, Any]) -> None:
            return None

        namespace["_process_activation_card_job"] = keep_queued
        result = await namespace["_post_activation_card_task"](
            object(), 8002, 1, 0, 0, False, "native", deliver_inline=True
        )
        assert result is True
        assert calls == [8002]

    asyncio.run(total_failure())
    asyncio.run(durable_queue())


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="zivo-card-recovery-") as temp_dir:
        db_path = Path(temp_dir) / "runtime.db"
        create_schema(db_path)
        namespace = extracted_namespace(db_path)
        test_atomic_register_and_repair(namespace, db_path)
        test_queue_or_delivery_result(namespace)
        test_crash_after_register_before_mark(Path(temp_dir) / "crash.db")

    register_src = ast.get_source_segment(SOURCE, next(node for node in TREE.body if isinstance(node, ast.FunctionDef) and node.name == "register_installation")) or ""
    assert register_src.index("_activation_card_job_upsert_in_connection") < register_src.index("_group_lifecycle_upsert_in_connection") < register_src.index("con.commit()")
    for required in ('"group_title"', '"peer_kind"', '"group_access_hash"'):
        assert required in register_src

    auto_src = ast.get_source_segment(SOURCE, next(node for node in TREE.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "try_auto_activate_pending_group")) or ""
    for required in ('"group_title"', '"peer_kind"', '"group_access_hash"'):
        assert required in auto_src
    manual_src = ast.get_source_segment(SOURCE, next(node for node in TREE.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_group_install_command")) or ""
    assert 'install_source="manual_owner_command"' in manual_src
    assert "activation_card={" in manual_src
    assert "already_persisted=True" in manual_src
    manual_new_install = manual_src[manual_src.index('install_source="manual_owner_command"'):]
    assert manual_new_install.index("activation_card={") < manual_new_install.index("clear_pending_group_activation")
    for required in ('"group_title"', '"peer_kind"', '"group_access_hash"'):
        assert required in manual_new_install

    emergency_src = ast.get_source_segment(SOURCE, next(node for node in TREE.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "handle_emergency_install_command")) or ""
    assert "activation_card=emergency_card" in emergency_src
    assert "_activation_card_job_upsert_in_connection" in emergency_src
    assert "_group_lifecycle_upsert_in_connection" in emergency_src
    for required in ('"group_title"', '"peer_kind"', '"group_access_hash"'):
        assert required in emergency_src
    assert "already_persisted=True" in emergency_src
    assert "send_activation_message" not in emergency_src
    print("CHECK ZIVO60.96.11 ACTIVATION CARD CRASH RECOVERY: PASS")


if __name__ == "__main__":
    main()
