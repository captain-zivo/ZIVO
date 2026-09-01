from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import zivo_premium as premium

ROOT = Path(__file__).resolve().parent
MAIN = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
PREMIUM_SRC = (ROOT / 'zivo_premium.py').read_text(encoding='utf-8')
INSTALLER = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')

assert 'VERSION = "zivo60.96.39.4"' in MAIN


def create_96_38_orders_table(db: Path) -> None:
    con = sqlite3.connect(db)
    try:
        con.executescript(
            '''
            CREATE TABLE premium_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                group_title TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                amount_rial INTEGER NOT NULL,
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
            INSERT INTO premium_orders(
                buyer_user_id,group_id,group_title,plan,duration_days,amount_rial,
                method,status,created_at,updated_at
            ) VALUES(49123456,24000041,'Legacy Group','silver',30,550000,'card','created',
                     '2026-08-29T00:00:00+00:00','2026-08-29T00:00:00+00:00');
            '''
        )
        con.commit()
    finally:
        con.close()


# 1) Exact 96.38 schema: order_code/order_kind do not exist at all.
with tempfile.TemporaryDirectory(prefix='zivo-premium-9638-') as td:
    db = Path(td) / 'legacy.db'
    create_96_38_orders_table(db)
    premium._SCHEMA_READY.discard(str(db.resolve()))
    premium.configure(db)

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in con.execute('PRAGMA table_info(premium_orders)')}
        assert {'order_code', 'order_kind'}.issubset(columns), columns
        row = con.execute('SELECT order_code,order_kind FROM premium_orders WHERE order_id=1').fetchone()
        assert row is not None
        assert str(row['order_code']).startswith('ZV-'), dict(row)
        assert row['order_kind'] == 'subscription', dict(row)
        indexes = {row[1] for row in con.execute("PRAGMA index_list('premium_orders')")}
        assert 'idx_premium_orders_code' in indexes, indexes
        assert con.execute('PRAGMA quick_check').fetchone()[0].lower() == 'ok'
    finally:
        con.close()

    # Re-running configure/init_db is idempotent and must not mutate the code.
    old_code = premium.get_order(1)['order_code']
    premium._SCHEMA_READY.discard(str(db.resolve()))
    premium.configure(db)
    assert premium.get_order(1)['order_code'] == old_code

    # A new 96.39+ order can be created immediately after the legacy migration.
    created = premium.create_order(49123456, 24000041, 'Legacy Group', 'gold', 60)
    assert str(created['order_code']).startswith('ZV-')
    assert created['order_code'] != old_code


# 2) Interrupted/partial migration: columns exist but duplicate public codes do not
# yet have their UNIQUE index.  Migration must repair this before creating index.
with tempfile.TemporaryDirectory(prefix='zivo-premium-partial-') as td:
    db = Path(td) / 'partial.db'
    con = sqlite3.connect(db)
    try:
        con.executescript(
            '''
            CREATE TABLE premium_orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT NOT NULL DEFAULT '',
                order_kind TEXT NOT NULL DEFAULT 'subscription',
                buyer_user_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                group_title TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL,
                duration_days INTEGER NOT NULL,
                amount_rial INTEGER NOT NULL,
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
            INSERT INTO premium_orders(order_code,buyer_user_id,group_id,group_title,plan,duration_days,amount_rial,created_at,updated_at)
            VALUES('ZV-ABC-ABCDE',11,101,'A','silver',30,550000,'2026-08-29T00:00:00+00:00','2026-08-29T00:00:00+00:00');
            INSERT INTO premium_orders(order_code,buyer_user_id,group_id,group_title,plan,duration_days,amount_rial,created_at,updated_at)
            VALUES('ZV-ABC-ABCDE',12,102,'B','gold',30,990000,'2026-08-29T00:00:00+00:00','2026-08-29T00:00:00+00:00');
            '''
        )
        con.commit()
    finally:
        con.close()

    premium._SCHEMA_READY.discard(str(db.resolve()))
    premium.configure(db)
    con = sqlite3.connect(db)
    try:
        codes = [r[0] for r in con.execute('SELECT order_code FROM premium_orders ORDER BY order_id')]
        assert len(codes) == len(set(codes)) == 2, codes
        assert all(str(code).startswith('ZV-') for code in codes), codes
        indexes = {row[1] for row in con.execute("PRAGMA index_list('premium_orders')")}
        assert 'idx_premium_orders_code' in indexes, indexes
        assert con.execute('PRAGMA quick_check').fetchone()[0].lower() == 'ok'
    finally:
        con.close()

# 3) Static ordering contract: premature order_code index is not in the base
# executescript; migration creates it only after the ALTER TABLE guards.
base_script_pos = PREMIUM_SRC.index('CREATE TABLE IF NOT EXISTS premium_orders')
migration_comment_pos = PREMIUM_SRC.index('Durable, ordered migrations')
index_pos = PREMIUM_SRC.index('CREATE UNIQUE INDEX IF NOT EXISTS idx_premium_orders_code')
assert base_script_pos < migration_comment_pos < index_pos
assert PREMIUM_SRC.index("ALTER TABLE premium_orders ADD COLUMN order_code") < index_pos
assert "con.execute('BEGIN IMMEDIATE')" in PREMIUM_SRC

# 4) Installer must ship and execute this live-schema migration regression.
deploy_block = INSTALLER.split('DEPLOY_FILES=(', 1)[1].split('\n)', 1)[0]
assert 'check_zivo60_96_39_4_premium_schema_migration.py' in deploy_block
assert INSTALLER.count('check_zivo60_96_39_4_premium_schema_migration.py') >= 4

print('CHECK ZIVO60.96.39.4 PREMIUM SCHEMA MIGRATION: PASS')
print('  exact 96.38 DB without order_code/order_kind migrates before index creation: PASS')
print('  legacy orders receive stable public ZV codes: PASS')
print('  interrupted duplicate-code migration is repaired before UNIQUE index: PASS')
print('  repeated init_db/configure remains idempotent: PASS')
print('  post-migration order creation + SQLite quick_check: PASS')
print('  migration regression is deployed and executed by installer: PASS')
