from pathlib import Path
import ast
p=Path(__file__).with_name("zivo60.py")
s=p.read_text(encoding="utf-8")
for token in (
    'VERSION = "zivo60.96.44"',
    'async def _ipc_premium_dispatch(',
    'if op == "premium":',
    'premium.create_order(',
    'premium.pay_order_with_wallet(',
    'await _zibal_request_for_order(order)',
    'manual_receipt_required',
    'if op == "social":',
):
    assert token in s, token
ast.parse(s)
print("ZIVO 96.44 OFFICIAL PREMIUM IPC STATIC: PASS")
