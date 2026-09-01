#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
INSTALLER_PATH = Path(os.environ.get('ZIVO_INSTALLER_UNDER_TEST', str(ROOT / 'install_zivo60.sh')))
INSTALLER = INSTALLER_PATH.read_text(encoding='utf-8') if INSTALLER_PATH.is_file() else ''
TREE = ast.parse(SRC)

assert any(f'VERSION = "zivo60.96.{v}"' in SRC for v in range(27, 100))
assert 'async def iter_dialogs_exhaustive_raw' in SRC
assert 'functions.messages.GetDialogsRequest' in SRC
assert 'folder_id=folder_id' in SRC
assert 'for folder_id in (0, 1)' in SRC
assert 'page_size = 100' in SRC
assert 'response=%s' in SRC
assert 'repeated cursor' in SRC
assert 'raw exhaustive dialog folder PASS' in SRC


def fn(name: str) -> str:
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SRC, node) or ''

full = fn('full_dialog_inventory_sync')
campaign = fn('campaign_live_dialog_targets')
assert 'iter_dialogs_exhaustive_raw' in full
assert 'iter_dialogs_exhaustive_raw' in campaign
assert 'client.iter_dialogs(limit=None)' not in full
assert 'client.iter_dialogs(limit=None)' not in campaign

# Synthetic runtime: 350 normal + 180 archived dialogs. Every raw response is a
# generic object, deliberately NOT messages.DialogsSlice. The old SPlusthon
# iterator would stop when response type isn't DialogsSlice; our raw paginator
# must continue until the short final page and yield all 530 unique dialogs.
class FakePeer:
    def __init__(self, key: int):
        self.key = int(key)

class FakeEntity:
    def __init__(self, key: int):
        self.id = int(key)
        self.title = f'G{key}'
        self.first_name = ''

class FakeMessage:
    def __init__(self, peer: FakePeer, mid: int, date: datetime):
        self.peer_id = peer
        self.id = int(mid)
        self.date = date

class FakeDialog:
    def __init__(self, peer: FakePeer, top_message: int):
        self.peer = peer
        self.top_message = int(top_message)

class FakeGetDialogsRequest:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

class FakeFunctions:
    class messages:
        GetDialogsRequest = FakeGetDialogsRequest

class FakeTypes:
    class InputPeerEmpty:
        pass

class FakeUtils:
    @staticmethod
    def get_peer_id(obj: Any) -> int:
        if hasattr(obj, 'key'):
            return int(obj.key)
        if hasattr(obj, 'id'):
            return int(obj.id)
        raise ValueError('no peer id')

    @staticmethod
    def get_input_peer(entity: Any) -> Any:
        return entity

class Log:
    def info(self, *a, **k):
        pass
    def warning(self, *a, **k):
        pass

base = datetime(2026, 8, 29, tzinfo=timezone.utc)

def build_rows(folder: int, count: int, start_key: int):
    out = []
    for i in range(count):
        key = start_key + i
        peer = FakePeer(key)
        entity = FakeEntity(key)
        mid = 1_000_000 - i
        msg = FakeMessage(peer, mid, base - timedelta(seconds=i))
        dlg = FakeDialog(peer, mid)
        out.append((dlg, entity, msg))
    return out

ROWS = {
    0: build_rows(0, 350, 10_000),
    1: build_rows(1, 180, 20_000),
}

class FakeClient:
    def __init__(self):
        self.calls = []

    async def __call__(self, request):
        folder = int(request.folder_id)
        rows = ROWS[folder]
        start = 0
        if int(request.offset_id or 0) > 0:
            for idx, (_, _, msg) in enumerate(rows):
                if int(msg.id) == int(request.offset_id):
                    start = idx + 1
                    break
        chunk = rows[start:start + int(request.limit)]
        self.calls.append((folder, start, len(chunk), int(request.offset_id or 0)))
        # Generic SimpleNamespace on purpose: not DialogsSlice.
        return SimpleNamespace(
            dialogs=[x[0] for x in chunk],
            chats=[x[1] for x in chunk],
            users=[],
            messages=[x[2] for x in chunk],
        )

    async def get_input_entity(self, entity):
        return entity

    async def iter_dialogs(self, limit=None, folder=None):
        raise AssertionError('high-level iterator fallback must not be needed')

client = FakeClient()
ns = {
    'Any': Any, 'Dict': Dict, 'Optional': Optional, 'Tuple': Tuple,
    'SimpleNamespace': SimpleNamespace,
    'asyncio': asyncio, 'functions': FakeFunctions, 'types': FakeTypes,
    'utils': FakeUtils, 'safe_int': lambda x: int(x) if x is not None else None,
    'client': client, 'log': Log(), 'ACCOUNT_KEY': 'main',
}
for name in ('_raw_dialog_peer_id', '_raw_dialog_message_key', 'iter_dialogs_exhaustive_raw'):
    exec(fn(name), ns)

async def collect():
    return [d async for d in ns['iter_dialogs_exhaustive_raw']('synthetic-530')]

items = asyncio.run(collect())
assert len(items) == 530, len(items)
assert len({d.entity.id for d in items}) == 530
# 350 => 100+100+100+50 (4 pages), 180 => 100+80 (2 pages)
assert [c[2] for c in client.calls if c[0] == 0] == [100, 100, 100, 50], client.calls
assert [c[2] for c in client.calls if c[0] == 1] == [100, 80], client.calls
assert len(client.calls) == 6

if INSTALLER:
    assert 'check_zivo60_96_27_exhaustive_raw_dialog_pagination.py' in INSTALLER
    assert 'install -m 600 "$SRC/check_zivo60_96_27_exhaustive_raw_dialog_pagination.py" "$BASE/check_zivo60_96_27_exhaustive_raw_dialog_pagination.py"' in INSTALLER

print('CHECK ZIVO60.96.27 EXHAUSTIVE RAW DIALOG PAGINATION: PASS')
print('  raw GetDialogsRequest pagination ignores DialogsSlice early-stop: PASS')
print('  folder 0 + archive folder 1 exhaustive scan: PASS')
print('  synthetic 530 dialogs discovered across 6 raw pages: PASS')
print('  full inventory + campaign both use raw exhaustive paginator: PASS')
