#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path

import zivo_premium as premium


ROOT = Path(__file__).resolve().parent
CORE = (ROOT / "zivo60.py").read_text(encoding="utf-8")

assert 'VERSION = "zivo60.96.52"' in CORE
for token in (
    'action == "wallet_info"',
    'action == "create_wallet_topup"',
    'action=="wallet_summary"',
    'action=="wallet_adjust"',
    'clamp_zero=False',
):
    assert token in CORE, token


with tempfile.TemporaryDirectory(prefix="zivo-wallet-96-52-") as tmp:
    db = Path(tmp) / "zivo.db"
    premium.configure(db)
    premium.official_user_pass_gate(1001, username="buyer", first_name="خریدار")
    premium.official_user_pass_gate(1002, username="friend", first_name="دوست")

    # Zibal callback/manual verification ultimately reaches approve_order.
    # Repeated callbacks must credit a top-up exactly once.
    zibal_topup = premium.create_wallet_topup_order(1001, 1_000_000)
    zibal_oid = int(zibal_topup["order_id"])
    first = premium.approve_order(zibal_oid, "zibal-verify")
    second = premium.approve_order(zibal_oid, "zibal-verify-retry")
    assert first["status"] == second["status"] == "activated"
    assert premium.wallet_balance(1001) == 1_000_000
    assert sum(int(x["delta_rial"]) for x in premium.wallet_ledger(1001, 20) if int(x["order_id"] or 0) == zibal_oid) == 1_000_000

    # Card receipt preserves full buyer identity and a durable rejection reason;
    # resubmission + approval credits the exact amount once.
    card_topup = premium.create_wallet_topup_order(1001, 500_000)
    card_oid = int(card_topup["order_id"])
    premium.mark_card_waiting(card_oid)
    submitted = premium.manual_receipt_submit(card_oid, 1001, "PHOTO-CARD-1", 77, "رسید تست")
    assert submitted["buyer"]["username"] == "buyer"
    assert submitted["review"]["receipt_file_id"] == "PHOTO-CARD-1"
    rejected = premium.admin_reject_manual(card_oid, 999, "amount", "مبلغ واریزی اشتباه است")
    assert rejected["status"] == "rejected"
    assert rejected["review"]["admin_reason_text"] == "مبلغ واریزی اشتباه است"
    premium.manual_receipt_submit(card_oid, 1001, "PHOTO-CARD-2", 78, "رسید اصلاح‌شده")
    approved = premium.admin_approve_manual(card_oid, 999)
    assert approved["status"] == "activated"
    assert premium.wallet_balance(1001) == 1_500_000
    assert premium.admin_approve_manual(card_oid, 999)["status"] == "activated"
    assert premium.wallet_balance(1001) == 1_500_000

    # Admin controls resolve username, enrich the profile and never silently
    # clamp an excessive debit to zero.
    detail = premium.wallet_account_detail("@buyer", 20)
    assert detail and detail["user"]["first_name"] == "خریدار"
    added = premium.adjust_wallet(1001, 5_000_000, reason="هدیه پشتیبانی", source="soroush-admin", admin_id=999, clamp_zero=False)
    assert added["balance_after_rial"] == 6_500_000
    subtracted = premium.adjust_wallet(1001, -250_000, reason="اصلاح حساب", source="soroush-admin", admin_id=999, clamp_zero=False)
    assert subtracted["balance_after_rial"] == 6_250_000
    before_failed_debit = premium.wallet_balance(1001)
    try:
        premium.adjust_wallet(1001, -(before_failed_debit + 1), reason="نباید اجرا شود", clamp_zero=False)
        raise AssertionError("excess wallet debit unexpectedly succeeded")
    except ValueError as exc:
        assert str(exc) == "INSUFFICIENT_WALLET_BALANCE"
    assert premium.wallet_balance(1001) == before_failed_debit
    listed = premium.wallet_accounts(20, 0)
    assert any(int(x["user_id"]) == 1001 and x["username"] == "buyer" for x in listed)

    # Subscription purchase from wallet is atomic and idempotent.
    sub_order = premium.create_order(1001, 70001, "گروه کیف پول", "silver", 30)
    sub_cost = int(sub_order["amount_rial"])
    balance_before_sub = premium.wallet_balance(1001)
    paid_sub = premium.pay_order_with_wallet(int(sub_order["order_id"]), 1001)
    assert paid_sub["method"] == "wallet" and paid_sub["status"] == "activated"
    assert premium.wallet_balance(1001) == balance_before_sub - sub_cost
    assert premium.get_subscription(70001, use_cache=False)["plan"] == "silver"
    premium.pay_order_with_wallet(int(sub_order["order_id"]), 1001)
    assert premium.wallet_balance(1001) == balance_before_sub - sub_cost

    # Meow for a user and Meow gift-code orders use the same wallet transaction.
    meow_order = premium.create_meow_purchase_order(1001, 1002, 250)
    meow_cost = int(meow_order["amount_rial"])
    before_meow = premium.wallet_balance(1001)
    paid_meow = premium.pay_order_with_wallet(int(meow_order["order_id"]), 1001)
    assert paid_meow["status"] == "activated" and premium.wallet_balance(1001) == before_meow - meow_cost
    with sqlite3.connect(db) as con:
        meow_balance = int(con.execute("SELECT balance FROM social_meow_accounts WHERE user_id=1002").fetchone()[0])
    assert meow_balance == 250

    gift_order = premium.create_meow_gift_order(1001, 300)
    gift_cost = int(gift_order["amount_rial"])
    before_gift = premium.wallet_balance(1001)
    paid_gift = premium.pay_order_with_wallet(int(gift_order["order_id"]), 1001)
    assert paid_gift["status"] == "activated"
    assert str(paid_gift.get("gift_code") or "").startswith("ZIVO")
    assert premium.wallet_balance(1001) == before_gift - gift_cost

    # A wallet top-up can only use an external payment method.
    circular = premium.create_wallet_topup_order(1001, 100_000)
    circular_before = premium.wallet_balance(1001)
    try:
        premium.pay_order_with_wallet(int(circular["order_id"]), 1001)
        raise AssertionError("circular wallet top-up unexpectedly succeeded")
    except ValueError as exc:
        assert str(exc) == "WALLET_TOPUP_CANNOT_USE_WALLET"
    assert premium.wallet_balance(1001) == circular_before
    assert premium.get_order(int(circular["order_id"]))["status"] == "created"

    # Insufficient funds leave both wallet and order unchanged.
    poor_order = premium.create_order(1002, 70002, "گروه کمبود", "gold", 30)
    try:
        premium.pay_order_with_wallet(int(poor_order["order_id"]), 1002)
        raise AssertionError("insufficient purchase unexpectedly succeeded")
    except ValueError as exc:
        assert str(exc) == "INSUFFICIENT_WALLET_BALANCE"
    assert premium.wallet_balance(1002) == 0
    assert premium.get_order(int(poor_order["order_id"]))["status"] == "created"

    # Two concurrent taps may both receive success, but exactly one debit and
    # exactly one fulfillment are committed.
    premium.adjust_wallet(1002, 5_000_000, reason="concurrency-seed", clamp_zero=False)
    race_order = premium.create_order(1002, 70003, "گروه همزمانی", "diamond", 30)
    race_oid = int(race_order["order_id"])
    race_cost = int(race_order["amount_rial"])
    race_before = premium.wallet_balance(1002)
    results: list[dict] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(3)

    def pay() -> None:
        try:
            barrier.wait()
            results.append(premium.pay_order_with_wallet(race_oid, 1002))
        except BaseException as exc:  # surfaced after both threads join
            errors.append(exc)

    threads = [threading.Thread(target=pay), threading.Thread(target=pay)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=20)
    assert not errors, errors
    assert len(results) == 2 and all(x["status"] == "activated" for x in results)
    assert premium.wallet_balance(1002) == race_before - race_cost
    race_ledger = [x for x in premium.wallet_ledger(1002, 50) if int(x["order_id"] or 0) == race_oid]
    assert len(race_ledger) == 1 and int(race_ledger[0]["delta_rial"]) == -race_cost
    assert premium.get_subscription(70003, use_cache=False)["order_id"] == race_oid

print("CHECK ZIVO60.96.52 WALLET COMMERCE: PASS")
print("  Zibal/card top-up + idempotent credit: PASS")
print("  audited admin add/subtract + exact non-negative debit: PASS")
print("  wallet subscription/Meow/gift fulfillment: PASS")
print("  insufficient/circular/concurrent payment atomicity: PASS")
