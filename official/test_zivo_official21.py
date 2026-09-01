from __future__ import annotations

import sys
import types
from typing import Any, Dict

# The production installer provides requests.  The isolated source regression
# injects a tiny import stub because all network I/O is replaced by fake IPC and
# a fake transport below.
try:
    import requests as _requests  # noqa: F401
except ModuleNotFoundError:
    requests_stub = types.ModuleType("requests")
    requests_stub.Session = object
    requests_stub.Response = object
    sys.modules["requests"] = requests_stub

import zivo_official21 as mod


assert mod.VERSION == "zivo-official21"
assert str(mod.BASE_DIR) == "/opt/ZIVO_OFFICIAL_BOT21"
for token in ("کیف پول", "شارژ کیف پول", "خریدهای من"):
    assert token in mod.HELP_TEXT + mod.COMMAND_LIST_TEXT


class Transport:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, Any]] = []
        self.media: list[tuple[str, Dict[str, Any], str]] = []
        self.acks: list[str] = []

    def send_text(self, chat_id: Any, text: Any, reply_markup: Any = None) -> Dict[str, Any]:
        self.sent.append((str(chat_id), str(text), reply_markup))
        return {"ok": True}

    def send_media(self, chat_id: Any, item: Dict[str, Any], caption: str = "") -> Dict[str, Any]:
        self.media.append((str(chat_id), dict(item), str(caption)))
        return {"ok": True}

    def answer_callback(self, callback_id: Any) -> bool:
        self.acks.append(str(callback_id))
        return True


def callback(uid: Any, data: str, cid: str = "cb") -> Dict[str, Any]:
    return {
        "callback_query": {
            "id": cid,
            "from": {"id": uid},
            "message": {"message_id": "1", "chat": {"id": uid}},
            "data": data,
        }
    }


def message(uid: Any, text: str = "", *, photo: bool = False) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "from": {"id": uid, "username": f"u{uid}", "first_name": f"User {uid}"},
        "chat": {"id": uid},
        "message_id": "44",
        "type": "TEXT",
        "text": text,
    }
    if photo:
        body.pop("text", None)
        body["photo"] = [{"file_id": "PHOTO-RECEIPT"}]
        body["caption"] = text
    return {"message": body}


USER = "60001"
FRIEND = "60002"
OWNER = str(next(iter(mod.GLOBAL_OWNER_IDS)))
wallets = {int(USER): 2_000_000, int(FRIEND): 300_000}
ledger = {
    int(USER): [{"delta_rial": 2_000_000, "balance_after": 2_000_000, "reason": "wallet-topup", "source": "zibal", "created_at": "2026-08-31T10:00:00"}],
    int(FRIEND): [],
}
profiles = {
    int(USER): {"user_id": int(USER), "first_name": "خریدار", "username": "buyer", "seen": True, "membership_passed": True, "last_seen_at": "2026-08-31T10:00:00"},
    int(FRIEND): {"user_id": int(FRIEND), "first_name": "دوست", "username": "friend", "seen": True, "membership_passed": True, "last_seen_at": "2026-08-31T09:00:00"},
}
orders: Dict[int, Dict[str, Any]] = {
    20: {"order_id": 20, "order_code": "ZV-MEOW-20", "order_kind": "meow_purchase", "buyer_user_id": int(USER), "target_user_id": int(FRIEND), "meow_amount": 500, "amount_rial": 200_000, "status": "created", "group_id": 0},
}
next_order = [100]
calls: list[Dict[str, Any]] = []


def full_order(order: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(order)
    out["buyer"] = dict(profiles.get(int(order.get("buyer_user_id") or 0), {}))
    out["target"] = dict(profiles.get(int(order.get("target_user_id") or 0), {}))
    out["review"] = {"receipt_file_id": out.get("receipt_path", ""), "admin_status": "pending"}
    return out


def wallet_detail(uid: int) -> Dict[str, Any]:
    return {
        "user_id": uid,
        "balance_rial": wallets.get(uid, 0),
        "updated_at": "2026-08-31T10:00:00",
        "user": dict(profiles[uid]),
        "ledger": list(ledger.get(uid, [])),
    }


def fake_ipc(account: str, payload: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Any]:
    del timeout
    calls.append(dict(payload))
    op = str(payload.get("op") or "")
    action = str(payload.get("action") or "")
    requester = int(payload.get("requester_user_id") or 0)
    payment = {"zibal_enabled": True, "card_enabled": True}
    if op == "status":
        return {"ok": True, "account_key": account, "account_label": account, "enabled": True, "connected": True, "self_id": 1, "groups_count": 1}
    if op == "official_gate":
        return {"ok": True}
    if op == "premium":
        if action == "wallet_info":
            return {"ok": True, "wallet_balance": wallets.get(requester, 0), "ledger": list(ledger.get(requester, []))}
        if action == "create_wallet_topup":
            oid = next_order[0]
            next_order[0] += 1
            amount = int(payload.get("amount_rial") or 0)
            orders[oid] = {"order_id": oid, "order_code": f"ZV-TOPUP-{oid}", "order_kind": "wallet_topup", "buyer_user_id": requester, "amount_rial": amount, "status": "created", "group_id": 0}
            return {"ok": True, "order": dict(orders[oid]), "wallet_balance": wallets.get(requester, 0), "payment": payment}
        oid = int(payload.get("order_ref") or 0)
        order = orders.get(oid)
        if not order:
            return {"ok": False, "error": "ORDER_NOT_FOUND"}
        if action == "order":
            return {"ok": True, "order": dict(order), "wallet_balance": wallets.get(requester, 0), "payment": payment}
        if action == "wallet_pay":
            amount = int(order.get("amount_rial") or 0)
            if wallets.get(requester, 0) < amount:
                return {"ok": False, "error": "INSUFFICIENT_WALLET_BALANCE", "order": dict(order), "wallet_balance": wallets.get(requester, 0)}
            wallets[requester] -= amount
            order["status"] = "activated"
            order["method"] = "wallet"
            if order.get("order_kind") == "meow_gift_code":
                order["gift_code"] = "ZIVO12345678"
            return {"ok": True, "activated": True, "order": dict(order), "wallet_balance": wallets[requester]}
        if action == "zibal":
            order["status"] = "gateway_pending"
            order["zibal_track_id"] = oid * 10
            return {"ok": True, "order": dict(order), "payment_url": f"https://gateway.zibal.ir/start/{oid * 10}"}
        if action == "card":
            order["status"] = "awaiting_receipt"
            order["method"] = "card"
            return {"ok": True, "manual_receipt_required": True, "order": dict(order), "card_number": "6037991234567890", "card_holder": "ZIVO", "amount_rial": int(order["amount_rial"])}
        if action == "check_payment":
            return {"ok": True, "activated": order.get("status") == "activated", "pending": order.get("status") != "activated", "order": dict(order)}
        if action == "cancel":
            order["status"] = "cancelled"
            return {"ok": True, "cancelled": True, "order": dict(order)}
    if op == "official_payment_admin":
        if action == "wallet_summary":
            return {"ok": True, "wallet_count": len(wallets), "summary": {"wallet_users": len([x for x in wallets.values() if x > 0]), "wallet_total_rial": sum(wallets.values()), "wallet_topups": 1}}
        if action == "wallet_list":
            rows = []
            for uid, balance in wallets.items():
                rows.append({"user_id": uid, "balance_rial": balance, "first_name": profiles[uid]["first_name"], "username": profiles[uid]["username"]})
            return {"ok": True, "wallet_count": len(rows), "wallets": rows}
        if action == "wallet_detail":
            ref = str(payload.get("reference") or "").strip().lstrip("@").casefold()
            uid = int(ref) if ref.isdigit() else next((key for key, profile in profiles.items() if profile["username"] == ref), 0)
            return {"ok": uid in profiles, "wallet": wallet_detail(uid) if uid in profiles else None, "error": "WALLET_USER_NOT_FOUND" if uid not in profiles else ""}
        if action == "wallet_adjust":
            uid = int(payload.get("reference") or 0)
            delta = int(payload.get("delta_rial") or 0)
            before = wallets.get(uid, 0)
            if before + delta < 0:
                return {"ok": False, "error": "INSUFFICIENT_WALLET_BALANCE"}
            wallets[uid] = before + delta
            ledger.setdefault(uid, []).insert(0, {"delta_rial": delta, "balance_after": wallets[uid], "reason": payload.get("reason"), "source": "soroush-admin"})
            return {"ok": True, "adjustment": {"actual_delta_rial": delta, "balance_before_rial": before, "balance_after_rial": wallets[uid]}, "wallet": wallet_detail(uid)}
        if action == "receipt_submit":
            oid = int(payload.get("order_id") or 0)
            order = orders[oid]
            order["status"] = "receipt_submitted"
            order["receipt_path"] = str(payload.get("file_id") or "")
            return {"ok": True, "order": full_order(order)}
        if action == "detail":
            ref = str(payload.get("order_ref") or "")
            order = orders.get(int(ref)) if ref.isdigit() else next((row for row in orders.values() if row.get("order_code") == ref), None)
            return {"ok": bool(order), "order": full_order(order) if order else None}
        if action == "list":
            return {"ok": True, "orders": [dict(row) for row in orders.values()]}
    if op == "official_admin":
        return {"ok": True, "official": {"enabled": 2}, "account_network": {"private_enabled": 2}, "accounts": [], "active_campaigns": 0}
    return {"ok": True, "groups": []}


transport = Transport()
core = mod.BotCore(mod.Store(), transport)
core._ipc = fake_ipc

# Main/economy menus expose wallet and charge actions.
menu_buttons = [button for row in core._main_menu_for(USER)["inline_keyboard"] for button in row]
assert any(button.get("callback_data") == "wallet:home" for button in menu_buttons)
assert any(button.get("callback_data") == "wallet:topup" for button in menu_buttons)
economy_buttons = [button for row in core._economy_markup17()["inline_keyboard"] for button in row]
assert any(button.get("callback_data") == "wallet:home" for button in economy_buttons)

# User wallet shows balance and ledger.
text = core.handle_callback(callback(USER, "wallet:home", "wallet-home"))
assert "2,000,000 ریال" in text and "شارژ کیف پول" in text
assert transport.acks.count("wallet-home") == 1

# Top-up amount -> external payment methods only (never circular wallet pay).
core.handle_callback(callback(USER, "wallet:topup"))
text = core.handle(message(USER, "۱۰۰۰۰۰۰"))
topup_oid = max(orders)
buttons = [button for row in transport.sent[-1][2]["inline_keyboard"] for button in row]
callbacks = {button.get("callback_data") for button in buttons}
assert f"prem:z:{topup_oid}" in callbacks and f"prem:c:{topup_oid}" in callbacks
assert f"prem:w:{topup_oid}" not in callbacks
assert "زیبال" in text and "کارت‌به‌کارت" in text

# Zibal starts only after the user selects it and activates the watcher.
before_zibal = len([call for call in calls if call.get("action") == "zibal"])
ztext = core.handle_callback(callback(USER, f"prem:z:{topup_oid}"))
after_zibal = len([call for call in calls if call.get("action") == "zibal"])
assert after_zibal == before_zibal + 1 and "درگاه زیبال آماده شد" in ztext
assert topup_oid in core._payment_watch
orders[topup_oid]["status"] = "activated"
wallets[int(USER)] += int(orders[topup_oid]["amount_rial"])
success = core._premium_success_page(USER, USER, dict(orders[topup_oid]), topup_oid)
assert "کیف پول با موفقیت شارژ شد" in success and "موجودی جدید" in success

# Card-to-card uses photo-only receipt and sends full order/user/amount to owner.
card_order = core._wallet_topup_create(USER, USER, 500_000)
assert "روش شارژ" in card_order
card_oid = max(orders)
card_text = core.handle_callback(callback(USER, f"prem:c:{card_oid}"))
assert "مبلغ دقیق" in card_text and "ارسال رسید" in card_text
core.handle_callback(callback(USER, f"receipt:start:{card_oid}"))
assert "فقط عکس" in core.handle(message(USER, "متن"))
receipt_result = core.handle(message(USER, "", photo=True))
assert "رسید دریافت شد" in receipt_result
owner_messages = [text for chat, text, _ in transport.sent if chat == OWNER]
assert any("خریدار" in text and USER in text and "500,000 ریال" in text for text in owner_messages)
assert any(chat == OWNER and item.get("file_id") == "PHOTO-RECEIPT" for chat, item, _ in transport.media)

# Meow checkout displays all available methods without starting Zibal early;
# wallet payment fulfills through the shared premium action.
zibal_before_page = len([call for call in calls if call.get("action") == "zibal"])
page = core._meow_payment_page(USER, USER, 20)
zibal_after_page = len([call for call in calls if call.get("action") == "zibal"])
assert zibal_after_page == zibal_before_page
meow_buttons = [button for row in transport.sent[-1][2]["inline_keyboard"] for button in row]
meow_callbacks = {button.get("callback_data") for button in meow_buttons}
assert {"prem:w:20", "prem:z:20", "prem:c:20"}.issubset(meow_callbacks)
assert "موجودی کیف پول" in page
meow_success = core.handle_callback(callback(USER, "prem:w:20"))
assert "Meow شارژ شد" in meow_success and orders[20]["method"] == "wallet"

# Soroush owner panel: wallet list/detail, audited add, reason, confirmation,
# and user notification with the resulting balance.
admin_home = core.handle_callback(callback(OWNER, "admin:home"))
assert "مدیریت کامل کیف پول" in admin_home
admin_buttons = [button for row in transport.sent[-1][2]["inline_keyboard"] for button in row]
assert any(button.get("callback_data") == "walletadmin:home" for button in admin_buttons)
assert "مجموع موجودی" in core.handle_callback(callback(OWNER, "walletadmin:home"))
assert "خریدار" in core.handle_callback(callback(OWNER, f"walletadmin:u:{USER}"))
core.handle_callback(callback(OWNER, f"walletadmin:add:{USER}"))
core.handle(message(OWNER, "250000"))
preview = core.handle(message(OWNER, "هدیه پشتیبانی"))
assert "+250,000 ریال" in preview and "هدیه پشتیبانی" in preview
before_adjust = wallets[int(USER)]
done = core.handle_callback(callback(OWNER, "walletadmin:confirm"))
assert wallets[int(USER)] == before_adjust + 250_000
assert "تغییر کیف پول ثبت شد" in done
adjust_calls = [call for call in calls if call.get("action") == "wallet_adjust"]
assert adjust_calls[-1]["reason"] == "هدیه پشتیبانی" and int(adjust_calls[-1]["delta_rial"]) == 250_000
assert any(chat == USER and "کیف پول ZIVO توسط مدیریت" in text for chat, text, _ in transport.sent)

# Exact debit UX blocks an amount greater than the current balance before the
# confirmation request, matching the atomic Core rule.
core.handle_callback(callback(OWNER, f"walletadmin:minus:{FRIEND}"))
too_much = core.handle(message(OWNER, "999999"))
assert "موجودی کافی نیست" in too_much and wallets[int(FRIEND)] == 300_000

# Text commands are documented and work without callbacks.
assert "کیف پول ریالی" in core.handle(message(USER, "کیف پول"))
assert "مبلغ شارژ" in core.handle(message(USER, "شارژ کیف پول"))

print("ZIVO OFFICIAL21 WALLET COMMERCE UI TEST: PASS")
print("  wallet home/top-up/Zibal/card receipt: PASS")
print("  subscription/Meow wallet method routing: PASS")
print("  Soroush admin list/detail/add/subtract/reason: PASS")
