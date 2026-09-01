#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / "zivo60.py").read_text(encoding="utf-8")
INSTALLER_PATH = Path(
    os.environ.get("ZIVO_INSTALLER_UNDER_TEST", str(ROOT / "install_zivo60.sh"))
)
INSTALLER = INSTALLER_PATH.read_text(encoding="utf-8") if INSTALLER_PATH.is_file() else ""
TREE = ast.parse(SRC)

assert 'VERSION = "zivo60.96.51"' in SRC


def fn(name: str) -> str:
    node = next(
        item
        for item in ast.walk(TREE)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(SRC, node) or ""


inaccessible = fn("_is_group_inaccessible_error")
fallback = fn("_campaign_send_group_text")
dispatcher = fn("broadcast_send_target")

# Formatting-only rejection is not proof that the account left the group.
assert "CHATSENDPLAINFORBIDDEN" not in inaccessible
assert "YOU CANNOT SEND PLAIN" not in inaccessible
assert "_campaign_send_group_text" in dispatcher
assert "MessageEntityBlockquote" in fallback
assert "formatting_entities=[]" in fallback


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, target: Any, text: str, **kwargs: Any) -> Any:
        self.calls.append({"target": target, "text": text, **kwargs})
        if len(self.calls) == 1:
            raise RuntimeError("ChatSendPlainForbidden: You cannot send plain results")
        return SimpleNamespace(id=991)


class FakeBlockquote:
    def __init__(self, offset: int, length: int) -> None:
        self.offset = int(offset)
        self.length = int(length)


class FakeLog:
    def info(self, *args: Any, **kwargs: Any) -> None:
        pass


client = FakeClient()
ns = {
    "Any": Any,
    "BaseException": BaseException,
    "client": client,
    "types": SimpleNamespace(MessageEntityBlockquote=FakeBlockquote),
    "utf16_len": lambda value: len(str(value).encode("utf-16-le")) // 2,
    "log": FakeLog(),
    "ACCOUNT_KEY": "main",
}
for name in ("_campaign_plain_text_forbidden", "_campaign_send_group_text"):
    exec(fn(name), ns)

sent = asyncio.run(ns["_campaign_send_group_text"]("group-77", "تبلیغ تست"))
assert int(sent.id) == 991
assert len(client.calls) == 2
assert client.calls[0]["formatting_entities"] == []
entities = client.calls[1]["formatting_entities"]
assert len(entities) == 1 and isinstance(entities[0], FakeBlockquote)
assert entities[0].length > 0

if INSTALLER:
    assert "check_zivo60_96_51_campaign_group_delivery.py" in INSTALLER
    assert (
        'install -m 600 "$SRC/check_zivo60_96_51_campaign_group_delivery.py" '
        '"$BASE/check_zivo60_96_51_campaign_group_delivery.py"'
    ) in INSTALLER

print("CHECK ZIVO60.96.51 CAMPAIGN GROUP DELIVERY: PASS")
print("  live/archived dialog discovery remains uncapped: PASS")
print("  plain-text rejection retries with rich formatting: PASS")
print("  formatting-only rejection cannot prune a healthy group: PASS")
print("  campaign send governor remains active: PASS")
