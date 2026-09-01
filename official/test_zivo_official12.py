import tempfile, socket, threading, json
from pathlib import Path
import zivo_official12 as mod
assert mod.VERSION == "zivo-official12"
store=mod.Store()
class T:
    def __init__(self): self.sent=[]
    def send_text(self, chat_id, text, reply_markup=None): self.sent.append((chat_id,text,reply_markup)); return {"ok":True}
    def answer_callback(self,*a,**k): return {"ok":True}
transport=T(); core=mod.BotCore(store,transport)
# Managed group + premium catalog/order flow with mocked direct IPC.
def fake_ipc(account,payload,timeout=45.0):
    op=payload.get("op"); act=payload.get("action")
    if op=="groups": return {"ok":True,"groups":[{"group_id":777,"title":"Test Group","account_key":"acc2","account_label":"acc2","member_count":123}]}
    if op=="status": return {"ok":True,"account_key":account,"account_label":account,"enabled":True,"connected":True,"self_id":1,"groups_count":1}
    if op=="social": return {"ok":True,"result_text":"SOCIAL_OK"}
    if op=="premium" and act=="catalog": return {"ok":True,"plans":[{"plan":"silver","label":"نقره‌ای","prices":[{"duration_days":30,"money_toman":"55,000 تومان","money_rial":"550,000 ریال"}]}],"wallet_balance":600000}
    if op=="premium" and act=="status": return {"ok":True,"subscription":{"plan":"free","status":"active"},"plan_label":"رایگان"}
    if op=="premium" and act=="create_order": return {"ok":True,"order":{"order_id":9,"order_code":"ZV-ABC-12345","amount_rial":550000,"group_id":777,"group_title":"Test Group","plan":"silver","duration_days":30},"plan_label":"نقره‌ای","duration_label":"۱ ماهه","money_rial":"550,000 ریال","money_toman":"55,000 تومان","wallet_balance":600000,"zibal_enabled":True,"card_enabled":False}
    if op=="premium" and act=="wallet_pay": return {"ok":True,"activated":True,"order":{"order_id":9,"order_code":"ZV-ABC-12345","group_id":777,"group_title":"Test Group","plan":"silver"},"subscription":{"plan":"silver","status":"active"},"wallet_balance":50000}
    if op=="premium" and act=="history": return {"ok":True,"orders":[]}
    if op=="premium" and act=="my_subscriptions": return {"ok":True,"subscriptions":[]}
    raise AssertionError((account,payload))
core._ipc=fake_ipc
assert core._social_private("49145577","میو") == "SOCIAL_OK"
core._premium_groups_menu("49145577","49145577")
assert any("Test Group" in str(x[1]) or "خرید اشتراک" in str(x[1]) for x in transport.sent)
core._premium_group_menu("49145577","49145577",777)
assert any("انتخاب پلن" in x[1] for x in transport.sent)
core._premium_create_order("49145577","49145577",777,"silver",30)
assert any("سفارش ساخته شد" in x[1] for x in transport.sent)
core._premium_pay("49145577","49145577",9,"wallet")
assert any("اشتراک فعال شد" in x[1] for x in transport.sent)
print("ZIVO OFFICIAL12 IPC PREMIUM UI TESTS: PASS")
