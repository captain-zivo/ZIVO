from pathlib import Path
import tempfile, ast
import zivo_premium as premium

root=Path(__file__).resolve().parent
src=(root/'zivo60.py').read_text(encoding='utf-8')
assert ('VERSION = "zivo60.96.45"' in src) or ('VERSION = "zivo60.96.48"' in src)
for token in (
    'async def _ipc_inspect_group_link(',
    'if op == "inspect_link":',
    'if action == "discount_apply":',
    'if action == "check_payment":',
    'if action == "cancel":',
    'premium.apply_discount_code(',
    'premium.cancel_order(',
):
    assert token in src, token
ast.parse(src)

with tempfile.TemporaryDirectory() as td:
    premium.configure(Path(td)/'premium.db')
    premium.set_price('silver',30,550_000,True)
    code=premium.set_discount_code('WELCOME10',10)
    assert code['code']=='WELCOME10' and code['percent']==10
    order=premium.create_order(1001,777,'Test Group','silver',30)
    assert order['amount_rial']==550_000
    updated=premium.apply_discount_code(order['order_id'],1001,'WELCOME10')
    assert updated['original_amount_rial']==550_000
    assert updated['discount_rial']==55_000
    assert updated['amount_rial']==495_000
    assert updated['discount_code']=='WELCOME10'
    cancelled=premium.cancel_order(order['order_id'],1001)
    assert cancelled['status']=='cancelled'
    assert premium.remove_discount_code('WELCOME10') is True
print('ZIVO 96.45 UX CHECKOUT + DISCOUNT IPC TEST: PASS')
