from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_DB_PATH = Path('/opt/zivo60/zivo_multi_accounts.db')
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY: set[str] = set()
_PLAN_CACHE: Dict[int, Tuple[float, Dict[str, Any]]] = {}
_PLAN_CACHE_TTL = 20.0

PLAN_FREE = 'free'
PLAN_SILVER = 'silver'
PLAN_GOLD = 'gold'
PLAN_DIAMOND = 'diamond'
PLAN_ORDER = (PLAN_FREE, PLAN_SILVER, PLAN_GOLD, PLAN_DIAMOND)
PLAN_RANK = {name: idx for idx, name in enumerate(PLAN_ORDER)}
PLAN_LABEL_FA = {
    PLAN_FREE: 'رایگان',
    PLAN_SILVER: 'نقره‌ای',
    PLAN_GOLD: 'طلایی',
    PLAN_DIAMOND: 'الماس',
}
PLAN_LABEL_EN = {
    PLAN_FREE: 'FREE',
    PLAN_SILVER: 'SILVER',
    PLAN_GOLD: 'GOLD',
    PLAN_DIAMOND: 'DIAMOND',
}

DURATION_LABEL_FA = {30: '۱ ماهه', 60: '۲ ماهه', 90: '۳ ماهه'}
DURATION_ORDER = (30, 60, 90)

# Prices are stored and displayed in RIAL. They are editable from Telegram admin.
MEOW_UNIT_PRICE_RIAL = 400  # 40 toman per Meow
MEOW_MIN_PURCHASE = 100
MEOW_GIFT_PREFIX = 'ZIVO'

DEFAULT_PRICES_RIAL = {
    # ZIVO 96.39 public pricing. Amounts are persisted in IRR.
    (PLAN_SILVER, 30): 550_000,
    (PLAN_SILVER, 60): 1_000_000,
    (PLAN_SILVER, 90): 1_390_000,
    (PLAN_GOLD, 30): 990_000,
    (PLAN_GOLD, 60): 1_790_000,
    (PLAN_GOLD, 90): 2_490_000,
    (PLAN_DIAMOND, 30): 1_200_000,
    (PLAN_DIAMOND, 60): 2_150_000,
    (PLAN_DIAMOND, 90): 2_990_000,
}

PLAN_ENTITLEMENTS: Dict[str, Dict[str, Any]] = {
    PLAN_FREE: {
        'cleanup_limit': 700,
        'content_filter': False,
        'welcome_media': False,
        'speaker_profiles': ['normal'],
        'speaker_learning': False,
        'schedule_limit': 0,
        'scheduled_cleanup': False,
        'daily_report': False,
        'weekly_report': False,
        'user_dossier': False,
        'admin_audit': False,
        'manual_backup': False,
        'restore_backup': False,
        'copy_settings': False,
        'auto_backup': False,
        'anti_raid': False,
        'anti_raid_pro': False,
        'ai_speaker': False,
        'ai_daily_quota': 0,
        'auto_moderation': False,
        'watch_list': False,
        'group_health': False,
        'per_lock_punishment': False,
        'pet_discount_percent': 0,
        'meow_luck_multiplier': 1.00,
        'diamond_activation_meow': 0,
    },
    PLAN_SILVER: {
        'cleanup_limit': 2000,
        'content_filter': True,
        'welcome_media': False,
        'speaker_profiles': ['normal', 'funny', 'chatty', 'quiet', 'anime', 'rude'],
        'speaker_learning': True,
        'schedule_limit': 1,
        'scheduled_cleanup': True,
        'daily_report': False,
        'weekly_report': False,
        'user_dossier': False,
        'admin_audit': False,
        'manual_backup': False,
        'restore_backup': False,
        'copy_settings': False,
        'auto_backup': False,
        'anti_raid': False,
        'anti_raid_pro': False,
        'ai_speaker': False,
        'ai_daily_quota': 0,
        'auto_moderation': False,
        'watch_list': False,
        'group_health': False,
        'per_lock_punishment': False,
        'pet_discount_percent': 10,
        'meow_luck_multiplier': 1.15,
        'diamond_activation_meow': 0,
    },
    PLAN_GOLD: {
        'cleanup_limit': 5000,
        'content_filter': True,
        'welcome_media': True,
        'speaker_profiles': ['normal', 'funny', 'chatty', 'quiet', 'anime', 'rude'],
        'speaker_learning': True,
        'schedule_limit': 8,
        'scheduled_cleanup': True,
        'daily_report': True,
        'weekly_report': False,
        'user_dossier': True,
        'admin_audit': True,
        'manual_backup': True,
        'restore_backup': True,
        'copy_settings': True,
        'auto_backup': False,
        'anti_raid': True,
        'anti_raid_pro': False,
        'ai_speaker': True,
        'ai_daily_quota': 50,
        'auto_moderation': False,
        'watch_list': False,
        'group_health': False,
        'per_lock_punishment': True,
        'pet_discount_percent': 20,
        'meow_luck_multiplier': 1.35,
        'diamond_activation_meow': 0,
    },
    PLAN_DIAMOND: {
        'cleanup_limit': None,
        'content_filter': True,
        'welcome_media': True,
        'speaker_profiles': ['normal', 'funny', 'chatty', 'quiet', 'anime', 'rude', 'ai-custom'],
        'speaker_learning': True,
        'schedule_limit': 50,
        'scheduled_cleanup': True,
        'daily_report': True,
        'weekly_report': True,
        'user_dossier': True,
        'admin_audit': True,
        'manual_backup': True,
        'restore_backup': True,
        'copy_settings': True,
        'auto_backup': True,
        'anti_raid': True,
        'anti_raid_pro': True,
        'ai_speaker': True,
        'ai_daily_quota': 0,
        'auto_moderation': True,
        'watch_list': True,
        'group_health': True,
        'per_lock_punishment': True,
        'pet_discount_percent': 30,
        'meow_luck_multiplier': 1.60,
        'diamond_activation_meow': 100,
    },
}

FEATURE_MIN_PLAN: Dict[str, str] = {
    'content_filter': PLAN_SILVER,
    'scheduled_cleanup': PLAN_SILVER,
    'speaker_learning': PLAN_SILVER,
    'welcome_media': PLAN_GOLD,
    'daily_report': PLAN_GOLD,
    'user_dossier': PLAN_GOLD,
    'admin_audit': PLAN_GOLD,
    'manual_backup': PLAN_GOLD,
    'restore_backup': PLAN_GOLD,
    'copy_settings': PLAN_GOLD,
    'anti_raid': PLAN_GOLD,
    'ai_speaker': PLAN_GOLD,
    'per_lock_punishment': PLAN_GOLD,
    'weekly_report': PLAN_DIAMOND,
    'auto_backup': PLAN_DIAMOND,
    'anti_raid_pro': PLAN_DIAMOND,
    'auto_moderation': PLAN_DIAMOND,
    'watch_list': PLAN_DIAMOND,
    'group_health': PLAN_DIAMOND,
}


DEFAULT_SETTINGS = {
    'card_enabled': '0',
    'card_number': '',
    'card_holder': '',
    'zibal_enabled': '0',
    'zibal_merchant': '',
    'zibal_callback_url': '',
    'payment_domain': '',
    'grace_hours': '24',
}


def configure(db_path: Any) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _PLAN_CACHE.clear()
    init_db()


@contextmanager
def _connect():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH), timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=15000')
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    try:
        yield con
    except Exception:
        if con.in_transaction:
            con.rollback()
        raise
    finally:
        con.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or '').strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_ORDER_CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def _base36(value: int) -> str:
    chars = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    number = max(0, int(value or 0))
    if number == 0:
        return '0'
    out = []
    while number:
        number, rem = divmod(number, 36)
        out.append(chars[rem])
    return ''.join(reversed(out))


def _legacy_order_code(order_id: int, user_id: int) -> str:
    # Stable migration code for pre-96.39 orders. It is non-sequential-looking
    # and unique once the order-id component is included.
    user_part = _base36(int(user_id or 0) % (36 ** 3)).rjust(3, '0')
    order_part = _base36((int(order_id or 0) * 7919 + int(user_id or 0)) % (36 ** 5)).rjust(5, '0')
    return f'ZV-{user_part}-{order_part}'


def _new_order_code(user_id: int) -> str:
    user_part = _base36(int(user_id or 0) % (36 ** 3)).rjust(3, '0')
    random_part = ''.join(secrets.choice(_ORDER_CODE_ALPHABET) for _ in range(5))
    return f'ZV-{user_part}-{random_part}'


def normalize_order_code(value: Any) -> str:
    text = str(value or '').strip().upper().replace('_', '-').replace('–', '-').replace('—', '-')
    text = re.sub(r'\s+', '', text)
    if re.fullmatch(r'ZV-[0-9A-Z]{3}-[0-9A-Z]{5}(?:-[0-9]+)?', text):
        return text
    return ''


def init_db() -> None:
    key = str(_DB_PATH.resolve())
    if key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if key in _SCHEMA_READY:
            return
        with _connect() as con:
            con.executescript(
                '''
                CREATE TABLE IF NOT EXISTS premium_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS premium_plan_prices (
                    plan TEXT NOT NULL,
                    duration_days INTEGER NOT NULL,
                    amount_rial INTEGER NOT NULL DEFAULT 0 CHECK(amount_rial >= 0),
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(plan, duration_days)
                );

                CREATE TABLE IF NOT EXISTS premium_subscriptions (
                    group_id INTEGER PRIMARY KEY,
                    plan TEXT NOT NULL DEFAULT 'free',
                    status TEXT NOT NULL DEFAULT 'active',
                    buyer_user_id INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT,
                    expires_at TEXT,
                    grace_until TEXT,
                    source TEXT NOT NULL DEFAULT 'system',
                    order_id INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_sub_expiry
                    ON premium_subscriptions(status, expires_at);

                CREATE TABLE IF NOT EXISTS premium_orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_code TEXT NOT NULL DEFAULT '',
                    order_kind TEXT NOT NULL DEFAULT 'subscription',
                    buyer_user_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL,
                    group_title TEXT NOT NULL DEFAULT '',
                    plan TEXT NOT NULL,
                    duration_days INTEGER NOT NULL,
                    amount_rial INTEGER NOT NULL,
                    original_amount_rial INTEGER NOT NULL DEFAULT 0,
                    discount_code TEXT NOT NULL DEFAULT '',
                    discount_rial INTEGER NOT NULL DEFAULT 0,
                    target_user_id INTEGER NOT NULL DEFAULT 0,
                    meow_amount INTEGER NOT NULL DEFAULT 0,
                    gift_code TEXT NOT NULL DEFAULT '',
                    method TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'created',
                    zibal_track_id INTEGER NOT NULL DEFAULT 0,
                    zibal_result INTEGER NOT NULL DEFAULT 0,
                    gateway_ref_id TEXT NOT NULL DEFAULT '',
                    receipt_path TEXT NOT NULL DEFAULT '',
                    receipt_message_id INTEGER NOT NULL DEFAULT 0,
                    receipt_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    paid_at TEXT,
                    verified_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_orders_user
                    ON premium_orders(buyer_user_id, status, order_id DESC);
                CREATE INDEX IF NOT EXISTS idx_premium_orders_group
                    ON premium_orders(group_id, order_id DESC);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_premium_orders_track
                    ON premium_orders(zibal_track_id) WHERE zibal_track_id > 0;

                CREATE TABLE IF NOT EXISTS premium_payment_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    event_kind TEXT NOT NULL,
                    external_id TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_events_order
                    ON premium_payment_events(order_id, event_id DESC);

                CREATE TABLE IF NOT EXISTS premium_checkout_sessions (
                    user_id INTEGER PRIMARY KEY,
                    group_id INTEGER NOT NULL DEFAULT 0,
                    group_title TEXT NOT NULL DEFAULT '',
                    order_id INTEGER NOT NULL DEFAULT 0,
                    stage TEXT NOT NULL DEFAULT '',
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS premium_wallets (
                    user_id INTEGER PRIMARY KEY,
                    balance_rial INTEGER NOT NULL DEFAULT 0 CHECK(balance_rial >= 0),
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS premium_wallet_ledger (
                    ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    delta_rial INTEGER NOT NULL,
                    balance_before INTEGER NOT NULL,
                    balance_after INTEGER NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    order_id INTEGER NOT NULL DEFAULT 0,
                    admin_id INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_wallet_ledger_user
                    ON premium_wallet_ledger(user_id, ledger_id DESC);

                CREATE TABLE IF NOT EXISTS premium_bonus_claims (
                    claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL DEFAULT 0,
                    bonus_kind TEXT NOT NULL,
                    amount INTEGER NOT NULL DEFAULT 0,
                    order_id INTEGER NOT NULL DEFAULT 0,
                    claimed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_bonus_guard
                    ON premium_bonus_claims(group_id, bonus_kind, claimed_at DESC);


                CREATE TABLE IF NOT EXISTS premium_group_notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT 'subscription-activated',
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    claimed_by TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_premium_group_notifications_pending
                    ON premium_group_notifications(status, next_attempt_at, notification_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_premium_group_notification_order_kind
                    ON premium_group_notifications(order_id, kind) WHERE order_id > 0;

                CREATE TABLE IF NOT EXISTS premium_feature_settings (
                    group_id INTEGER NOT NULL,
                    feature_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    config_json TEXT NOT NULL DEFAULT '{}',
                    updated_by INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, feature_name)
                );
                CREATE TABLE IF NOT EXISTS official_managed_groups (
                    user_id INTEGER NOT NULL,
                    group_id INTEGER NOT NULL,
                    account_key TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    member_count INTEGER NOT NULL DEFAULT -1,
                    verified_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, group_id)
                );
                CREATE INDEX IF NOT EXISTS idx_official_managed_groups_user
                    ON official_managed_groups(user_id, verified_at DESC);

                CREATE TABLE IF NOT EXISTS premium_ai_daily_usage (
                    group_id INTEGER NOT NULL,
                    usage_day TEXT NOT NULL,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, usage_day)
                );

                CREATE TABLE IF NOT EXISTS official_private_users (
                    user_id INTEGER PRIMARY KEY,
                    first_seen_at TEXT NOT NULL,
                    membership_passed INTEGER NOT NULL DEFAULT 0,
                    passed_at TEXT NOT NULL DEFAULT '',
                    broadcast_enabled INTEGER NOT NULL DEFAULT 1,
                    username TEXT NOT NULL DEFAULT '',
                    first_name TEXT NOT NULL DEFAULT '',
                    last_seen_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS premium_meow_gift_codes (
                    code TEXT PRIMARY KEY,
                    creator_user_id INTEGER NOT NULL,
                    meow_amount INTEGER NOT NULL,
                    order_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'active',
                    redeemed_by INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    redeemed_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_premium_meow_gift_creator
                    ON premium_meow_gift_codes(creator_user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS premium_official_notifications (
                    notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    order_id INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at TEXT NOT NULL,
                    sent_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(order_id, user_id, kind)
                );
                CREATE INDEX IF NOT EXISTS idx_premium_official_notifications_pending
                    ON premium_official_notifications(status, notification_id);

                CREATE TABLE IF NOT EXISTS premium_watch_list (
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    added_by INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(group_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS premium_watch_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    event_kind TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_watch_events_user
                    ON premium_watch_events(group_id,user_id,event_id DESC);
                CREATE TABLE IF NOT EXISTS premium_admin_audit (
                    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    actor_user_id INTEGER NOT NULL DEFAULT 0,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'group',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_admin_audit_group
                    ON premium_admin_audit(group_id,audit_id DESC);
                '''
            )
            # Durable, ordered migrations for databases created by 96.38/96.38.1.
            # IMPORTANT: CREATE TABLE IF NOT EXISTS does not add new columns to an
            # existing table.  Therefore no index/query may reference order_code or
            # order_kind until the ALTER TABLE phase below has completed.
            con.execute('BEGIN IMMEDIATE')
            order_columns = {str(row[1]) for row in con.execute('PRAGMA table_info(premium_orders)').fetchall()}
            if 'order_code' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN order_code TEXT NOT NULL DEFAULT ''")
            if 'order_kind' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN order_kind TEXT NOT NULL DEFAULT 'subscription'")
            if 'original_amount_rial' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN original_amount_rial INTEGER NOT NULL DEFAULT 0")
            if 'discount_code' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN discount_code TEXT NOT NULL DEFAULT ''")
            if 'discount_rial' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN discount_rial INTEGER NOT NULL DEFAULT 0")
            if 'target_user_id' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN target_user_id INTEGER NOT NULL DEFAULT 0")
            if 'meow_amount' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN meow_amount INTEGER NOT NULL DEFAULT 0")
            if 'gift_code' not in order_columns:
                con.execute("ALTER TABLE premium_orders ADD COLUMN gift_code TEXT NOT NULL DEFAULT ''")
            # 96.49 durable manual-payment review ledger. The order remains the
            # accounting source of truth; this table records every admin decision,
            # reversal snapshot and human-facing rejection reason.
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS premium_manual_review (
                    order_id INTEGER PRIMARY KEY,
                    receipt_file_id TEXT NOT NULL DEFAULT '',
                    receipt_caption TEXT NOT NULL DEFAULT '',
                    submitted_by INTEGER NOT NULL DEFAULT 0,
                    submitted_at TEXT NOT NULL DEFAULT '',
                    admin_status TEXT NOT NULL DEFAULT 'pending',
                    admin_id INTEGER NOT NULL DEFAULT 0,
                    admin_reason_code TEXT NOT NULL DEFAULT '',
                    admin_reason_text TEXT NOT NULL DEFAULT '',
                    activation_snapshot_json TEXT NOT NULL DEFAULT '{}',
                    last_action_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS premium_manual_review_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL,
                    actor_user_id INTEGER NOT NULL DEFAULT 0,
                    action TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_premium_manual_review_status
                    ON premium_manual_review(admin_status, last_action_at);
                CREATE INDEX IF NOT EXISTS idx_premium_manual_review_events_order
                    ON premium_manual_review_events(order_id, event_id DESC);
                """
            )
            official_user_columns = {str(row[1]) for row in con.execute('PRAGMA table_info(official_private_users)').fetchall()}
            if 'broadcast_enabled' not in official_user_columns:
                con.execute("ALTER TABLE official_private_users ADD COLUMN broadcast_enabled INTEGER NOT NULL DEFAULT 1")
            if 'username' not in official_user_columns:
                con.execute("ALTER TABLE official_private_users ADD COLUMN username TEXT NOT NULL DEFAULT ''")
            if 'first_name' not in official_user_columns:
                con.execute("ALTER TABLE official_private_users ADD COLUMN first_name TEXT NOT NULL DEFAULT ''")
            if 'last_seen_at' not in official_user_columns:
                con.execute("ALTER TABLE official_private_users ADD COLUMN last_seen_at TEXT NOT NULL DEFAULT ''")
            con.execute("UPDATE premium_orders SET original_amount_rial=amount_rial WHERE original_amount_rial<=0")

            # Backfill and de-duplicate public codes before creating the UNIQUE index.
            # This makes the migration safe for both pristine 96.38 databases and a
            # partially migrated database from an interrupted deployment.
            seen_codes: set[str] = set()
            rows = con.execute(
                "SELECT order_id,buyer_user_id,order_code FROM premium_orders ORDER BY order_id"
            ).fetchall()
            for row in rows:
                oid = int(row['order_id'] or 0)
                uid = int(row['buyer_user_id'] or 0)
                raw_code = str(row['order_code'] or '').strip().upper()
                code = normalize_order_code(raw_code)
                if not code or code in seen_codes:
                    code = _legacy_order_code(oid, uid)
                    suffix = 0
                    while code in seen_codes or con.execute(
                        'SELECT 1 FROM premium_orders WHERE order_code=? AND order_id!=?',
                        (code, oid),
                    ).fetchone() is not None:
                        suffix += 1
                        code = f"{_legacy_order_code(oid, uid)}-{suffix}"
                    con.execute('UPDATE premium_orders SET order_code=? WHERE order_id=?', (code, oid))
                elif raw_code != code:
                    con.execute('UPDATE premium_orders SET order_code=? WHERE order_id=?', (code, oid))
                seen_codes.add(code)

            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_premium_orders_code ON premium_orders(order_code) WHERE order_code != ''")
            con.execute("CREATE INDEX IF NOT EXISTS idx_premium_orders_group ON premium_orders(group_id, order_id DESC)")

            now = _now_iso()
            for k, v in DEFAULT_SETTINGS.items():
                con.execute(
                    'INSERT OR IGNORE INTO premium_settings(key,value,updated_at) VALUES(?,?,?)',
                    (k, str(v), now),
                )
            for (plan, days), amount in DEFAULT_PRICES_RIAL.items():
                con.execute(
                    '''INSERT OR IGNORE INTO premium_plan_prices
                       (plan,duration_days,amount_rial,enabled,updated_at)
                       VALUES(?,?,?,?,?)''',
                    (plan, int(days), int(amount), 1, now),
                )
            pricing_marker = con.execute("SELECT value FROM premium_settings WHERE key='pricing_profile_96_39'").fetchone()
            if pricing_marker is None or str(pricing_marker['value'] or '') != '1':
                for (plan, days), amount in DEFAULT_PRICES_RIAL.items():
                    con.execute(
                        '''INSERT INTO premium_plan_prices(plan,duration_days,amount_rial,enabled,updated_at)
                           VALUES(?,?,?,?,?) ON CONFLICT(plan,duration_days) DO UPDATE SET
                           amount_rial=excluded.amount_rial,enabled=1,updated_at=excluded.updated_at''',
                        (plan, int(days), int(amount), 1, now),
                    )
                con.execute("UPDATE premium_plan_prices SET enabled=0,updated_at=? WHERE duration_days NOT IN (30,60,90)", (now,))
                con.execute(
                    '''INSERT INTO premium_settings(key,value,updated_at) VALUES('pricing_profile_96_39','1',?)
                       ON CONFLICT(key) DO UPDATE SET value='1',updated_at=excluded.updated_at''',
                    (now,),
                )
            con.commit()
        _SCHEMA_READY.add(key)


def normalize_plan(value: Any) -> str:
    raw = str(value or '').strip().lower().replace('‌', ' ')
    aliases = {
        'free': PLAN_FREE, 'رایگان': PLAN_FREE,
        'silver': PLAN_SILVER, 'نقره': PLAN_SILVER, 'نقره ای': PLAN_SILVER, 'نقره‌ای': PLAN_SILVER,
        'gold': PLAN_GOLD, 'طلایی': PLAN_GOLD, 'طلا': PLAN_GOLD,
        'diamond': PLAN_DIAMOND, 'الماس': PLAN_DIAMOND, 'الماسی': PLAN_DIAMOND,
    }
    return aliases.get(raw, raw if raw in PLAN_ORDER else '')


def plan_label(plan: Any) -> str:
    return PLAN_LABEL_FA.get(normalize_plan(plan), 'نامشخص')


def duration_label(days: Any) -> str:
    return DURATION_LABEL_FA.get(int(days or 0), f'{int(days or 0)} روزه')


def money_rial(amount: Any) -> str:
    return f"{int(amount or 0):,} ریال"


def money_toman(amount_rial: Any) -> str:
    return f"{int(amount_rial or 0) // 10:,} تومان"


def get_setting(key: str, default: str = '') -> str:
    init_db()
    with _connect() as con:
        row = con.execute('SELECT value FROM premium_settings WHERE key=?', (str(key),)).fetchone()
    return str(row['value']) if row is not None else str(default)


def set_setting(key: str, value: Any) -> None:
    init_db()
    with _connect() as con:
        con.execute(
            '''INSERT INTO premium_settings(key,value,updated_at) VALUES(?,?,?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at''',
            (str(key), str(value), _now_iso()),
        )


def setting_bool(key: str, default: bool = False) -> bool:
    value = get_setting(key, '1' if default else '0').strip().lower()
    return value in {'1', 'true', 'yes', 'on', 'enabled'}


def payment_settings() -> Dict[str, Any]:
    return {
        'card_enabled': setting_bool('card_enabled'),
        'card_number': get_setting('card_number'),
        'card_holder': get_setting('card_holder'),
        'zibal_enabled': setting_bool('zibal_enabled'),
        'zibal_merchant': get_setting('zibal_merchant'),
        'zibal_callback_url': get_setting('zibal_callback_url'),
        'payment_domain': get_setting('payment_domain'),
        'grace_hours': max(0, int(get_setting('grace_hours', '24') or 24)),
    }


def normalize_payment_domain(value: Any) -> str:
    raw = str(value or '').strip().lower()
    if not raw:
        return ''
    raw = re.sub(r'^https?://', '', raw, flags=re.I)
    raw = raw.split('/', 1)[0].strip().strip('.')
    if ':' in raw:
        host, _, port = raw.partition(':')
        if port and port not in {'80', '443'}:
            return ''
        raw = host
    if len(raw) > 253 or '.' not in raw:
        return ''
    labels = raw.split('.')
    if any(not label or len(label) > 63 or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', label) for label in labels):
        return ''
    return raw


def set_payment_domain(value: Any) -> str:
    domain = normalize_payment_domain(value)
    if not domain:
        raise ValueError('INVALID_PAYMENT_DOMAIN')
    callback = f'https://{domain}/zivo/zibal/callback'
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        for key, val in (('payment_domain', domain), ('zibal_callback_url', callback)):
            con.execute(
                'INSERT INTO premium_settings(key,value,updated_at) VALUES(?,?,?) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
                (key, val, now),
            )
        con.commit()
    return domain


def normalize_card_number(value: Any) -> str:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits if len(digits) == 16 else ''


def set_card_number(value: Any) -> str:
    number = normalize_card_number(value)
    if not number:
        raise ValueError('CARD_NUMBER_MUST_BE_16_DIGITS')
    set_setting('card_number', number)
    return number


def set_price(plan: Any, duration_days: int, amount_rial: int, enabled: bool = True) -> None:
    p = normalize_plan(plan)
    days = int(duration_days)
    amount = int(amount_rial)
    if p not in {PLAN_SILVER, PLAN_GOLD, PLAN_DIAMOND}:
        raise ValueError('INVALID_PLAN')
    if days not in DURATION_ORDER:
        raise ValueError('INVALID_DURATION')
    if amount < 0:
        raise ValueError('INVALID_AMOUNT')
    with _connect() as con:
        con.execute(
            '''INSERT INTO premium_plan_prices(plan,duration_days,amount_rial,enabled,updated_at)
               VALUES(?,?,?,?,?) ON CONFLICT(plan,duration_days) DO UPDATE SET
               amount_rial=excluded.amount_rial, enabled=excluded.enabled, updated_at=excluded.updated_at''',
            (p, days, amount, 1 if enabled else 0, _now_iso()),
        )


def get_price(plan: Any, duration_days: int) -> Optional[int]:
    p = normalize_plan(plan)
    with _connect() as con:
        row = con.execute(
            'SELECT amount_rial,enabled FROM premium_plan_prices WHERE plan=? AND duration_days=?',
            (p, int(duration_days)),
        ).fetchone()
    if row is None or not int(row['enabled'] or 0):
        return None
    amount = int(row['amount_rial'] or 0)
    return amount if amount > 0 else None


def all_prices() -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            'SELECT plan,duration_days,amount_rial,enabled FROM premium_plan_prices ORDER BY CASE plan WHEN \'silver\' THEN 1 WHEN \'gold\' THEN 2 WHEN \'diamond\' THEN 3 ELSE 9 END, duration_days'
        ).fetchall()
    return [dict(row) for row in rows]


def _effective_subscription_from_row(row: Optional[sqlite3.Row]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    if row is None:
        return {'plan': PLAN_FREE, 'status': 'active', 'expires_at': None, 'grace_until': None, 'buyer_user_id': 0, 'source': 'free'}
    plan = normalize_plan(row['plan']) or PLAN_FREE
    status = str(row['status'] or 'active')
    expires = _parse_iso(row['expires_at'])
    grace = _parse_iso(row['grace_until'])
    if plan == PLAN_FREE:
        status = 'active'
        expires = None
        grace = None
    elif expires is not None and now > expires:
        if grace is not None and now <= grace:
            status = 'grace'
        else:
            plan = PLAN_FREE
            status = 'expired'
    started = _parse_iso(row['started_at'])
    return {
        'plan': plan,
        'status': status,
        'started_at': started.isoformat() if started else None,
        'expires_at': expires.isoformat() if expires else None,
        'grace_until': grace.isoformat() if grace else None,
        'buyer_user_id': int(row['buyer_user_id'] or 0),
        'source': str(row['source'] or ''),
        'order_id': int(row['order_id'] or 0),
    }


def get_subscription(group_id: int, *, use_cache: bool = True) -> Dict[str, Any]:
    gid = int(group_id)
    now_mono = time.monotonic()
    cached = _PLAN_CACHE.get(gid)
    if use_cache and cached is not None and now_mono - cached[0] <= _PLAN_CACHE_TTL:
        return dict(cached[1])
    with _connect() as con:
        row = con.execute('SELECT * FROM premium_subscriptions WHERE group_id=?', (gid,)).fetchone()
    state = _effective_subscription_from_row(row)
    _PLAN_CACHE[gid] = (now_mono, dict(state))
    return state


def plan_for_group(group_id: int) -> str:
    return str(get_subscription(group_id).get('plan') or PLAN_FREE)


def entitlements_for_group(group_id: int) -> Dict[str, Any]:
    plan = plan_for_group(group_id)
    result = dict(PLAN_ENTITLEMENTS.get(plan, PLAN_ENTITLEMENTS[PLAN_FREE]))
    result['plan'] = plan
    result['plan_label'] = plan_label(plan)
    return result


def has_plan(group_id: int, minimum_plan: Any) -> bool:
    current = plan_for_group(group_id)
    wanted = normalize_plan(minimum_plan) or PLAN_FREE
    return PLAN_RANK.get(current, 0) >= PLAN_RANK.get(wanted, 0)

def required_plan_for_feature(feature_name: Any) -> str:
    return str(FEATURE_MIN_PLAN.get(str(feature_name or '').strip(), PLAN_FREE))


def feature_allowed(group_id: int, feature_name: Any) -> bool:
    feature = str(feature_name or '').strip()
    if not feature:
        return True
    return has_plan(int(group_id), required_plan_for_feature(feature))


def entitlement(group_id: int, key: Any, default: Any = None) -> Any:
    return entitlements_for_group(int(group_id)).get(str(key), default)


def cleanup_limit(group_id: int) -> int:
    value = entitlement(group_id, 'cleanup_limit', 700)
    return 0 if value is None else max(1, int(value))


def pet_discount_percent(group_id: int) -> int:
    return max(0, min(100, int(entitlement(group_id, 'pet_discount_percent', 0) or 0)))


def meow_luck_multiplier(group_id: int) -> float:
    return max(1.0, float(entitlement(group_id, 'meow_luck_multiplier', 1.0) or 1.0))


def get_feature_setting(group_id: int, feature_name: Any) -> Dict[str, Any]:
    init_db()
    gid = int(group_id)
    feature = str(feature_name or '').strip()
    with _connect() as con:
        row = con.execute('SELECT * FROM premium_feature_settings WHERE group_id=? AND feature_name=?', (gid, feature)).fetchone()
    if row is None:
        return {'group_id': gid, 'feature_name': feature, 'enabled': False, 'config': {}}
    try:
        config = json.loads(str(row['config_json'] or '{}'))
    except Exception:
        config = {}
    return {'group_id': gid, 'feature_name': feature, 'enabled': bool(int(row['enabled'] or 0)), 'config': config if isinstance(config, dict) else {}, 'updated_by': int(row['updated_by'] or 0), 'updated_at': str(row['updated_at'] or '')}


def set_feature_setting(group_id: int, feature_name: Any, enabled: bool, *, updated_by: int = 0, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    init_db()
    gid = int(group_id)
    feature = str(feature_name or '').strip()
    if not feature:
        raise ValueError('FEATURE_REQUIRED')
    if enabled and not feature_allowed(gid, feature):
        raise PermissionError('PREMIUM_REQUIRED:' + required_plan_for_feature(feature))
    payload = json.dumps(config or {}, ensure_ascii=False, separators=(',', ':'))
    now = _now_iso()
    with _connect() as con:
        con.execute("""INSERT INTO premium_feature_settings(group_id,feature_name,enabled,config_json,updated_by,updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(group_id,feature_name) DO UPDATE SET enabled=excluded.enabled,config_json=excluded.config_json,updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (gid, feature, 1 if enabled else 0, payload, int(updated_by or 0), now))
    return get_feature_setting(gid, feature)


def watch_user(group_id: int, user_id: int, *, added_by: int = 0, active: bool = True) -> Dict[str, Any]:
    if active and not feature_allowed(group_id, 'watch_list'):
        raise PermissionError('PREMIUM_REQUIRED:' + PLAN_DIAMOND)
    now = _now_iso()
    with _connect() as con:
        con.execute("""INSERT INTO premium_watch_list(group_id,user_id,added_by,active,created_at) VALUES(?,?,?,?,?)
                       ON CONFLICT(group_id,user_id) DO UPDATE SET added_by=excluded.added_by,active=excluded.active""",
                    (int(group_id), int(user_id), int(added_by or 0), 1 if active else 0, now))
    return {'group_id': int(group_id), 'user_id': int(user_id), 'active': bool(active), 'added_by': int(added_by or 0)}


def is_watched(group_id: int, user_id: int) -> bool:
    with _connect() as con:
        row = con.execute('SELECT active FROM premium_watch_list WHERE group_id=? AND user_id=?', (int(group_id), int(user_id))).fetchone()
    return bool(row is not None and int(row['active'] or 0))


def record_watch_event(group_id: int, user_id: int, event_kind: Any, detail: Any = '') -> None:
    if not is_watched(group_id, user_id):
        return
    with _connect() as con:
        con.execute('INSERT INTO premium_watch_events(group_id,user_id,event_kind,detail,created_at) VALUES(?,?,?,?,?)',
                    (int(group_id), int(user_id), str(event_kind or 'message')[:80], str(detail or '')[:500], _now_iso()))


def watch_report(group_id: int, user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute('SELECT * FROM premium_watch_events WHERE group_id=? AND user_id=? ORDER BY event_id DESC LIMIT ?', (int(group_id), int(user_id), max(1, min(100, int(limit))))).fetchall()
    return [dict(row) for row in rows]


def record_admin_audit(group_id: int, actor_user_id: int, action: Any, detail: Any = '', source: str = 'group') -> None:
    if not feature_allowed(group_id, 'admin_audit'):
        return
    with _connect() as con:
        con.execute('INSERT INTO premium_admin_audit(group_id,actor_user_id,action,detail,source,created_at) VALUES(?,?,?,?,?,?)',
                    (int(group_id), int(actor_user_id or 0), str(action or '')[:120], str(detail or '')[:800], str(source or 'group')[:40], _now_iso()))


def admin_audit_rows(group_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute('SELECT * FROM premium_admin_audit WHERE group_id=? ORDER BY audit_id DESC LIMIT ?', (int(group_id), max(1, min(100, int(limit))))).fetchall()
    return [dict(row) for row in rows]


def official_add_managed_group(user_id: int, group_id: int, account_key: str, title: str = '', member_count: int = -1) -> Dict[str, Any]:
    init_db()
    uid, gid = int(user_id or 0), int(group_id or 0)
    key = str(account_key or '').strip().lower()
    if uid <= 0 or gid <= 0 or not key:
        raise ValueError('OFFICIAL_GROUP_ACCESS_INVALID')
    now = _now_iso()
    with _connect() as con:
        con.execute(
            'INSERT INTO official_managed_groups(user_id,group_id,account_key,title,member_count,verified_at) VALUES(?,?,?,?,?,?) '
            'ON CONFLICT(user_id,group_id) DO UPDATE SET account_key=excluded.account_key,title=excluded.title,member_count=excluded.member_count,verified_at=excluded.verified_at',
            (uid, gid, key, str(title or '')[:180], int(member_count if member_count is not None else -1), now),
        )
        con.commit()
    return {'user_id': uid, 'group_id': gid, 'account_key': key, 'title': str(title or ''), 'member_count': int(member_count if member_count is not None else -1), 'verified_at': now}


def official_managed_groups(user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    init_db()
    uid = int(user_id or 0)
    if uid <= 0:
        return []
    with _connect() as con:
        rows = con.execute(
            'SELECT * FROM official_managed_groups WHERE user_id=? ORDER BY verified_at DESC LIMIT ?',
            (uid, max(1, min(500, int(limit)))),
        ).fetchall()
    return [dict(r) for r in rows]


def consume_ai_daily_quota(group_id: int) -> Dict[str, Any]:
    """Consume one AI reply slot according to the current plan.

    ai_daily_quota=0 means plan-unlimited (Diamond). FREE/SILVER are denied by
    the ai_speaker entitlement before this function is normally called.
    """
    gid = int(group_id or 0)
    plan = plan_for_group(gid)
    if not bool(PLAN_ENTITLEMENTS.get(plan, {}).get('ai_speaker')):
        return {'allowed': False, 'plan': plan, 'limit': 0, 'used': 0, 'remaining': 0}
    limit = int(PLAN_ENTITLEMENTS.get(plan, {}).get('ai_daily_quota') or 0)
    if limit <= 0:
        return {'allowed': True, 'plan': plan, 'limit': 0, 'used': 0, 'remaining': -1}
    day = datetime.now(timezone.utc).date().isoformat()
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT used_count FROM premium_ai_daily_usage WHERE group_id=? AND usage_day=?', (gid, day)).fetchone()
        used = int(row['used_count'] or 0) if row is not None else 0
        if used >= limit:
            con.rollback()
            return {'allowed': False, 'plan': plan, 'limit': limit, 'used': used, 'remaining': 0}
        used += 1
        con.execute(
            'INSERT INTO premium_ai_daily_usage(group_id,usage_day,used_count,updated_at) VALUES(?,?,?,?) '
            'ON CONFLICT(group_id,usage_day) DO UPDATE SET used_count=excluded.used_count,updated_at=excluded.updated_at',
            (gid, day, used, now),
        )
        con.commit()
    return {'allowed': True, 'plan': plan, 'limit': limit, 'used': used, 'remaining': max(0, limit-used)}


def official_user_state(user_id: int) -> Dict[str, Any]:
    init_db()
    uid = int(user_id or 0)
    if uid <= 0:
        return {'seen': False, 'membership_passed': False}
    with _connect() as con:
        row = con.execute('SELECT * FROM official_private_users WHERE user_id=?', (uid,)).fetchone()
    if row is None:
        return {'user_id': uid, 'seen': False, 'membership_passed': False}
    data = dict(row)
    data['seen'] = True
    data['membership_passed'] = bool(int(data.get('membership_passed') or 0))
    return data


def _normalize_official_username(value: Any) -> str:
    text = str(value or '').strip().lstrip('@').casefold()
    return re.sub(r'[^a-z0-9_.-]+', '', text)[:64]


def official_user_mark_seen(
    user_id: int, *, membership_passed: bool = False, username: Any = '', first_name: Any = ''
) -> Dict[str, Any]:
    init_db()
    uid = int(user_id or 0)
    if uid <= 0:
        raise ValueError('OFFICIAL_USER_INVALID')
    now = _now_iso()
    uname = _normalize_official_username(username)
    fname = str(first_name or '').strip()[:120]
    with _connect() as con:
        con.execute(
            """INSERT INTO official_private_users(
                   user_id,first_seen_at,membership_passed,passed_at,broadcast_enabled,username,first_name,last_seen_at,updated_at
               ) VALUES(?,?,?,?,1,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
               membership_passed=MAX(official_private_users.membership_passed,excluded.membership_passed),
               passed_at=CASE WHEN excluded.membership_passed=1 AND official_private_users.passed_at='' THEN excluded.passed_at ELSE official_private_users.passed_at END,
               username=CASE WHEN excluded.username!='' THEN excluded.username ELSE official_private_users.username END,
               first_name=CASE WHEN excluded.first_name!='' THEN excluded.first_name ELSE official_private_users.first_name END,
               last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at""",
            (uid, now, 1 if membership_passed else 0, now if membership_passed else '', uname, fname, now, now),
        )
        con.commit()
    return official_user_state(uid)


def official_user_pass_gate(user_id: int, *, username: Any = '', first_name: Any = '') -> Dict[str, Any]:
    return official_user_mark_seen(user_id, membership_passed=True, username=username, first_name=first_name)


def official_find_user(reference: Any) -> Optional[Dict[str, Any]]:
    """Resolve only users that have actually started the Official bot."""
    init_db()
    raw = str(reference or '').strip()
    with _connect() as con:
        if raw.lstrip('+').isdigit():
            row = con.execute('SELECT * FROM official_private_users WHERE user_id=?', (int(raw),)).fetchone()
        else:
            uname = _normalize_official_username(raw)
            if not uname:
                return None
            row = con.execute('SELECT * FROM official_private_users WHERE username=? ORDER BY updated_at DESC LIMIT 1', (uname,)).fetchone()
    if row is None:
        return None
    data = dict(row); data['seen'] = True; data['membership_passed'] = bool(int(data.get('membership_passed') or 0))
    return data


def official_broadcast_user_ids(limit: int = 50000) -> List[int]:
    init_db()
    with _connect() as con:
        rows = con.execute(
            'SELECT user_id FROM official_private_users WHERE broadcast_enabled=1 ORDER BY updated_at DESC LIMIT ?',
            (max(1, min(100000, int(limit or 50000))),),
        ).fetchall()
    return [int(row['user_id']) for row in rows if int(row['user_id'] or 0) > 0]


def official_broadcast_counts() -> Dict[str, int]:
    init_db()
    with _connect() as con:
        total = int(con.execute('SELECT COUNT(*) FROM official_private_users').fetchone()[0] or 0)
        enabled = int(con.execute('SELECT COUNT(*) FROM official_private_users WHERE broadcast_enabled=1').fetchone()[0] or 0)
    return {'total': total, 'enabled': enabled, 'disabled': max(0, total-enabled)}


def official_set_broadcast_enabled(user_id: int, enabled: bool) -> Dict[str, Any]:
    init_db()
    uid = int(user_id or 0)
    if uid <= 0:
        raise ValueError('OFFICIAL_USER_INVALID')
    official_user_mark_seen(uid)
    with _connect() as con:
        con.execute('UPDATE official_private_users SET broadcast_enabled=?,updated_at=? WHERE user_id=?',
                    (1 if enabled else 0, _now_iso(), uid))
        con.commit()
    state = official_user_state(uid)
    state['broadcast_enabled'] = bool(enabled)
    return state


def reserve_bonus_once(group_id: int, user_id: int, bonus_kind: str, amount: int, order_id: int = 0) -> bool:
    """Atomically reserve a one-time group benefit.

    Returns False when the same group/bonus kind was already granted/reserved.
    This is deliberately independent of renewals and buyer changes.
    """
    init_db()
    gid, uid, oid = int(group_id or 0), int(user_id or 0), int(order_id or 0)
    kind = str(bonus_kind or '').strip()[:80]
    amt = int(amount or 0)
    if gid <= 0 or uid <= 0 or not kind or amt <= 0:
        return False
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute(
            'SELECT claim_id FROM premium_bonus_claims WHERE group_id=? AND bonus_kind=? LIMIT 1',
            (gid, kind),
        ).fetchone()
        if row is not None:
            con.rollback(); return False
        con.execute(
            'INSERT INTO premium_bonus_claims(group_id,user_id,bonus_kind,amount,order_id,claimed_at) VALUES(?,?,?,?,?,?)',
            (gid, uid, kind, amt, oid, now),
        )
        con.commit()
    return True


def release_bonus_reservation(group_id: int, bonus_kind: str, order_id: int = 0) -> None:
    """Release only the reservation belonging to this failed order."""
    init_db()
    with _connect() as con:
        con.execute(
            'DELETE FROM premium_bonus_claims WHERE group_id=? AND bonus_kind=? AND order_id=?',
            (int(group_id or 0), str(bonus_kind or '')[:80], int(order_id or 0)),
        )
        con.commit()


def activate_subscription(
    group_id: int,
    plan: Any,
    duration_days: int,
    *,
    buyer_user_id: int = 0,
    source: str = 'operator',
    order_id: int = 0,
) -> Dict[str, Any]:
    gid = int(group_id)
    p = normalize_plan(plan)
    days = int(duration_days)
    if p not in {PLAN_SILVER, PLAN_GOLD, PLAN_DIAMOND} or days <= 0:
        raise ValueError('INVALID_SUBSCRIPTION')
    current = get_subscription(gid, use_cache=False)
    now = datetime.now(timezone.utc)
    current_expiry = _parse_iso(current.get('expires_at'))
    start_base = current_expiry if current_expiry is not None and current_expiry > now and current.get('plan') == p else now
    expires = start_base + timedelta(days=days)
    grace_hours = max(0, int(get_setting('grace_hours', '24') or 24))
    grace = expires + timedelta(hours=grace_hours)
    with _connect() as con:
        con.execute(
            '''INSERT INTO premium_subscriptions
               (group_id,plan,status,buyer_user_id,started_at,expires_at,grace_until,source,order_id,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(group_id) DO UPDATE SET
               plan=excluded.plan,status=excluded.status,buyer_user_id=excluded.buyer_user_id,
               started_at=excluded.started_at,expires_at=excluded.expires_at,grace_until=excluded.grace_until,
               source=excluded.source,order_id=excluded.order_id,updated_at=excluded.updated_at''',
            (gid, p, 'active', int(buyer_user_id or 0), now.isoformat(), expires.isoformat(), grace.isoformat(), str(source), int(order_id or 0), now.isoformat()),
        )
    _PLAN_CACHE.pop(gid, None)
    return get_subscription(gid, use_cache=False)


def set_free(group_id: int, source: str = 'operator') -> Dict[str, Any]:
    gid = int(group_id)
    with _connect() as con:
        con.execute(
            '''INSERT INTO premium_subscriptions(group_id,plan,status,buyer_user_id,started_at,expires_at,grace_until,source,order_id,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(group_id) DO UPDATE SET plan='free',status='active',expires_at=NULL,grace_until=NULL,source=excluded.source,order_id=0,updated_at=excluded.updated_at''',
            (gid, PLAN_FREE, 'active', 0, _now_iso(), None, None, str(source), 0, _now_iso()),
        )
    _PLAN_CACHE.pop(gid, None)
    return get_subscription(gid, use_cache=False)


def _insert_order(
    buyer_user_id: int,
    group_id: int,
    group_title: str,
    plan: str,
    duration_days: int,
    amount_rial: int,
    *,
    order_kind: str = 'subscription',
) -> Dict[str, Any]:
    uid = int(buyer_user_id or 0)
    if uid <= 0:
        raise ValueError('INVALID_BUYER')
    now = _now_iso()
    with _connect() as con:
        for _ in range(32):
            code = _new_order_code(uid)
            try:
                cur = con.execute(
                    '''INSERT INTO premium_orders
                       (order_code,order_kind,buyer_user_id,group_id,group_title,plan,duration_days,amount_rial,original_amount_rial,status,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,\'created\',?,?)''',
                    (code, str(order_kind), uid, int(group_id or 0), str(group_title or '')[:200], str(plan or ''), int(duration_days or 0), int(amount_rial), int(amount_rial), now, now),
                )
                oid = int(cur.lastrowid)
                return get_order(oid) or {}
            except sqlite3.IntegrityError:
                continue
    raise RuntimeError('ORDER_CODE_GENERATION_FAILED')


def create_order(buyer_user_id: int, group_id: int, group_title: str, plan: Any, duration_days: int) -> Dict[str, Any]:
    p = normalize_plan(plan)
    days = int(duration_days)
    amount = get_price(p, days)
    if p not in {PLAN_SILVER, PLAN_GOLD, PLAN_DIAMOND} or days not in DURATION_ORDER or amount is None:
        raise ValueError('PRICE_NOT_AVAILABLE')
    if int(group_id or 0) <= 0:
        raise ValueError('INVALID_GROUP')
    return _insert_order(buyer_user_id, group_id, group_title, p, days, int(amount), order_kind='subscription')


def meow_price_rial(meow_amount: int) -> int:
    amount = int(meow_amount or 0)
    if amount < MEOW_MIN_PURCHASE:
        raise ValueError('MEOW_MIN_100')
    if amount > 10_000_000:
        raise ValueError('MEOW_AMOUNT_TOO_LARGE')
    return amount * MEOW_UNIT_PRICE_RIAL


def create_meow_purchase_order(buyer_user_id: int, target_user_id: int, meow_amount: int) -> Dict[str, Any]:
    uid = int(buyer_user_id or 0); target = int(target_user_id or 0); meow = int(meow_amount or 0)
    if target <= 0 or official_find_user(target) is None:
        raise ValueError('MEOW_TARGET_OFFICIAL_NOT_STARTED')
    amount_rial = meow_price_rial(meow)
    row = _insert_order(uid, 0, f'Meow برای {target}', '', 0, amount_rial, order_kind='meow_purchase')
    with _connect() as con:
        con.execute('UPDATE premium_orders SET target_user_id=?,meow_amount=?,updated_at=? WHERE order_id=?',
                    (target, meow, _now_iso(), int(row['order_id'])))
        con.commit()
    return get_order(int(row['order_id'])) or {}


def create_meow_gift_order(buyer_user_id: int, meow_amount: int) -> Dict[str, Any]:
    uid = int(buyer_user_id or 0); meow = int(meow_amount or 0)
    amount_rial = meow_price_rial(meow)
    row = _insert_order(uid, 0, 'کد هدیه Meow', '', 0, amount_rial, order_kind='meow_gift_code')
    with _connect() as con:
        con.execute('UPDATE premium_orders SET meow_amount=?,updated_at=? WHERE order_id=?',
                    (meow, _now_iso(), int(row['order_id'])))
        con.commit()
    return get_order(int(row['order_id'])) or {}


def _ensure_meow_tables_tx(con: sqlite3.Connection) -> None:
    now = int(datetime.now(timezone.utc).timestamp())
    con.execute("""CREATE TABLE IF NOT EXISTS social_meow_accounts (
        user_id INTEGER PRIMARY KEY,balance INTEGER NOT NULL DEFAULT 0 CHECK(balance>=0),
        total_earned INTEGER NOT NULL DEFAULT 0,total_spent INTEGER NOT NULL DEFAULT 0,
        last_claim_at INTEGER NOT NULL DEFAULT 0,created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
    con.execute("""CREATE TABLE IF NOT EXISTS social_meow_ledger (
        tx_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,delta INTEGER NOT NULL,
        balance_after INTEGER NOT NULL,kind TEXT NOT NULL,reference TEXT NOT NULL DEFAULT '',created_at INTEGER NOT NULL)""")


def _credit_meow_tx(con: sqlite3.Connection, user_id: int, amount: int, kind: str, reference: str) -> int:
    uid=int(user_id); value=int(amount); now=int(datetime.now(timezone.utc).timestamp())
    if uid<=0 or value<=0: raise ValueError('INVALID_MEOW_CREDIT')
    _ensure_meow_tables_tx(con)
    row=con.execute('SELECT balance FROM social_meow_accounts WHERE user_id=?',(uid,)).fetchone()
    before=int(row['balance'] or 0) if row is not None else 0
    after=before+value
    con.execute("""INSERT INTO social_meow_accounts(user_id,balance,total_earned,total_spent,last_claim_at,created_at,updated_at)
                 VALUES(?,?,?,0,0,?,?) ON CONFLICT(user_id) DO UPDATE SET
                 balance=excluded.balance,total_earned=social_meow_accounts.total_earned+?,updated_at=excluded.updated_at""",
                (uid,after,value,now,now,value))
    con.execute('INSERT INTO social_meow_ledger(user_id,delta,balance_after,kind,reference,created_at) VALUES(?,?,?,?,?,?)',
                (uid,value,after,str(kind)[:80],str(reference)[:120],now))
    return after


def _new_meow_gift_code_tx(con: sqlite3.Connection, creator_user_id: int, meow_amount: int, order_id: int, now: str) -> str:
    existing=con.execute('SELECT code FROM premium_meow_gift_codes WHERE order_id=?',(int(order_id),)).fetchone()
    if existing is not None: return str(existing['code'])
    for _ in range(64):
        code=MEOW_GIFT_PREFIX+''.join(secrets.choice('0123456789') for _ in range(8))
        try:
            con.execute("INSERT INTO premium_meow_gift_codes(code,creator_user_id,meow_amount,order_id,status,created_at) VALUES(?,?,?,?,'active',?)",
                        (code,int(creator_user_id),int(meow_amount),int(order_id),now))
            return code
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError('MEOW_GIFT_CODE_GENERATION_FAILED')


def meow_gift_code_info(code: Any) -> Optional[Dict[str, Any]]:
    normalized=str(code or '').strip().upper().replace(' ','')
    if not re.fullmatch(r'ZIVO\d{8}', normalized): return None
    with _connect() as con:
        row=con.execute('SELECT * FROM premium_meow_gift_codes WHERE code=?',(normalized,)).fetchone()
    return dict(row) if row is not None else None


def redeem_meow_gift_code(code: Any, redeemer_user_id: int) -> Dict[str, Any]:
    normalized=str(code or '').strip().upper().replace(' ',''); uid=int(redeemer_user_id or 0)
    if uid<=0 or not re.fullmatch(r'ZIVO\d{8}',normalized): raise ValueError('MEOW_GIFT_CODE_INVALID')
    now=_now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM premium_meow_gift_codes WHERE code=?',(normalized,)).fetchone()
        if row is None: raise ValueError('MEOW_GIFT_CODE_NOT_FOUND')
        data=dict(row)
        if str(data.get('status') or '')!='active': raise ValueError('MEOW_GIFT_CODE_USED')
        amount=int(data.get('meow_amount') or 0); creator=int(data.get('creator_user_id') or 0)
        balance=_credit_meow_tx(con,uid,amount,'gift_code',normalized)
        con.execute("UPDATE premium_meow_gift_codes SET status='redeemed',redeemed_by=?,redeemed_at=? WHERE code=? AND status='active'",(uid,now,normalized))
        redeemer_state = official_user_state(uid)
        redeemer_name = str(redeemer_state.get('first_name') or '').strip()
        redeemer_username = str(redeemer_state.get('username') or '').strip().lstrip('@')
        redeemer_label = redeemer_name or (('@' + redeemer_username) if redeemer_username else str(uid))
        if redeemer_username and redeemer_name:
            redeemer_label += f' · @{redeemer_username}'
        con.execute("INSERT OR IGNORE INTO premium_official_notifications(user_id,order_id,kind,text,status,created_at) VALUES(?,?,?,?,'queued',?)",
                    (creator,int(data.get('order_id') or 0),'meow-gift-redeemed',f'🎁 کد هدیه {normalized} استفاده شد.\n👤 دریافت‌کننده: {redeemer_label} ({uid})\n🐱 مقدار: {amount:,} Meow',now))
        con.commit()
    return {'code':normalized,'creator_user_id':creator,'redeemer_user_id':uid,'meow_amount':amount,'balance_after':balance,'order_id':int(data.get('order_id') or 0)}


def pending_official_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows=con.execute("SELECT * FROM premium_official_notifications WHERE status='queued' ORDER BY notification_id LIMIT ?",(max(1,min(200,int(limit))),)).fetchall()
    return [dict(r) for r in rows]


def finish_official_notification(notification_id: int, success: bool) -> None:
    with _connect() as con:
        con.execute('UPDATE premium_official_notifications SET status=?,sent_at=? WHERE notification_id=?',
                    ('sent' if success else 'queued', _now_iso() if success else '', int(notification_id)))
        con.commit()


def create_wallet_topup_order(buyer_user_id: int, amount_rial: int) -> Dict[str, Any]:
    amount = int(amount_rial or 0)
    if amount < 100_000 or amount > 500_000_000:
        raise ValueError('INVALID_WALLET_TOPUP_AMOUNT')
    return _insert_order(buyer_user_id, 0, 'کیف پول ZIVO', '', 0, amount, order_kind='wallet_topup')


def get_order(order_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as con:
        row = con.execute('SELECT * FROM premium_orders WHERE order_id=?', (int(order_id),)).fetchone()
    return dict(row) if row is not None else None


def get_order_by_code(order_code: Any) -> Optional[Dict[str, Any]]:
    code = normalize_order_code(order_code)
    if not code:
        return None
    with _connect() as con:
        row = con.execute('SELECT * FROM premium_orders WHERE order_code=?', (code,)).fetchone()
    return dict(row) if row is not None else None


def orders_for_user(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            'SELECT * FROM premium_orders WHERE buyer_user_id=? ORDER BY order_id DESC LIMIT ?',
            (int(user_id), max(1, min(100, int(limit or 20)))),
        ).fetchall()
    return [dict(row) for row in rows]


def order_count_for_user(user_id: int, *, order_kind: str = "", status: str = "") -> int:
    clauses = ["buyer_user_id=?"]
    params: List[Any] = [int(user_id)]
    if str(order_kind or "").strip():
        clauses.append("order_kind=?")
        params.append(str(order_kind).strip())
    if str(status or "").strip():
        clauses.append("status=?")
        params.append(str(status).strip())
    with _connect() as con:
        row = con.execute(
            "SELECT COUNT(*) AS n FROM premium_orders WHERE " + " AND ".join(clauses),
            params,
        ).fetchone()
    return int(row["n"] or 0) if row is not None else 0


def active_subscriptions_for_buyer(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute(
            '''SELECT s.*, o.group_title, o.order_code, o.amount_rial, o.duration_days
               FROM premium_subscriptions s
               LEFT JOIN premium_orders o ON o.order_id=s.order_id
               WHERE s.buyer_user_id=? AND s.plan!='free'
               ORDER BY s.updated_at DESC LIMIT ?''',
            (int(user_id), max(1, min(100, int(limit or 30)))),
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        effective = get_subscription(int(data.get('group_id') or 0), use_cache=False)
        data.update({f'effective_{k}': v for k, v in effective.items()})
        result.append(data)
    return result


def recent_orders(limit: int = 30) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute('SELECT * FROM premium_orders ORDER BY order_id DESC LIMIT ?', (max(1, min(200, int(limit or 30))),)).fetchall()
    return [dict(row) for row in rows]


def active_subscriptions(limit: int = 50) -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT * FROM premium_subscriptions WHERE plan!='free' ORDER BY updated_at DESC LIMIT ?", (max(1, min(200, int(limit or 50))),)).fetchall()
    return [dict(row) for row in rows]


def wallet_accounts(limit: int = 30, offset: int = 0) -> List[Dict[str, Any]]:
    """Return wallet rows enriched with the persisted Official-bot identity."""
    init_db()
    lim = max(1, min(200, int(limit or 30)))
    skip = max(0, int(offset or 0))
    with _connect() as con:
        rows = con.execute(
            '''SELECT w.user_id,w.balance_rial,w.updated_at,
                      COALESCE(u.username,'') AS username,
                      COALESCE(u.first_name,'') AS first_name,
                      COALESCE(u.membership_passed,0) AS membership_passed,
                      COALESCE(u.last_seen_at,'') AS last_seen_at
               FROM premium_wallets w
               LEFT JOIN official_private_users u ON u.user_id=w.user_id
               ORDER BY w.balance_rial DESC,w.updated_at DESC,w.user_id
               LIMIT ? OFFSET ?''',
            (lim, skip),
        ).fetchall()
    return [dict(row) for row in rows]


def wallet_account_count() -> int:
    init_db()
    with _connect() as con:
        row = con.execute('SELECT COUNT(*) AS n FROM premium_wallets').fetchone()
    return int(row['n'] or 0) if row is not None else 0


def wallet_account_detail(reference: Any, ledger_limit: int = 20) -> Optional[Dict[str, Any]]:
    """Resolve a wallet by Official username/numeric ID and include its audit trail."""
    init_db()
    raw = str(reference or '').strip()
    profile: Optional[Dict[str, Any]] = None
    uid = 0
    if raw.lstrip('+').isdigit():
        uid = int(raw)
        state = official_user_state(uid)
        profile = state if bool(state.get('seen')) else None
    else:
        profile = official_find_user(raw)
        uid = int((profile or {}).get('user_id') or 0)
    if uid <= 0:
        return None
    with _connect() as con:
        wallet = con.execute('SELECT * FROM premium_wallets WHERE user_id=?', (uid,)).fetchone()
    if wallet is None and profile is None:
        return None
    data = dict(wallet) if wallet is not None else {
        'user_id': uid,
        'balance_rial': 0,
        'updated_at': '',
    }
    data['user'] = profile or {'user_id': uid, 'seen': False, 'membership_passed': False}
    data['ledger'] = wallet_ledger(uid, ledger_limit)
    return data


def get_order_by_track(track_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as con:
        row = con.execute('SELECT * FROM premium_orders WHERE zibal_track_id=?', (int(track_id),)).fetchone()
    return dict(row) if row is not None else None


def update_order(order_id: int, **fields: Any) -> Dict[str, Any]:
    allowed = {
        'method','status','zibal_track_id','zibal_result','gateway_ref_id','receipt_path',
        'receipt_message_id','receipt_note','paid_at','verified_at','amount_rial',
        'original_amount_rial','discount_code','discount_rial',
    }
    pairs = [(key, value) for key, value in fields.items() if key in allowed]
    if not pairs:
        return get_order(order_id) or {}
    pairs.append(('updated_at', _now_iso()))
    sql = 'UPDATE premium_orders SET ' + ','.join(f'{key}=?' for key, _ in pairs) + ' WHERE order_id=?'
    with _connect() as con:
        con.execute(sql, [value for _, value in pairs] + [int(order_id)])
    return get_order(order_id) or {}


def normalize_discount_code(value: Any) -> str:
    raw = str(value or '').strip().upper()
    raw = re.sub(r'[^A-Z0-9_-]+', '', raw)
    return raw[:32]


def set_discount_code(code: Any, percent: int) -> Dict[str, Any]:
    normalized = normalize_discount_code(code)
    pct = int(percent or 0)
    if not normalized or pct < 1 or pct > 90:
        raise ValueError('INVALID_DISCOUNT_CODE')
    set_setting(f'discount_code:{normalized}', str(pct))
    return {'code': normalized, 'percent': pct, 'active': True}


def remove_discount_code(code: Any) -> bool:
    normalized = normalize_discount_code(code)
    if not normalized:
        return False
    key = f'discount_code:{normalized}'
    with _connect() as con:
        cur = con.execute('DELETE FROM premium_settings WHERE key=?', (key,))
    return int(cur.rowcount or 0) > 0


def list_discount_codes() -> List[Dict[str, Any]]:
    with _connect() as con:
        rows = con.execute("SELECT key,value,updated_at FROM premium_settings WHERE key LIKE 'discount_code:%' ORDER BY key").fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        code = str(row['key']).split(':', 1)[1]
        try:
            pct = int(str(row['value'] or '0'))
        except Exception:
            pct = 0
        if code and 1 <= pct <= 90:
            out.append({'code': code, 'percent': pct, 'updated_at': str(row['updated_at'] or '')})
    return out


def apply_discount_code(order_id: int, user_id: int, code: Any) -> Dict[str, Any]:
    oid = int(order_id or 0)
    uid = int(user_id or 0)
    normalized = normalize_discount_code(code)
    if oid <= 0 or uid <= 0 or not normalized:
        raise ValueError('INVALID_DISCOUNT_REQUEST')
    raw_pct = get_setting(f'discount_code:{normalized}', '')
    try:
        pct = int(raw_pct)
    except Exception:
        pct = 0
    if pct < 1 or pct > 90:
        raise ValueError('DISCOUNT_CODE_NOT_FOUND')
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM premium_orders WHERE order_id=?', (oid,)).fetchone()
        if row is None:
            raise ValueError('ORDER_NOT_FOUND')
        order = dict(row)
        if int(order.get('buyer_user_id') or 0) != uid:
            raise ValueError('ORDER_NOT_OWNED')
        if str(order.get('status') or '') not in {'created'} or int(order.get('zibal_track_id') or 0) > 0:
            raise ValueError('DISCOUNT_ORDER_LOCKED')
        original = max(1, int(order.get('original_amount_rial') or order.get('amount_rial') or 0))
        discount = max(1, int(round(original * pct / 100.0)))
        final = max(1, original - discount)
        con.execute(
            'UPDATE premium_orders SET amount_rial=?,original_amount_rial=?,discount_code=?,discount_rial=?,updated_at=? WHERE order_id=?',
            (final, original, normalized, discount, now, oid),
        )
        con.execute(
            'INSERT INTO premium_payment_events(order_id,event_kind,external_id,payload_json,created_at) VALUES(?,?,?,?,?)',
            (oid, 'discount_applied', normalized, json.dumps({'percent': pct, 'original_amount_rial': original, 'discount_rial': discount, 'final_amount_rial': final}, ensure_ascii=False), now),
        )
        con.commit()
    result = get_order(oid) or {}
    result['discount_percent'] = pct
    return result


def cancel_order(order_id: int, user_id: int) -> Dict[str, Any]:
    oid = int(order_id or 0)
    uid = int(user_id or 0)
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM premium_orders WHERE order_id=?', (oid,)).fetchone()
        if row is None:
            raise ValueError('ORDER_NOT_FOUND')
        order = dict(row)
        if int(order.get('buyer_user_id') or 0) != uid:
            raise ValueError('ORDER_NOT_OWNED')
        status = str(order.get('status') or '')
        if status == 'activated':
            raise ValueError('ORDER_ALREADY_ACTIVATED')
        if status == 'cancelled':
            con.rollback()
            return order
        if status in {'receipt_submitted'}:
            raise ValueError('ORDER_REVIEW_IN_PROGRESS')
        con.execute("UPDATE premium_orders SET status='cancelled',updated_at=? WHERE order_id=?", (now, oid))
        con.execute(
            'INSERT INTO premium_payment_events(order_id,event_kind,external_id,payload_json,created_at) VALUES(?,?,?,?,?)',
            (oid, 'order_cancelled', str(uid), '{}', now),
        )
        con.commit()
    return get_order(oid) or {}


def record_event(order_id: int, event_kind: str, external_id: Any = '', payload: Optional[Dict[str, Any]] = None) -> None:
    with _connect() as con:
        con.execute(
            'INSERT INTO premium_payment_events(order_id,event_kind,external_id,payload_json,created_at) VALUES(?,?,?,?,?)',
            (int(order_id), str(event_kind)[:80], str(external_id)[:120], json.dumps(payload or {}, ensure_ascii=False)[:4000], _now_iso()),
        )


def attach_zibal_track(order_id: int, track_id: int, result: int = 100) -> Dict[str, Any]:
    return update_order(order_id, method='zibal', status='gateway_pending', zibal_track_id=int(track_id), zibal_result=int(result))


def mark_card_waiting(order_id: int) -> Dict[str, Any]:
    return update_order(order_id, method='card', status='awaiting_receipt')


def attach_card_receipt(order_id: int, receipt_path: str, receipt_message_id: int = 0, note: str = '') -> Dict[str, Any]:
    return update_order(
        order_id,
        method='card', status='receipt_submitted', receipt_path=str(receipt_path),
        receipt_message_id=int(receipt_message_id or 0), receipt_note=str(note or '')[:1000],
    )


def pending_receipt_order(user_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as con:
        row = con.execute(
            '''SELECT * FROM premium_orders
               WHERE buyer_user_id=? AND status='awaiting_receipt' AND method='card'
               ORDER BY order_id DESC LIMIT 1''',
            (int(user_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def pending_orders(statuses: Sequence[str] = ('receipt_submitted',), limit: int = 20) -> List[Dict[str, Any]]:
    wanted = tuple(str(x) for x in statuses if str(x))
    if not wanted:
        return []
    marks = ','.join('?' for _ in wanted)
    with _connect() as con:
        rows = con.execute(
            f'SELECT * FROM premium_orders WHERE status IN ({marks}) ORDER BY order_id DESC LIMIT ?',
            (*wanted, max(1, min(200, int(limit)))),
        ).fetchall()
    return [dict(row) for row in rows]


def approve_order(order_id: int, source: str) -> Dict[str, Any]:
    """Atomically approve a paid order exactly once.

    Card-admin and Zibal callbacks can race/retry. The order row, wallet credit
    or subscription renewal, and audit event therefore commit in one
    BEGIN IMMEDIATE transaction. A second caller observes ``activated`` and
    returns without applying money/time twice.
    """
    init_db()
    oid = int(order_id or 0)
    if oid <= 0:
        raise ValueError('ORDER_NOT_FOUND')
    source_text = str(source or 'payment')[:80]
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    try:
        grace_hours = max(0, int(get_setting('grace_hours', '24') or 24))
    except Exception:
        grace_hours = 24

    wallet_after: Optional[int] = None
    activated_group_id = 0
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM premium_orders WHERE order_id=?', (oid,)).fetchone()
        if row is None:
            raise ValueError('ORDER_NOT_FOUND')
        order = dict(row)
        status = str(order.get('status') or '')
        if status == 'activated':
            con.rollback()
            return order
        if status in {'rejected', 'cancelled'}:
            raise ValueError('ORDER_NOT_APPROVABLE')

        kind = str(order.get('order_kind') or 'subscription')
        amount = max(0, int(order.get('amount_rial') or 0))
        uid = int(order.get('buyer_user_id') or 0)
        if uid <= 0 or amount <= 0:
            raise ValueError('INVALID_ORDER_AMOUNT')

        if kind == 'wallet_topup':
            wrow = con.execute('SELECT balance_rial FROM premium_wallets WHERE user_id=?', (uid,)).fetchone()
            before = max(0, int(wrow['balance_rial'] or 0)) if wrow is not None else 0
            wallet_after = before + amount
            con.execute(
                """INSERT INTO premium_wallets(user_id,balance_rial,updated_at) VALUES(?,?,?)
                   ON CONFLICT(user_id) DO UPDATE SET balance_rial=excluded.balance_rial,updated_at=excluded.updated_at""",
                (uid, wallet_after, now),
            )
            con.execute(
                """INSERT INTO premium_wallet_ledger
                   (user_id,delta_rial,balance_before,balance_after,reason,source,order_id,admin_id,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (uid, amount, before, wallet_after, 'wallet-topup', source_text, oid, 0, now),
            )
            event_kind = 'wallet_topup_activated'
            event_payload = {'amount_rial': amount, 'balance_before': before, 'balance_after': wallet_after}
        elif kind == 'meow_purchase':
            target = int(order.get('target_user_id') or 0); meow = int(order.get('meow_amount') or 0)
            if target <= 0 or meow < MEOW_MIN_PURCHASE:
                raise ValueError('INVALID_MEOW_PURCHASE')
            balance_after = _credit_meow_tx(con, target, meow, 'purchase', f'order:{oid}')
            buyer_state = official_user_state(uid); buyer_name = str(buyer_state.get('first_name') or buyer_state.get('username') or uid)
            con.execute("INSERT OR IGNORE INTO premium_official_notifications(user_id,order_id,kind,text,status,created_at) VALUES(?,?,?,?,'queued',?)",
                        (target, oid, 'meow-purchase-received', f'🐱 {meow:,} Meow از طرف {buyer_name} ({uid}) برایت شارژ شد.\n💰 موجودی جدید: {balance_after:,} Meow', now))
            event_kind = 'meow_purchase_activated'
            event_payload = {'target_user_id': target, 'meow_amount': meow, 'balance_after': balance_after}
        elif kind == 'meow_gift_code':
            meow = int(order.get('meow_amount') or 0)
            if meow < MEOW_MIN_PURCHASE:
                raise ValueError('INVALID_MEOW_GIFT_PURCHASE')
            code = _new_meow_gift_code_tx(con, uid, meow, oid, now)
            con.execute('UPDATE premium_orders SET gift_code=? WHERE order_id=?', (code, oid))
            event_kind = 'meow_gift_code_activated'
            event_payload = {'gift_code': code, 'meow_amount': meow}
        else:
            gid = int(order.get('group_id') or 0)
            plan = normalize_plan(order.get('plan'))
            days = int(order.get('duration_days') or 0)
            if gid <= 0 or plan not in {PLAN_SILVER, PLAN_GOLD, PLAN_DIAMOND} or days not in DURATION_ORDER:
                raise ValueError('INVALID_SUBSCRIPTION')
            srow = con.execute('SELECT * FROM premium_subscriptions WHERE group_id=?', (gid,)).fetchone()
            existing = dict(srow) if srow is not None else {}
            current_expiry = _parse_iso(existing.get('expires_at'))
            start_base = current_expiry if current_expiry is not None and current_expiry > now_dt and existing.get('plan') == plan else now_dt
            expires = start_base + timedelta(days=days)
            grace = expires + timedelta(hours=grace_hours)
            con.execute(
                """INSERT INTO premium_subscriptions
                   (group_id,plan,status,buyer_user_id,started_at,expires_at,grace_until,source,order_id,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(group_id) DO UPDATE SET
                   plan=excluded.plan,status=excluded.status,buyer_user_id=excluded.buyer_user_id,
                   started_at=excluded.started_at,expires_at=excluded.expires_at,grace_until=excluded.grace_until,
                   source=excluded.source,order_id=excluded.order_id,updated_at=excluded.updated_at""",
                (gid, plan, 'active', uid, now, expires.isoformat(), grace.isoformat(), source_text, oid, now),
            )
            activated_group_id = gid
            event_kind = 'subscription_activated'
            event_payload = {
                'group_id': gid, 'plan': plan, 'duration_days': days,
                'expires_at': expires.isoformat(), 'grace_until': grace.isoformat(),
            }

        con.execute(
            """UPDATE premium_orders
               SET status='activated',paid_at=COALESCE(paid_at,?),verified_at=?,updated_at=?
               WHERE order_id=?""",
            (now, now, now, oid),
        )
        con.execute(
            """INSERT INTO premium_payment_events(order_id,event_kind,external_id,payload_json,created_at)
               VALUES(?,?,?,?,?)""",
            (oid, event_kind, source_text, json.dumps(event_payload, ensure_ascii=False)[:4000], now),
        )
        con.commit()

    if activated_group_id > 0:
        _PLAN_CACHE.pop(activated_group_id, None)
    result = get_order(oid) or {}
    if wallet_after is not None:
        result['wallet_balance_after_rial'] = int(wallet_after)
    elif activated_group_id > 0:
        result['subscription'] = get_subscription(activated_group_id, use_cache=False)
    return result


def reject_order(order_id: int, note: str = '') -> Dict[str, Any]:
    """Reject an unpaid/manual-receipt order without racing an activation."""
    init_db()
    oid = int(order_id or 0)
    if oid <= 0:
        raise ValueError('ORDER_NOT_FOUND')
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM premium_orders WHERE order_id=?', (oid,)).fetchone()
        if row is None:
            raise ValueError('ORDER_NOT_FOUND')
        status = str(row['status'] or '')
        if status == 'activated':
            raise ValueError('ORDER_ALREADY_ACTIVATED')
        if status == 'rejected':
            con.rollback()
            return dict(row)
        con.execute(
            """UPDATE premium_orders SET status='rejected',receipt_note=?,updated_at=? WHERE order_id=?""",
            (str(note or 'admin-rejected')[:1000], now, oid),
        )
        con.execute(
            """INSERT INTO premium_payment_events(order_id,event_kind,external_id,payload_json,created_at)
               VALUES(?,?,?,?,?)""",
            (oid, 'order_rejected', 'admin', json.dumps({'note': str(note or '')[:1000]}, ensure_ascii=False), now),
        )
        con.commit()
    return get_order(oid) or {}


def set_checkout_session(user_id: int, group_id: int, group_title: str = '', order_id: int = 0, stage: str = 'group-selected', ttl_minutes: int = 60) -> None:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=max(5, min(1440, int(ttl_minutes))))
    with _connect() as con:
        con.execute(
            '''INSERT INTO premium_checkout_sessions(user_id,group_id,group_title,order_id,stage,expires_at,updated_at)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
               group_id=excluded.group_id,group_title=excluded.group_title,order_id=excluded.order_id,
               stage=excluded.stage,expires_at=excluded.expires_at,updated_at=excluded.updated_at''',
            (int(user_id), int(group_id), str(group_title or '')[:200], int(order_id or 0), str(stage), expires.isoformat(), now.isoformat()),
        )


def get_checkout_session(user_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as con:
        row = con.execute('SELECT * FROM premium_checkout_sessions WHERE user_id=?', (int(user_id),)).fetchone()
    if row is None:
        return None
    data = dict(row)
    expiry = _parse_iso(data.get('expires_at'))
    if expiry is not None and expiry < datetime.now(timezone.utc):
        clear_checkout_session(user_id)
        return None
    return data


def clear_checkout_session(user_id: int) -> None:
    with _connect() as con:
        con.execute('DELETE FROM premium_checkout_sessions WHERE user_id=?', (int(user_id),))



def queue_group_notification(group_id: int, order_id: int, text: str, kind: str = 'subscription-activated') -> int:
    gid = int(group_id or 0)
    body = str(text or '').strip()
    if gid <= 0 or not body:
        return 0
    now = _now_iso()
    oid = int(order_id or 0)
    notification_kind = str(kind or 'subscription-activated')[:80]
    with _connect() as con:
        if oid > 0:
            con.execute(
                '''INSERT OR IGNORE INTO premium_group_notifications(group_id,order_id,kind,text,status,created_at)
                   VALUES(?,?,?,?, 'queued', ?)''',
                (gid, oid, notification_kind, body[:4000], now),
            )
            row = con.execute(
                'SELECT notification_id FROM premium_group_notifications WHERE order_id=? AND kind=?',
                (oid, notification_kind),
            ).fetchone()
            return int(row['notification_id'] or 0) if row is not None else 0
        cur = con.execute(
            '''INSERT INTO premium_group_notifications(group_id,order_id,kind,text,status,created_at)
               VALUES(?,?,?,?, 'queued', ?)''',
            (gid, 0, notification_kind, body[:4000], now),
        )
        return int(cur.lastrowid or 0)


def pending_group_notifications(limit: int = 20) -> List[Dict[str, Any]]:
    now = _now_iso()
    with _connect() as con:
        rows = con.execute(
            '''SELECT * FROM premium_group_notifications
               WHERE status IN ('queued','retry') AND (next_attempt_at IS NULL OR next_attempt_at<=?)
               ORDER BY notification_id LIMIT ?''',
            (now, max(1, min(100, int(limit or 20)))),
        ).fetchall()
    return [dict(row) for row in rows]


def claim_group_notification(notification_id: int, account_key: str) -> Optional[Dict[str, Any]]:
    nid = int(notification_id or 0)
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM premium_group_notifications WHERE notification_id=?', (nid,)).fetchone()
        if row is None or str(row['status'] or '') not in {'queued','retry'}:
            con.rollback()
            return None
        next_at = _parse_iso(row['next_attempt_at'])
        if next_at is not None and next_at > datetime.now(timezone.utc):
            con.rollback()
            return None
        con.execute(
            "UPDATE premium_group_notifications SET status='sending',claimed_by=?,attempts=attempts+1 WHERE notification_id=?",
            (str(account_key or '')[:80], nid),
        )
        con.commit()
    with _connect() as con:
        out = con.execute('SELECT * FROM premium_group_notifications WHERE notification_id=?', (nid,)).fetchone()
    return dict(out) if out is not None else None


def finish_group_notification(notification_id: int, success: bool, error: str = '') -> None:
    nid = int(notification_id or 0)
    now_dt = datetime.now(timezone.utc)
    with _connect() as con:
        if success:
            con.execute(
                "UPDATE premium_group_notifications SET status='sent',sent_at=?,last_error='' WHERE notification_id=?",
                (now_dt.isoformat(), nid),
            )
            return
        row = con.execute('SELECT attempts FROM premium_group_notifications WHERE notification_id=?', (nid,)).fetchone()
        attempts = int(row['attempts'] or 1) if row is not None else 1
        delay = min(1800, 20 * (2 ** min(6, max(0, attempts - 1))))
        next_at = now_dt + timedelta(seconds=delay)
        con.execute(
            "UPDATE premium_group_notifications SET status='retry',next_attempt_at=?,last_error=? WHERE notification_id=?",
            (next_at.isoformat(), str(error or '')[:500], nid),
        )


def wallet_balance(user_id: int) -> int:
    init_db()
    uid = int(user_id or 0)
    if uid <= 0:
        return 0
    with _connect() as con:
        row = con.execute('SELECT balance_rial FROM premium_wallets WHERE user_id=?', (uid,)).fetchone()
    return max(0, int(row['balance_rial'] or 0)) if row is not None else 0


def wallet_ledger(user_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    init_db()
    uid = int(user_id or 0)
    with _connect() as con:
        rows = con.execute(
            'SELECT * FROM premium_wallet_ledger WHERE user_id=? ORDER BY ledger_id DESC LIMIT ?',
            (uid, max(1, min(200, int(limit or 20)))),
        ).fetchall()
    return [dict(row) for row in rows]


def adjust_wallet(
    user_id: int,
    delta_rial: int,
    *,
    reason: str = 'admin-adjust',
    source: str = 'telegram-admin',
    order_id: int = 0,
    admin_id: int = 0,
    clamp_zero: bool = True,
) -> Dict[str, Any]:
    init_db()
    uid = int(user_id or 0)
    requested = int(delta_rial or 0)
    if uid <= 0 or requested == 0:
        raise ValueError('INVALID_WALLET_ADJUSTMENT')
    now = _now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT balance_rial FROM premium_wallets WHERE user_id=?', (uid,)).fetchone()
        before = max(0, int(row['balance_rial'] or 0)) if row is not None else 0
        after = before + requested
        if after < 0:
            if not clamp_zero:
                raise ValueError('INSUFFICIENT_WALLET_BALANCE')
            after = 0
        actual = after - before
        con.execute(
            """INSERT INTO premium_wallets(user_id,balance_rial,updated_at) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET balance_rial=excluded.balance_rial,updated_at=excluded.updated_at""",
            (uid, after, now),
        )
        con.execute(
            """INSERT INTO premium_wallet_ledger
               (user_id,delta_rial,balance_before,balance_after,reason,source,order_id,admin_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (uid, actual, before, after, str(reason)[:200], str(source)[:80], int(order_id or 0), int(admin_id or 0), now),
        )
        con.commit()
    return {
        'user_id': uid,
        'requested_delta_rial': requested,
        'actual_delta_rial': actual,
        'balance_before_rial': before,
        'balance_after_rial': after,
    }


def pay_order_with_wallet(order_id: int, user_id: int) -> Dict[str, Any]:
    """Atomically debit the buyer wallet and fulfill any purchasable order.

    Wallet top-up orders are intentionally excluded: paying a wallet top-up
    from the same wallet would be a meaningless circular transaction.  Every
    other commercial order is debited and fulfilled in the same SQLite
    transaction, so retries can never charge or grant twice.
    """
    init_db()
    oid = int(order_id or 0)
    uid = int(user_id or 0)
    if oid <= 0 or uid <= 0:
        raise ValueError('INVALID_WALLET_PAYMENT')
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    try:
        grace_hours = max(0, int(get_setting('grace_hours', '24') or 24))
    except Exception:
        grace_hours = 24
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row = con.execute('SELECT * FROM premium_orders WHERE order_id=?', (oid,)).fetchone()
        if row is None:
            raise ValueError('ORDER_NOT_FOUND')
        order = dict(row)
        if int(order.get('buyer_user_id') or 0) != uid:
            raise ValueError('ORDER_NOT_OWNED')
        status = str(order.get('status') or '')
        if status == 'activated':
            con.rollback()
            return order
        if status in {'rejected', 'cancelled'}:
            raise ValueError('ORDER_NOT_PAYABLE')
        kind = str(order.get('order_kind') or 'subscription')
        if kind == 'wallet_topup':
            raise ValueError('WALLET_TOPUP_CANNOT_USE_WALLET')
        amount = max(0, int(order.get('amount_rial') or 0))
        if amount <= 0:
            raise ValueError('INVALID_ORDER_AMOUNT')
        wrow = con.execute('SELECT balance_rial FROM premium_wallets WHERE user_id=?', (uid,)).fetchone()
        before = max(0, int(wrow['balance_rial'] or 0)) if wrow is not None else 0
        if before < amount:
            raise ValueError('INSUFFICIENT_WALLET_BALANCE')
        after = before - amount
        con.execute(
            """INSERT INTO premium_wallets(user_id,balance_rial,updated_at) VALUES(?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET balance_rial=excluded.balance_rial,updated_at=excluded.updated_at""",
            (uid, after, now),
        )
        ledger_reason = {
            'subscription': 'subscription-payment',
            'meow_purchase': 'meow-purchase-payment',
            'meow_gift_code': 'meow-gift-payment',
        }.get(kind, 'order-payment')
        con.execute(
            """INSERT INTO premium_wallet_ledger
               (user_id,delta_rial,balance_before,balance_after,reason,source,order_id,admin_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (uid, -amount, before, after, ledger_reason, 'wallet', oid, 0, now),
        )
        activated_group_id = 0
        fulfillment: Dict[str, Any] = {'order_kind': kind}
        if kind == 'meow_purchase':
            target = int(order.get('target_user_id') or 0)
            meow = int(order.get('meow_amount') or 0)
            if target <= 0 or meow < MEOW_MIN_PURCHASE:
                raise ValueError('INVALID_MEOW_PURCHASE')
            meow_after = _credit_meow_tx(con, target, meow, 'purchase', f'wallet-order:{oid}')
            # Stay on the same transaction/connection.  Opening a second
            # connection here while BEGIN IMMEDIATE is held can deadlock the
            # wallet payment path under concurrent requests.
            buyer_row = con.execute(
                'SELECT first_name,username FROM official_private_users WHERE user_id=?',
                (uid,),
            ).fetchone()
            buyer_name = str(
                (buyer_row['first_name'] if buyer_row is not None else '')
                or (buyer_row['username'] if buyer_row is not None else '')
                or uid
            )
            con.execute(
                "INSERT OR IGNORE INTO premium_official_notifications(user_id,order_id,kind,text,status,created_at) VALUES(?,?,?,?,'queued',?)",
                (target, oid, 'meow-purchase-received', f'🐱 {meow:,} Meow از طرف {buyer_name} ({uid}) برایت شارژ شد.\n💰 موجودی جدید: {meow_after:,} Meow', now),
            )
            fulfillment.update({'target_user_id': target, 'meow_amount': meow, 'meow_balance_after': meow_after})
        elif kind == 'meow_gift_code':
            meow = int(order.get('meow_amount') or 0)
            if meow < MEOW_MIN_PURCHASE:
                raise ValueError('INVALID_MEOW_GIFT_PURCHASE')
            gift_code = _new_meow_gift_code_tx(con, uid, meow, oid, now)
            con.execute('UPDATE premium_orders SET gift_code=? WHERE order_id=?', (gift_code, oid))
            fulfillment.update({'gift_code': gift_code, 'meow_amount': meow})
        else:
            gid = int(order.get('group_id') or 0)
            plan = normalize_plan(order.get('plan'))
            days = int(order.get('duration_days') or 0)
            if gid <= 0 or plan not in {PLAN_SILVER, PLAN_GOLD, PLAN_DIAMOND} or days <= 0:
                raise ValueError('INVALID_SUBSCRIPTION')
            srow = con.execute('SELECT * FROM premium_subscriptions WHERE group_id=?', (gid,)).fetchone()
            existing = dict(srow) if srow is not None else {}
            current_expiry = _parse_iso(existing.get('expires_at'))
            start_base = current_expiry if current_expiry is not None and current_expiry > now_dt and existing.get('plan') == plan else now_dt
            expires = start_base + timedelta(days=days)
            grace = expires + timedelta(hours=grace_hours)
            con.execute(
                """INSERT INTO premium_subscriptions
                   (group_id,plan,status,buyer_user_id,started_at,expires_at,grace_until,source,order_id,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(group_id) DO UPDATE SET
                   plan=excluded.plan,status=excluded.status,buyer_user_id=excluded.buyer_user_id,
                   started_at=excluded.started_at,expires_at=excluded.expires_at,grace_until=excluded.grace_until,
                   source=excluded.source,order_id=excluded.order_id,updated_at=excluded.updated_at""",
                (gid, plan, 'active', uid, now, expires.isoformat(), grace.isoformat(), 'wallet', oid, now),
            )
            activated_group_id = gid
            fulfillment.update({'group_id': gid, 'plan': plan, 'duration_days': days, 'expires_at': expires.isoformat()})
        con.execute(
            """UPDATE premium_orders SET method='wallet',status='activated',paid_at=?,verified_at=?,updated_at=?
               WHERE order_id=?""",
            (now, now, now, oid),
        )
        con.execute(
            """INSERT INTO premium_payment_events(order_id,event_kind,external_id,payload_json,created_at)
               VALUES(?,?,?,?,?)""",
            (oid, 'wallet_payment_verified', str(uid), json.dumps({'amount_rial': amount, 'balance_before': before, 'balance_after': after, **fulfillment}, ensure_ascii=False), now),
        )
        con.commit()
    if activated_group_id > 0:
        _PLAN_CACHE.pop(activated_group_id, None)
    result = get_order(oid) or {}
    result['wallet_balance_after_rial'] = after
    return result

def summary() -> Dict[str, Any]:
    with _connect() as con:
        subs = int(con.execute("SELECT COUNT(*) FROM premium_subscriptions WHERE plan!='free'").fetchone()[0] or 0)
        pending_receipts = int(con.execute("SELECT COUNT(*) FROM premium_orders WHERE status='receipt_submitted'").fetchone()[0] or 0)
        gateway_pending = int(con.execute("SELECT COUNT(*) FROM premium_orders WHERE status='gateway_pending'").fetchone()[0] or 0)
        activated = int(con.execute("SELECT COUNT(*) FROM premium_orders WHERE status='activated'").fetchone()[0] or 0)
        total_orders = int(con.execute("SELECT COUNT(*) FROM premium_orders").fetchone()[0] or 0)
        wallet_topups = int(con.execute("SELECT COUNT(*) FROM premium_orders WHERE order_kind='wallet_topup' AND status='activated'").fetchone()[0] or 0)
        wallet_users = int(con.execute("SELECT COUNT(*) FROM premium_wallets WHERE balance_rial>0").fetchone()[0] or 0)
        wallet_total = int(con.execute("SELECT COALESCE(SUM(balance_rial),0) FROM premium_wallets").fetchone()[0] or 0)
    return {
        'premium_groups': subs,
        'pending_receipts': pending_receipts,
        'gateway_pending': gateway_pending,
        'activated_orders': activated,
        'total_orders': total_orders,
        'wallet_topups': wallet_topups,
        'wallet_users': wallet_users,
        'wallet_total_rial': wallet_total,
        **payment_settings(),
    }


# ---------------------------------------------------------------------------
# ZIVO 96.49 manual-payment review / reversible fulfillment ledger
# ---------------------------------------------------------------------------

def _admin_review_event(con: sqlite3.Connection, order_id: int, actor_id: int, action: str, detail: Dict[str, Any] | None = None) -> None:
    con.execute(
        "INSERT INTO premium_manual_review_events(order_id,actor_user_id,action,detail_json,created_at) VALUES(?,?,?,?,?)",
        (int(order_id), int(actor_id or 0), str(action)[:80], json.dumps(detail or {}, ensure_ascii=False)[:8000], _now_iso()),
    )


def manual_receipt_submit(order_id: int, buyer_user_id: int, file_id: str, message_id: int = 0, caption: str = '') -> Dict[str, Any]:
    init_db(); oid=int(order_id); uid=int(buyer_user_id)
    order=get_order(oid)
    if not order or int(order.get('buyer_user_id') or 0)!=uid:
        raise ValueError('ORDER_NOT_FOUND')
    if str(order.get('method') or '')!='card' or str(order.get('status') or '') not in {'awaiting_receipt','receipt_submitted','rejected'}:
        raise ValueError('ORDER_NOT_WAITING_RECEIPT')
    fid=str(file_id or '').strip()
    if not fid: raise ValueError('RECEIPT_PHOTO_REQUIRED')
    now=_now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE premium_orders SET status='receipt_submitted',receipt_path=?,receipt_message_id=?,receipt_note=?,updated_at=? WHERE order_id=?",
                    (fid,int(message_id or 0),str(caption or '')[:1000],now,oid))
        con.execute("""INSERT INTO premium_manual_review(order_id,receipt_file_id,receipt_caption,submitted_by,submitted_at,admin_status,last_action_at)
                     VALUES(?,?,?,?,?,'pending',?) ON CONFLICT(order_id) DO UPDATE SET
                     receipt_file_id=excluded.receipt_file_id,receipt_caption=excluded.receipt_caption,
                     submitted_by=excluded.submitted_by,submitted_at=excluded.submitted_at,
                     admin_status='pending',admin_reason_code='',admin_reason_text='',last_action_at=excluded.last_action_at""",
                    (oid,fid,str(caption or '')[:1000],uid,now,now))
        _admin_review_event(con,oid,uid,'receipt_submitted',{'file_id':fid,'message_id':int(message_id or 0)})
        con.commit()
    return manual_order_detail(oid) or {}


def manual_review_row(order_id: int) -> Dict[str, Any]:
    init_db()
    with _connect() as con:
        row=con.execute('SELECT * FROM premium_manual_review WHERE order_id=?',(int(order_id),)).fetchone()
    return dict(row) if row is not None else {}


def manual_order_detail(order_ref: Any) -> Optional[Dict[str, Any]]:
    init_db(); order=None
    ref=str(order_ref or '').strip()
    if ref.isdigit(): order=get_order(int(ref))
    if order is None: order=get_order_by_code(ref)
    if order is None: return None
    out=dict(order); out['review']=manual_review_row(int(out['order_id']))
    out['buyer']=official_user_state(int(out.get('buyer_user_id') or 0))
    target=int(out.get('target_user_id') or 0)
    out['target']=official_user_state(target) if target>0 else {}
    if int(out.get('group_id') or 0)>0:
        out['subscription']=get_subscription(int(out['group_id']),use_cache=False)
    with _connect() as con:
        ev=con.execute('SELECT * FROM premium_manual_review_events WHERE order_id=? ORDER BY event_id DESC LIMIT 30',(int(out['order_id']),)).fetchall()
    out['review_events']=[dict(r) for r in ev]
    return out


def manual_orders(limit: int = 30, status: str = '') -> List[Dict[str, Any]]:
    init_db(); lim=max(1,min(200,int(limit or 30))); s=str(status or '').strip()
    with _connect() as con:
        if s:
            rows=con.execute("""SELECT o.* FROM premium_orders o LEFT JOIN premium_manual_review r ON r.order_id=o.order_id
                                WHERE COALESCE(r.admin_status,'')=? ORDER BY o.order_id DESC LIMIT ?""",(s,lim)).fetchall()
        else:
            rows=con.execute("SELECT * FROM premium_orders ORDER BY order_id DESC LIMIT ?",(lim,)).fetchall()
    return [dict(r) for r in rows]


def _capture_activation_snapshot_tx(con: sqlite3.Connection, order: Dict[str, Any]) -> Dict[str, Any]:
    kind=str(order.get('order_kind') or 'subscription')
    snap={'kind':kind,'captured_at':_now_iso()}
    if kind=='subscription':
        gid=int(order.get('group_id') or 0)
        row=con.execute('SELECT * FROM premium_subscriptions WHERE group_id=?',(gid,)).fetchone()
        snap['subscription_before']=dict(row) if row is not None else None
    elif kind=='meow_purchase':
        uid=int(order.get('target_user_id') or 0)
        _ensure_meow_tables_tx(con)
        row=con.execute('SELECT balance,total_earned,total_spent FROM social_meow_accounts WHERE user_id=?',(uid,)).fetchone()
        snap['target_user_id']=uid; snap['meow_before']=dict(row) if row is not None else {'balance':0,'total_earned':0,'total_spent':0}
    elif kind=='meow_gift_code':
        snap['gift_before']=None
    return snap


def admin_approve_manual(order_id: int, admin_id: int) -> Dict[str, Any]:
    init_db(); oid=int(order_id); aid=int(admin_id)
    order=get_order(oid)
    if not order: raise ValueError('ORDER_NOT_FOUND')
    status=str(order.get('status') or '')
    if status=='activated': return manual_order_detail(oid) or order
    now=_now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT * FROM premium_orders WHERE order_id=?',(oid,)).fetchone(); order=dict(row)
        if str(order.get('status') or '') in {'rejected','cancelled'}:
            # Explicit admin reconsideration: reopen using the already attached receipt.
            if not str(order.get('receipt_path') or '').strip(): raise ValueError('RECEIPT_REQUIRED_TO_REOPEN')
            con.execute("UPDATE premium_orders SET status='receipt_submitted',updated_at=? WHERE order_id=?",(now,oid)); order['status']='receipt_submitted'
        snap=_capture_activation_snapshot_tx(con,order)
        con.execute("""INSERT INTO premium_manual_review(order_id,admin_status,admin_id,activation_snapshot_json,last_action_at)
                     VALUES(?,'approving',?,?,?) ON CONFLICT(order_id) DO UPDATE SET
                     admin_status='approving',admin_id=excluded.admin_id,activation_snapshot_json=excluded.activation_snapshot_json,last_action_at=excluded.last_action_at""",
                    (oid,aid,json.dumps(snap,ensure_ascii=False),now))
        _admin_review_event(con,oid,aid,'approve_requested',snap)
        con.commit()
    activated=approve_order(oid,f'manual-admin:{aid}')
    if str(activated.get('order_kind') or '') == 'meow_gift_code' and str(activated.get('gift_code') or ''):
        with _connect() as con:
            con.execute("UPDATE premium_meow_gift_codes SET status='active',redeemed_by=0,redeemed_at=NULL WHERE code=? AND status='revoked'", (str(activated.get('gift_code')),))
            con.commit()
    with _connect() as con:
        con.execute("UPDATE premium_manual_review SET admin_status='approved',admin_id=?,admin_reason_code='',admin_reason_text='',last_action_at=? WHERE order_id=?",(aid,_now_iso(),oid))
        _admin_review_event(con,oid,aid,'approved',{'status':'activated'})
        con.commit()
    return manual_order_detail(oid) or activated


def admin_reject_manual(order_id: int, admin_id: int, reason_code: str, reason_text: str = '') -> Dict[str, Any]:
    init_db(); oid=int(order_id); aid=int(admin_id); code=str(reason_code or 'other')[:80]; text=str(reason_text or '')[:1500]
    order=get_order(oid)
    if not order: raise ValueError('ORDER_NOT_FOUND')
    if str(order.get('status') or '')=='activated':
        return admin_reverse_manual(oid,aid,code,text)
    now=_now_iso()
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        con.execute("UPDATE premium_orders SET status='rejected',receipt_note=?,updated_at=? WHERE order_id=?",(text or code,now,oid))
        con.execute("""INSERT INTO premium_manual_review(order_id,admin_status,admin_id,admin_reason_code,admin_reason_text,last_action_at)
                     VALUES(?,'rejected',?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET
                     admin_status='rejected',admin_id=excluded.admin_id,admin_reason_code=excluded.admin_reason_code,
                     admin_reason_text=excluded.admin_reason_text,last_action_at=excluded.last_action_at""",(oid,aid,code,text,now))
        _admin_review_event(con,oid,aid,'rejected',{'reason_code':code,'reason_text':text})
        con.commit()
    return manual_order_detail(oid) or {}


def _set_meow_balance_allow_negative_tx(con: sqlite3.Connection, user_id: int, delta: int, reference: str) -> int:
    uid=int(user_id); change=int(delta); now=int(datetime.now(timezone.utc).timestamp()); _ensure_meow_tables_tx(con)
    row=con.execute('SELECT balance,total_earned,total_spent FROM social_meow_accounts WHERE user_id=?',(uid,)).fetchone()
    if row is None:
        con.execute('INSERT INTO social_meow_accounts(user_id,balance,total_earned,total_spent,last_claim_at,created_at,updated_at) VALUES(?,0,0,0,0,?,?)',(uid,now,now))
        before=0
    else: before=int(row['balance'] or 0)
    after=before+change
    con.execute('UPDATE social_meow_accounts SET balance=?,updated_at=? WHERE user_id=?',(after,now,uid))
    con.execute('INSERT INTO social_meow_ledger(user_id,delta,balance_after,kind,reference,created_at) VALUES(?,?,?,?,?,?)',(uid,change,after,'admin-order-reversal',str(reference)[:120],now))
    return after


def admin_reverse_manual(order_id: int, admin_id: int, reason_code: str='admin-reversal', reason_text: str='') -> Dict[str, Any]:
    init_db(); oid=int(order_id); aid=int(admin_id); now=_now_iso()
    order=get_order(oid)
    if not order: raise ValueError('ORDER_NOT_FOUND')
    if str(order.get('status') or '')!='activated':
        return admin_reject_manual(oid,aid,reason_code,reason_text)
    review=manual_review_row(oid); snap={}
    try: snap=json.loads(str(review.get('activation_snapshot_json') or '{}'))
    except Exception: snap={}
    kind=str(order.get('order_kind') or 'subscription'); result_meta={}
    with _connect() as con:
        con.execute('BEGIN IMMEDIATE')
        if kind=='subscription':
            gid=int(order.get('group_id') or 0); before=snap.get('subscription_before')
            current=con.execute('SELECT * FROM premium_subscriptions WHERE group_id=?',(gid,)).fetchone()
            # Only mutate the live plan when this order still owns the subscription.
            if current is not None and int(current['order_id'] or 0)==oid:
                if isinstance(before,dict) and int(before.get('group_id') or 0)==gid:
                    con.execute("""INSERT INTO premium_subscriptions(group_id,plan,status,buyer_user_id,started_at,expires_at,grace_until,source,order_id,updated_at)
                                 VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(group_id) DO UPDATE SET plan=excluded.plan,status=excluded.status,buyer_user_id=excluded.buyer_user_id,
                                 started_at=excluded.started_at,expires_at=excluded.expires_at,grace_until=excluded.grace_until,source=excluded.source,order_id=excluded.order_id,updated_at=excluded.updated_at""",
                                (gid,str(before.get('plan') or 'free'),str(before.get('status') or 'active'),int(before.get('buyer_user_id') or 0),before.get('started_at'),before.get('expires_at'),before.get('grace_until'),str(before.get('source') or 'rollback'),int(before.get('order_id') or 0),now))
                    result_meta['subscription_restored']=True
                else:
                    con.execute("DELETE FROM premium_subscriptions WHERE group_id=?",(gid,)); result_meta['subscription_restored']='free'
            else: result_meta['subscription_restored']='skipped-newer-order'
        elif kind=='meow_purchase':
            target=int(order.get('target_user_id') or 0); amount=int(order.get('meow_amount') or 0)
            result_meta['meow_balance_after']=_set_meow_balance_allow_negative_tx(con,target,-amount,f'order:{oid}')
        elif kind=='meow_gift_code':
            code=str(order.get('gift_code') or '')
            grow=con.execute('SELECT * FROM premium_meow_gift_codes WHERE code=?',(code,)).fetchone() if code else None
            if grow is not None:
                if str(grow['status'] or '')=='redeemed':
                    redeemer=int(grow['redeemed_by'] or 0); amount=int(grow['meow_amount'] or 0)
                    result_meta['redeemer_balance_after']=_set_meow_balance_allow_negative_tx(con,redeemer,-amount,f'gift-reversal:{code}')
                con.execute("UPDATE premium_meow_gift_codes SET status='revoked' WHERE code=?",(code,)); result_meta['gift_revoked']=code
        elif kind=='wallet_topup':
            uid=int(order.get('buyer_user_id') or 0); amount=int(order.get('amount_rial') or 0)
            w=con.execute('SELECT balance_rial FROM premium_wallets WHERE user_id=?',(uid,)).fetchone(); before=int(w['balance_rial'] or 0) if w else 0; after=max(0,before-amount); actual=after-before
            con.execute("INSERT INTO premium_wallets(user_id,balance_rial,updated_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET balance_rial=excluded.balance_rial,updated_at=excluded.updated_at",(uid,after,now))
            con.execute("INSERT INTO premium_wallet_ledger(user_id,delta_rial,balance_before,balance_after,reason,source,order_id,admin_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",(uid,actual,before,after,'admin-order-reversal','manual-admin',oid,aid,now)); result_meta['wallet_balance_after']=after; result_meta['wallet_unrecovered_rial']=max(0,amount-before)
        con.execute("UPDATE premium_orders SET status='reversed',receipt_note=?,updated_at=? WHERE order_id=?",(str(reason_text or reason_code)[:1000],now,oid))
        con.execute("""INSERT INTO premium_manual_review(order_id,admin_status,admin_id,admin_reason_code,admin_reason_text,last_action_at)
                     VALUES(?,'reversed',?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET admin_status='reversed',admin_id=excluded.admin_id,
                     admin_reason_code=excluded.admin_reason_code,admin_reason_text=excluded.admin_reason_text,last_action_at=excluded.last_action_at""",(oid,aid,str(reason_code)[:80],str(reason_text)[:1500],now))
        _admin_review_event(con,oid,aid,'reversed',result_meta)
        con.commit()
    if kind=='subscription' and int(order.get('group_id') or 0)>0: _PLAN_CACHE.pop(int(order['group_id']),None)
    out=manual_order_detail(oid) or {}; out['reversal']=result_meta; return out


def queue_official_notice(user_id: int, order_id: int, kind: str, text: str) -> None:
    init_db(); uid=int(user_id); oid=int(order_id); now=_now_iso()
    with _connect() as con:
        con.execute("INSERT OR IGNORE INTO premium_official_notifications(user_id,order_id,kind,text,status,created_at) VALUES(?,?,?,?,'queued',?)",(uid,oid,str(kind)[:80],str(text)[:3900],now)); con.commit()
