#!/usr/bin/env python3
from __future__ import annotations
import ast, asyncio, fcntl, os, tempfile, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)

assert any(f'VERSION = "zivo60.96.{v}"' in SRC for v in range(23, 100))
for token in (
    'FULL_DIALOG_INVENTORY_LOCK_PATH',
    'FULL_DIALOG_INVENTORY_PAGE_PAUSE_SECONDS',
    'FULL_DIALOG_INVENTORY_PRIORITY_QUIET_SECONDS',
    'FULL_DIALOG_INVENTORY_PENDING_SOFT',
    '_try_acquire_full_inventory_lock',
    '_full_inventory_low_priority_checkpoint',
    '_priority_traffic_is_hot(FULL_DIALOG_INVENTORY_PRIORITY_QUIET_SECONDS)',
    '_transport_pending_request_count(client)',
    'await _full_inventory_low_priority_checkpoint(stats["dialogs"])',
    'private target 404 cooldown',
    'PRIVATE_TARGET_NOT_FOUND_COOLDOWN',
    'shared-lock+pm-priority',
):
    assert token in SRC, token

# Unlimited scan remains intact.
assert ('client.iter_dialogs(limit=None)' in SRC) or ('iter_dialogs_exhaustive_raw' in SRC)


def fn(name: str) -> str:
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SRC, node) or ''

sync_src = fn('full_dialog_inventory_sync')
assert ('iter_dialogs(limit=None)' in sync_src) or ('iter_dialogs_exhaustive_raw' in sync_src)
assert '_full_inventory_low_priority_checkpoint' in sync_src
assert 'TELEGRAM_PRIVATE_DISCOVERY_LIMIT' not in sync_src

worker_src = fn('full_dialog_inventory_worker')
assert '_try_acquire_full_inventory_lock' in worker_src
assert '_release_full_inventory_lock' in worker_src
assert '_priority_traffic_is_hot(FULL_DIALOG_INVENTORY_PRIORITY_QUIET_SECONDS)' in worker_src

send_src = fn('send_private')
assert '_private_not_found_cooldown_active' in send_src
assert '_is_private_not_found_error' in send_src
assert '_mark_private_not_found_cooldown' in send_src

# Cross-process lock is exclusive.
td = Path(tempfile.mkdtemp())
lock_path = td / 'inventory.lock'
ns = {
    'Optional': Optional, 'Any': Any, 'FULL_DIALOG_INVENTORY_LOCK_PATH': lock_path,
    'fcntl': fcntl, 'ACCOUNT_KEY': 'main', 'os': os, 'datetime': datetime, 'timezone': timezone,
}
exec(fn('_try_acquire_full_inventory_lock'), ns)
exec(fn('_release_full_inventory_lock'), ns)
h1 = ns['_try_acquire_full_inventory_lock']()
assert h1 is not None
h2 = ns['_try_acquire_full_inventory_lock']()
assert h2 is None
ns['_release_full_inventory_lock'](h1)
h3 = ns['_try_acquire_full_inventory_lock']()
assert h3 is not None
ns['_release_full_inventory_lock'](h3)

# 404 cooldown classification and state are deterministic.
ns2 = {
    'BaseException': BaseException, 'Optional': Optional, 'time': time,
    '_private_not_found_until': {}, 'PRIVATE_NOT_FOUND_COOLDOWN_SECONDS': 300.0,
}
for name in ('_is_private_not_found_error', '_private_not_found_cooldown_active', '_mark_private_not_found_cooldown'):
    exec(fn(name), ns2)
err = RuntimeError('RPCError 404: NOT_FOUND (caused by SendMessageRequest)')
assert ns2['_is_private_not_found_error'](err) is True
assert ns2['_private_not_found_cooldown_active'](123) is False
ns2['_mark_private_not_found_cooldown'](123)
assert ns2['_private_not_found_cooldown_active'](123) is True

# Low-priority checkpoint actually waits while priority traffic is hot.
checkpoint_src = fn('_full_inventory_low_priority_checkpoint')
state = {'calls': 0}
class Log:
    def info(self, *a, **k):
        pass
async def fake_sleep(_):
    state['calls'] += 1
    await asyncio.sleep(0)
def priority(_window=None):
    return state['calls'] < 2
ns3 = {
    'asyncio': asyncio, 'log': Log(), 'ACCOUNT_KEY': 'main', 'client': object(),
    'FULL_DIALOG_INVENTORY_PRIORITY_QUIET_SECONDS': 2.5,
    'FULL_DIALOG_INVENTORY_PENDING_SOFT': 12,
    'FULL_DIALOG_INVENTORY_PAGE_PAUSE_SECONDS': 0.0,
    '_priority_traffic_is_hot': priority,
    '_transport_pending_request_count': lambda _c: 0,
}
# swap only sleep inside extracted function globals by proxy module-like object
class A:
    @staticmethod
    async def sleep(x):
        await fake_sleep(x)
ns3['asyncio'] = A
exec(checkpoint_src, ns3)
asyncio.run(ns3['_full_inventory_low_priority_checkpoint'](100))
assert state['calls'] >= 3

print('CHECK ZIVO60.96.23 PRIVATE PRIORITY + THROTTLED FULL INVENTORY: PASS')
print('  unlimited/exhaustive dialog scan preserved: PASS')
print('  one-account-at-a-time cross-process inventory lock: PASS')
print('  page-level PM/command priority checkpoint: PASS')
print('  transport pending-pressure pause: PASS')
print('  404 private target cooldown skips duplicate retry RPC: PASS')
