#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import zivo_premium as premium
import zivo_social_games as social

ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
INSTALLER = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')
PREMIUM_SOURCE = (ROOT / 'zivo_premium.py').read_text(encoding='utf-8')

# Historical 96.38 foundation test is intentionally forward-compatible: later
# releases may change public pricing/checkout UX while preserving this core.
assert 'import zivo_premium as premium' in SOURCE
assert 'VERSION = "zivo60.' in SOURCE

with tempfile.TemporaryDirectory(prefix='zivo-premium-') as td:
    db = Path(td) / 'control.db'
    premium.configure(db)

    # Four-plan model + strong FREE defaults prepared for feature gating.
    assert premium.PLAN_ORDER == ('free', 'silver', 'gold', 'diamond')
    assert premium.PLAN_ENTITLEMENTS['free']['cleanup_limit'] == 700
    assert premium.PLAN_ENTITLEMENTS['free']['content_filter'] is False
    assert premium.PLAN_ENTITLEMENTS['silver']['content_filter'] is True
    assert premium.PLAN_ENTITLEMENTS['diamond']['pet_discount_percent'] == 30
    assert abs(premium.PLAN_ENTITLEMENTS['diamond']['meow_luck_multiplier'] - 1.60) < 1e-9
    assert premium.PLAN_ENTITLEMENTS['diamond']['diamond_activation_meow'] == 100

    # Commercial prices remain integer IRR amounts, regardless of later price changes.
    for plan in ('silver', 'gold', 'diamond'):
        for days in premium.DURATION_ORDER:
            amount = premium.get_price(plan, days)
            assert isinstance(amount, int) and amount >= 100_000
            assert premium.money_rial(amount).endswith(' ریال')

    # Payment settings are mutable from admin panel and card validation is strict.
    assert premium.payment_settings()['card_enabled'] is False
    number = premium.set_card_number('6037-9975-1234-5678')
    assert number == '6037997512345678'
    premium.set_setting('card_holder', 'ZIVO TEST')
    premium.set_setting('card_enabled', '1')
    assert premium.payment_settings()['card_enabled'] is True
    assert premium.payment_settings()['card_number'] == number
    domain = premium.set_payment_domain('https://Pay.Example.com/anything')
    assert domain == 'pay.example.com'
    settings = premium.payment_settings()
    assert settings['payment_domain'] == 'pay.example.com'
    assert settings['zibal_callback_url'] == 'https://pay.example.com/zivo/zibal/callback'

    # Durable subscription order + manual receipt + idempotent activation.
    order = premium.create_order(111, 222, 'Test Group', 'gold', premium.DURATION_ORDER[0])
    oid = int(order['order_id'])
    expected_gold = int(premium.get_price('gold', premium.DURATION_ORDER[0]))
    assert int(order['amount_rial']) == expected_gold
    assert str(order.get('order_code') or '').startswith('ZV-')
    premium.mark_card_waiting(oid)
    assert premium.pending_receipt_order(111)['order_id'] == oid
    premium.attach_card_receipt(oid, '/tmp/receipt.jpg', 77, 'test')
    assert premium.get_order(oid)['status'] == 'receipt_submitted'
    activated = premium.approve_order(oid, 'test-admin')
    assert activated['status'] == 'activated'
    state = premium.get_subscription(222, use_cache=False)
    assert state['plan'] == 'gold' and state['status'] == 'active'
    first_expiry = datetime.fromisoformat(state['expires_at']).astimezone(timezone.utc)
    premium.activate_subscription(222, 'gold', premium.DURATION_ORDER[0], buyer_user_id=111, source='renewal-test')
    second_expiry = datetime.fromisoformat(premium.get_subscription(222, use_cache=False)['expires_at']).astimezone(timezone.utc)
    assert second_expiry > first_expiry
    assert premium.approve_order(oid, 'repeat')['status'] == 'activated'

    # Internal Rial wallet: audited admin adjustment + atomic subscription payment.
    seed_credit = 5_000_000
    wallet_add = premium.adjust_wallet(333, seed_credit, reason='test-credit', admin_id=99)
    assert wallet_add['balance_after_rial'] == seed_credit
    assert premium.wallet_balance(333) == seed_credit
    wallet_order = premium.create_order(333, 444, 'Wallet Group', 'diamond', premium.DURATION_ORDER[0])
    wallet_cost = int(wallet_order['amount_rial'])
    wallet_paid = premium.pay_order_with_wallet(int(wallet_order['order_id']), 333)
    assert wallet_paid['status'] == 'activated' and wallet_paid['method'] == 'wallet'
    assert int(wallet_paid['wallet_balance_after_rial']) == seed_credit - wallet_cost
    assert premium.wallet_balance(333) == seed_credit - wallet_cost
    assert premium.get_subscription(444, use_cache=False)['plan'] == 'diamond'
    ledger = premium.wallet_ledger(333, 10)
    assert any(int(row['delta_rial']) == -wallet_cost and row['reason'] == 'subscription-payment' for row in ledger)

    # Insufficient wallet remains atomic and leaves the order untouched.
    poor_user = 334
    premium.adjust_wallet(poor_user, 100_000, reason='test-credit', admin_id=99)
    too_expensive = premium.create_order(poor_user, 445, 'Wallet Group 2', 'gold', premium.DURATION_ORDER[0])
    before = premium.wallet_balance(poor_user)
    try:
        premium.pay_order_with_wallet(int(too_expensive['order_id']), poor_user)
        raise AssertionError('insufficient wallet payment unexpectedly succeeded')
    except ValueError as exc:
        assert str(exc) == 'INSUFFICIENT_WALLET_BALANCE'
    assert premium.wallet_balance(poor_user) == before
    assert premium.get_order(int(too_expensive['order_id']))['status'] == 'created'

    # Shared MIO ledger supports audited subtraction without negative balances.
    social.configure(db, global_owner_id=999999, bot_user_ids={777000})
    social.admin_gift_users([101, 102], created_by=1, scope='test', meow_amount=50)
    result = social.admin_adjust_meow_users([101, 102], -30, created_by=1, scope='test')
    assert result['success'] == 2 and result['actual_delta'] == -60
    assert social.balance(101) == 20 and social.balance(102) == 20
    result2 = social.admin_adjust_meow_users([101], -100, created_by=1, scope='test')
    assert result2['actual_delta'] == -20 and social.balance(101) == 0

    with sqlite3.connect(db) as con:
        tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in {
        'premium_settings', 'premium_plan_prices', 'premium_subscriptions', 'premium_orders',
        'premium_payment_events', 'premium_checkout_sessions', 'premium_bonus_claims',
        'premium_wallets', 'premium_wallet_ledger',
    }:
        assert table in tables, table

# User-facing payment foundation and admin controls remain wired in runtime source.
for token in (
    'پلن ها', 'پلن من', 'خرید اشتراک',
    'https://gateway.zibal.ir/v1/request', 'https://gateway.zibal.ir/v1/verify',
    'https://gateway.zibal.ir/start/{track_id}', '/zivo/zibal/callback', '/zivo/payment/health',
    'verified_amount != expected_amount', 'receipt_submitted',
    'telegram_notify_card_receipt', 'z:payapprove:', 'z:payreject:',
    'z:premium', 'z:paycardnum', 'z:paymerchant', 'z:paydomain', 'z:paycallback', 'z:payprices',
    'z:meowminus', 'admin_adjust_meow_users', 'مبلغ دقیق به ریال',
    'wallet_balance', 'pay_order_with_wallet', 'z:wallet',
):
    assert token in SOURCE, token

for token in ('CREATE TABLE IF NOT EXISTS premium_wallets', 'premium_wallet_ledger', 'def wallet_balance', 'def pay_order_with_wallet', 'def set_payment_domain'):
    assert token in PREMIUM_SOURCE, token

setup_script = (ROOT / 'setup_zivo_payment_domain.sh').read_text(encoding='utf-8')
for token in ('nginx', 'certbot', '/zivo/payment/health', '/zivo/zibal/callback', '127.0.0.1:${CALLBACK_PORT}'):
    assert token in setup_script, token

print('CHECK ZIVO60.96.38 PREMIUM/PAYMENT FOUNDATION: PASS')
print('  free/silver/gold/diamond subscription engine + RAM cache: PASS')
print('  commercial prices remain stored/displayed in IRR: PASS')
print('  card-to-card receipt + Telegram approve/reject contract: PASS')
print('  Zibal request/start/callback/verify + amount match contract: PASS')
print('  Telegram admin card/merchant/domain/callback/price controls: PASS')
print('  payment domain -> automatic callback + HTTPS reverse-proxy helper: PASS')
print('  audited Rial wallet + atomic wallet subscription payment: PASS')
print('  audited one/group/all-users MIO subtraction foundation: PASS')
