#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared control plane for ZIVO multi-account runtime.

Each Soroush account owns its own session and local ZIVO database. A small
shared SQLite database is used only for account state/heartbeats and queued
cross-account advertising jobs. This prevents two processes from opening the
same SPlusthon session while still letting one Telegram panel control all
accounts.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()


@contextmanager
def connect(path: Path):
    """Open one short-lived shared-control connection and always close it.

    sqlite3.Connection's own context manager commits/rolls back but does NOT
    close the connection.  The multi-account control plane is polled often, so
    leaving those handles open eventually exhausts RLIMIT_NOFILE and breaks
    SQLite plus Telegram DNS/socket creation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=2.0, isolation_level=None)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA busy_timeout=2000")
        yield con
    finally:
        con.close()


def init_control_db(path: Path) -> None:
    """Initialize the shared schema once per process, not on every read.

    The control plane is queried from all three bot processes. Re-running the
    DDL/PRAGMA schema script on every account-state lookup creates avoidable
    cross-process SQLite lock pressure on the realtime private/join path.
    """
    path = Path(path)
    key = str(path.resolve())
    if key in _INITIALIZED_PATHS and path.exists():
        return
    with _INIT_LOCK:
        if key in _INITIALIZED_PATHS and path.exists():
            return
        with connect(path) as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_key TEXT PRIMARY KEY,
                    label TEXT NOT NULL DEFAULT '',
                    phone TEXT NOT NULL DEFAULT '',
                    self_id INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    is_controller INTEGER NOT NULL DEFAULT 0,
                    session_path TEXT NOT NULL DEFAULT '',
                    db_path TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'configured',
                    last_error TEXT NOT NULL DEFAULT '',
                    last_heartbeat_at TEXT NOT NULL DEFAULT '',
                    groups_count INTEGER NOT NULL DEFAULT 0,
                    private_count INTEGER NOT NULL DEFAULT 0,
                    join_capacity_until TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS campaign_jobs (
                    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    batch_id TEXT NOT NULL DEFAULT '',
                    account_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    target_scope TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_text TEXT NOT NULL DEFAULT '',
                    media_path TEXT NOT NULL DEFAULT '',
                    repeat_count INTEGER NOT NULL DEFAULT 1,
                    interval_seconds INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    total_targets INTEGER NOT NULL DEFAULT 0,
                    group_targets INTEGER NOT NULL DEFAULT 0,
                    private_targets INTEGER NOT NULL DEFAULT 0,
                    total_planned INTEGER NOT NULL DEFAULT 0,
                    attempted INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failure_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    current_round INTEGER NOT NULL DEFAULT 0,
                    stop_requested INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    telegram_chat_id INTEGER NOT NULL DEFAULT 0,
                    telegram_message_id INTEGER NOT NULL DEFAULT 0,
                    campaign_mode TEXT NOT NULL DEFAULT 'standard',
                    target_group_link TEXT NOT NULL DEFAULT '',
                    target_group_id INTEGER NOT NULL DEFAULT 0,
                    target_member_count INTEGER NOT NULL DEFAULT 0,
                    baseline_member_count INTEGER NOT NULL DEFAULT -1,
                    current_member_count INTEGER NOT NULL DEFAULT -1,
                    current_batch_size INTEGER NOT NULL DEFAULT 0,
                    sent_banner_count INTEGER NOT NULL DEFAULT 0,
                    deleted_banner_count INTEGER NOT NULL DEFAULT 0,
                    cleanup_failure_count INTEGER NOT NULL DEFAULT 0,
                    measurement_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_multi_job_account_status
                ON campaign_jobs(account_key, status, job_id);
                CREATE INDEX IF NOT EXISTS idx_multi_job_batch
                ON campaign_jobs(batch_id, job_id);

                CREATE TABLE IF NOT EXISTS campaign_deliveries (
                    delivery_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    account_key TEXT NOT NULL DEFAULT '',
                    target_group_id INTEGER NOT NULL DEFAULT 0,
                    sent_message_id INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'sent',
                    created_at TEXT NOT NULL DEFAULT '',
                    deleted_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_campaign_deliveries_job
                ON campaign_deliveries(job_id, status, delivery_id);

                CREATE TABLE IF NOT EXISTS campaign_target_claims (
                    batch_id TEXT NOT NULL,
                    target_kind TEXT NOT NULL,
                    target_id INTEGER NOT NULL,
                    account_key TEXT NOT NULL DEFAULT '',
                    job_id INTEGER NOT NULL DEFAULT 0,
                    claimed_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY(batch_id, target_kind, target_id)
                );
                CREATE INDEX IF NOT EXISTS idx_campaign_target_claims_job
                ON campaign_target_claims(job_id, target_kind, target_id);

                CREATE TABLE IF NOT EXISTS join_jobs (
                    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_account TEXT NOT NULL,
                    target_account TEXT NOT NULL,
                    requester_user_id INTEGER NOT NULL DEFAULT 0,
                    source_message_id INTEGER NOT NULL DEFAULT 0,
                    link_kind TEXT NOT NULL,
                    link_value TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    result_code TEXT NOT NULL DEFAULT '',
                    result_group_id INTEGER NOT NULL DEFAULT 0,
                    result_title TEXT NOT NULL DEFAULT '',
                    result_member_count INTEGER NOT NULL DEFAULT -1,
                    joined_now INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_join_job_target_status
                ON join_jobs(target_account, status, job_id);
                CREATE INDEX IF NOT EXISTS idx_join_job_source
                ON join_jobs(source_account, source_message_id, job_id);

                CREATE TABLE IF NOT EXISTS remote_control_jobs (
                    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_account TEXT NOT NULL,
                    requester_user_id INTEGER NOT NULL DEFAULT 0,
                    group_id INTEGER NOT NULL DEFAULT 0,
                    command_text TEXT NOT NULL DEFAULT '',
                    target_user_id INTEGER NOT NULL DEFAULT 0,
                    target_message_id INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'queued',
                    result_code TEXT NOT NULL DEFAULT '',
                    result_text TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL DEFAULT '',
                    finished_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_remote_control_target_status
                ON remote_control_jobs(target_account, status, job_id);
                CREATE INDEX IF NOT EXISTS idx_remote_control_requester
                ON remote_control_jobs(requester_user_id, job_id);
                CREATE INDEX IF NOT EXISTS idx_remote_control_group
                ON remote_control_jobs(group_id, job_id);

                CREATE TABLE IF NOT EXISTS group_claims (
                    group_id INTEGER PRIMARY KEY,
                    account_key TEXT NOT NULL,
                    self_id INTEGER NOT NULL DEFAULT 0,
                    group_title TEXT NOT NULL DEFAULT '',
                    public_username TEXT NOT NULL DEFAULT '',
                    invite_fingerprint TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    claimed_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_group_claim_public_username
                ON group_claims(public_username) WHERE public_username != '';
                CREATE UNIQUE INDEX IF NOT EXISTS idx_group_claim_invite_fingerprint
                ON group_claims(invite_fingerprint) WHERE invite_fingerprint != '';
                CREATE INDEX IF NOT EXISTS idx_group_claim_account
                ON group_claims(account_key, status, group_id);

                CREATE TABLE IF NOT EXISTS group_event_leases (
                    group_id INTEGER PRIMARY KEY,
                    account_key TEXT NOT NULL,
                    lease_until REAL NOT NULL DEFAULT 0,
                    last_message_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_group_event_leases_owner
                ON group_event_leases(account_key, lease_until, group_id);

                CREATE TABLE IF NOT EXISTS settings_snapshots (
                    token TEXT PRIMARY KEY,
                    source_account TEXT NOT NULL DEFAULT '',
                    source_group_id INTEGER NOT NULL DEFAULT 0,
                    section_key TEXT NOT NULL DEFAULT 'all',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    summary_json TEXT NOT NULL DEFAULT '{}',
                    created_by INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_settings_snapshots_expiry
                ON settings_snapshots(expires_at);
                """
            )
            # Schema migration for databases created by 60.61-60.66.
            columns = {str(row[1]) for row in con.execute("PRAGMA table_info(accounts)").fetchall()}
            if "join_capacity_until" not in columns:
                con.execute("ALTER TABLE accounts ADD COLUMN join_capacity_until TEXT NOT NULL DEFAULT ''")
            join_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(join_jobs)").fetchall()}
            if "result_member_count" not in join_columns:
                con.execute("ALTER TABLE join_jobs ADD COLUMN result_member_count INTEGER NOT NULL DEFAULT -1")
            campaign_columns = {str(row[1]) for row in con.execute("PRAGMA table_info(campaign_jobs)").fetchall()}
            if "campaign_mode" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN campaign_mode TEXT NOT NULL DEFAULT 'standard'")
            if "target_group_link" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN target_group_link TEXT NOT NULL DEFAULT ''")
            if "target_group_id" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN target_group_id INTEGER NOT NULL DEFAULT 0")
            if "target_member_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN target_member_count INTEGER NOT NULL DEFAULT 0")
            if "baseline_member_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN baseline_member_count INTEGER NOT NULL DEFAULT -1")
            if "current_member_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN current_member_count INTEGER NOT NULL DEFAULT -1")
            if "current_batch_size" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN current_batch_size INTEGER NOT NULL DEFAULT 0")
            if "sent_banner_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN sent_banner_count INTEGER NOT NULL DEFAULT 0")
            if "deleted_banner_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN deleted_banner_count INTEGER NOT NULL DEFAULT 0")
            if "cleanup_failure_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN cleanup_failure_count INTEGER NOT NULL DEFAULT 0")
            if "measurement_error" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN measurement_error TEXT NOT NULL DEFAULT ''")
            if "group_targets" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN group_targets INTEGER NOT NULL DEFAULT 0")
            if "private_targets" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN private_targets INTEGER NOT NULL DEFAULT 0")
            if "skipped_count" not in campaign_columns:
                con.execute("ALTER TABLE campaign_jobs ADD COLUMN skipped_count INTEGER NOT NULL DEFAULT 0")
        _INITIALIZED_PATHS.add(key)


def register_account(
    path: Path,
    *,
    account_key: str,
    label: str,
    phone: str,
    self_id: int,
    enabled: bool,
    is_controller: bool,
    session_path: str,
    db_path: str,
    status: str = "configured",
) -> None:
    init_control_db(path)
    now = utcnow()
    with connect(path) as con:
        con.execute(
            """
            INSERT INTO accounts (
                account_key, label, phone, self_id, enabled, is_controller,
                session_path, db_path, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_key) DO UPDATE SET
                label = excluded.label,
                phone = CASE WHEN excluded.phone != '' THEN excluded.phone ELSE accounts.phone END,
                self_id = CASE WHEN excluded.self_id != 0 THEN excluded.self_id ELSE accounts.self_id END,
                is_controller = excluded.is_controller,
                session_path = excluded.session_path,
                db_path = excluded.db_path,
                status = CASE WHEN accounts.status = 'disabled' AND excluded.status = 'configured'
                              THEN accounts.status ELSE excluded.status END,
                updated_at = excluded.updated_at
            """,
            (
                account_key, label, phone, int(self_id or 0), 1 if enabled else 0,
                1 if is_controller else 0, session_path, db_path, status, now,
            ),
        )


def ensure_default_accounts(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    init_control_db(path)
    for item in rows:
        register_account(path, **item)


def _read_env_file(path: Path) -> Dict[str, str]:
    result: Dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            result[key] = value
    except FileNotFoundError:
        pass
    return result


def reconcile_accounts_from_env(path: Path, env_dir: Path) -> int:
    """Self-heal shared account metadata from durable systemd env files.

    Authentication writes a non-zero ZIVO_SELF_ID into each account env.  The
    env files are therefore the durable source of account identity, while the
    shared database remains the source of operator enabled/disabled state.
    Existing enabled flags are deliberately preserved.
    """
    init_control_db(path)
    count = 0
    for env_path in sorted(Path(env_dir).glob("*.env")):
        env = _read_env_file(env_path)
        account_key = str(env.get("ZIVO_ACCOUNT_KEY") or env_path.stem).strip().lower()
        if not account_key:
            continue
        try:
            self_id = int(str(env.get("ZIVO_SELF_ID") or "0").strip() or 0)
        except Exception:
            self_id = 0
        is_controller = str(env.get("ZIVO_ACCOUNT_CONTROLLER") or "0").strip().lower() in {"1", "true", "yes", "on"}
        current = get_account(path, account_key)
        enabled = bool(int(current["enabled"] or 0)) if current is not None else bool(is_controller or self_id > 0)
        status = str(current["status"] or "configured") if current is not None else ("configured" if self_id > 0 or is_controller else "auth-needed")
        register_account(
            path,
            account_key=account_key,
            label=str(env.get("ZIVO_ACCOUNT_LABEL") or account_key),
            phone=str(env.get("ZIVO_PHONE") or ""),
            self_id=self_id,
            enabled=enabled,
            is_controller=is_controller,
            session_path=str(env.get("ZIVO_SESSION") or ""),
            db_path=str(env.get("ZIVO_DB") or ""),
            status=status,
        )
        count += 1
    return count


def list_accounts(path: Path) -> List[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            "SELECT * FROM accounts ORDER BY is_controller DESC, account_key ASC"
        ).fetchall()


def get_account(path: Path, account_key: str) -> Optional[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            "SELECT * FROM accounts WHERE account_key = ?", (str(account_key),)
        ).fetchone()


def set_account_enabled(path: Path, account_key: str, enabled: bool) -> None:
    init_control_db(path)
    now = utcnow()
    with connect(path) as con:
        con.execute(
            """
            UPDATE accounts
            SET enabled = ?, status = ?, updated_at = ?
            WHERE account_key = ?
            """,
            (1 if enabled else 0, "configured" if enabled else "disabled", now, str(account_key)),
        )


def account_enabled(path: Path, account_key: str, default: bool = True) -> bool:
    row = get_account(path, account_key)
    if row is None:
        return bool(default)
    return bool(int(row["enabled"] or 0))


def update_heartbeat(
    path: Path,
    *,
    account_key: str,
    status: str,
    self_id: int,
    groups_count: int,
    private_count: int,
    last_error: str = "",
) -> None:
    init_control_db(path)
    now = utcnow()
    with connect(path) as con:
        con.execute(
            """
            UPDATE accounts
            SET status = ?, self_id = CASE WHEN ? != 0 THEN ? ELSE self_id END,
                groups_count = ?, private_count = ?, last_error = ?,
                last_heartbeat_at = ?, updated_at = ?
            WHERE account_key = ?
            """,
            (
                status, int(self_id or 0), int(self_id or 0), int(groups_count), int(private_count),
                str(last_error or "")[:500], now, now, str(account_key),
            ),
        )


def create_campaign_jobs(
    path: Path,
    *,
    batch_id: str,
    account_keys: Iterable[str],
    scope: str,
    content: Dict[str, Any],
    repeat_count: int,
    interval_seconds: int,
    telegram_chat_id: int = 0,
    telegram_message_id: int = 0,
    campaign_mode: str = "standard",
    target_group_link: str = "",
    target_group_id: int = 0,
    target_member_count: int = 0,
    baseline_member_count: int = -1,
) -> List[int]:
    init_control_db(path)
    now = utcnow()
    ids: List[int] = []
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            for key in account_keys:
                cur = con.execute(
                    """
                    INSERT INTO campaign_jobs (
                        batch_id, account_key, created_at, target_scope, content_type,
                        content_text, media_path, repeat_count, interval_seconds,
                        status, telegram_chat_id, telegram_message_id, campaign_mode,
                        target_group_link, target_group_id, target_member_count,
                        baseline_member_count, current_member_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(batch_id), str(key), now, str(scope), str(content.get("type") or "text"),
                        str(content.get("text") or ""), str(content.get("path") or ""),
                        max(1, int(repeat_count)), max(0, int(interval_seconds)),
                        int(telegram_chat_id), int(telegram_message_id), str(campaign_mode or "standard"),
                        str(target_group_link or ""), int(target_group_id or 0), int(target_member_count or 0),
                        int(baseline_member_count), int(baseline_member_count),
                    ),
                )
                ids.append(int(cur.lastrowid))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return ids


def supersede_standard_jobs(path: Path, account_keys: Iterable[str], *, reason: str = "SUPERSEDED_BY_NEW_ADMIN_BATCH") -> int:
    """Stop older standard broadcast jobs so a fresh explicit admin send is never stuck behind stale queue rows.

    Running/scanning jobs are asked to stop at their next cooperative checkpoint;
    queued jobs are finalized immediately. Target-growth jobs are intentionally
    left untouched because they have their own lifecycle/cleanup contract.
    """
    init_control_db(path)
    keys = sorted({str(k).strip() for k in account_keys if str(k).strip()})
    if not keys:
        return 0
    placeholders = ",".join("?" for _ in keys)
    now = utcnow()
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            rows = con.execute(
                f"""
                SELECT job_id, status FROM campaign_jobs
                WHERE account_key IN ({placeholders})
                  AND campaign_mode = 'standard'
                  AND status IN ('queued','scanning','running')
                """,
                keys,
            ).fetchall()
            for row in rows:
                status = str(row["status"] or "")
                con.execute(
                    """
                    UPDATE campaign_jobs
                    SET stop_requested = 1,
                        status = CASE WHEN status='queued' THEN 'stopped' ELSE status END,
                        finished_at = CASE WHEN status='queued' THEN ? ELSE finished_at END,
                        last_error = ?
                    WHERE job_id = ?
                    """,
                    (now, str(reason)[:500], int(row["job_id"])),
                )
            con.execute("COMMIT")
            return len(rows)
        except Exception:
            con.execute("ROLLBACK")
            raise


def claim_next_job(path: Path, account_key: str) -> Optional[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute(
                """
                SELECT * FROM campaign_jobs
                WHERE account_key = ? AND status = 'queued' AND stop_requested = 0
                ORDER BY job_id DESC LIMIT 1
                """,
                (str(account_key),),
            ).fetchone()
            if row is None:
                con.execute("COMMIT")
                return None
            now = utcnow()
            changed = con.execute(
                """
                UPDATE campaign_jobs
                SET status = 'running', started_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, int(row["job_id"])),
            ).rowcount
            if not changed:
                con.execute("ROLLBACK")
                return None
            result = con.execute(
                "SELECT * FROM campaign_jobs WHERE job_id = ?", (int(row["job_id"]),)
            ).fetchone()
            con.execute("COMMIT")
            return result
        except Exception:
            con.execute("ROLLBACK")
            raise


def get_job(path: Path, job_id: int) -> Optional[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute("SELECT * FROM campaign_jobs WHERE job_id = ?", (int(job_id),)).fetchone()


def update_job(path: Path, job_id: int, **fields: Any) -> None:
    allowed = {
        "status", "started_at", "finished_at", "total_targets", "group_targets", "private_targets", "total_planned",
        "attempted", "success_count", "failure_count", "skipped_count", "current_round",
        "stop_requested", "last_error", "current_member_count", "current_batch_size",
        "sent_banner_count", "deleted_banner_count", "cleanup_failure_count",
        "measurement_error", "target_group_id", "baseline_member_count",
    }
    pairs = [(k, v) for k, v in fields.items() if k in allowed]
    if not pairs:
        return
    sql = "UPDATE campaign_jobs SET " + ", ".join(f"{k} = ?" for k, _ in pairs) + " WHERE job_id = ?"
    with connect(path) as con:
        con.execute(sql, [v for _, v in pairs] + [int(job_id)])


def request_job_stop(path: Path, job_id: int) -> None:
    with connect(path) as con:
        con.execute(
            "UPDATE campaign_jobs SET stop_requested = 1, status = CASE WHEN status='queued' THEN 'stopped' ELSE status END WHERE job_id = ?",
            (int(job_id),),
        )


def active_job_count(path: Path) -> int:
    init_control_db(path)
    with connect(path) as con:
        return int(con.execute(
            "SELECT COUNT(*) FROM campaign_jobs WHERE status IN ('queued','scanning','running')"
        ).fetchone()[0] or 0)


def recover_running_jobs(path: Path, account_key: str) -> int:
    init_control_db(path)
    with connect(path) as con:
        changed = con.execute(
            """
            UPDATE campaign_jobs
            SET status = CASE
                    WHEN stop_requested = 1 AND last_error = 'TARGET_REACHED_BY_BATCH'
                        THEN 'target_reached_cleanup_partial'
                    WHEN stop_requested = 1 THEN 'stopped'
                    ELSE 'queued'
                END,
                started_at = CASE WHEN stop_requested = 1 THEN started_at ELSE '' END,
                last_error = CASE WHEN stop_requested = 1 THEN last_error ELSE 'PROCESS_RECOVERY_REQUEUE' END
            WHERE account_key = ? AND status IN ('scanning','running','cleanup')
            """,
            (str(account_key),),
        ).rowcount
        return int(changed or 0)


def recent_jobs(path: Path, limit: int = 12) -> List[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            "SELECT * FROM campaign_jobs ORDER BY job_id DESC LIMIT ?", (max(1, int(limit)),)
        ).fetchall()


def batch_jobs(path: Path, batch_id: str) -> List[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            "SELECT * FROM campaign_jobs WHERE batch_id = ? ORDER BY job_id", (str(batch_id),)
        ).fetchall()


def signal_target_batch_reached(
    path: Path, *, batch_id: str, source_job_id: int, current_member_count: int
) -> int:
    """Stop sibling target jobs and route every sent banner to cleanup."""
    init_control_db(path)
    changed = 0
    now = utcnow()
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            rows = con.execute(
                "SELECT * FROM campaign_jobs WHERE batch_id = ? AND campaign_mode = 'target_growth'",
                (str(batch_id),),
            ).fetchall()
            for row in rows:
                job_id = int(row["job_id"])
                if job_id == int(source_job_id):
                    continue
                status = str(row["status"] or "")
                sent = int(row["sent_banner_count"] or 0)
                deleted = int(row["deleted_banner_count"] or 0)
                if status in {"cleanup", "target_reached", "target_reached_cleanup_partial"}:
                    continue
                if status == "running":
                    next_status = "running"
                    finished_at = str(row["finished_at"] or "")
                elif sent > deleted:
                    next_status = "target_reached_cleanup_partial"
                    finished_at = now
                else:
                    next_status = "target_reached"
                    finished_at = now
                con.execute(
                    """
                    UPDATE campaign_jobs
                    SET status = ?, stop_requested = 1,
                        last_error = 'TARGET_REACHED_BY_BATCH',
                        current_member_count = ?, current_batch_size = 0,
                        finished_at = ?
                    WHERE job_id = ?
                    """,
                    (next_status, int(current_member_count), finished_at, job_id),
                )
                changed += 1
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return changed


def claim_campaign_target(
    path: Path, *, batch_id: str, target_kind: str, target_id: int,
    account_key: str, job_id: int
) -> bool:
    """Claim one logical campaign recipient across all account processes.

    A group/user visible in more than one ZIVO session should receive one copy
    per campaign batch. Repeats inside the same job keep ownership.
    """
    init_control_db(path)
    batch = str(batch_id or '').strip()
    kind = str(target_kind or '').strip().lower()
    tid = int(target_id or 0)
    if not batch or kind not in {'group', 'private'} or tid <= 0:
        return False
    with connect(path) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            row = con.execute(
                'SELECT account_key, job_id FROM campaign_target_claims WHERE batch_id=? AND target_kind=? AND target_id=?',
                (batch, kind, tid),
            ).fetchone()
            if row is not None:
                owned = int(row['job_id'] or 0) == int(job_id)
                con.execute('COMMIT')
                return bool(owned)
            con.execute(
                """
                INSERT INTO campaign_target_claims(
                    batch_id, target_kind, target_id, account_key, job_id, claimed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (batch, kind, tid, str(account_key or ''), int(job_id), utcnow()),
            )
            con.execute('COMMIT')
            return True
        except Exception:
            con.execute('ROLLBACK')
            raise


def release_campaign_target_claim(
    path: Path, *, batch_id: str, target_kind: str, target_id: int, job_id: int
) -> bool:
    init_control_db(path)
    with connect(path) as con:
        changed = con.execute(
            """
            DELETE FROM campaign_target_claims
            WHERE batch_id=? AND target_kind=? AND target_id=? AND job_id=?
            """,
            (str(batch_id or ''), str(target_kind or '').strip().lower(), int(target_id or 0), int(job_id)),
        ).rowcount
        return bool(changed)


def record_campaign_delivery(
    path: Path, *, job_id: int, account_key: str, target_group_id: int, sent_message_id: int
) -> int:
    init_control_db(path)
    with connect(path) as con:
        cur = con.execute(
            """
            INSERT INTO campaign_deliveries(
                job_id, account_key, target_group_id, sent_message_id, status, created_at
            ) VALUES (?, ?, ?, ?, 'sent', ?)
            """,
            (int(job_id), str(account_key), int(target_group_id), int(sent_message_id), utcnow()),
        )
        return int(cur.lastrowid)


def campaign_deliveries(path: Path, job_id: int, status: str = "") -> List[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        if status:
            return con.execute(
                "SELECT * FROM campaign_deliveries WHERE job_id=? AND status=? ORDER BY delivery_id",
                (int(job_id), str(status)),
            ).fetchall()
        return con.execute(
            "SELECT * FROM campaign_deliveries WHERE job_id=? ORDER BY delivery_id",
            (int(job_id),),
        ).fetchall()


def update_campaign_delivery(path: Path, delivery_id: int, *, status: str, last_error: str = "") -> None:
    init_control_db(path)
    with connect(path) as con:
        con.execute(
            """
            UPDATE campaign_deliveries
            SET status=?, deleted_at=CASE WHEN ?='deleted' THEN ? ELSE deleted_at END, last_error=?
            WHERE delivery_id=?
            """,
            (str(status), str(status), utcnow(), str(last_error or '')[:500], int(delivery_id)),
        )


def mark_account_join_capacity(path: Path, account_key: str, seconds: int = 1200) -> str:
    """Temporarily remove an account from new-group routing after ChannelsTooMuch."""
    init_control_db(path)
    now = datetime.now(timezone.utc)
    until = (now + timedelta(seconds=max(60, int(seconds)))).isoformat()
    with connect(path) as con:
        con.execute(
            """
            UPDATE accounts
            SET join_capacity_until = ?, last_error = 'JOIN_CAPACITY', updated_at = ?
            WHERE account_key = ?
            """,
            (until, now.isoformat(), str(account_key or '').strip().lower()),
        )
    return until


def clear_account_join_capacity(path: Path, account_key: str) -> None:
    init_control_db(path)
    with connect(path) as con:
        con.execute(
            "UPDATE accounts SET join_capacity_until = '', last_error = CASE WHEN last_error='JOIN_CAPACITY' THEN '' ELSE last_error END, updated_at = ? WHERE account_key = ?",
            (utcnow(), str(account_key or '').strip().lower()),
        )


def account_join_capacity_blocked(path: Path, account_key: str) -> bool:
    row = get_account(path, account_key)
    if row is None or 'join_capacity_until' not in row.keys():
        return False
    value = str(row['join_capacity_until'] or '').strip()
    if not value:
        return False
    try:
        until = datetime.fromisoformat(value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > datetime.now(timezone.utc)
    except Exception:
        return False


def eligible_join_accounts(path: Path, exclude_account_key: str = '') -> List[sqlite3.Row]:
    """Return authorized enabled accounts that can accept a routed group join."""
    init_control_db(path)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    heartbeat_cutoff = (now_dt - timedelta(seconds=45)).isoformat()
    exclude = str(exclude_account_key or '').strip().lower()
    with connect(path) as con:
        return con.execute(
            """
            SELECT * FROM accounts
            WHERE account_key != ?
              AND enabled = 1
              AND self_id != 0
              AND status = 'online'
              AND last_heartbeat_at != ''
              AND last_heartbeat_at >= ?
              AND (join_capacity_until = '' OR join_capacity_until <= ?)
            ORDER BY groups_count ASC, account_key ASC
            """,
            (exclude, heartbeat_cutoff, now),
        ).fetchall()


def create_join_job(
    path: Path,
    *,
    source_account: str,
    target_account: str,
    requester_user_id: int,
    source_message_id: int,
    link_kind: str,
    link_value: str,
) -> int:
    init_control_db(path)
    with connect(path) as con:
        cur = con.execute(
            """
            INSERT INTO join_jobs (
                source_account, target_account, requester_user_id, source_message_id,
                link_kind, link_value, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (
                str(source_account), str(target_account), int(requester_user_id or 0),
                int(source_message_id or 0), str(link_kind), str(link_value), utcnow(),
            ),
        )
        return int(cur.lastrowid)


def claim_next_join_job(path: Path, account_key: str) -> Optional[sqlite3.Row]:
    init_control_db(path)
    key = str(account_key or '').strip().lower()
    with connect(path) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            row = con.execute(
                "SELECT * FROM join_jobs WHERE target_account=? AND status='queued' ORDER BY job_id ASC LIMIT 1",
                (key,),
            ).fetchone()
            if row is None:
                con.execute('COMMIT')
                return None
            changed = con.execute(
                "UPDATE join_jobs SET status='running', started_at=? WHERE job_id=? AND status='queued'",
                (utcnow(), int(row['job_id'])),
            ).rowcount
            if not changed:
                con.execute('ROLLBACK')
                return None
            result = con.execute('SELECT * FROM join_jobs WHERE job_id=?', (int(row['job_id']),)).fetchone()
            con.execute('COMMIT')
            return result
        except Exception:
            con.execute('ROLLBACK')
            raise


def get_join_job(path: Path, job_id: int) -> Optional[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute('SELECT * FROM join_jobs WHERE job_id=?', (int(job_id),)).fetchone()


def update_join_job(path: Path, job_id: int, **fields: Any) -> None:
    allowed = {
        'status', 'result_code', 'result_group_id', 'result_title', 'result_member_count', 'joined_now',
        'started_at', 'finished_at', 'last_error', 'target_account',
    }
    pairs = [(k, v) for k, v in fields.items() if k in allowed]
    if not pairs:
        return
    sql = 'UPDATE join_jobs SET ' + ', '.join(f'{k}=?' for k, _ in pairs) + ' WHERE job_id=?'
    with connect(path) as con:
        con.execute(sql, [v for _, v in pairs] + [int(job_id)])


def recover_running_join_jobs(path: Path, account_key: str) -> int:
    init_control_db(path)
    with connect(path) as con:
        changed = con.execute(
            """
            UPDATE join_jobs
            SET status='queued', started_at='', last_error='PROCESS_RECOVERY_REQUEUE'
            WHERE target_account=? AND status='running'
            """,
            (str(account_key or '').strip().lower(),),
        ).rowcount
        return int(changed or 0)


def recent_unfinished_join_requests(
    path: Path,
    source_account: str,
    *,
    age_seconds: int = 7200,
    limit: int = 30,
) -> List[sqlite3.Row]:
    """Return recent user link requests that never reached a successful job.

    Used after restart/deploy to recover links that failed on one secondary
    account. Probe jobs are excluded and a later successful attempt suppresses
    the old failure, preventing duplicate user replies.
    """
    init_control_db(path)
    now_dt = datetime.now(timezone.utc)
    cutoff = (now_dt - timedelta(seconds=max(60, int(age_seconds)))).isoformat()
    key = str(source_account or '').strip().lower()
    with connect(path) as con:
        return con.execute(
            """
            SELECT j.*
            FROM join_jobs j
            WHERE j.source_account = ?
              AND j.requester_user_id > 0
              AND j.source_message_id > 0
              AND j.link_kind IN ('invite', 'public')
              AND j.status IN ('failed', 'capacity')
              AND j.created_at >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM join_jobs ok
                  WHERE ok.source_account = j.source_account
                    AND ok.source_message_id = j.source_message_id
                    AND ok.requester_user_id = j.requester_user_id
                    AND ok.link_kind = j.link_kind
                    AND ok.link_value = j.link_value
                    AND ok.status = 'done'
              )
              AND j.job_id = (
                  SELECT MAX(j2.job_id) FROM join_jobs j2
                  WHERE j2.source_account = j.source_account
                    AND j2.source_message_id = j.source_message_id
                    AND j2.requester_user_id = j.requester_user_id
                    AND j2.link_kind = j.link_kind
                    AND j2.link_value = j.link_value
              )
            ORDER BY j.job_id ASC
            LIMIT ?
            """,
            (key, cutoff, max(1, min(100, int(limit)))),
        ).fetchall()


def historical_unfinished_join_requests(
    path: Path,
    source_account: str,
    *,
    age_seconds: int = 2592000,
    limit: int = 250,
) -> List[sqlite3.Row]:
    """Return older unresolved private group-link requests for repair.

    A later successful attempt suppresses the old failure. Only the newest
    unresolved row for one user/message/link is returned so a historical
    repair pass cannot create duplicate acknowledgements.
    """
    init_control_db(path)
    now_dt = datetime.now(timezone.utc)
    cutoff = (now_dt - timedelta(seconds=max(3600, int(age_seconds)))).isoformat()
    key = str(source_account or '').strip().lower()
    with connect(path) as con:
        rows = con.execute(
            """
            SELECT j.*
            FROM join_jobs j
            WHERE j.source_account = ?
              AND j.requester_user_id > 0
              AND j.source_message_id > 0
              AND j.link_kind IN ('invite', 'public')
              AND j.status IN ('failed', 'capacity')
              AND j.created_at >= ?
              AND NOT EXISTS (
                  SELECT 1 FROM join_jobs ok
                  WHERE ok.source_account = j.source_account
                    AND ok.source_message_id = j.source_message_id
                    AND ok.requester_user_id = j.requester_user_id
                    AND ok.link_kind = j.link_kind
                    AND ok.link_value = j.link_value
                    AND ok.status = 'done'
              )
              AND j.job_id = (
                  SELECT MAX(j2.job_id) FROM join_jobs j2
                  WHERE j2.source_account = j.source_account
                    AND j2.source_message_id = j.source_message_id
                    AND j2.requester_user_id = j.requester_user_id
                    AND j2.link_kind = j.link_kind
                    AND j2.link_value = j.link_value
              )
            ORDER BY j.job_id DESC
            LIMIT ?
            """,
            (key, cutoff, max(1, min(1000, int(limit)))),
        ).fetchall()
    return list(reversed(rows))


def _normalize_public_username(value: str) -> str:
    return str(value or "").strip().lstrip("@").lower()


def lookup_group_claim(
    path: Path,
    *,
    group_id: int = 0,
    public_username: str = "",
    invite_fingerprint: str = "",
) -> Optional[sqlite3.Row]:
    """Look up an exclusive group owner without mutating shared state."""
    init_control_db(path)
    gid = int(group_id or 0)
    username = _normalize_public_username(public_username)
    fingerprint = str(invite_fingerprint or "").strip().lower()
    with connect(path) as con:
        if gid > 0:
            row = con.execute(
                "SELECT * FROM group_claims WHERE group_id = ?", (gid,)
            ).fetchone()
            if row is not None:
                return row
        if username:
            row = con.execute(
                "SELECT * FROM group_claims WHERE public_username = ?", (username,)
            ).fetchone()
            if row is not None:
                return row
        if fingerprint:
            return con.execute(
                "SELECT * FROM group_claims WHERE invite_fingerprint = ?", (fingerprint,)
            ).fetchone()
    return None


def claim_group(
    path: Path,
    *,
    group_id: int,
    account_key: str,
    self_id: int = 0,
    group_title: str = "",
    public_username: str = "",
    invite_fingerprint: str = "",
    status: str = "pending",
) -> tuple[bool, Optional[sqlite3.Row]]:
    """Atomically claim a group for one ZIVO account.

    Returns (owned_by_this_account, row).  BEGIN IMMEDIATE serializes claims
    across the three independent bot processes, so simultaneous links cannot
    leave two ZIVO accounts assigned to the same group.
    """
    init_control_db(path)
    gid = int(group_id or 0)
    if gid <= 0:
        raise ValueError("group_id must be positive")
    key = str(account_key or "").strip().lower()
    if not key:
        raise ValueError("account_key is required")
    username = _normalize_public_username(public_username)
    fingerprint = str(invite_fingerprint or "").strip().lower()
    now = utcnow()

    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            existing = con.execute(
                "SELECT * FROM group_claims WHERE group_id = ?", (gid,)
            ).fetchone()
            if existing is not None:
                if str(existing["account_key"] or "").lower() != key:
                    con.execute("COMMIT")
                    return False, existing
                con.execute(
                    """
                    UPDATE group_claims
                    SET self_id = CASE WHEN ? != 0 THEN ? ELSE self_id END,
                        group_title = CASE WHEN ? != '' THEN ? ELSE group_title END,
                        public_username = CASE WHEN ? != '' THEN ? ELSE public_username END,
                        invite_fingerprint = CASE WHEN ? != '' THEN ? ELSE invite_fingerprint END,
                        status = ?, updated_at = ?
                    WHERE group_id = ?
                    """,
                    (
                        int(self_id or 0), int(self_id or 0),
                        str(group_title or ""), str(group_title or ""),
                        username, username, fingerprint, fingerprint,
                        str(status or "pending"), now, gid,
                    ),
                )
                row = con.execute(
                    "SELECT * FROM group_claims WHERE group_id = ?", (gid,)
                ).fetchone()
                con.execute("COMMIT")
                return True, row

            alias_row = None
            if username:
                alias_row = con.execute(
                    "SELECT * FROM group_claims WHERE public_username = ?", (username,)
                ).fetchone()
            if alias_row is None and fingerprint:
                alias_row = con.execute(
                    "SELECT * FROM group_claims WHERE invite_fingerprint = ?", (fingerprint,)
                ).fetchone()
            if alias_row is not None:
                # Even a same-account alias that points at another group is not
                # silently reassigned; the concrete group_id is authoritative.
                con.execute("COMMIT")
                return (
                    str(alias_row["account_key"] or "").lower() == key
                    and int(alias_row["group_id"] or 0) == gid,
                    alias_row,
                )

            try:
                con.execute(
                    """
                    INSERT INTO group_claims (
                        group_id, account_key, self_id, group_title,
                        public_username, invite_fingerprint, status,
                        claimed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gid, key, int(self_id or 0), str(group_title or ""),
                        username, fingerprint, str(status or "pending"), now, now,
                    ),
                )
            except sqlite3.IntegrityError:
                # Another process may have won the unique alias race after our
                # pre-check. Resolve the winner under the same transaction.
                winner = con.execute(
                    "SELECT * FROM group_claims WHERE group_id = ?", (gid,)
                ).fetchone()
                if winner is None and username:
                    winner = con.execute(
                        "SELECT * FROM group_claims WHERE public_username = ?", (username,)
                    ).fetchone()
                if winner is None and fingerprint:
                    winner = con.execute(
                        "SELECT * FROM group_claims WHERE invite_fingerprint = ?", (fingerprint,)
                    ).fetchone()
                con.execute("COMMIT")
                return False, winner

            row = con.execute(
                "SELECT * FROM group_claims WHERE group_id = ?", (gid,)
            ).fetchone()
            con.execute("COMMIT")
            return True, row
        except Exception:
            con.execute("ROLLBACK")
            raise


def set_group_claim_status(
    path: Path,
    *,
    group_id: int,
    account_key: str,
    status: str,
    group_title: str = "",
) -> bool:
    init_control_db(path)
    now = utcnow()
    with connect(path) as con:
        changed = con.execute(
            """
            UPDATE group_claims
            SET status = ?,
                group_title = CASE WHEN ? != '' THEN ? ELSE group_title END,
                updated_at = ?
            WHERE group_id = ? AND account_key = ?
            """,
            (
                str(status or "active"), str(group_title or ""), str(group_title or ""),
                now, int(group_id), str(account_key or "").strip().lower(),
            ),
        ).rowcount
        return bool(changed)


def release_group_claim(path: Path, *, group_id: int, account_key: str) -> bool:
    """Release only this account's own claim; never delete another bot's row."""
    init_control_db(path)
    with connect(path) as con:
        changed = con.execute(
            "DELETE FROM group_claims WHERE group_id = ? AND account_key = ?",
            (int(group_id), str(account_key or "").strip().lower()),
        ).rowcount
        return bool(changed)




def acquire_group_event_lease(
    path: Path,
    *,
    group_id: int,
    account_key: str,
    message_id: int = 0,
    ttl_seconds: float = 4.0,
) -> tuple[bool, Optional[sqlite3.Row]]:
    """Choose exactly one live account to handle a conflicted legacy group.

    Static group_claims describe historical installation ownership and can be
    stale after years of account moves/rejoins.  A real incoming group event is
    stronger membership evidence.  This short shared lease lets the first
    account that actually receives traffic handle it, while duplicate member
    accounts suppress their copy.  If the winner stops receiving events, another
    account can take over automatically after a few seconds.
    """
    init_control_db(path)
    gid = int(group_id or 0)
    key = str(account_key or '').strip().lower()
    if gid <= 0 or not key:
        return False, None
    now_epoch = float(time.time())
    lease_until = now_epoch + max(1.0, min(30.0, float(ttl_seconds)))
    now_iso = utcnow()
    with connect(path) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            row = con.execute(
                'SELECT * FROM group_event_leases WHERE group_id = ?', (gid,)
            ).fetchone()
            owner = str(row['account_key'] or '').strip().lower() if row is not None else ''
            expired = row is None or float(row['lease_until'] or 0) <= now_epoch
            if row is None or owner == key or expired:
                con.execute(
                    """
                    INSERT INTO group_event_leases(
                        group_id, account_key, lease_until, last_message_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(group_id) DO UPDATE SET
                        account_key = excluded.account_key,
                        lease_until = excluded.lease_until,
                        last_message_id = excluded.last_message_id,
                        updated_at = excluded.updated_at
                    """,
                    (gid, key, lease_until, int(message_id or 0), now_iso),
                )
                winner = con.execute(
                    'SELECT * FROM group_event_leases WHERE group_id = ?', (gid,)
                ).fetchone()
                con.execute('COMMIT')
                return True, winner
            con.execute('COMMIT')
            return False, row
        except Exception:
            con.execute('ROLLBACK')
            raise


def seed_group_claims_bulk(
    path: Path,
    *,
    account_key: str,
    self_id: int,
    groups: Iterable[Dict[str, Any]],
    status: str = "active",
) -> tuple[int, int]:
    """Seed many historical local group claims in one shared transaction.

    Startup used to call ``claim_group`` once per installed group. With roughly
    two thousand legacy groups per account that meant thousands of BEGIN/COMMIT
    cycles before the runtime could become ready. Live event leases are now the
    authoritative routing signal, so startup seeding only needs to preserve
    historical claims efficiently. Existing foreign owners are never stolen.
    """
    init_control_db(path)
    key = str(account_key or "").strip().lower()
    if not key:
        raise ValueError("account_key is required")
    now = utcnow()
    owned = 0
    conflicts = 0
    with connect(path) as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            for item in groups:
                gid = int(item.get("group_id") or 0)
                if gid <= 0:
                    continue
                title = str(item.get("group_title") or "")
                username = _normalize_public_username(str(item.get("public_username") or ""))
                fingerprint = str(item.get("invite_fingerprint") or "").strip().lower()
                existing = con.execute(
                    "SELECT * FROM group_claims WHERE group_id = ?", (gid,)
                ).fetchone()
                if existing is not None:
                    if str(existing["account_key"] or "").strip().lower() != key:
                        conflicts += 1
                        continue
                    con.execute(
                        """
                        UPDATE group_claims
                        SET self_id = CASE WHEN ? != 0 THEN ? ELSE self_id END,
                            group_title = CASE WHEN ? != '' THEN ? ELSE group_title END,
                            public_username = CASE WHEN ? != '' THEN ? ELSE public_username END,
                            invite_fingerprint = CASE WHEN ? != '' THEN ? ELSE invite_fingerprint END,
                            status = ?, updated_at = ?
                        WHERE group_id = ?
                        """,
                        (
                            int(self_id or 0), int(self_id or 0),
                            title, title, username, username, fingerprint, fingerprint,
                            str(status or "active"), now, gid,
                        ),
                    )
                    owned += 1
                    continue

                alias_row = None
                if username:
                    alias_row = con.execute(
                        "SELECT * FROM group_claims WHERE public_username = ?", (username,)
                    ).fetchone()
                if alias_row is None and fingerprint:
                    alias_row = con.execute(
                        "SELECT * FROM group_claims WHERE invite_fingerprint = ?", (fingerprint,)
                    ).fetchone()
                if alias_row is not None:
                    conflicts += 1
                    continue
                try:
                    con.execute(
                        """
                        INSERT INTO group_claims(
                            group_id, account_key, self_id, group_title,
                            public_username, invite_fingerprint, status, claimed_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            gid, key, int(self_id or 0), title, username, fingerprint,
                            str(status or "active"), now, now,
                        ),
                    )
                    owned += 1
                except sqlite3.IntegrityError:
                    conflicts += 1
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return int(owned), int(conflicts)


def lookup_group_event_lease(path: Path, group_id: int) -> Optional[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            'SELECT * FROM group_event_leases WHERE group_id = ?', (int(group_id),)
        ).fetchone()


def adopt_group_claim_from_live_event(
    path: Path,
    *,
    group_id: int,
    account_key: str,
    self_id: int = 0,
    group_title: str = '',
) -> Optional[sqlite3.Row]:
    """Make the live event-lease winner the durable routing owner.

    This is deliberately stronger than startup seeding: a real inbound event is
    current membership evidence, while old per-account installation rows may be
    stale copies left by historical releases. Alias fields are preserved.
    """
    init_control_db(path)
    gid = int(group_id or 0)
    key = str(account_key or '').strip().lower()
    if gid <= 0 or not key:
        return None
    now = utcnow()
    with connect(path) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            existing = con.execute(
                'SELECT * FROM group_claims WHERE group_id = ?', (gid,)
            ).fetchone()
            if existing is None:
                con.execute(
                    """
                    INSERT INTO group_claims(
                        group_id, account_key, self_id, group_title,
                        public_username, invite_fingerprint, status, claimed_at, updated_at
                    ) VALUES (?, ?, ?, ?, '', '', 'active', ?, ?)
                    """,
                    (gid, key, int(self_id or 0), str(group_title or ''), now, now),
                )
            else:
                con.execute(
                    """
                    UPDATE group_claims
                    SET account_key = ?,
                        self_id = CASE WHEN ? != 0 THEN ? ELSE self_id END,
                        group_title = CASE WHEN ? != '' THEN ? ELSE group_title END,
                        status = 'active', updated_at = ?
                    WHERE group_id = ?
                    """,
                    (key, int(self_id or 0), int(self_id or 0),
                     str(group_title or ''), str(group_title or ''), now, gid),
                )
            row = con.execute(
                'SELECT * FROM group_claims WHERE group_id = ?', (gid,)
            ).fetchone()
            con.execute('COMMIT')
            return row
        except Exception:
            con.execute('ROLLBACK')
            raise


def put_settings_snapshot(
    path: Path,
    *,
    token: str,
    source_account: str,
    source_group_id: int,
    section_key: str,
    payload_json: str,
    summary_json: str,
    created_by: int,
    created_at: str,
    expires_at: str,
) -> None:
    """Mirror one settings-copy token into the shared multi-account plane."""
    init_control_db(path)
    now = utcnow()
    with connect(path) as con:
        con.execute("DELETE FROM settings_snapshots WHERE expires_at != '' AND expires_at < ?", (now,))
        con.execute(
            """
            INSERT INTO settings_snapshots (
                token, source_account, source_group_id, section_key,
                payload_json, summary_json, created_by, created_at,
                expires_at, use_count, last_used_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?)
            ON CONFLICT(token) DO UPDATE SET
                source_account = excluded.source_account,
                source_group_id = excluded.source_group_id,
                section_key = excluded.section_key,
                payload_json = excluded.payload_json,
                summary_json = excluded.summary_json,
                created_by = excluded.created_by,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at,
                updated_at = excluded.updated_at
            """,
            (
                str(token or '').upper().strip(),
                str(source_account or '').strip().lower(),
                int(source_group_id or 0),
                str(section_key or 'all'),
                str(payload_json or '{}'),
                str(summary_json or '{}'),
                int(created_by or 0),
                str(created_at or now),
                str(expires_at or ''),
                now,
            ),
        )


def get_settings_snapshot(path: Path, token: str) -> Optional[sqlite3.Row]:
    init_control_db(path)
    normalized = str(token or '').upper().strip()
    now = utcnow()
    with connect(path) as con:
        row = con.execute(
            "SELECT * FROM settings_snapshots WHERE token = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            return None
        expires = str(row['expires_at'] or '')
        if expires and expires < now:
            con.execute("DELETE FROM settings_snapshots WHERE token = ?", (normalized,))
            return None
        return row


def mark_settings_snapshot_used(path: Path, token: str) -> None:
    init_control_db(path)
    now = utcnow()
    with connect(path) as con:
        con.execute(
            """
            UPDATE settings_snapshots
            SET use_count = use_count + 1,
                last_used_at = ?,
                updated_at = ?
            WHERE token = ?
            """,
            (now, now, str(token or '').upper().strip()),
        )


def recover_settings_snapshot_from_accounts(path: Path, token: str) -> Optional[Dict[str, Any]]:
    """Find a pre-shared token in any configured account DB and promote it.

    This keeps settings codes created before the shared table existed usable when
    the destination group belongs to another ZIVO account.
    """
    init_control_db(path)
    normalized = str(token or '').upper().strip()
    if not normalized:
        return None
    accounts = list_accounts(path)
    for account in accounts:
        db_path = Path(str(account['db_path'] or ''))
        if not db_path.is_file():
            continue
        con = None
        try:
            con = sqlite3.connect(
                f"file:{db_path}?mode=ro",
                uri=True,
                timeout=0.75,
            )
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT * FROM settings_copy_snapshots WHERE token = ?",
                (normalized,),
            ).fetchone()
            if row is None:
                continue
            expires_at = str(row['expires_at'] or '')
            if expires_at and expires_at < utcnow():
                continue
            result = dict(row)
            put_settings_snapshot(
                path,
                token=normalized,
                source_account=str(account['account_key'] or ''),
                source_group_id=int(row['source_group_id'] or 0),
                section_key=str(row['section_key'] or 'all'),
                payload_json=str(row['payload_json'] or '{}'),
                summary_json=str(row['summary_json'] or '{}'),
                created_by=int(row['created_by'] or 0),
                created_at=str(row['created_at'] or ''),
                expires_at=expires_at,
            )
            result['source_account'] = str(account['account_key'] or '')
            return result
        except (sqlite3.Error, OSError):
            continue
        finally:
            if con is not None:
                try:
                    con.close()
                except Exception:
                    pass
    return None


def create_remote_control_job(
    path: Path,
    *,
    target_account: str,
    requester_user_id: int,
    group_id: int,
    command_text: str,
    target_user_id: int = 0,
    target_message_id: int = 0,
) -> int:
    init_control_db(path)
    command = str(command_text or '').strip()
    if not command:
        raise ValueError('REMOTE_CONTROL_COMMAND_EMPTY')
    with connect(path) as con:
        cur = con.execute(
            """
            INSERT INTO remote_control_jobs (
                target_account, requester_user_id, group_id, command_text,
                target_user_id, target_message_id, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)
            """,
            (
                str(target_account or '').strip().lower(), int(requester_user_id or 0),
                int(group_id or 0), command[:2000], int(target_user_id or 0),
                int(target_message_id or 0), utcnow(),
            ),
        )
        return int(cur.lastrowid)


def claim_next_remote_control_job(path: Path, account_key: str) -> Optional[sqlite3.Row]:
    init_control_db(path)
    key = str(account_key or '').strip().lower()
    with connect(path) as con:
        con.execute('BEGIN IMMEDIATE')
        try:
            row = con.execute(
                "SELECT * FROM remote_control_jobs WHERE target_account=? AND status='queued' ORDER BY job_id ASC LIMIT 1",
                (key,),
            ).fetchone()
            if row is None:
                con.execute('COMMIT')
                return None
            changed = con.execute(
                "UPDATE remote_control_jobs SET status='running', started_at=? WHERE job_id=? AND status='queued'",
                (utcnow(), int(row['job_id'])),
            ).rowcount
            if not changed:
                con.execute('ROLLBACK')
                return None
            result = con.execute(
                'SELECT * FROM remote_control_jobs WHERE job_id=?', (int(row['job_id']),)
            ).fetchone()
            con.execute('COMMIT')
            return result
        except Exception:
            con.execute('ROLLBACK')
            raise


def get_remote_control_job(path: Path, job_id: int) -> Optional[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            'SELECT * FROM remote_control_jobs WHERE job_id=?', (int(job_id),)
        ).fetchone()


def update_remote_control_job(path: Path, job_id: int, **fields: Any) -> None:
    allowed = {
        'status', 'result_code', 'result_text', 'started_at', 'finished_at', 'last_error'
    }
    pairs = [(key, value) for key, value in fields.items() if key in allowed]
    if not pairs:
        return
    sql = 'UPDATE remote_control_jobs SET ' + ', '.join(f'{key}=?' for key, _ in pairs) + ' WHERE job_id=?'
    with connect(path) as con:
        con.execute(sql, [value for _, value in pairs] + [int(job_id)])


def recover_running_remote_control_jobs(path: Path, account_key: str) -> int:
    init_control_db(path)
    with connect(path) as con:
        changed = con.execute(
            """
            UPDATE remote_control_jobs
            SET status='queued', started_at='', last_error='PROCESS_RECOVERY_REQUEUE'
            WHERE target_account=? AND status='running'
            """,
            (str(account_key or '').strip().lower(),),
        ).rowcount
        return int(changed or 0)


def recent_remote_control_jobs(
    path: Path,
    requester_user_id: int,
    *,
    limit: int = 30,
) -> List[sqlite3.Row]:
    init_control_db(path)
    with connect(path) as con:
        return con.execute(
            "SELECT * FROM remote_control_jobs WHERE requester_user_id=? ORDER BY job_id DESC LIMIT ?",
            (int(requester_user_id or 0), max(1, min(200, int(limit)))),
        ).fetchall()
