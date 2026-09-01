#!/usr/bin/env python3
from __future__ import annotations
import ast
import asyncio
import os
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / 'zivo60.py'
INSTALLER = Path(os.environ.get('ZIVO_INSTALLER_UNDER_TEST', str(ROOT / 'install_zivo60.sh')))
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.17"' in SRC


def node(name: str):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def fn_text(name: str) -> str:
    n = node(name); lines = SRC.splitlines(True)
    return ''.join(lines[n.lineno - 1:n.end_lineno])


def exec_fn(ns: dict[str, Any], name: str):
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), 'exec'), ns)


# 1) Central client send path must use the governor and group-command priority.
client = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == 'SafeReconnectSoroushClient')
method = next(n for n in client.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'send_message')
lines = SRC.splitlines(True)
client_send = ''.join(lines[method.lineno - 1:method.end_lineno])
assert 'governed_send_message_rpc' in client_send
assert '_group_command_reply_to.get() is not None' in client_send
assert 'super(SafeReconnectSoroushClient, self).send_message' in client_send

# 2) Short FloodWait must pause and retry foreground command exactly through the central lane.
class FloodWaitError(Exception):
    def __init__(self, seconds: float):
        self.seconds = seconds
        super().__init__(f'A wait of {seconds} seconds is required (caused by SendMessageRequest)')

class Log:
    def warning(self, *a, **k):
        pass

ns: dict[str, Any] = {
    'Any': Any,
    'Optional': Optional,
    'BaseException': BaseException,
    'asyncio': asyncio,
    'time': time,
    're': __import__('re'),
    'log': Log(),
    'ACCOUNT_KEY': 'acc2',
    'SEND_RPC_MIN_INTERVAL_SECONDS': 0.01,
    'SEND_RPC_FLOOD_BUFFER_SECONDS': 0.01,
    'SEND_RPC_COMMAND_RETRY_MAX_WAIT_SECONDS': 2.0,
    'SEND_RPC_COMMAND_RETRIES': 2,
    'SEND_RPC_BACKGROUND_PRIORITY_WAIT_SECONDS': 0.05,
    '_send_rpc_sem': asyncio.Semaphore(1),
    '_send_rpc_next_allowed_at': 0.0,
    '_send_rpc_pause_until': 0.0,
    '_send_rpc_last_flood_log_at': 0.0,
    '_send_command_waiters': 0,
}
exec_fn(ns, 'delete_rpc_flood_wait_seconds')
exec_fn(ns, 'governed_send_message_rpc')

async def check_command_retry():
    calls = {'n': 0}
    async def sender():
        calls['n'] += 1
        if calls['n'] == 1:
            raise FloodWaitError(0.1)
        return 'sent'
    started = time.monotonic()
    result = await ns['governed_send_message_rpc'](sender, command_priority=True)
    elapsed = time.monotonic() - started
    assert result == 'sent'
    assert calls['n'] == 2, calls
    # parser intentionally floors a FloodWait to 0.5 sec
    assert elapsed >= 0.49, elapsed
    assert elapsed < 1.8, elapsed
    assert ns['_send_command_waiters'] == 0

asyncio.run(check_command_retry())

# 3) A background FloodWait must arm one shared pause so the next command cannot hammer immediately.
ns['_send_rpc_sem'] = asyncio.Semaphore(1)
ns['_send_rpc_next_allowed_at'] = 0.0
ns['_send_rpc_pause_until'] = 0.0
ns['_send_command_waiters'] = 0
async def check_shared_pause():
    async def noisy_background():
        raise FloodWaitError(0.1)
    try:
        await ns['governed_send_message_rpc'](noisy_background, command_priority=False)
    except FloodWaitError:
        pass
    else:
        raise AssertionError('background flood must propagate after arming pause')
    async def command_sender():
        return 'ok'
    started = time.monotonic()
    result = await ns['governed_send_message_rpc'](command_sender, command_priority=True)
    elapsed = time.monotonic() - started
    assert result == 'ok'
    assert elapsed >= 0.49, elapsed

asyncio.run(check_shared_pause())

# 4) Existing plain-message fallback and legacy route must remain intact.
assert 'group text rich fallback PASS' in fn_text('send_group_text')
router = fn_text('_zivo_router_impl')
assert 'legacy command live route' in router
assert 'prepare_legacy_group_command_route' in router

# 5) Installer must reconcile the governor defaults for all three accounts and validate this test.
installer = INSTALLER.read_text(encoding='utf-8')
for setting in (
    'ZIVO_SEND_RPC_MIN_INTERVAL=0.18',
    'ZIVO_SEND_RPC_FLOOD_BUFFER=0.35',
    'ZIVO_SEND_RPC_COMMAND_RETRY_MAX_WAIT=6.0',
    'ZIVO_SEND_RPC_COMMAND_RETRIES=2',
    'ZIVO_SEND_RPC_BACKGROUND_PRIORITY_WAIT=0.75',
):
    assert setting in installer, setting
assert 'check_zivo60_96_17_send_flood_recovery.py' in installer

print('CHECK ZIVO60.96.17 SEND FLOOD RECOVERY + COMMAND DELIVERY: PASS')
print('  foreground short-FloodWait retry: PASS')
print('  shared account send pause after background FloodWait: PASS')
print('  command priority over fresh background sends: PASS')
print('  legacy-group route + plain fallback preserved: PASS')
print('  installer governor defaults: PASS')
