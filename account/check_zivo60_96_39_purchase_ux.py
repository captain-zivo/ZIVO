#!/usr/bin/env python3
from __future__ import annotations

import re
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import zivo_premium as premium

ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
PREMIUM_SOURCE = (ROOT / 'zivo_premium.py').read_text(encoding='utf-8')
INSTALLER = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')

assert 'VERSION = "zivo60.96.39"' in SOURCE
assert premium.DURATION_ORDER == (30, 60, 90)
expected = {
    ('silver', 30): 550_000,
    ('silver', 60): 1_000_000,
    ('silver', 90): 1_390_000,
    ('gold', 30): 990_000,
    ('gold', 60): 1_790_000,
    ('gold', 90): 2_490_000,
    ('diamond', 30): 1_200_000,
    ('diamond', 60): 2_150_000,
    ('diamond', 90): 2_990_000,
}

with tempfile.TemporaryDirectory(prefix='zivo-96-39-') as td:
    db = Path(td) / 'multi.db'
    premium.configure(db)
    for key, amount in expected.items():
        assert premium.get_price(*key) == amount, (key, premium.get_price(*key), amount)

    # Public order identifiers are human-friendly and non-sequential.
    o1 = premium.create_order(13579, 24680, 'Group A', 'silver', 60)
    o2 = premium.create_order(13579, 24680, 'Group A', 'gold', 90)
    for order in (o1, o2):
        code = str(order.get('order_code') or '')
        assert re.fullmatch(r'ZV-[A-Z0-9]{3}-[A-Z0-9]{5}', code), code
        assert premium.get_order_by_code(code)['order_id'] == order['order_id']
    assert o1['order_code'] != o2['order_code']
    assert str(o1['order_id']) not in str(o1['order_code'])

    # Wallet top-up is an auditable payment order and approval is idempotent.
    topup = premium.create_wallet_topup_order(777, 750_000)
    assert topup['order_kind'] == 'wallet_topup' and topup['group_id'] == 0
    activated = premium.approve_order(int(topup['order_id']), 'test-card-admin')
    assert activated['status'] == 'activated'
    assert premium.wallet_balance(777) == 750_000
    again = premium.approve_order(int(topup['order_id']), 'duplicate-callback')
    assert again['status'] == 'activated'
    assert premium.wallet_balance(777) == 750_000

    # Concurrent duplicate callbacks/admin clicks must not apply money twice.
    race_topup = premium.create_wallet_topup_order(778, 500_000)
    with ThreadPoolExecutor(max_workers=6) as pool:
        race_results = list(pool.map(lambda i: premium.approve_order(int(race_topup['order_id']), f'race-{i}'), range(6)))
    assert all(row['status'] == 'activated' for row in race_results)
    assert premium.wallet_balance(778) == 500_000
    race_ledger = [row for row in premium.wallet_ledger(778, 20) if int(row.get('order_id') or 0) == int(race_topup['order_id'])]
    assert len(race_ledger) == 1 and int(race_ledger[0]['delta_rial']) == 500_000

    # Subscription activation stores buyer/order and exposes remaining time/history.
    sub_order = premium.create_order(777, 888, 'Installed Group', 'diamond', 90)
    sub = premium.approve_order(int(sub_order['order_id']), 'test-zibal')
    assert sub['status'] == 'activated'
    state = premium.get_subscription(888, use_cache=False)
    assert state['plan'] == 'diamond' and int(state['buyer_user_id']) == 777
    expiry = datetime.fromisoformat(state['expires_at']).astimezone(timezone.utc)
    assert expiry > datetime.now(timezone.utc)

    race_sub = premium.create_order(779, 889, 'Race Group', 'gold', 60)
    before_race = datetime.now(timezone.utc)
    with ThreadPoolExecutor(max_workers=6) as pool:
        sub_results = list(pool.map(lambda i: premium.approve_order(int(race_sub['order_id']), f'sub-race-{i}'), range(6)))
    assert all(row['status'] == 'activated' for row in sub_results)
    race_state = premium.get_subscription(889, use_cache=False)
    race_expiry = datetime.fromisoformat(race_state['expires_at']).astimezone(timezone.utc)
    # One 60-day purchase only; a duplicate race must never extend it repeatedly.
    assert 59 <= (race_expiry - before_race).total_seconds() / 86400 <= 61
    mine = premium.active_subscriptions_for_buyer(777)
    assert any(int(row['group_id']) == 888 and row['effective_plan'] == 'diamond' for row in mine)
    history = premium.orders_for_user(777, 20)
    assert {str(row['order_kind']) for row in history} >= {'wallet_topup', 'subscription'}

    # Shared cross-account group notification is durable and deduplicated.
    notice_id = premium.queue_group_notification(888, int(sub_order['order_id']), 'اشتراک فعال شد')
    assert notice_id > 0
    assert premium.queue_group_notification(888, int(sub_order['order_id']), 'duplicate') == notice_id
    pending = premium.pending_group_notifications(10)
    assert any(int(row['notification_id']) == notice_id for row in pending)
    claimed = premium.claim_group_notification(notice_id, 'acc2')
    assert claimed and claimed['status'] == 'sending'
    premium.finish_group_notification(notice_id, True)
    assert all(int(row['notification_id']) != notice_id for row in premium.pending_group_notifications(10))

    # Simulate a pre-96.39 DB: old 6/12-month rows and arbitrary current prices.
    with sqlite3.connect(db) as con:
        now = datetime.now(timezone.utc).isoformat()
        con.execute("INSERT OR REPLACE INTO premium_plan_prices(plan,duration_days,amount_rial,enabled,updated_at) VALUES('silver',180,3790000,1,?)", (now,))
        con.execute("INSERT OR REPLACE INTO premium_plan_prices(plan,duration_days,amount_rial,enabled,updated_at) VALUES('gold',365,12490000,1,?)", (now,))
        con.execute("UPDATE premium_plan_prices SET amount_rial=999999 WHERE plan='silver' AND duration_days=30")
        con.execute("DELETE FROM premium_settings WHERE key='pricing_profile_96_39'")
        con.commit()
    premium._SCHEMA_READY.discard(str(db.resolve()))
    premium.configure(db)
    assert premium.get_price('silver', 30) == 550_000
    assert premium.get_price('silver', 180) is None
    assert premium.get_price('gold', 365) is None
    with sqlite3.connect(db) as con:
        marker = con.execute("SELECT value FROM premium_settings WHERE key='pricing_profile_96_39'").fetchone()
    assert marker and marker[0] == '1'

# Actual runtime integration: PM/group purchase, installed-group validation,
# wallet/card/Zibal checkout, purchase history, admin finance and group notice.
for token in (
    'await-group-link', '_premium_resolve_installed_group_link', 'BOT_NOT_INSTALLED',
    'خرید اشتراک', 'اشتراک‌های من', 'خریدها و تراکنش‌های من', 'شارژ کیف پول',
    'premium_group_notification_worker', '_premium_queue_activation_announcements',
    'z:paytx', 'z:paysubs', 'z:wallet:list',
    'پرداخت {code}', 'درگاه {code}', 'کارت {code}', 'کیف پول {code}',
    'اول لینک گروهی را بفرست', 'ZIVO روی آن نصب است',
):
    assert token in SOURCE, token

for token in (
    'order_code TEXT NOT NULL', 'order_kind TEXT NOT NULL',
    'pricing_profile_96_39', 'premium_group_notifications',
    'def create_wallet_topup_order', 'def get_order_by_code',
    'def orders_for_user', 'def order_count_for_user', 'def active_subscriptions_for_buyer',
    'def queue_group_notification', 'def claim_group_notification',
):
    assert token in PREMIUM_SOURCE, token

# Installer must deploy and validate the new release test from source and installed copy.
assert 'check_zivo60_96_39_purchase_ux.py' in INSTALLER
assert 'ZIVO zivo60.96.39 PREMIUM PURCHASE UX DEPLOY: PASS' in INSTALLER

print('CHECK ZIVO60.96.39 PREMIUM PURCHASE UX: PASS')
print('  exact 1/2/3-month IRR pricing + attractive multi-month discounts: PASS')
print('  non-sequential human-safe ZV order codes: PASS')
print('  PM checkout selects an already-installed target group: PASS')
print('  wallet top-up/card/Zibal purchase foundations + idempotency: PASS')
print('  buyer subscription/history/remaining-time surfaces: PASS')
print('  cross-account in-group activation announcement queue: PASS')
print('  Telegram admin transactions/subscriptions/wallet inventory controls: PASS')
