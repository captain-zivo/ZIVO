import sys,tempfile,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent/'account'
sys.path.insert(0,str(ROOT))
import zivo_premium as p
import zivo_social_games as sg

tmp=Path(tempfile.mkdtemp())/'test.db'
p._DB_PATH=tmp; p._SCHEMA_READY.clear()
sg._DB_PATH=tmp; sg._SCHEMA_READY.clear()
p.init_db(); sg.init_social_db()
# users started official
p.official_user_mark_seen(1001,username='buyer',first_name='Buyer')
p.official_user_mark_seen(2002,username='target',first_name='Target')
# meow manual approve/reverse
order=p.create_meow_purchase_order(1001,2002,100)
p.mark_card_waiting(order['order_id'])
d=p.manual_receipt_submit(order['order_id'],1001,'photo-file-1',55,'ok')
assert d['status']=='receipt_submitted'
a=p.admin_approve_manual(order['order_id'],999)
assert a['status']=='activated'
with sqlite3.connect(tmp) as con: bal=con.execute('select balance from social_meow_accounts where user_id=2002').fetchone()[0]
assert bal==100,bal
r=p.admin_reverse_manual(order['order_id'],999,'mistake','mistake')
with sqlite3.connect(tmp) as con: bal=con.execute('select balance from social_meow_accounts where user_id=2002').fetchone()[0]
assert bal==0,bal
assert r['status']=='reversed'
# reject then approve again
p.admin_approve_manual(order['order_id'],999)
assert p.get_order(order['order_id'])['status']=='activated'
p.admin_reject_manual(order['order_id'],999,'admin-correction','reversed again')
assert p.get_order(order['order_id'])['status']=='reversed'
# gift code approve, redeem, spend, reverse => negative
og=p.create_meow_gift_order(1001,100); p.mark_card_waiting(og['order_id']); p.manual_receipt_submit(og['order_id'],1001,'photo-gift'); ag=p.admin_approve_manual(og['order_id'],999)
code=ag['gift_code']; red=p.redeem_meow_gift_code(code,2002); assert red['balance_after']==100
with sqlite3.connect(tmp) as con:
    con.execute('update social_meow_accounts set balance=20 where user_id=2002'); con.commit()
rg=p.admin_reverse_manual(og['order_id'],999,'mistake','gift rollback')
with sqlite3.connect(tmp) as con:
    bal=con.execute('select balance from social_meow_accounts where user_id=2002').fetchone()[0]
    status=con.execute('select status from premium_meow_gift_codes where code=?',(code,)).fetchone()[0]
assert bal==-80,bal
assert status=='revoked',status
# subscription snapshot restore
# seed old silver
with sqlite3.connect(tmp) as con:
    con.execute("insert or replace into premium_subscriptions(group_id,plan,status,buyer_user_id,started_at,expires_at,grace_until,source,order_id,updated_at) values(77,'silver','active',1001,'2026-01-01T00:00:00+00:00','2030-01-01T00:00:00+00:00','2030-01-02T00:00:00+00:00','old',1,'2026-01-01T00:00:00+00:00')"); con.commit()
# price set
p.set_price('gold',30,100000)
os=p.create_order(1001,77,'Group77','gold',30); p.mark_card_waiting(os['order_id']); p.manual_receipt_submit(os['order_id'],1001,'photo-sub'); p.admin_approve_manual(os['order_id'],999)
assert p.get_subscription(77,use_cache=False)['plan']=='gold'
p.admin_reverse_manual(os['order_id'],999,'mistake','rollback')
assert p.get_subscription(77,use_cache=False)['plan']=='silver'
print('ZIVO 96.49 PAYMENT REVERSAL TEST: PASS')
