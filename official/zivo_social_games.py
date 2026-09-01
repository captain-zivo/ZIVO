#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Persistent social games and the global MIO economy for ZIVO.

The module intentionally contains no Soroush-specific objects.  It keeps money
mutations inside BEGIN IMMEDIATE transactions, while zivo60.py is responsible
for resolving peers and delivering the returned Persian messages.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import random
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


_DB_PATH = Path(os.getenv("ZIVO_MULTI_ACCOUNT_DB", "/opt/zivo60/zivo_multi_accounts.db"))
_GLOBAL_OWNER_ID = 0
_BOT_USER_IDS: set[int] = set()
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()
_TTT_LOCK = threading.Lock()
_TTT_GAMES: Dict[int, Dict[str, Any]] = {}
_MARKET_LOCK = threading.Lock()
_MARKET_CACHE: Tuple[float, str] = (0.0, "")
_MARKET_SNAPSHOT_LOCK = threading.Lock()
_MARKET_SNAPSHOT_CACHE: Tuple[float, Dict[str, Any]] = (0.0, {})
_MARKET_SNAPSHOT_FAILURE_UNTIL = 0.0
_PET_NAME_CACHE: Dict[int, Tuple[float, str]] = {}
_PET_NAME_CACHE_TTL_SECONDS = 60.0
_IRAN_TZ = timezone(timedelta(hours=3, minutes=30))

_MARKET_CACHE_SECONDS = 120
_MARKET_FAILURE_COOLDOWN_SECONDS = 15
_MARKET_HTTP_TIMEOUT_SECONDS = 4
_MARKET_MAX_HTTP_ATTEMPTS_PER_ASSET = 2
_MARKET_PROVIDER_HTTP_BUDGET_SECONDS = (
    _MARKET_HTTP_TIMEOUT_SECONDS * _MARKET_MAX_HTTP_ATTEMPTS_PER_ASSET
)
_TGJU_MARKET_SLUGS: Tuple[Tuple[str, str], ...] = (
    ("usd", "price_dollar_rl"),
    ("eur", "price_eur"),
    ("gbp", "price_gbp"),
    ("gold18", "geram18"),
)

MEOW_CLAIM_COOLDOWN_SECONDS = 300
MEOW_TRANSFER_MIN = 20
MEOW_TRANSFER_TAX_PERCENT = 2
MEOW_WAGER_MIN = 20
MEOW_WAGER_TAX_PERCENT = 10
TRANSFER_CONFIRM_SECONDS = 180
WAGER_EXPIRE_SECONDS = 300
PET_HUNGER_SECONDS = 24 * 60 * 60
PET_PLAY_COOLDOWN_SECONDS = 30 * 60
PET_FOOD_PRICE = 8

# 60.96.20 owner economy + Telegram admin gifting.  The global bot owner keeps
# an effectively infinite wallet through a SQLite guard, while all admin gifts
# remain auditable and transactional.
UNLIMITED_MEOW_SENTINEL = 9_000_000_000_000_000
ADMIN_GIFT_MAX_MEOW = 1_000_000_000_000_000


def configure(db_path: Any, *, global_owner_id: int = 0, bot_user_ids: Iterable[int] = ()) -> None:
    global _DB_PATH, _GLOBAL_OWNER_ID, _BOT_USER_IDS
    _DB_PATH = Path(db_path)
    _GLOBAL_OWNER_ID = int(global_owner_id or 0)
    _BOT_USER_IDS = {int(value) for value in bot_user_ids if int(value or 0) > 0}
    _PET_NAME_CACHE.clear()
    init_social_db()
    if _GLOBAL_OWNER_ID > 0:
        set_unlimited_meow(_GLOBAL_OWNER_ID, True)


@contextmanager
def _connect():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH), timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        yield con
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def _now() -> int:
    return int(time.time())


def init_social_db() -> None:
    key = str(_DB_PATH.resolve())
    if key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return
        with _connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS social_meow_accounts (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER NOT NULL DEFAULT 0 CHECK(balance >= 0),
                    total_earned INTEGER NOT NULL DEFAULT 0,
                    total_spent INTEGER NOT NULL DEFAULT 0,
                    last_claim_at INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS social_meow_ledger (
                    tx_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    delta INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    reference TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_social_ledger_user
                ON social_meow_ledger(user_id, tx_id DESC);

                CREATE TABLE IF NOT EXISTS social_unlimited_meow (
                    user_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS social_admin_gift_batches (
                    gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_by INTEGER NOT NULL DEFAULT 0,
                    gift_scope TEXT NOT NULL DEFAULT '',
                    target_ref TEXT NOT NULL DEFAULT '',
                    gift_kind TEXT NOT NULL DEFAULT '',
                    meow_amount INTEGER NOT NULL DEFAULT 0,
                    pet_spec TEXT NOT NULL DEFAULT '',
                    total_targets INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    partial_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_social_admin_gift_batches_created
                ON social_admin_gift_batches(gift_id DESC);

                CREATE TABLE IF NOT EXISTS social_admin_gift_items (
                    gift_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT '',
                    meow_applied INTEGER NOT NULL DEFAULT 0,
                    pet_applied INTEGER NOT NULL DEFAULT 0,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (gift_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS social_admin_meow_adjustments (
                    adjustment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_by INTEGER NOT NULL DEFAULT 0,
                    scope TEXT NOT NULL DEFAULT '',
                    target_ref TEXT NOT NULL DEFAULT '',
                    requested_delta INTEGER NOT NULL,
                    total_targets INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    skipped_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    actual_delta INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS social_admin_meow_adjustment_items (
                    adjustment_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    before_balance INTEGER NOT NULL DEFAULT 0,
                    actual_delta INTEGER NOT NULL DEFAULT 0,
                    after_balance INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY(adjustment_id,user_id)
                );

                CREATE TRIGGER IF NOT EXISTS trg_social_unlimited_meow_guard
                AFTER UPDATE OF balance ON social_meow_accounts
                WHEN EXISTS (
                    SELECT 1 FROM social_unlimited_meow u
                    WHERE u.user_id = NEW.user_id AND u.enabled = 1
                ) AND NEW.balance != 9000000000000000
                BEGIN
                    UPDATE social_meow_accounts
                    SET balance = 9000000000000000, updated_at = NEW.updated_at
                    WHERE user_id = NEW.user_id;
                END;

                CREATE TABLE IF NOT EXISTS social_transfers (
                    transfer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sender_id INTEGER NOT NULL,
                    recipient_id INTEGER NOT NULL,
                    amount INTEGER NOT NULL,
                    tax INTEGER NOT NULL,
                    net_amount INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    scope TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    confirmed_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_social_transfer_sender
                ON social_transfers(sender_id, status, transfer_id DESC);

                CREATE TABLE IF NOT EXISTS social_intents (
                    user_id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL DEFAULT '{}',
                    scope TEXT NOT NULL DEFAULT '',
                    expires_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS social_wagers (
                    wager_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    creator_id INTEGER NOT NULL,
                    joiner_id INTEGER NOT NULL DEFAULT 0,
                    stake INTEGER NOT NULL,
                    tax INTEGER NOT NULL DEFAULT 0,
                    prize INTEGER NOT NULL DEFAULT 0,
                    winner_id INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    finished_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_social_wager_group
                ON social_wagers(group_id, status, wager_id DESC);

                CREATE TABLE IF NOT EXISTS social_private_starts (
                    user_id INTEGER NOT NULL,
                    account_key TEXT NOT NULL,
                    last_seen_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, account_key)
                );

                CREATE TABLE IF NOT EXISTS social_notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    claimed_by TEXT NOT NULL DEFAULT '',
                    claimed_at INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_try_at INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    sent_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_social_notification_pending
                ON social_notifications(status, next_try_at, notification_id);

                CREATE TABLE IF NOT EXISTS social_ship_history (
                    ship_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    first_user_id INTEGER NOT NULL,
                    second_user_id INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_social_ship_group
                ON social_ship_history(group_id, ship_id DESC);

                CREATE TABLE IF NOT EXISTS social_pets (
                    pet_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    species TEXT NOT NULL,
                    breed TEXT NOT NULL,
                    name TEXT NOT NULL DEFAULT '',
                    purchase_price INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'alive',
                    happiness INTEGER NOT NULL DEFAULT 60,
                    last_fed_at INTEGER NOT NULL,
                    last_played_at INTEGER NOT NULL DEFAULT 0,
                    purchased_at INTEGER NOT NULL,
                    died_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_social_one_living_pet
                ON social_pets(user_id) WHERE status = 'alive';

                CREATE TABLE IF NOT EXISTS social_houses (
                    ownership_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    house_code TEXT NOT NULL,
                    purchase_price INTEGER NOT NULL,
                    purchased_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'owned'
                );
                CREATE INDEX IF NOT EXISTS idx_social_houses_user
                ON social_houses(user_id, status, ownership_id DESC);

                CREATE TABLE IF NOT EXISTS social_house_listings (
                    listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ownership_id INTEGER NOT NULL,
                    seller_id INTEGER NOT NULL,
                    buyer_id INTEGER NOT NULL DEFAULT 0,
                    asking_price INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at INTEGER NOT NULL,
                    finished_at INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_social_house_listing_open
                ON social_house_listings(status, listing_id DESC);
                """
            )
            notification_columns = {
                str(row["name"]) for row in con.execute("PRAGMA table_info(social_notifications)")
            }
            if "claimed_at" not in notification_columns:
                con.execute(
                    "ALTER TABLE social_notifications "
                    "ADD COLUMN claimed_at INTEGER NOT NULL DEFAULT 0"
                )
        _SCHEMA_READY.add(key)


def normalize_text(value: Any) -> str:
    text = str(value or "").replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    return " ".join(text.strip().split())


def normalize_pet_text(value: Any) -> str:
    """Pet-only tolerant normalization; does not change other social commands."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = (
        text.replace("ي", "ی")
        .replace("ى", "ی")
        .replace("ك", "ک")
        .replace("ۀ", "ه")
        .replace("ة", "ه")
        .replace("\u200c", " ")
        .replace("\u200d", "")
        .replace("\u200e", "")
        .replace("\u200f", "")
        .replace("ـ", "")
    )
    text = text.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    text = re.sub(r"[-_/]+", " ", text)
    return " ".join(text.strip().lower().split())


def _money(value: int) -> str:
    amount = int(value)
    if amount >= UNLIMITED_MEOW_SENTINEL // 2:
        return "∞ میو 🐾"
    return f"{amount:,} میو 🐾"


def _duration(seconds: int) -> str:
    value = max(0, int(seconds))
    minutes, sec = divmod(value, 60)
    if minutes:
        return f"{minutes} دقیقه و {sec} ثانیه" if sec else f"{minutes} دقیقه"
    return f"{sec} ثانیه"


def _ensure_account(con: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    uid = int(user_id)
    now = _now()
    con.execute(
        "INSERT OR IGNORE INTO social_meow_accounts "
        "(user_id, balance, total_earned, total_spent, last_claim_at, created_at, updated_at) "
        "VALUES (?, 0, 0, 0, 0, ?, ?)",
        (uid, now, now),
    )
    unlimited = con.execute(
        "SELECT enabled FROM social_unlimited_meow WHERE user_id=?", (uid,)
    ).fetchone()
    if unlimited is not None and int(unlimited["enabled"] or 0) == 1:
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, updated_at=? WHERE user_id=? AND balance!=?",
            (UNLIMITED_MEOW_SENTINEL, now, uid, UNLIMITED_MEOW_SENTINEL),
        )
    return con.execute("SELECT * FROM social_meow_accounts WHERE user_id=?", (uid,)).fetchone()


def _ledger(con: sqlite3.Connection, user_id: int, delta: int, kind: str, reference: str = "") -> int:
    row = con.execute("SELECT balance FROM social_meow_accounts WHERE user_id=?", (int(user_id),)).fetchone()
    balance = int(row["balance"] if row else 0)
    con.execute(
        "INSERT INTO social_meow_ledger (user_id, delta, balance_after, kind, reference, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(user_id), int(delta), balance, str(kind), str(reference)[:120], _now()),
    )
    return balance


def balance(user_id: int) -> int:
    init_social_db()
    with _connect() as con:
        row = _ensure_account(con, int(user_id))
        return int(row["balance"] or 0)


def set_unlimited_meow(user_id: int, enabled: bool = True) -> None:
    init_social_db()
    uid = int(user_id)
    if uid <= 0:
        return
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        _ensure_account(con, uid)
        con.execute(
            "INSERT INTO social_unlimited_meow(user_id, enabled, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at",
            (uid, 1 if enabled else 0, now),
        )
        if enabled:
            con.execute(
                "UPDATE social_meow_accounts SET balance=?, updated_at=? WHERE user_id=?",
                (UNLIMITED_MEOW_SENTINEL, now, uid),
            )
        con.commit()


def is_unlimited_meow(user_id: int) -> bool:
    init_social_db()
    uid = int(user_id)
    if uid <= 0:
        return False
    with _connect() as con:
        row = con.execute(
            "SELECT enabled FROM social_unlimited_meow WHERE user_id=?", (uid,)
        ).fetchone()
        return bool(row is not None and int(row["enabled"] or 0) == 1)


def admin_gift_users(
    user_ids: Iterable[int],
    *,
    created_by: int = 0,
    scope: str = "",
    target_ref: str = "",
    meow_amount: int = 0,
    pet_spec: str = "",
) -> Dict[str, Any]:
    """Grant MIO and/or one catalog pet to known users in one audited batch.

    Existing living pets are never overwritten.  In a combo gift the MIO still
    applies and that recipient is reported as partial.  Bot service accounts are
    excluded, while the configured global owner remains eligible and infinite.
    """
    init_social_db()
    amount = int(meow_amount or 0)
    if amount < 0 or amount > ADMIN_GIFT_MAX_MEOW:
        raise ValueError("ADMIN_GIFT_MEOW_OUT_OF_RANGE")
    pet_item = resolve_pet_catalog_item(pet_spec) if str(pet_spec or "").strip() else None
    if str(pet_spec or "").strip() and pet_item is None:
        raise ValueError("ADMIN_GIFT_PET_UNKNOWN")
    if amount <= 0 and pet_item is None:
        raise ValueError("ADMIN_GIFT_EMPTY")

    targets = sorted({
        int(uid) for uid in user_ids
        if int(uid or 0) > 0 and int(uid or 0) not in _BOT_USER_IDS
    })
    now = _now()
    kind = "meow+pet" if amount > 0 and pet_item is not None else ("meow" if amount > 0 else "pet")
    result: Dict[str, Any] = {
        "gift_id": 0, "targets": len(targets), "success": 0, "partial": 0,
        "skipped": 0, "failed": 0, "meow_amount": amount,
        "pet": "", "kind": kind,
    }
    if pet_item is not None:
        result["pet"] = f"{pet_item[0]} {pet_item[1]}"

    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute(
            "INSERT INTO social_admin_gift_batches "
            "(created_by, gift_scope, target_ref, gift_kind, meow_amount, pet_spec, total_targets, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (int(created_by or 0), str(scope or "")[:40], str(target_ref or "")[:120],
             kind, amount, result["pet"], len(targets), now),
        )
        gift_id = int(cur.lastrowid or 0)
        result["gift_id"] = gift_id

        for uid in targets:
            meow_applied = 0
            pet_applied = 0
            details: List[str] = []
            try:
                account = _ensure_account(con, uid)
                if amount > 0:
                    if is_unlimited_row := con.execute(
                        "SELECT enabled FROM social_unlimited_meow WHERE user_id=?", (uid,)
                    ).fetchone():
                        if int(is_unlimited_row["enabled"] or 0) == 1:
                            con.execute(
                                "UPDATE social_meow_accounts SET balance=?, updated_at=? WHERE user_id=?",
                                (UNLIMITED_MEOW_SENTINEL, now, uid),
                            )
                        else:
                            new_balance = int(account["balance"] or 0) + amount
                            con.execute(
                                "UPDATE social_meow_accounts SET balance=?, total_earned=total_earned+?, updated_at=? WHERE user_id=?",
                                (new_balance, amount, now, uid),
                            )
                    else:
                        new_balance = int(account["balance"] or 0) + amount
                        con.execute(
                            "UPDATE social_meow_accounts SET balance=?, total_earned=total_earned+?, updated_at=? WHERE user_id=?",
                            (new_balance, amount, now, uid),
                        )
                    _ledger(con, uid, amount, "admin_gift", str(gift_id))
                    meow_applied = 1

                if pet_item is not None:
                    living = _living_pet(con, uid)
                    if living is None:
                        species, breed, _price = pet_item
                        con.execute(
                            "INSERT INTO social_pets "
                            "(user_id, species, breed, purchase_price, status, happiness, last_fed_at, purchased_at) "
                            "VALUES (?, ?, ?, 0, 'alive', 100, ?, ?)",
                            (uid, species, breed, now, now),
                        )
                        pet_applied = 1
                    else:
                        details.append(f"pet_exists:{living['breed']}")

                if meow_applied and pet_item is not None and not pet_applied:
                    status = "partial"
                    result["partial"] += 1
                elif meow_applied or pet_applied:
                    status = "success"
                    result["success"] += 1
                else:
                    status = "skipped"
                    result["skipped"] += 1
                con.execute(
                    "INSERT INTO social_admin_gift_items "
                    "(gift_id, user_id, status, meow_applied, pet_applied, detail, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (gift_id, uid, status, meow_applied, pet_applied, ";".join(details)[:300], now),
                )
            except Exception as exc:
                result["failed"] += 1
                con.execute(
                    "INSERT OR REPLACE INTO social_admin_gift_items "
                    "(gift_id, user_id, status, meow_applied, pet_applied, detail, created_at) "
                    "VALUES (?, ?, 'failed', ?, ?, ?, ?)",
                    (gift_id, uid, meow_applied, pet_applied, f"{type(exc).__name__}:{exc}"[:300], now),
                )

        con.execute(
            "UPDATE social_admin_gift_batches SET success_count=?, partial_count=?, skipped_count=?, failed_count=? WHERE gift_id=?",
            (result["success"], result["partial"], result["skipped"], result["failed"], gift_id),
        )
        con.commit()
    return result



def recent_admin_gifts(limit: int = 10) -> List[Dict[str, Any]]:
    init_social_db()
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM social_admin_gift_batches ORDER BY gift_id DESC LIMIT ?",
            (max(1, min(50, int(limit))),),
        ).fetchall()
    return [dict(row) for row in rows]


def claim_meow(user_id: int, luck_multiplier: float = 1.0) -> str:
    init_social_db()
    uid = int(user_id)
    now = _now()
    luck = max(1.0, min(2.0, float(luck_multiplier or 1.0)))
    pool = [10, 10, 11, 12, 12, 13, 14, 15, 16, 18, 20]
    if luck >= 1.10:
        pool += [18, 20]
    if luck >= 1.30:
        pool += [18, 20, 22, 25]
    if luck >= 1.50:
        pool += [20, 22, 25, 30, 40]
    reward = secrets.choice(tuple(pool))
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = _ensure_account(con, uid)
        wait = MEOW_CLAIM_COOLDOWN_SECONDS - (now - int(row["last_claim_at"] or 0))
        if wait > 0:
            con.rollback()
            return (
                "⏳ هنوز وقت میوی بعدی نرسیده!\n"
                f"🐾 { _duration(wait) } دیگه دوباره بنویس: میو\n"
                f"💰 موجودی فعلی: {_money(int(row['balance'] or 0))}"
            )
        new_balance = int(row["balance"] or 0) + int(reward)
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_earned=total_earned+?, "
            "last_claim_at=?, updated_at=? WHERE user_id=?",
            (new_balance, reward, now, now, uid),
        )
        _ledger(con, uid, reward, "claim", "meow")
        con.commit()
    lucky = "\n✨ این میو خوش‌شانس بود!" if reward >= 18 else ""
    return (
        "🐾 میوووو! جایزه‌ات رسید 😸\n"
        f"➕ دریافتی: {_money(reward)}\n"
        f"💰 موجودی جدید: {_money(new_balance)}\n"
        "⏱ میوی بعدی: ۵ دقیقه دیگه"
        f"{lucky}"
    )


def set_intent(user_id: int, kind: str, payload: Dict[str, Any], scope: str, ttl: int = 180) -> None:
    init_social_db()
    with _connect() as con:
        con.execute(
            "INSERT INTO social_intents (user_id, kind, payload, scope, expires_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET kind=excluded.kind, payload=excluded.payload, "
            "scope=excluded.scope, expires_at=excluded.expires_at",
            (int(user_id), str(kind), json.dumps(payload, ensure_ascii=False), str(scope), _now() + int(ttl)),
        )


def get_intent(user_id: int) -> Optional[Dict[str, Any]]:
    init_social_db()
    with _connect() as con:
        row = con.execute("SELECT * FROM social_intents WHERE user_id=?", (int(user_id),)).fetchone()
        if row is None:
            return None
        if int(row["expires_at"] or 0) < _now():
            con.execute("DELETE FROM social_intents WHERE user_id=?", (int(user_id),))
            return None
        try:
            payload = json.loads(str(row["payload"] or "{}"))
        except Exception:
            payload = {}
        return {"kind": str(row["kind"]), "payload": payload, "scope": str(row["scope"] or "")}


def clear_intent(user_id: int) -> None:
    init_social_db()
    with _connect() as con:
        con.execute("DELETE FROM social_intents WHERE user_id=?", (int(user_id),))


def mark_private_started(user_id: int, account_key: str) -> None:
    init_social_db()
    uid = int(user_id)
    key = str(account_key or "main")[:64]
    with _connect() as con:
        con.execute(
            "INSERT INTO social_private_starts (user_id, account_key, last_seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, account_key) DO UPDATE SET last_seen_at=excluded.last_seen_at",
            (uid, key, _now()),
        )


def mark_private_started_batch(user_ids: Iterable[int], account_key: str) -> int:
    init_social_db()
    key = str(account_key or "main")[:64]
    now = _now()
    ids = sorted({int(value) for value in user_ids if int(value or 0) > 0})
    if not ids:
        return 0
    with _connect() as con:
        con.executemany(
            "INSERT INTO social_private_starts (user_id, account_key, last_seen_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, account_key) DO UPDATE SET last_seen_at=MAX(last_seen_at, excluded.last_seen_at)",
            [(uid, key, now) for uid in ids],
        )
    return len(ids)


def has_started_any_bot(user_id: int) -> bool:
    init_social_db()
    with _connect() as con:
        return con.execute(
            "SELECT 1 FROM social_private_starts WHERE user_id=? LIMIT 1", (int(user_id),)
        ).fetchone() is not None


def _queue_notification(con: sqlite3.Connection, user_id: int, text: str) -> None:
    con.execute(
        "INSERT INTO social_notifications (user_id, text, status, next_try_at, created_at) "
        "VALUES (?, ?, 'pending', 0, ?)",
        (int(user_id), str(text)[:1800], _now()),
    )


def queue_notification(user_id: int, text: str) -> None:
    init_social_db()
    with _connect() as con:
        _queue_notification(con, int(user_id), str(text))


def claim_notifications(account_key: str, limit: int = 5) -> List[Dict[str, Any]]:
    init_social_db()
    key = str(account_key or "main")[:64]
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        # A process may stop after claiming a PM but before reporting the send
        # result.  Release only genuinely stale claims, so another account can
        # deliver them instead of leaving the notification stuck forever.
        con.execute(
            "UPDATE social_notifications SET status='pending', claimed_by='', claimed_at=0 "
            "WHERE status='sending' AND claimed_at > 0 AND claimed_at <= ?",
            (now - 300,),
        )
        rows = con.execute(
            """
            SELECT n.notification_id, n.user_id, n.text, n.attempts
            FROM social_notifications n
            WHERE n.status='pending' AND n.next_try_at <= ?
              AND EXISTS (
                  SELECT 1 FROM social_private_starts s
                  WHERE s.user_id=n.user_id AND s.account_key=?
              )
            ORDER BY n.notification_id ASC LIMIT ?
            """,
            (now, key, max(1, int(limit))),
        ).fetchall()
        ids = [int(row["notification_id"]) for row in rows]
        if ids:
            marks = ",".join("?" for _ in ids)
            con.execute(
                f"UPDATE social_notifications SET status='sending', claimed_by=?, claimed_at=? "
                f"WHERE notification_id IN ({marks})",
                (key, now, *ids),
            )
        con.commit()
    return [dict(row) for row in rows]


def finish_notification(notification_id: int, success: bool, error: str = "") -> None:
    init_social_db()
    with _connect() as con:
        row = con.execute(
            "SELECT attempts FROM social_notifications WHERE notification_id=?",
            (int(notification_id),),
        ).fetchone()
        if row is None:
            return
        attempts = int(row["attempts"] or 0) + (0 if success else 1)
        if success:
            con.execute(
                "UPDATE social_notifications SET status='sent', sent_at=?, claimed_at=0, last_error='' WHERE notification_id=?",
                (_now(), int(notification_id)),
            )
        elif attempts >= 10:
            con.execute(
                "UPDATE social_notifications SET status='failed', claimed_at=0, attempts=?, last_error=? WHERE notification_id=?",
                (attempts, str(error)[:300], int(notification_id)),
            )
        else:
            delay = min(1800, 30 * (2 ** min(attempts, 6)))
            con.execute(
                "UPDATE social_notifications SET status='pending', claimed_by='', claimed_at=0, attempts=?, "
                "next_try_at=?, last_error=? WHERE notification_id=?",
                (attempts, _now() + delay, str(error)[:300], int(notification_id)),
            )


def prepare_transfer(sender_id: int, recipient_id: int, amount: int, scope: str = "") -> str:
    init_social_db()
    sender = int(sender_id)
    recipient = int(recipient_id)
    value = int(amount)
    if sender == recipient:
        return "😹 نمی‌تونی میو رو به خودت انتقال بدی."
    if value < MEOW_TRANSFER_MIN:
        return f"⛔ حداقل انتقال {_money(MEOW_TRANSFER_MIN)} است."
    if recipient <= 0 or recipient in _BOT_USER_IDS:
        return "❌ کاربر مقصد برای انتقال معتبر نیست."
    if not has_started_any_bot(recipient):
        return (
            "🤖 کاربر مقصد هنوز هیچ‌کدام از ربات‌های زیوو را در پیوی استارت نکرده.\n"
            "اول باید یک پیام به یکی از ربات‌ها بفرستد؛ بعد انتقال را دوباره انجام بده."
        )
    tax = max(1, math.ceil(value * MEOW_TRANSFER_TAX_PERCENT / 100.0))
    net = value - tax
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        sender_row = _ensure_account(con, sender)
        _ensure_account(con, recipient)
        if int(sender_row["balance"] or 0) < value:
            con.rollback()
            return (
                "💸 موجودی کافی نیست.\n"
                f"💰 موجودی تو: {_money(int(sender_row['balance'] or 0))}\n"
                f"📤 مبلغ لازم: {_money(value)}"
            )
        con.execute(
            "UPDATE social_transfers SET status='cancelled' WHERE sender_id=? AND status='pending'",
            (sender,),
        )
        cur = con.execute(
            "INSERT INTO social_transfers "
            "(sender_id, recipient_id, amount, tax, net_amount, status, scope, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
            (sender, recipient, value, tax, net, str(scope), _now(), _now() + TRANSFER_CONFIRM_SECONDS),
        )
        transfer_id = int(cur.lastrowid)
        con.commit()
    return (
        "📤 ZIVO | تأیید انتقال میو\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🧾 شماره انتقال: {transfer_id}\n"
        f"👤 مقصد: {recipient}\n"
        f"💰 مبلغ: {_money(value)}\n"
        f"🏦 مالیات ۲٪: {_money(tax)}\n"
        f"📥 دریافتی مقصد: {_money(net)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "برای انجام بنویس: تایید انتقال\n"
        "برای انصراف بنویس: لغو انتقال"
    )


def confirm_transfer(sender_id: int, sender_name: str = "کاربر") -> str:
    init_social_db()
    sender = int(sender_id)
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM social_transfers WHERE sender_id=? AND status='pending' "
            "ORDER BY transfer_id DESC LIMIT 1",
            (sender,),
        ).fetchone()
        if row is None:
            con.rollback()
            return "📭 انتقال در انتظار تأییدی برای تو وجود نداره."
        if int(row["expires_at"] or 0) < now:
            con.execute("UPDATE social_transfers SET status='expired' WHERE transfer_id=?", (int(row["transfer_id"]),))
            con.commit()
            return "⌛ زمان تأیید این انتقال تمام شده؛ دوباره درخواست انتقال بساز."
        recipient = int(row["recipient_id"])
        amount = int(row["amount"])
        net = int(row["net_amount"])
        tax = int(row["tax"])
        sender_row = _ensure_account(con, sender)
        recipient_row = _ensure_account(con, recipient)
        if int(sender_row["balance"] or 0) < amount:
            con.execute("UPDATE social_transfers SET status='failed' WHERE transfer_id=?", (int(row["transfer_id"]),))
            con.commit()
            return "💸 موجودی‌ات از زمان ساخت درخواست کم شده و انتقال انجام نشد."
        sender_balance = int(sender_row["balance"]) - amount
        recipient_balance = int(recipient_row["balance"]) + net
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, updated_at=? WHERE user_id=?",
            (sender_balance, amount, now, sender),
        )
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_earned=total_earned+?, updated_at=? WHERE user_id=?",
            (recipient_balance, net, now, recipient),
        )
        con.execute(
            "UPDATE social_transfers SET status='confirmed', confirmed_at=? WHERE transfer_id=?",
            (now, int(row["transfer_id"])),
        )
        _ledger(con, sender, -amount, "transfer_out", str(row["transfer_id"]))
        _ledger(con, recipient, net, "transfer_in", str(row["transfer_id"]))
        _queue_notification(
            con,
            recipient,
            "🐾 یک انتقال میو برایت رسید!\n"
            f"👤 فرستنده: {sender_name} ({sender})\n"
            f"📥 دریافتی: {_money(net)}\n"
            f"💰 موجودی جدید: {_money(recipient_balance)}",
        )
        con.commit()
    return (
        "✅ انتقال میو با موفقیت انجام شد.\n"
        f"📤 از حساب تو کم شد: {_money(amount)}\n"
        f"🏦 مالیات: {_money(tax)}\n"
        f"📥 برای کاربر مقصد: {_money(net)}\n"
        f"💰 موجودی جدید تو: {_money(sender_balance)}\n"
        "📨 نتیجه در پیوی کاربر مقصد هم ارسال می‌شود."
    )


def cancel_transfer(sender_id: int) -> str:
    init_social_db()
    with _connect() as con:
        cur = con.execute(
            "UPDATE social_transfers SET status='cancelled' WHERE transfer_id=("
            "SELECT transfer_id FROM social_transfers WHERE sender_id=? AND status='pending' "
            "ORDER BY transfer_id DESC LIMIT 1)",
            (int(sender_id),),
        )
    return "✅ درخواست انتقال لغو شد." if cur.rowcount else "📭 انتقالی برای لغو وجود نداره."


def create_wager(group_id: int, creator_id: int, stake: int, creator_name: str = "کاربر") -> str:
    init_social_db()
    gid, uid, value = int(group_id), int(creator_id), int(stake)
    if value < MEOW_WAGER_MIN:
        return f"⛔ حداقل مبلغ بازی {_money(MEOW_WAGER_MIN)} است."
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        account = _ensure_account(con, uid)
        if int(account["balance"] or 0) < value:
            con.rollback()
            return f"💸 موجودی کافی نداری. موجودی تو: {_money(int(account['balance'] or 0))}"
        con.execute(
            "UPDATE social_wagers SET status='expired', finished_at=? "
            "WHERE group_id=? AND status='open' AND expires_at < ?",
            (_now(), gid, _now()),
        )
        old = con.execute(
            "SELECT wager_id FROM social_wagers WHERE group_id=? AND status='open' LIMIT 1", (gid,)
        ).fetchone()
        if old is not None:
            con.rollback()
            return "🎲 یک بازی میو در این گروه منتظر حریف است؛ اول همان را تمام یا لغو کنید."
        cur = con.execute(
            "INSERT INTO social_wagers (group_id, creator_id, stake, status, created_at, expires_at) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (gid, uid, value, _now(), _now() + WAGER_EXPIRE_SECONDS),
        )
        wager_id = int(cur.lastrowid)
        con.commit()
    total = value * 2
    tax = max(1, math.ceil(total * MEOW_WAGER_TAX_PERCENT / 100.0))
    prize = total - tax
    return (
        "🎲 ZIVO | بازی شانسی میو\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🧾 بازی شماره: {wager_id}\n"
        f"👤 سازنده: {creator_name}\n"
        f"💰 سهم هر نفر: {_money(value)}\n"
        f"🏦 مالیات بازی: {_money(tax)}\n"
        f"🏆 جایزه برنده: {_money(prize)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "اولین کاربری که بنویسد «تایید بازی» وارد بازی می‌شود.\n"
        "لغو فقط توسط سازنده یا مالک کل زیوو انجام می‌شود."
    )


def accept_wager(group_id: int, joiner_id: int, creator_name: str = "بازیکن اول", joiner_name: str = "بازیکن دوم") -> str:
    init_social_db()
    gid, joiner, now = int(group_id), int(joiner_id), _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM social_wagers WHERE group_id=? AND status='open' ORDER BY wager_id DESC LIMIT 1",
            (gid,),
        ).fetchone()
        if row is None:
            con.rollback()
            return "📭 بازیِ منتظر حریفی در این گروه وجود نداره."
        if int(row["expires_at"] or 0) < now:
            con.execute("UPDATE social_wagers SET status='expired', finished_at=? WHERE wager_id=?", (now, int(row["wager_id"])))
            con.commit()
            return "⌛ زمان پیوستن به این بازی تمام شد."
        creator = int(row["creator_id"])
        if joiner == creator:
            con.rollback()
            return "😄 نمی‌تونی حریف بازی خودت بشی؛ منتظر یک نفر دیگه باش."
        stake = int(row["stake"])
        first = _ensure_account(con, creator)
        second = _ensure_account(con, joiner)
        if int(first["balance"] or 0) < stake:
            con.execute("UPDATE social_wagers SET status='failed', finished_at=? WHERE wager_id=?", (now, int(row["wager_id"])))
            con.commit()
            return "💸 موجودی سازنده بازی دیگه کافی نیست؛ بازی بسته شد."
        if int(second["balance"] or 0) < stake:
            con.rollback()
            return f"💸 برای ورود به این بازی باید {_money(stake)} داشته باشی؛ موجودی تو {_money(int(second['balance'] or 0))} است."
        pot = stake * 2
        tax = max(1, math.ceil(pot * MEOW_WAGER_TAX_PERCENT / 100.0))
        prize = pot - tax
        winner = secrets.choice((creator, joiner))
        first_balance = int(first["balance"]) - stake + (prize if winner == creator else 0)
        second_balance = int(second["balance"]) - stake + (prize if winner == joiner else 0)
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, "
            "total_earned=total_earned+?, updated_at=? WHERE user_id=?",
            (first_balance, stake, prize if winner == creator else 0, now, creator),
        )
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, "
            "total_earned=total_earned+?, updated_at=? WHERE user_id=?",
            (second_balance, stake, prize if winner == joiner else 0, now, joiner),
        )
        con.execute(
            "UPDATE social_wagers SET joiner_id=?, tax=?, prize=?, winner_id=?, status='finished', finished_at=? "
            "WHERE wager_id=?",
            (joiner, tax, prize, winner, now, int(row["wager_id"])),
        )
        _ledger(con, creator, -stake + (prize if winner == creator else 0), "wager", str(row["wager_id"]))
        _ledger(con, joiner, -stake + (prize if winner == joiner else 0), "wager", str(row["wager_id"]))
        con.commit()
    winner_name = creator_name if winner == creator else joiner_name
    loser_name = joiner_name if winner == creator else creator_name
    return (
        "🎰 نتیجه بازی میو مشخص شد!\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🏆 برنده: {winner_name}\n"
        f"😿 بازنده: {loser_name}\n"
        f"💰 جایزه برنده: {_money(prize)}\n"
        f"🏦 مالیات بازی: {_money(tax)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💳 موجودی {creator_name}: {_money(first_balance)}\n"
        f"💳 موجودی {joiner_name}: {_money(second_balance)}"
    )


def cancel_wager(group_id: int, actor_id: int) -> str:
    init_social_db()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM social_wagers WHERE group_id=? AND status='open' ORDER BY wager_id DESC LIMIT 1",
            (int(group_id),),
        ).fetchone()
        if row is None:
            return "📭 هیچ بازی میوی فعالی برای لغو وجود نداره."
        if int(actor_id) not in {int(row["creator_id"]), int(_GLOBAL_OWNER_ID)}:
            return "⛔ فقط سازنده بازی یا مالک کل زیوو می‌تواند این بازی را لغو کند."
        con.execute(
            "UPDATE social_wagers SET status='cancelled', finished_at=? WHERE wager_id=?",
            (_now(), int(row["wager_id"])),
        )
    return "🛑 بازی میو لغو شد و هیچ مبلغی از کسی کم نشد."


def open_wager_info(group_id: int) -> Optional[Dict[str, Any]]:
    init_social_db()
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM social_wagers WHERE group_id=? AND status='open' ORDER BY wager_id DESC LIMIT 1",
            (int(group_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def _board_text(cells: Sequence[str]) -> str:
    icons = [value if value in {"❌", "🟢"} else str(index + 1) for index, value in enumerate(cells)]
    return "\n".join((f" {icons[0]} │ {icons[1]} │ {icons[2]}", "───┼───┼───", f" {icons[3]} │ {icons[4]} │ {icons[5]}", "───┼───┼───", f" {icons[6]} │ {icons[7]} │ {icons[8]}"))


def _ttt_winner(cells: Sequence[str]) -> str:
    lines = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))
    for a, b, c in lines:
        if cells[a] and cells[a] == cells[b] == cells[c]:
            return cells[a]
    return ""


def tic_tac_toe(group_id: int, actor_id: int, actor_name: str, action: str, cell: int = 0) -> str:
    gid, uid = int(group_id), int(actor_id)
    name = str(actor_name or f"کاربر {uid}")[:50]
    with _TTT_LOCK:
        game = _TTT_GAMES.get(gid)
        if game and time.monotonic() - float(game.get("created") or 0) > 900:
            _TTT_GAMES.pop(gid, None)
            game = None
        if action == "start":
            if game:
                return "🎮 یک بازی دوز در این گروه باز است. برای ورود بنویس: پیوستن دوز"
            _TTT_GAMES[gid] = {
                "x": uid, "o": 0, "x_name": name, "o_name": "", "turn": uid,
                "cells": [""] * 9, "created": time.monotonic(),
            }
            return (
                "🎮 ZIVO | بازی دوز\n━━━━━━━━━━━━━━━━━━\n"
                f"❌ سازنده: {name}\n🟢 حریف: منتظر بازیکن\n\n{_board_text([''] * 9)}\n\n"
                "برای ورود بنویس: پیوستن دوز\n"
                "بعد از ورود، فقط همین دو بازیکن می‌توانند حرکت کنند."
            )
        if not game:
            return "📭 بازی دوز فعالی نیست. برای ساخت بازی بنویس: بازی دوز"
        if action == "join":
            if uid == int(game["x"]):
                return "😄 خودت سازنده‌ای؛ باید یک نفر دیگه وارد بازی بشه."
            if int(game["o"] or 0):
                if uid in {int(game["x"]), int(game["o"])}:
                    return f"🎮 تو همین حالا داخل بازی هستی.\n\n{_board_text(game['cells'])}"
                return "🔒 این بازی دونفره تکمیل شده؛ کاربران دیگر نمی‌توانند وارد یا حرکتش را خراب کنند."
            game["o"] = uid
            game["o_name"] = name
            return (
                "🎮 بازی دوز شروع شد!\n━━━━━━━━━━━━━━━━━━\n"
                f"❌ {game['x_name']}\n🟢 {name}\n\n{_board_text(game['cells'])}\n\n"
                f"نوبت: {game['x_name']} ❌\nبرای حرکت بنویس: دوز 1 تا دوز 9"
            )
        if action == "cancel":
            if uid not in {int(game["x"]), int(game["o"] or 0), int(_GLOBAL_OWNER_ID)}:
                return "⛔ فقط بازیکنان همین بازی یا مالک کل زیوو می‌توانند دوز را لغو کنند."
            _TTT_GAMES.pop(gid, None)
            return "🛑 بازی دوز لغو شد."
        if action == "status":
            turn_name = game["x_name"] if int(game["turn"]) == int(game["x"]) else game["o_name"]
            return f"🎮 وضعیت دوز\n\n{_board_text(game['cells'])}\n\nنوبت: {turn_name or 'منتظر حریف'}"
        if action != "move":
            return "⚠️ فرمان دوز نامعتبره."
        if not int(game["o"] or 0):
            return "⏳ هنوز کسی به بازی نپیوسته. فرمان ورود: پیوستن دوز"
        if uid not in {int(game["x"]), int(game["o"])}:
            return "🔒 فقط دو بازیکن همین بازی اجازه حرکت دارند."
        if uid != int(game["turn"]):
            turn_name = game["x_name"] if int(game["turn"]) == int(game["x"]) else game["o_name"]
            return f"⏳ هنوز نوبت تو نیست؛ نوبت {turn_name} است."
        if not 1 <= int(cell) <= 9:
            return "⚠️ شماره خانه باید بین 1 تا 9 باشد؛ نمونه: دوز 5"
        index = int(cell) - 1
        if game["cells"][index]:
            return "⚠️ این خانه قبلاً پر شده؛ یک خانه خالی انتخاب کن."
        mark = "❌" if uid == int(game["x"]) else "🟢"
        game["cells"][index] = mark
        winner_mark = _ttt_winner(game["cells"])
        if winner_mark:
            winner_name = game["x_name"] if winner_mark == "❌" else game["o_name"]
            board = _board_text(game["cells"])
            _TTT_GAMES.pop(gid, None)
            return f"🎉 پایان بازی دوز!\n\n{board}\n\n🏆 برنده: {winner_name} {winner_mark}\nبرای بازی تازه: بازی دوز"
        if all(game["cells"]):
            board = _board_text(game["cells"])
            _TTT_GAMES.pop(gid, None)
            return f"🤝 بازی مساوی شد!\n\n{board}\n\nبرای بازی تازه: بازی دوز"
        game["turn"] = int(game["o"]) if uid == int(game["x"]) else int(game["x"])
        turn_name = game["x_name"] if int(game["turn"]) == int(game["x"]) else game["o_name"]
        return f"🎮 حرکت ثبت شد.\n\n{_board_text(game['cells'])}\n\nنوبت: {turn_name}"


_FEMALE_NAMES = {
    "فاطمه","زهرا","مریم","سارا","نگار","نازنین","نرگس","مهسا","الهام","ریحانه","حدیث","هانیه",
    "آیدا","آتنا","یلدا","یاسمن","رها","ستایش","مبینا","کیمیا","لیلا","پریسا","سمانه","غزل",
}
_MALE_NAMES = {
    "علی","محمد","حسین","رضا","مهدی","امیر","میلاد","سینا","سجاد","محمدرضا","آرمان","عرفان",
    "پویا","پدرام","کیان","سامان","یاسین","پارسا","ماهان","شایان","ابوالفضل","مصطفی","مجتبی","رامین",
}


def _name_gender(name: str) -> str:
    first = normalize_text(name).split(" ", 1)[0]
    if first in _FEMALE_NAMES:
        return "f"
    if first in _MALE_NAMES:
        return "m"
    return "u"


_SHIP_LINES = (
    "انگار الگوریتم دل زیوو امروز این دوتا رو کنار هم نوشته 💞",
    "بین این دو نفر یه وایب قشنگ پیدا شد؛ بقیش با خودشون 🌹",
    "زیوو فال این لحظه رو گرفت و اسم این دو نفر کنار هم افتاد ✨",
    "دو تا اسم، یک قاب و کلی احتمال قشنگ؛ شیپ امروز آماده‌ست 💗",
    "اگه قصه‌ای قرار باشه شروع بشه، شاید از همین دو اسم باشه 🌙",
    "کوپید زیوو تیرشو انداخت؛ حالا ببینیم به هدف خورده یا نه 😂💘",
)


def choose_ship(group_id: int, active_users: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    init_social_db()
    unique: Dict[int, Dict[str, Any]] = {}
    for item in active_users:
        uid = int(item.get("user_id") or 0)
        if uid <= 0 or uid in _BOT_USER_IDS:
            continue
        unique.setdefault(uid, dict(item))
    users = list(unique.values())
    if len(users) < 2:
        return {"text": "💞 برای شیپ حداقل دو کاربر فعال در ۱۰۰ پیام اخیر لازم داریم.", "users": []}
    with _connect() as con:
        recent_rows = con.execute(
            "SELECT first_user_id, second_user_id FROM social_ship_history WHERE group_id=? "
            "ORDER BY ship_id DESC LIMIT 30",
            (int(group_id),),
        ).fetchall()
    recent_pairs = {tuple(sorted((int(row[0]), int(row[1])))) for row in recent_rows}
    immediate_pair = tuple(sorted((int(recent_rows[0][0]), int(recent_rows[0][1])))) if recent_rows else ()
    opposite: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    all_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    for i, first in enumerate(users):
        for second in users[i + 1:]:
            pair_key = tuple(sorted((int(first["user_id"]), int(second["user_id"]))))
            if pair_key in recent_pairs:
                continue
            all_pairs.append((first, second))
            genders = {_name_gender(str(first.get("name") or "")), _name_gender(str(second.get("name") or ""))}
            if genders == {"f", "m"}:
                opposite.append((first, second))
    pool = opposite or all_pairs
    if not pool:
        # When every possible pair was recently used, avoid getting stuck and
        # only exclude the immediately previous pair.
        for i, first in enumerate(users):
            for second in users[i + 1:]:
                key = tuple(sorted((int(first["user_id"]), int(second["user_id"]))))
                if key != immediate_pair:
                    pool.append((first, second))
    if not pool:
        pool = [(users[0], users[1])]
    first, second = secrets.choice(pool)
    with _connect() as con:
        con.execute(
            "INSERT INTO social_ship_history (group_id, first_user_id, second_user_id, created_at) VALUES (?, ?, ?, ?)",
            (int(group_id), int(first["user_id"]), int(second["user_id"]), _now()),
        )
    first_name = str(first.get("name") or first.get("username") or first["user_id"])[:50]
    second_name = str(second.get("name") or second.get("username") or second["user_id"])[:50]
    return {
        "text": (
            "💞 ZIVO | شیپ کاربران فعال\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"💗 {first_name}\n"
            "                 ×\n"
            f"💗 {second_name}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{secrets.choice(_SHIP_LINES)}\n"
            "🎲 انتخاب از بین کاربران فعال ۱۰۰ پیام اخیر و کاملاً تصادفی بود."
        ),
        "users": [first, second],
    }


PET_CATALOG: Dict[str, Tuple[str, str, int]] = {}
PET_ALIASES: Dict[str, str] = {}
for _species, _base, _breeds in (
    ("سگ", 180, ("هاسکی","ژرمن شپرد","گلدن رتریور","لابرادور","پامرانین","شیتزو","دوبرمن","ساموید","کورگی","پودل")),
    ("گربه", 150, ("پرشین","بریتیش","اسکاتیش","سیامی","بنگال","مین کون","رگدال","اسفینکس","اگزوتیک","آنقوره")),
    ("طوطی", 120, ("عروس هلندی","کاسکو","ملنگو","برزیلی","ماکائو","کاکادو","راهب","آمازون","شاه طوطی","مرغ عشق")),
):
    for _index, _breed in enumerate(_breeds):
        _canonical = normalize_pet_text(f"{_species} {_breed}")
        PET_CATALOG[_canonical] = (_species, _breed, _base + (_index * 28))
        # The shop visibly lists breed names alone, so those names must resolve.
        # All current breeds are unique across species; ambiguous future aliases
        # are deliberately discarded instead of guessing the wrong pet.
        _breed_key = normalize_pet_text(_breed)
        if _breed_key in PET_ALIASES and PET_ALIASES[_breed_key] != _canonical:
            PET_ALIASES[_breed_key] = ""
        else:
            PET_ALIASES[_breed_key] = _canonical


def resolve_pet_catalog_item(pet_spec: Any) -> Optional[Tuple[str, str, int]]:
    spec = normalize_pet_text(pet_spec)
    if not spec:
        return None
    item = PET_CATALOG.get(spec)
    if item is not None:
        return item
    alias = PET_ALIASES.get(spec)
    if alias:
        return PET_CATALOG.get(alias)
    # Accept harmless Persian plural suffixes users copy from the shop heading.
    for suffix in (" ها", "ها"):
        if spec.endswith(suffix):
            candidate = spec[: -len(suffix)].strip()
            item = PET_CATALOG.get(candidate)
            if item is not None:
                return item
            alias = PET_ALIASES.get(candidate)
            if alias:
                return PET_CATALOG.get(alias)
    return None


def pet_shop_text() -> str:
    lines = ["🐾 ZIVO | فروشگاه پت", "━━━━━━━━━━━━━━━━━━"]
    for species in ("سگ", "گربه", "طوطی"):
        lines.append(f"\n{ {'سگ':'🐶','گربه':'🐱','طوطی':'🦜'}[species] } {species}‌ها:")
        for key, (kind, breed, price) in PET_CATALOG.items():
            if kind == species:
                lines.append(f"• {breed} — {_money(price)}")
    lines.extend(("", "نمونه خرید: خرید پت سگ هاسکی", f"🍗 قیمت هر غذا: {_money(PET_FOOD_PRICE)}", "⚠️ پت باید حداقل هر ۲۴ ساعت غذا بخورد."))
    return "\n".join(lines)


def _living_pet(con: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
    return con.execute(
        "SELECT * FROM social_pets WHERE user_id=? AND status='alive' ORDER BY pet_id DESC LIMIT 1",
        (int(user_id),),
    ).fetchone()


def living_pet_name(user_id: int) -> str:
    """Return the current live pet name with a small per-user cache.

    This function is intentionally cheap enough for the command-candidate path:
    a normal user's first short message may perform one indexed SQLite lookup,
    then repeated router checks for the same user are served from RAM.
    """
    uid = int(user_id or 0)
    if uid <= 0:
        return ""
    now_mono = time.monotonic()
    cached = _PET_NAME_CACHE.get(uid)
    if cached is not None:
        cache_ttl = _PET_NAME_CACHE_TTL_SECONDS if str(cached[1] or "") else 5.0
        if now_mono - float(cached[0]) < cache_ttl:
            return str(cached[1] or "")
    init_social_db()
    with _connect() as con:
        row = _living_pet(con, uid)
    name = ""
    if row is not None and int(row["last_fed_at"] or 0) > _now() - PET_HUNGER_SECONDS:
        name = normalize_text(row["name"] or "")[:30]
    _PET_NAME_CACHE[uid] = (now_mono, name)
    return name


def parse_pet_call(user_id: int, text: Any) -> Optional[Dict[str, Any]]:
    """Resolve natural calls such as `رکس`, `رکس بیا`, `رکس خوبی؟`."""
    value = normalize_text(text)
    if not value or len(value) > 64 or len(value.split()) > 5:
        return None
    name = living_pet_name(int(user_id or 0))
    if not name:
        return None
    clean = re.sub(r"[!?؟،,.؛:]+", " ", value)
    clean = " ".join(clean.split()).lower()
    clean_name = " ".join(normalize_text(name).split()).lower()
    if clean == clean_name:
        return {"action": "pet_call", "call": "name", "name": name}
    suffix = clean[len(clean_name):].strip() if clean.startswith(clean_name) else ""
    if not suffix or clean[:len(clean_name)] != clean_name:
        return None
    if suffix in {"بیا", "بیا اینجا", "بیا پیشم"}:
        kind = "come"
    elif suffix in {"خوبی", "حالت خوبه", "چطوری", "چه طوری"}:
        kind = "how"
    elif suffix in {"کجایی", "کجائی"}:
        kind = "where"
    else:
        return None
    return {"action": "pet_call", "call": kind, "name": name}


def pet_call(user_id: int, call: str = "name") -> str:
    expire_hungry_pets()
    with _connect() as con:
        row = _living_pet(con, int(user_id))
    if row is None:
        _PET_NAME_CACHE.pop(int(user_id), None)
        return "🐾 پت زنده‌ای نداری. برای انتخاب بنویس: فروشگاه پت"
    name = str(row["name"] or row["breed"] or "پت")
    _PET_NAME_CACHE[int(user_id)] = (time.monotonic(), normalize_text(row["name"] or ""))
    happiness = int(row["happiness"] or 0)
    species = str(row["species"] or "")
    icon = {"سگ": "🐶", "گربه": "🐱", "طوطی": "🦜"}.get(species, "🐾")
    mode = str(call or "name")
    if mode == "come":
        return f"{icon} «{name}» با ذوق اومد پیشت. شادی: {happiness}/100"
    if mode == "how":
        mood = "سرحاله" if happiness >= 70 else ("بد نیست" if happiness >= 40 else "یکم بی حوصله ست")
        return f"{icon} «{name}» {mood}؛ شادی: {happiness}/100"
    if mode == "where":
        return f"{icon} «{name}» همین دور و بره و صداتو شنید."
    return f"{icon} «{name}» صداتو شنید و بهت نگاه کرد."


def buy_pet(user_id: int, pet_spec: str, discount_percent: int = 0) -> str:
    init_social_db()
    item = resolve_pet_catalog_item(pet_spec)
    if item is None:
        return "❌ این نژاد پیدا نشد. برای دیدن همه گزینه‌ها بنویس: فروشگاه پت"
    species, breed, base_price = item
    discount = max(0, min(70, int(discount_percent or 0)))
    price = max(1, int(round(int(base_price) * (100 - discount) / 100.0)))
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        if _living_pet(con, int(user_id)) is not None:
            con.rollback()
            return "🐾 الان یک پت زنده داری؛ اول از دوست فعلی‌ات مراقبت کن."
        account = _ensure_account(con, int(user_id))
        if int(account["balance"] or 0) < price:
            con.rollback()
            return f"💸 برای خرید {breed} به {_money(price)} نیاز داری؛ موجودی تو {_money(int(account['balance'] or 0))} است."
        new_balance = int(account["balance"]) - price
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, updated_at=? WHERE user_id=?",
            (new_balance, price, now, int(user_id)),
        )
        con.execute(
            "INSERT INTO social_pets (user_id, species, breed, purchase_price, status, happiness, "
            "last_fed_at, purchased_at) VALUES (?, ?, ?, ?, 'alive', 60, ?, ?)",
            (int(user_id), species, breed, price, now, now),
        )
        _ledger(con, int(user_id), -price, "pet_buy", f"{species}:{breed}")
        con.commit()
    _PET_NAME_CACHE.pop(int(user_id), None)
    return (
        f"🎉 یک {species} نژاد {breed} خریدی!\n"
        f"💳 هزینه: {_money(price)}" + (f" (تخفیف Premium {discount}٪)" if discount else "") + "\n"
        f"💰 موجودی: {_money(new_balance)}\n"
        "برای اسم‌گذاری بنویس: اسم پت [نام]\n"
        "یادت نره هر روز بهش غذا بدی 🐾"
    )


def expire_hungry_pets(limit: int = 100) -> int:
    init_social_db()
    deadline = _now() - PET_HUNGER_SECONDS
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute(
            "SELECT * FROM social_pets WHERE status='alive' AND last_fed_at <= ? ORDER BY last_fed_at ASC LIMIT ?",
            (deadline, max(1, int(limit))),
        ).fetchall()
        now = _now()
        for row in rows:
            con.execute("UPDATE social_pets SET status='dead', died_at=? WHERE pet_id=?", (now, int(row["pet_id"])))
            _PET_NAME_CACHE.pop(int(row["user_id"]), None)
            pet_name = str(row["name"] or row["breed"])
            _queue_notification(
                con,
                int(row["user_id"]),
                "🕯 تسلیت...\n"
                f"پتت «{pet_name}» چون بیشتر از ۲۴ ساعت غذا نخورد از دنیا رفت.\n"
                "برای دوست بعدی حتماً هر روز سر بزن و غذاش بده. 💔",
            )
        con.commit()
    return len(rows)


def pet_status(user_id: int) -> str:
    expire_hungry_pets()
    with _connect() as con:
        row = _living_pet(con, int(user_id))
    if row is None:
        return "🐾 هنوز پت زنده‌ای نداری. برای انتخاب بنویس: فروشگاه پت"
    remaining = max(0, int(row["last_fed_at"]) + PET_HUNGER_SECONDS - _now())
    name = str(row["name"] or "بدون اسم")
    return (
        "🐾 ZIVO | پت من\n━━━━━━━━━━━━━━━━━━\n"
        f"🏷 نام: {name}\n"
        f"🧬 نوع: {row['species']} — {row['breed']}\n"
        f"😊 شادی: {int(row['happiness'])}/100\n"
        f"🍗 فرصت غذا: {_duration(remaining)}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "غذا دادن: غذای پت\nبازی کردن: بازی با پت"
    )


def name_pet(user_id: int, name: str) -> str:
    clean = normalize_text(name)[:30]
    if not clean or not re.search(r"[A-Za-zآ-ی]", clean):
        return "✏️ یک اسم کوتاه و معتبر بعد از دستور بنویس؛ نمونه: اسم پت پشمک"
    expire_hungry_pets()
    with _connect() as con:
        row = _living_pet(con, int(user_id))
        if row is None:
            return "🐾 پت زنده‌ای برای اسم‌گذاری نداری."
        con.execute("UPDATE social_pets SET name=? WHERE pet_id=?", (clean, int(row["pet_id"])))
    _PET_NAME_CACHE[int(user_id)] = (time.monotonic(), clean)
    return f"🏷 اسم پتت شد «{clean}». حالا می‌تونی صداش کنی؛ مثلاً: {clean} بیا"


def feed_pet(user_id: int) -> str:
    expire_hungry_pets()
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        pet = _living_pet(con, int(user_id))
        if pet is None:
            con.rollback()
            return "🐾 پت زنده‌ای نداری. برای خرید بنویس: فروشگاه پت"
        account = _ensure_account(con, int(user_id))
        if int(account["balance"] or 0) < PET_FOOD_PRICE:
            con.rollback()
            return f"💸 برای غذای پت به {_money(PET_FOOD_PRICE)} نیاز داری."
        new_balance = int(account["balance"]) - PET_FOOD_PRICE
        happiness = min(100, int(pet["happiness"] or 0) + 5)
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, updated_at=? WHERE user_id=?",
            (new_balance, PET_FOOD_PRICE, now, int(user_id)),
        )
        con.execute(
            "UPDATE social_pets SET last_fed_at=?, happiness=? WHERE pet_id=?",
            (now, happiness, int(pet["pet_id"])),
        )
        _ledger(con, int(user_id), -PET_FOOD_PRICE, "pet_food", str(pet["pet_id"]))
        con.commit()
    return f"🍗 {pet['name'] or pet['breed']} غذاشو خورد و خوشحال شد!\n😊 شادی: {happiness}/100\n💰 موجودی: {_money(new_balance)}"


def play_with_pet(user_id: int) -> str:
    expire_hungry_pets()
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        pet = _living_pet(con, int(user_id))
        if pet is None:
            con.rollback()
            return "🐾 پت زنده‌ای نداری که باهاش بازی کنی."
        wait = PET_PLAY_COOLDOWN_SECONDS - (now - int(pet["last_played_at"] or 0))
        if wait > 0:
            con.rollback()
            return f"😴 پتت فعلاً خسته‌ست؛ {_duration(wait)} دیگه دوباره بازی کنید."
        happiness = min(100, int(pet["happiness"] or 0) + secrets.choice((8, 10, 12, 15)))
        con.execute(
            "UPDATE social_pets SET happiness=?, last_played_at=? WHERE pet_id=?",
            (happiness, now, int(pet["pet_id"])),
        )
        con.commit()
    return f"🎾 با {pet['name'] or pet['breed']} بازی کردی!\n😊 میزان شادی: {happiness}/100"


HOUSE_CATALOG: Dict[str, Tuple[str, str, int]] = {
    "teh-zaf": ("تهران", "زعفرانیه", 6200),
    "teh-ela": ("تهران", "الهیه", 5700),
    "teh-nia": ("تهران", "نیاوران", 5200),
    "teh-far": ("تهران", "فرمانیه", 4800),
    "esf-jol": ("اصفهان", "جلفا", 3300),
    "esf-mar": ("اصفهان", "مرداویج", 2900),
    "shz-gha": ("شیراز", "قصرالدشت", 3100),
    "msh-saj": ("مشهد", "سجاد", 2800),
    "ras-gol": ("رشت", "گلسار", 2400),
    "kish-sea": ("کیش", "ساحلی", 4500),
}


def _house_daily_factor(code: str, day: Optional[str] = None) -> float:
    key = day or datetime.now(_IRAN_TZ).strftime("%Y-%m-%d")
    digest = hashlib.sha256(f"ZIVO-HOUSE:{code}:{key}".encode("utf-8")).digest()
    wave = (int.from_bytes(digest[:2], "big") % 1301 - 650) / 10000.0
    return 1.0 + wave


def house_market_value(code: str, day: Optional[str] = None) -> int:
    item = HOUSE_CATALOG.get(str(code))
    if item is None:
        return 0
    return max(1, int(round(item[2] * _house_daily_factor(str(code), day))))


def house_shop_text() -> str:
    today = datetime.now(_IRAN_TZ)
    yesterday = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    lines = ["🏠 ZIVO | بازار روز خانه", "━━━━━━━━━━━━━━━━━━"]
    for code, (city, district, _base) in HOUSE_CATALOG.items():
        current = house_market_value(code)
        previous = house_market_value(code, yesterday)
        diff = current - previous
        icon = "📈" if diff > 0 else ("📉" if diff < 0 else "➖")
        percent = (diff / previous * 100.0) if previous else 0.0
        lines.append(f"{icon} {code} | {city}، {district} — {_money(current)} ({percent:+.1f}٪)")
    lines.extend(("━━━━━━━━━━━━━━━━━━", "نمونه خرید: خرید خانه teh-zaf", "قیمت‌ها هر روز تغییر می‌کنند و امکان سود یا ضرر وجود دارد."))
    return "\n".join(lines)


def buy_house(user_id: int, code_or_name: str) -> str:
    init_social_db()
    raw = normalize_text(code_or_name).lower()
    code = raw if raw in HOUSE_CATALOG else ""
    if not code:
        for candidate, (city, district, _base) in HOUSE_CATALOG.items():
            if raw in {normalize_text(city).lower(), normalize_text(district).lower(), normalize_text(f"{city} {district}").lower()}:
                code = candidate
                break
    if not code:
        return "❌ این خانه در فروشگاه پیدا نشد. بنویس: فروشگاه خانه"
    city, district, _ = HOUSE_CATALOG[code]
    price = house_market_value(code)
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        account = _ensure_account(con, int(user_id))
        if int(account["balance"] or 0) < price:
            con.rollback()
            return f"💸 قیمت خانه {_money(price)} است و موجودی تو {_money(int(account['balance'] or 0))}."
        new_balance = int(account["balance"]) - price
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, updated_at=? WHERE user_id=?",
            (new_balance, price, now, int(user_id)),
        )
        cur = con.execute(
            "INSERT INTO social_houses (user_id, house_code, purchase_price, purchased_at, status) "
            "VALUES (?, ?, ?, ?, 'owned')",
            (int(user_id), code, price, now),
        )
        ownership = int(cur.lastrowid)
        _ledger(con, int(user_id), -price, "house_buy", str(ownership))
        con.commit()
    return f"🏡 مبارکه! مالک جدید خانه {city}، {district} شدی.\n🧾 شناسه دارایی: {ownership}\n💳 قیمت خرید: {_money(price)}\n💰 موجودی: {_money(new_balance)}"


def my_houses_text(user_id: int) -> str:
    init_social_db()
    with _connect() as con:
        rows = con.execute(
            "SELECT * FROM social_houses WHERE user_id=? AND status IN ('owned','listed') ORDER BY ownership_id DESC",
            (int(user_id),),
        ).fetchall()
    if not rows:
        return "🏠 هنوز خانه‌ای نداری. برای دیدن بازار بنویس: فروشگاه خانه"
    lines = ["🏘 ZIVO | خانه‌های من", "━━━━━━━━━━━━━━━━━━"]
    for row in rows:
        code = str(row["house_code"])
        city, district, _ = HOUSE_CATALOG.get(code, ("نامشخص", code, 0))
        current = house_market_value(code)
        profit = current - int(row["purchase_price"])
        icon = "📈" if profit >= 0 else "📉"
        state = "در آگهی" if str(row["status"]) == "listed" else "ملک شخصی"
        lines.append(f"#{row['ownership_id']} | {city}، {district} | {state}\n  خرید {_money(int(row['purchase_price']))} → ارزش {_money(current)} {icon} {profit:+,}")
    lines.append("فروش فوری: فروش فوری خانه [شناسه]")
    lines.append("ثبت آگهی: فروش خانه [شناسه] [قیمت]")
    return "\n".join(lines)


def instant_sell_house(user_id: int, ownership_id: int) -> str:
    init_social_db()
    now = _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM social_houses WHERE ownership_id=? AND user_id=? AND status='owned'",
            (int(ownership_id), int(user_id)),
        ).fetchone()
        if row is None:
            con.rollback()
            return "❌ این شناسه خانه متعلق به تو نیست یا داخل آگهی قرار دارد."
        code = str(row["house_code"])
        value = house_market_value(code)
        account = _ensure_account(con, int(user_id))
        new_balance = int(account["balance"]) + value
        con.execute("UPDATE social_houses SET status='sold_system' WHERE ownership_id=?", (int(ownership_id),))
        con.execute(
            "UPDATE social_meow_accounts SET balance=?, total_earned=total_earned+?, updated_at=? WHERE user_id=?",
            (new_balance, value, now, int(user_id)),
        )
        _ledger(con, int(user_id), value, "house_sell_system", str(ownership_id))
        con.commit()
    profit = value - int(row["purchase_price"])
    city, district, _ = HOUSE_CATALOG.get(code, ("نامشخص", code, 0))
    return f"✅ خانه {city}، {district} به قیمت روز فروخته شد.\n💵 دریافتی: {_money(value)}\n{'📈 سود' if profit >= 0 else '📉 ضرر'}: {profit:+,} میو\n💰 موجودی: {_money(new_balance)}"


def list_house(user_id: int, ownership_id: int, asking_price: int) -> str:
    init_social_db()
    price = int(asking_price)
    if price < 20:
        return "⛔ قیمت آگهی باید حداقل ۲۰ میو باشد."
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM social_houses WHERE ownership_id=? AND user_id=? AND status='owned'",
            (int(ownership_id), int(user_id)),
        ).fetchone()
        if row is None:
            con.rollback()
            return "❌ این خانه متعلق به تو نیست یا قبلاً برای فروش گذاشته شده."
        cur = con.execute(
            "INSERT INTO social_house_listings (ownership_id, seller_id, asking_price, status, created_at) "
            "VALUES (?, ?, ?, 'open', ?)",
            (int(ownership_id), int(user_id), price, _now()),
        )
        listing_id = int(cur.lastrowid)
        con.execute("UPDATE social_houses SET status='listed' WHERE ownership_id=?", (int(ownership_id),))
        con.commit()
    city, district, _ = HOUSE_CATALOG.get(str(row["house_code"]), ("نامشخص", str(row["house_code"]), 0))
    return f"📣 آگهی خانه ثبت شد.\n🏠 {city}، {district}\n🧾 شماره آگهی: {listing_id}\n💰 قیمت: {_money(price)}\nبرای لغو: لغو فروش خانه {listing_id}"


def house_marketplace_text() -> str:
    init_social_db()
    with _connect() as con:
        rows = con.execute(
            "SELECT l.*, h.house_code, h.purchase_price FROM social_house_listings l "
            "JOIN social_houses h ON h.ownership_id=l.ownership_id "
            "WHERE l.status='open' ORDER BY l.listing_id DESC LIMIT 25"
        ).fetchall()
    if not rows:
        return "🏘 فعلاً آگهی خانه‌ای از کاربران وجود ندارد."
    lines = ["🏘 ZIVO | بازار خانه کاربران", "━━━━━━━━━━━━━━━━━━"]
    for row in rows:
        code = str(row["house_code"])
        city, district, _ = HOUSE_CATALOG.get(code, ("نامشخص", code, 0))
        lines.append(f"#{row['listing_id']} | {city}، {district} | {_money(int(row['asking_price']))} | ارزش روز {_money(house_market_value(code))}")
    lines.append("خرید: خرید آگهی خانه [شماره آگهی]")
    return "\n".join(lines)


def cancel_house_listing(user_id: int, listing_id: int) -> str:
    init_social_db()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM social_house_listings WHERE listing_id=? AND seller_id=? AND status='open'",
            (int(listing_id), int(user_id)),
        ).fetchone()
        if row is None:
            con.rollback()
            return "❌ آگهی باز و متعلق به تو پیدا نشد."
        con.execute("UPDATE social_house_listings SET status='cancelled', finished_at=? WHERE listing_id=?", (_now(), int(listing_id)))
        con.execute("UPDATE social_houses SET status='owned' WHERE ownership_id=?", (int(row["ownership_id"]),))
        con.commit()
    return "✅ آگهی لغو شد و خانه دوباره به فهرست دارایی‌هایت برگشت."


def buy_listed_house(user_id: int, listing_id: int) -> str:
    init_social_db()
    buyer, now = int(user_id), _now()
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT l.*, h.house_code FROM social_house_listings l JOIN social_houses h "
            "ON h.ownership_id=l.ownership_id WHERE l.listing_id=? AND l.status='open' AND h.status='listed'",
            (int(listing_id),),
        ).fetchone()
        if row is None:
            con.rollback()
            return "❌ این آگهی دیگر باز نیست یا فروخته شده."
        seller, price = int(row["seller_id"]), int(row["asking_price"])
        if buyer == seller:
            con.rollback()
            return "😄 نمی‌تونی خانه خودت رو از خودت بخری."
        buyer_row = _ensure_account(con, buyer)
        seller_row = _ensure_account(con, seller)
        if int(buyer_row["balance"] or 0) < price:
            con.rollback()
            return f"💸 برای خرید به {_money(price)} نیاز داری؛ موجودی تو {_money(int(buyer_row['balance'] or 0))} است."
        buyer_balance = int(buyer_row["balance"]) - price
        seller_balance = int(seller_row["balance"]) + price
        con.execute("UPDATE social_meow_accounts SET balance=?, total_spent=total_spent+?, updated_at=? WHERE user_id=?", (buyer_balance, price, now, buyer))
        con.execute("UPDATE social_meow_accounts SET balance=?, total_earned=total_earned+?, updated_at=? WHERE user_id=?", (seller_balance, price, now, seller))
        con.execute("UPDATE social_houses SET user_id=?, purchase_price=?, purchased_at=?, status='owned' WHERE ownership_id=?", (buyer, price, now, int(row["ownership_id"])))
        con.execute("UPDATE social_house_listings SET buyer_id=?, status='sold', finished_at=? WHERE listing_id=?", (buyer, now, int(listing_id)))
        _ledger(con, buyer, -price, "house_market_buy", str(listing_id))
        _ledger(con, seller, price, "house_market_sell", str(listing_id))
        code = str(row["house_code"])
        city, district, _ = HOUSE_CATALOG.get(code, ("نامشخص", code, 0))
        _queue_notification(con, seller, f"🏠 خانه‌ات در {city}، {district} فروخته شد.\n💵 مبلغ واریزی: {_money(price)}\n💰 موجودی جدید: {_money(seller_balance)}")
        con.commit()
    return f"🏡 خرید انجام شد؛ مالک جدید خانه {city}، {district} شمایی!\n💳 از حسابت کم شد: {_money(price)}\n💰 موجودی: {_money(buyer_balance)}"


def profile_section(user_id: int) -> str:
    init_social_db()
    expire_hungry_pets()
    with _connect() as con:
        account = _ensure_account(con, int(user_id))
        pet = _living_pet(con, int(user_id))
        houses = con.execute(
            "SELECT COUNT(*) AS c FROM social_houses WHERE user_id=? AND status IN ('owned','listed')",
            (int(user_id),),
        ).fetchone()
    pet_text = f"{pet['species']} {pet['breed']} ({pet['name'] or 'بدون اسم'})" if pet else "ندارد"
    return (
        "🐾 دارایی‌های سرگرمی:\n"
        f"● موجودی: {_money(int(account['balance'] or 0))}\n"
        f"● پت: {pet_text}\n"
        f"● تعداد خانه: {int(houses['c'] or 0)}\n"
        f"● کل میوی به‌دست‌آمده: {_money(int(account['total_earned'] or 0))}"
    )


CITY_COORDS: Dict[str, Tuple[float, float, str]] = {
    "تهران": (35.6892, 51.3890, "تهران"), "کرج": (35.8400, 50.9391, "کرج"),
    "رشت": (37.2808, 49.5832, "رشت"), "ساری": (36.5659, 53.0586, "ساری"),
    "گرگان": (36.8456, 54.4393, "گرگان"), "تبریز": (38.0800, 46.2919, "تبریز"),
    "ارومیه": (37.5527, 45.0761, "ارومیه"), "اردبیل": (38.2498, 48.2933, "اردبیل"),
    "زنجان": (36.6736, 48.4787, "زنجان"), "قزوین": (36.2688, 50.0041, "قزوین"),
    "قم": (34.6416, 50.8746, "قم"), "اراک": (34.0954, 49.7013, "اراک"),
    "همدان": (34.7992, 48.5146, "همدان"), "سنندج": (35.3219, 46.9862, "سنندج"),
    "کرمانشاه": (34.3142, 47.0650, "کرمانشاه"), "خرم آباد": (33.4878, 48.3558, "خرم‌آباد"),
    "خرم‌آباد": (33.4878, 48.3558, "خرم‌آباد"), "ایلام": (33.6374, 46.4227, "ایلام"),
    "اصفهان": (32.6546, 51.6680, "اصفهان"), "شهرکرد": (32.3256, 50.8644, "شهرکرد"),
    "یاسوج": (30.6684, 51.5880, "یاسوج"), "شیراز": (29.5918, 52.5837, "شیراز"),
    "بوشهر": (28.9234, 50.8203, "بوشهر"), "اهواز": (31.3183, 48.6706, "اهواز"),
    "بندرعباس": (27.1832, 56.2666, "بندرعباس"), "کرمان": (30.2839, 57.0834, "کرمان"),
    "یزد": (31.8974, 54.3569, "یزد"), "بیرجند": (32.8649, 59.2262, "بیرجند"),
    "مشهد": (36.2605, 59.6168, "مشهد"), "بجنورد": (37.4747, 57.3290, "بجنورد"),
    "سمنان": (35.5769, 53.3921, "سمنان"), "زاهدان": (29.4963, 60.8629, "زاهدان"),
    "کیش": (26.5320, 53.9800, "کیش"), "چالوس": (36.6550, 51.4204, "چالوس"),
    "رامسر": (36.9031, 50.6580, "رامسر"), "کاشان": (33.9850, 51.4100, "کاشان"),
}


def distance_text(origin: str, destination: str) -> str:
    first = CITY_COORDS.get(normalize_text(origin))
    second = CITY_COORDS.get(normalize_text(destination))
    if first is None or second is None:
        missing = origin if first is None else destination
        return f"🗺 شهر «{missing}» در فهرست فعلی پیدا نشد؛ نام مرکز شهر را کامل بنویس."
    lat1, lon1, name1 = first
    lat2, lon2, name2 = second
    if name1 == name2:
        return "📍 مبدا و مقصد یکی هستند؛ فاصله صفر کیلومتره."
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    direct = radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    # Mountain/coastal routes are less direct.  This is clearly labelled as an
    # estimate and avoids pretending to be live turn-by-turn navigation.
    road_factor = 1.22 if direct < 500 else 1.18
    road = max(1, int(round(direct * road_factor)))
    hours = road / 78.0
    whole_h = int(hours)
    minutes = int(round((hours - whole_h) * 60 / 5) * 5)
    if minutes >= 60:
        whole_h += 1
        minutes = 0
    duration = f"حدود {whole_h} ساعت" + (f" و {minutes} دقیقه" if minutes else "")
    return (
        "🚗 ZIVO | فاصله شهرها\n━━━━━━━━━━━━━━━━━━\n"
        f"📍 مبدا: {name1}\n🏁 مقصد: {name2}\n"
        f"🛣 فاصله تقریبی جاده‌ای: {road:,} کیلومتر\n"
        f"⏱ زمان تقریبی با ماشین: {duration}\n"
        f"📏 فاصله مستقیم: {int(round(direct)):,} کیلومتر\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "زمان و مسیر تقریبی‌اند و با جاده، ترافیک و توقف‌ها تغییر می‌کنند."
    )


def _extract_tgju_value(page: str, field: str) -> str:
    patterns = (
        rf'data-col=["\']info\.{re.escape(field)}["\'][^>]*>([^<]+)<',
        rf'info\.{re.escape(field)}[^>]*>\s*([^<]+)<',
        rf'"{re.escape(field)}"\s*:\s*"?([^",}}]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _numeric(value: Any) -> float:
    clean = normalize_text(value).replace(",", "").replace("٪", "").replace("%", "")
    clean = clean.replace("٬", "").replace("٫", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", clean)
    return float(match.group(0)) if match else 0.0


def _tgju_history_from_page(page: str, *, limit: int = 30) -> List[Dict[str, Any]]:
    """Extract TGJU's published daily *closing* observations.

    TGJU's current archive table is ordered open, low, high, close, change,
    percentage, Gregorian date, Persian date. Older mirrored markup can place
    the Persian date first and close fifth. A row is accepted only when one of
    those layouts is verified. This intentionally returns no points when the
    archive markup cannot be verified; callers must never manufacture a chart.
    """

    observations: List[Dict[str, Any]] = []
    seen_dates: set[str] = set()
    bounded_limit = max(2, min(120, int(limit or 30)))
    for raw_row in re.findall(r"<tr\b[^>]*>(.*?)</tr\s*>", str(page or ""), flags=re.I | re.S):
        raw_cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", raw_row, flags=re.I | re.S)
        if len(raw_cells) < 5:
            continue
        cells = [
            normalize_text(
                html.unescape(
                    re.sub(r"<[^>]+>", " ", re.sub(r"<script\b[^>]*>.*?</script>", " ", cell, flags=re.I | re.S))
                )
            )
            for cell in raw_cells
        ]
        date_pattern = r"(?:13|14|15)\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])"
        date_index = next(
            (index for index, cell in enumerate(cells) if re.fullmatch(date_pattern, cell)),
            -1,
        )
        if date_index < 0:
            continue
        date_value = cells[date_index]
        # TGJU's live archive currently publishes open/low/high/close/.../date,
        # while older and mirrored markup can place the date first and close
        # fifth. Accept only those two verified layouts.
        close_index = 4 if date_index == 0 and len(cells) >= 5 else 3
        if close_index >= len(cells):
            continue
        close_rial = _numeric(cells[close_index])
        if close_rial <= 0 or date_value in seen_dates:
            continue
        seen_dates.add(date_value)
        observations.append({"timestamp": date_value, "toman": close_rial / 10.0})
        if len(observations) >= bounded_limit:
            break
    # Public archive rows are newest-first; cards are easier to read and draw
    # when their provider observations are chronological.
    observations.reverse()
    return observations


def _tgju_asset(slug: str) -> Dict[str, Any]:
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ZIVO-Market/1.0)",
        "Accept-Language": "fa-IR,fa;q=0.9",
    }

    http_attempts = 0

    def read_page(url: str) -> str:
        nonlocal http_attempts
        if http_attempts >= _MARKET_MAX_HTTP_ATTEMPTS_PER_ASSET:
            raise RuntimeError(f"TGJU_HTTP_ATTEMPT_BUDGET_EXHAUSTED:{slug}")
        http_attempts += 1
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=_MARKET_HTTP_TIMEOUT_SECONDS) as response:
            return response.read(1_500_000).decode("utf-8", errors="ignore")

    history: List[Dict[str, Any]] = []
    page = ""
    profile_page = ""
    try:
        page = read_page(f"https://www.tgju.org/profile/{slug}/history")
        history = _tgju_history_from_page(page)
    except Exception:
        profile_page = read_page(f"https://www.tgju.org/profile/{slug}")
        page = profile_page
    last = _numeric(_extract_tgju_value(page, "last_trade.PDrCotVal"))
    change = _numeric(_extract_tgju_value(page, "change_percent"))
    time_value = _extract_tgju_value(page, "time")
    # TGJU has changed its HTML attributes more than once.  Keep a visible-
    # text fallback so the public profile pages remain usable if data-col keys
    # are renamed while the human-readable table is still present.
    visible = html.unescape(re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", page, flags=re.I | re.S))
    visible = " ".join(re.sub(r"<[^>]+>", " ", visible).split())
    if last <= 0:
        current_match = re.search(
            r"نرخ\s*فعلی\s*:*\s*([0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬]*)",
            visible,
        )
        if current_match:
            last = _numeric(current_match.group(1).replace("٬", ","))
    if not change:
        change_match = re.search(
            r"درصد\s*تغییر\s*نسبت\s*به\s*روز\s*گذشته\s*[:|]*\s*([+\-]?[0-9۰-۹٠-٩.,]+)\s*[%٪]",
            visible,
        )
        if change_match:
            change = _numeric(change_match.group(1))
    if not time_value:
        time_match = re.search(r"زمان\s*ثبت\s*آخرین\s*نرخ\s*[:|]*\s*([^|]{1,30})", visible)
        if time_match:
            time_value = normalize_text(time_match.group(1))[:30]
    if last <= 0 and not profile_page:
        # Some archive responses omit the data-col block while keeping the
        # historical table. Use the ordinary profile only for the current
        # quote, preserving the verified archive observations already parsed.
        profile_page = read_page(f"https://www.tgju.org/profile/{slug}")
    if last <= 0 and profile_page:
        last = _numeric(_extract_tgju_value(profile_page, "last_trade.PDrCotVal"))
        change = _numeric(_extract_tgju_value(profile_page, "change_percent"))
        time_value = _extract_tgju_value(profile_page, "time") or time_value
        profile_visible = html.unescape(
            re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", profile_page, flags=re.I | re.S)
        )
        profile_visible = " ".join(re.sub(r"<[^>]+>", " ", profile_visible).split())
        if last <= 0:
            profile_match = re.search(
                r"نرخ\s*فعلی\s*:*\s*([0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬]*)",
                profile_visible,
            )
            if profile_match:
                last = _numeric(profile_match.group(1).replace("٬", ","))
    if last <= 0:
        raise ValueError(f"TGJU_VALUE_MISSING:{slug}")
    return {
        "price_rial": last,
        "change": change,
        "time": time_value,
        "history": history,
    }


def _fresh_tgju_market_snapshot() -> Dict[str, Any]:
    """Fetch one all-or-nothing four-asset snapshot from TGJU."""

    assets: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(_TGJU_MARKET_SLUGS), thread_name_prefix="zivo-market") as pool:
        pending = {
            pool.submit(_tgju_asset, slug): (asset, slug)
            for asset, slug in _TGJU_MARKET_SLUGS
        }
        for future in as_completed(pending):
            asset, _slug = pending[future]
            assets[asset] = future.result()

    required = {asset for asset, _slug in _TGJU_MARKET_SLUGS}
    if set(assets) != required:
        raise ValueError("TGJU_MARKET_SNAPSHOT_INCOMPLETE")

    source = "شبکه اطلاع رسانی طلا و ارز (TGJU)"
    updated_values = [
        str(assets[asset].get("time") or "").strip()
        for asset, _slug in _TGJU_MARKET_SLUGS
        if str(assets[asset].get("time") or "").strip()
    ]
    updated = updated_values[0] if updated_values else ""
    quotes: Dict[str, Dict[str, Any]] = {}
    for asset, _slug in _TGJU_MARKET_SLUGS:
        item = assets[asset]
        history = list(item.get("history") or [])
        quote = {
            # TGJU explicitly publishes these four domestic-market values in
            # rial.  The provider boundary is the single authoritative place
            # where they are converted to toman.
            "toman": float(item["price_rial"]) / 10.0,
            "change_percent": float(item.get("change") or 0.0),
            "history": history,
            "history_verified": len(history) >= 2,
            "source": source,
            "updated_at": str(item.get("time") or updated),
        }
        quotes[asset] = quote

    snapshot: Dict[str, Any] = {
        "source": source,
        "updated_at": updated,
        "quotes": quotes,
        "cache_status": "live",
        "stale": False,
    }
    # Keep the existing flat schema available to older callers while the
    # structured quotes carry verified history for the new card renderer.
    snapshot.update(
        {
            "usd_toman": quotes["usd"]["toman"],
            "usd_change": quotes["usd"]["change_percent"],
            "eur_toman": quotes["eur"]["toman"],
            "eur_change": quotes["eur"]["change_percent"],
            "gbp_toman": quotes["gbp"]["toman"],
            "gbp_change": quotes["gbp"]["change_percent"],
            "gold_toman": quotes["gold18"]["toman"],
            "gold_change": quotes["gold18"]["change_percent"],
            "updated": updated,
        }
    )
    return snapshot


def market_snapshot_data() -> Dict[str, Any]:
    """Return live TGJU rates for USD/EUR/GBP/18K gold, already in toman.

    A complete healthy result is cached for 120 seconds.  On a later provider
    failure the last complete healthy result is returned and explicitly marked
    stale; if no healthy result has ever been obtained, the provider error is
    propagated so callers can show their normal unavailable-data response.
    """

    global _MARKET_SNAPSHOT_CACHE, _MARKET_SNAPSHOT_FAILURE_UNTIL
    now_mono = time.monotonic()
    with _MARKET_SNAPSHOT_LOCK:
        cached_at, cached_snapshot = _MARKET_SNAPSHOT_CACHE
        if cached_snapshot and now_mono - cached_at < _MARKET_CACHE_SECONDS:
            return deepcopy(cached_snapshot)
        if now_mono < _MARKET_SNAPSHOT_FAILURE_UNTIL:
            if cached_snapshot:
                fallback = deepcopy(cached_snapshot)
                fallback["cache_status"] = "stale"
                fallback["stale"] = True
                stale_source = (
                    str(fallback.get("source") or "TGJU")
                    + " | آخرین داده سالم؛ منبع زنده موقتاً در دسترس نیست"
                )
                fallback["source"] = stale_source
                quotes = fallback.get("quotes")
                if isinstance(quotes, dict):
                    for quote in quotes.values():
                        if isinstance(quote, dict):
                            quote["source"] = stale_source
                return fallback
            raise RuntimeError("TGJU_MARKET_FAILURE_COOLDOWN")
        try:
            snapshot = _fresh_tgju_market_snapshot()
        except Exception:
            _MARKET_SNAPSHOT_FAILURE_UNTIL = (
                time.monotonic() + _MARKET_FAILURE_COOLDOWN_SECONDS
            )
            if cached_snapshot:
                fallback = deepcopy(cached_snapshot)
                fallback["cache_status"] = "stale"
                fallback["stale"] = True
                stale_source = (
                    str(fallback.get("source") or "TGJU")
                    + " | آخرین داده سالم؛ منبع زنده موقتاً در دسترس نیست"
                )
                fallback["source"] = stale_source
                quotes = fallback.get("quotes")
                if isinstance(quotes, dict):
                    for quote in quotes.values():
                        if isinstance(quote, dict):
                            quote["source"] = stale_source
                return fallback
            raise
        _MARKET_SNAPSHOT_FAILURE_UNTIL = 0.0
        _MARKET_SNAPSHOT_CACHE = (now_mono, deepcopy(snapshot))
        return deepcopy(snapshot)


def _arzhaam_market(api_key: str) -> Dict[str, Any]:
    request = urllib.request.Request(
        "https://arzhaam.ir/api/rates/latest",
        headers={"X-App-Key": api_key, "Accept": "application/json", "User-Agent": "ZIVO-Market/1.0"},
    )
    with urllib.request.urlopen(request, timeout=7) as response:
        payload = json.loads(response.read(1_000_000).decode("utf-8"))
    rates = {str(item.get("assetId")): item for item in payload.get("rates") or [] if isinstance(item, dict)}
    usd, gold = rates.get("usd"), rates.get("gold_18")
    if not usd or not gold:
        raise ValueError("ARZHAAM_ASSET_MISSING")
    return {
        "usd_toman": int(float(usd.get("price") or 0)), "usd_change": float(usd.get("changePercent24h") or 0),
        "gold_toman": int(float(gold.get("price") or 0)), "gold_change": float(gold.get("changePercent24h") or 0),
        "updated": str(gold.get("updatedAt") or usd.get("updatedAt") or ""), "source": "ارزهام",
    }


def market_price_text() -> str:
    global _MARKET_CACHE
    now_mono = time.monotonic()
    with _MARKET_LOCK:
        if _MARKET_CACHE[1] and now_mono - _MARKET_CACHE[0] < 120:
            return _MARKET_CACHE[1]
        try:
            api_key = str(os.getenv("ARZHAM_API_KEY", "") or "").strip()
            if api_key:
                data = _arzhaam_market(api_key)
            else:
                usd = _tgju_asset("price_dollar_rl")
                gold = _tgju_asset("geram18")
                data = {
                    "usd_toman": int(round(usd["price_rial"] / 10.0)),
                    "usd_change": float(usd["change"]),
                    "gold_toman": int(round(gold["price_rial"] / 10.0)),
                    "gold_change": float(gold["change"]),
                    "updated": gold["time"] or usd["time"],
                    "source": "شبکه اطلاع‌رسانی طلا و ارز",
                }
            def trend(change: float) -> str:
                return "📈 رشد" if change > 0 else ("📉 کاهش" if change < 0 else "➖ بدون تغییر")
            text = (
                "💱 ZIVO | قیمت بازار ایران\n━━━━━━━━━━━━━━━━━━\n"
                f"💵 دلار آزاد: {int(data['usd_toman']):,} تومان\n"
                f"{trend(float(data['usd_change']))}: {abs(float(data['usd_change'])):.2f}٪\n\n"
                f"🥇 طلای ۱۸ عیار (هر گرم): {int(data['gold_toman']):,} تومان\n"
                f"{trend(float(data['gold_change']))}: {abs(float(data['gold_change'])):.2f}٪\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🕒 بروزرسانی: {data['updated'] or 'لحظاتی پیش'}\n"
                f"📡 منبع: {data['source']}\n"
                "این قیمت اطلاع‌رسانی است و ممکن است با نرخ معامله تفاوت جزئی داشته باشد."
            )
        except Exception:
            if _MARKET_CACHE[1]:
                return _MARKET_CACHE[1] + "\n⚠️ منبع زنده موقتاً قطع است؛ این آخرین پاسخ کش‌شده است."
            text = "⚠️ منبع زنده قیمت دلار و طلا موقتاً در دسترس نیست؛ چند دقیقه دیگه دوباره امتحان کن."
        _MARKET_CACHE = (now_mono, text)
        return text


def parse_social_command(text: Any, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    value = normalize_text(text)
    low = value.lower()
    if low in {"بازی دوز", "دوز بازی", "شروع دوز"}:
        return {"action": "ttt_start"}
    if low in {"پیوستن دوز", "ورود دوز", "پیوستن به دوز"}:
        return {"action": "ttt_join"}
    if low in {"لغو دوز", "پایان دوز"}:
        return {"action": "ttt_cancel"}
    if low in {"وضعیت دوز", "دوز"}:
        return {"action": "ttt_status"}
    match = re.fullmatch(r"دوز\s+([1-9])", low)
    if match:
        return {"action": "ttt_move", "cell": int(match.group(1))}
    if low in {"شیپ", "شیپ کن", "ship"}:
        return {"action": "ship"}
    if low in {"قیمت", "قیمت دلار", "قیمت طلا", "دلار", "طلا", "قیمت دلار و طلا", "قیمت طلا و دلار"}:
        return {"action": "market"}
    match = re.fullmatch(r"فاصله\s+(.+?)\s+(?:تا|به)\s+(.+)", value)
    if match:
        return {"action": "distance", "origin": match.group(1), "destination": match.group(2)}
    # Natural meow/howl aliases all share the same durable 5-minute claim
    # cooldown, so stretched spelling cannot be used to farm extra rewards.
    if re.fullmatch(r"میو{1,24}", low) or low in {
        "میو هاپ", "میوهاپ", "زوزه", "زوزه کشیدن", "زوزه بکش",
        "آوو", "آووو", "آوووو", "اَووو",
    }:
        return {"action": "meow_claim"}
    if low in {"موجودی", "موجودی میو", "دارایی من", "پروفایل میو", "وضعیت میو"}:
        return {"action": "meow_profile"}
    match = re.fullmatch(r"(?:انتقال(?:\s+میو)?|انتقال میو)\s+(\d+)(?:\s+(.+))?", value)
    if match:
        return {"action": "transfer_prepare", "amount": int(match.group(1)), "target": (match.group(2) or "").strip()}
    if low in {"تایید انتقال", "تأیید انتقال"}:
        return {"action": "transfer_confirm"}
    if low in {"لغو انتقال", "انصراف انتقال"}:
        return {"action": "transfer_cancel"}
    match = re.fullmatch(r"بازی\s+سر\s+(\d+)", value)
    if match:
        return {"action": "wager_start", "stake": int(match.group(1))}
    if low in {"تایید بازی", "تأیید بازی", "پیوستن بازی"}:
        return {"action": "wager_accept"}
    if low in {"لغو بازی", "انصراف بازی"}:
        return {"action": "wager_cancel"}
    if low in {"فروشگاه پت", "لیست پت", "لیست پت ها", "پت ها"}:
        return {"action": "pet_shop"}
    match = re.fullmatch(r"خرید\s+پت\s+(.+)", value)
    if match:
        return {"action": "pet_buy", "spec": match.group(1)}
    if low in {"پت من", "وضعیت پت", "پتم"}:
        return {"action": "pet_status"}
    match = re.fullmatch(r"اسم\s+پت\s+(.+)", value)
    if match:
        return {"action": "pet_name", "name": match.group(1)}
    if low in {"غذای پت", "غذا پت", "غذا دادن پت", "خرید غذای پت"}:
        return {"action": "pet_feed"}
    if low in {"بازی با پت", "بازی پت"}:
        return {"action": "pet_play"}
    if low in {"فروشگاه خانه", "بازار روز خانه", "قیمت خانه"}:
        return {"action": "house_shop"}
    if low in {"خانه های من", "خانه‌های من", "خونه های من", "املاک من"}:
        return {"action": "house_mine"}
    if low in {"بازار خانه", "آگهی خانه", "اگهی خانه"}:
        return {"action": "house_market"}
    match = re.fullmatch(r"خرید\s+آگهی\s+خانه\s+(\d+)", value)
    if match:
        return {"action": "house_buy_listing", "listing_id": int(match.group(1))}
    match = re.fullmatch(r"خرید\s+خانه\s+(.+)", value)
    if match:
        return {"action": "house_buy", "spec": match.group(1)}
    match = re.fullmatch(r"فروش\s+فوری\s+خانه\s+(\d+)", value)
    if match:
        return {"action": "house_sell_instant", "ownership_id": int(match.group(1))}
    match = re.fullmatch(r"فروش\s+خانه\s+(\d+)\s+(\d+)", value)
    if match:
        return {"action": "house_list", "ownership_id": int(match.group(1)), "price": int(match.group(2))}
    match = re.fullmatch(r"لغو\s+فروش\s+خانه\s+(\d+)", value)
    if match:
        return {"action": "house_cancel_listing", "listing_id": int(match.group(1))}
    if user_id is not None:
        pet_call_command = parse_pet_call(int(user_id), value)
        if pet_call_command is not None:
            return pet_call_command
    return None


SOCIAL_COMMAND_HEADS = frozenset({
    "بازی", "دوز", "پیوستن", "لغو", "وضعیت", "شیپ", "ship", "قیمت", "دلار", "طلا", "فاصله",
    "میو", "میوو", "میووو", "موجودی", "دارایی", "پروفایل", "انتقال", "تایید", "تأیید",
    "فروشگاه", "خرید", "اسم", "غذای", "غذا", "پت", "خانه", "خانه‌های", "خونه", "املاک", "بازار", "آگهی", "اگهی",
})


def social_help_text() -> str:
    return (
        "🎮 ZIVO | راهنمای سرگرمی‌های جدید\n━━━━━━━━━━━━━━━━━━\n"
        "دوز: بازی دوز | پیوستن دوز | دوز 1 | لغو دوز\n"
        "مهره‌ها: سازنده ❌ قرمز | بازیکن دوم 🟢 سبز\n"
        "شیپ فعال‌ها: شیپ\n"
        "بازار واقعی: قیمت دلار و طلا\n"
        "فاصله شهرها: فاصله تهران تا رشت\n\n"
        "🐾 اقتصاد میو\n"
        "میو | موجودی میو\n"
        "انتقال میو 50 (با ریپلای یا @username)\n"
        "تایید انتقال | لغو انتقال\n"
        "بازی سر 20 | تایید بازی | لغو بازی\n\n"
        "🐶 پت و خانه\n"
        "فروشگاه پت | خرید پت سگ هاسکی | اسم پت رکس\n"
        "صدا زدن پت: رکس | رکس بیا | رکس خوبی؟\n"
        "غذای پت | بازی با پت | پت من\n"
        "فروشگاه خانه | خرید خانه teh-zaf | خانه های من\n"
        "بازار خانه | فروش خانه 1 3000 | خرید آگهی خانه 1"
    )


def admin_adjust_meow_users(
    user_ids: Iterable[int], delta: int, *, created_by: int = 0, scope: str = "", target_ref: str = ""
) -> Dict[str, Any]:
    """Audited admin add/deduct. Deductions never make a wallet negative."""
    init_social_db()
    requested = int(delta)
    if requested == 0 or abs(requested) > ADMIN_GIFT_MAX_MEOW:
        raise ValueError("ADMIN_MEOW_ADJUST_OUT_OF_RANGE")
    targets = sorted({int(uid) for uid in user_ids if int(uid or 0) > 0 and int(uid or 0) not in _BOT_USER_IDS})
    now = _now()
    result = {"adjustment_id": 0, "targets": len(targets), "success": 0, "skipped": 0, "failed": 0, "requested_delta": requested, "actual_delta": 0}
    with _connect() as con:
        con.execute("BEGIN IMMEDIATE")
        cur = con.execute(
            "INSERT INTO social_admin_meow_adjustments(created_by,scope,target_ref,requested_delta,total_targets,created_at) VALUES(?,?,?,?,?,?)",
            (int(created_by or 0), str(scope)[:40], str(target_ref)[:120], requested, len(targets), now),
        )
        aid = int(cur.lastrowid or 0); result["adjustment_id"] = aid
        for uid in targets:
            try:
                account = _ensure_account(con, uid); before = int(account["balance"] or 0)
                unlimited = con.execute("SELECT enabled FROM social_unlimited_meow WHERE user_id=?", (uid,)).fetchone()
                if requested < 0 and unlimited is not None and int(unlimited["enabled"] or 0) == 1:
                    result["skipped"] += 1
                    con.execute("INSERT INTO social_admin_meow_adjustment_items VALUES(?,?,?,?,?,?,?,?)", (aid,uid,before,0,before,"skipped","unlimited_wallet",now))
                    continue
                actual = requested if requested > 0 else -min(before, abs(requested)); after = before + actual
                con.execute("UPDATE social_meow_accounts SET balance=?, updated_at=? WHERE user_id=?", (after, now, uid))
                if actual:
                    _ledger(con, uid, actual, "admin_adjust", f"{scope}:{target_ref}")
                result["actual_delta"] += actual; result["success"] += 1
                con.execute("INSERT INTO social_admin_meow_adjustment_items VALUES(?,?,?,?,?,?,?,?)", (aid,uid,before,actual,after,"success","",now))
            except Exception as exc:
                result["failed"] += 1
                con.execute("INSERT OR REPLACE INTO social_admin_meow_adjustment_items VALUES(?,?,?,?,?,?,?,?)", (aid,uid,0,0,0,"failed",f"{type(exc).__name__}:{exc}"[:240],now))
        con.execute("UPDATE social_admin_meow_adjustments SET success_count=?,skipped_count=?,failed_count=?,actual_delta=? WHERE adjustment_id=?", (result["success"],result["skipped"],result["failed"],result["actual_delta"],aid))
        con.commit()
    return result

def recent_admin_meow_adjustments(limit: int = 10) -> List[Dict[str, Any]]:
    init_social_db()
    with _connect() as con:
        rows = con.execute("SELECT * FROM social_admin_meow_adjustments ORDER BY adjustment_id DESC LIMIT ?", (max(1,min(50,int(limit))),)).fetchall()
    return [dict(row) for row in rows]
