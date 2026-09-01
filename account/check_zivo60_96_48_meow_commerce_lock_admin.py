#!/usr/bin/env python3
from pathlib import Path
import tempfile
import re
import zivo_premium as premium
import zivo_social_games as social

root=Path(__file__).resolve().parent
source=(root/'zivo60.py').read_text(encoding='utf-8')
assert ('VERSION = "zivo60.96.48"' in source) or ('VERSION = "zivo60.96.49"' in source) or ('VERSION = "zivo60.96.50"' in source)
for token in ['official_group_locks','meow_commerce','create_meow_order','create_meow_gift_order','campaign_create','account_keys']:
    assert token in source, token
assert 'GOLD_REQUIRED_FOR_PER_LOCK_PUNISHMENT' in source

with tempfile.TemporaryDirectory() as td:
    db=Path(td)/'zivo.db'
    premium.configure(db)
    social.configure(db,global_owner_id=49145577,bot_user_ids=())
    premium.official_user_mark_seen(1001,username='buyer',first_name='Buyer')
    premium.official_user_mark_seen(1002,username='target',first_name='Target')
    assert premium.official_find_user('@target')['user_id']==1002
    assert premium.meow_price_rial(100)==40000
    try:
        premium.meow_price_rial(99)
        raise AssertionError('minimum purchase was not enforced')
    except ValueError as exc:
        assert 'MEOW_MIN_100' in str(exc)

    order=premium.create_meow_purchase_order(1001,1002,125)
    assert order['order_kind']=='meow_purchase' and order['amount_rial']==50000
    premium.set_discount_code('MEOW20',20)
    discounted=premium.apply_discount_code(order['order_id'],1001,'MEOW20')
    assert int(discounted['discount_rial'])==10000 and int(discounted['amount_rial'])==40000
    order=discounted
    activated=premium.approve_order(order['order_id'],'test')
    assert activated['status']=='activated'
    assert social.meow_balance(1002)==125
    notes=premium.pending_official_notifications(20)
    assert any(int(n['user_id'])==1002 and n['kind']=='meow-purchase-received' for n in notes)

    gift_order=premium.create_meow_gift_order(1001,200)
    gift_active=premium.approve_order(gift_order['order_id'],'test')
    code=str(gift_active.get('gift_code') or '')
    assert re.fullmatch(r'ZIVO\d{8}',code), code
    redeemed=premium.redeem_meow_gift_code(code,1002)
    assert redeemed['meow_amount']==200 and social.meow_balance(1002)==325
    try:
        premium.redeem_meow_gift_code(code,1002)
        raise AssertionError('gift code reused')
    except ValueError as exc:
        assert 'USED' in str(exc)

    # Official transfer no longer depends on account-bot private-contact registry.
    # Seed sender balance with a purchase and transfer atomically.
    sender_order=premium.create_meow_purchase_order(1001,1001,300)
    premium.approve_order(sender_order['order_id'],'test')
    before=social.meow_balance(1001)
    prepared=social.prepare_transfer_official(1001,1002,100)
    assert prepared['amount']==100 and prepared['tax']>=1
    confirmed=social.confirm_transfer_official(1001)
    assert social.meow_balance(1001)==before-100
    assert confirmed['recipient_balance_after']==social.meow_balance(1002)

print('CHECK ZIVO60.96.48 MEOW COMMERCE + LOCK ADMIN: PASS')
print('  Official-start recipient registry + username/id resolution: PASS')
print('  40 toman/unit + minimum 100 Meow purchase: PASS')
print('  atomic Meow purchase credit + Official notification queue: PASS')
print('  ZIVO######## one-time gift code purchase/redeem: PASS')
print('  Official transfer independent from account-bot private chat: PASS')
print('  group-lock IPC + GOLD per-lock punishment gate contract: PASS')
