#!/usr/bin/env python3
from __future__ import annotations

import zivo_official22 as mod


assert mod.VERSION == "zivo-official22"
assert str(mod.BASE_DIR) == "/opt/ZIVO_OFFICIAL_BOT22"
assert "بالاترین اولویت پاسخ" in mod.CAPABILITY_STATUS_TEXT


class Transport:
    def __init__(self) -> None:
        self.sent = []
        self.acks = []
        self.reject = set()

    def send_text(self, chat_id, text, reply_markup=None):
        target = str(chat_id)
        if target in self.reject:
            raise RuntimeError("BOT_USER_NOT_STARTED")
        self.sent.append((target, str(text), reply_markup))
        return {"ok": True}

    def answer_callback(self, callback_id, text=""):
        self.acks.append(str(callback_id))
        return True


def message(uid, text="", **extra):
    payload = {
        "from": {"id": uid, "username": f"user{uid}", "first_name": f"User {uid}"},
        "chat": {"id": uid}, "message_id": "1", "text": text, "type": "TEXT",
    }
    payload.update(extra)
    return {"message": payload}


def callback(uid, data="noop"):
    return {"callback_query": {
        "id": f"cb-{uid}",
        "from": {"id": uid, "username": f"button{uid}", "first_name": f"Button {uid}"},
        "message": {"message_id": "2", "chat": {"id": uid}},
        "data": data,
    }}


transport = Transport()
core = mod.BotCore(mod.Store(), transport)
registry = {}
seen_calls = []


def fake_ipc(account, payload, timeout=45.0):
    op = payload.get("op")
    action = payload.get("action")
    uid = int(payload.get("requester_user_id") or 0)
    if op == "official_gate" and action == "seen":
        row = registry.setdefault(uid, {"user_id": uid})
        row.update({
            "username": str(payload.get("username") or "").strip().lstrip("@"),
            "first_name": str(payload.get("first_name") or "").strip(),
            "seen": True,
        })
        seen_calls.append(dict(payload))
        return {"ok": True, "state": dict(row)}
    if op == "official_gate" and action == "status":
        return {"ok": True, "state": dict(registry.get(uid) or {})}
    if op == "meow_commerce" and action == "resolve_target":
        reference = str(payload.get("reference") or "").strip().lstrip("@").casefold()
        row = next((dict(value) for key, value in registry.items()
                    if reference == str(key) or reference == str(value.get("username") or "").casefold()), None)
        return {"ok": bool(row), "user": row, "error": "" if row else "OFFICIAL_USER_NOT_STARTED"}
    if op == "official_group_access" and action == "list":
        return {"ok": True, "groups": []}
    if op == "premium" and action == "wallet_info":
        return {"ok": True, "wallet": {"balance_rial": 0, "ledger": []}}
    return {"ok": True}


core._ipc = fake_ipc

# Every private message is persisted before inherited state handlers can return.
core.handle(message(71001, "", type="PHOTO"))
assert registry[71001]["username"] == "user71001"
assert registry[71001]["first_name"] == "User 71001"

# Marking identity before the inherited first-contact check would skip the
# established onboarding gate. Official22 enriches a brand-new /start only
# after that flow has made its pre-event decision.
before_start = len(transport.sent)
core.handle(message(71003, "/start"))
assert any("به ZIVO خوش اومدی" in text for _, text, _ in transport.sent[before_start:])
assert registry[71003]["username"] == "user71003"

# Button-only users are also persisted, including username/name metadata.
core.handle_callback(callback(71002))
assert registry[71002]["username"] == "button71002"

# Real nested Bot API forward-origin variants resolve the forwarded actor and
# never accidentally select the requester in message.from.
nested = message(71001, "", forward_origin={
    "type": "user",
    "origin": {"senderUser": {"userId": 72002, "username": "nested", "firstName": "Nested User"}},
})
profile = core._forwarded_user_profile(nested)
assert profile == {"id": "72002", "username": "nested", "first_name": "Nested User"}, profile
assert core._forwarded_user_reference(nested) == "72002"

# A pre-96.53 user missing from Core is recovered only after the Official API
# proves that the bot can still message the numeric recipient.
result = core._resolve_target_from_raw("71001", nested, "")
assert result.get("ok") and result.get("registry_recovered"), result
assert registry[72002]["username"] == "nested"
assert any(target == "72002" and "همگام شد" in text for target, text, _ in transport.sent)

# Numeric input gets the same recovery; a rejected send remains blocked and is
# never silently registered as an Official-started user.
transport.reject.add("73003")
blocked = core._resolve_target_from_raw("71001", message(71001, "73003"), "73003")
assert not blocked.get("ok") and blocked.get("error") == "OFFICIAL_USER_NOT_STARTED", blocked
assert 73003 not in registry

# Unknown username cannot be guessed; UI asks for numeric id/forward instead of
# incorrectly requiring an account-bot private chat.
unknown = core._resolve_target_from_raw("71001", message(71001, "@missing"), "@missing")
assert unknown.get("error") == "OFFICIAL_USERNAME_UNKNOWN"
assert "آیدی عددی" in core._official_not_started_text()

print("ZIVO OFFICIAL22 START REGISTRY + NESTED FORWARD RECOVERY TEST: PASS")
print("  all private messages/callbacks persist Official identity: PASS")
print("  numeric/nested-forward stale registry repair after send proof: PASS")
print("  unreachable and username-only unknown targets stay blocked: PASS")
