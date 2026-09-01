from __future__ import annotations
import ast
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / 'zivo60.py'
SRC = MAIN.read_text(encoding='utf-8')
INSTALLER = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')
TREE = ast.parse(SRC)

assert any(v in SRC for v in ('VERSION = "zivo60.96.39.3"', 'VERSION = "zivo60.96.39.4"'))


def node(name: str):
    for item in TREE.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name:
            return item
    raise AssertionError(name)


def fn_text(name: str) -> str:
    return ast.get_source_segment(SRC, node(name)) or ''


# 1) Runtime boot must retry the existing authorized session probe, never enter
# interactive SendCode/SignIn/start().
boot_src = fn_text('safe_session_start')
assert 'ZIVO_SESSION_BOOT_ATTEMPTS' in boot_src
assert 'SESSION AUTH PROBE RETRY' in boot_src
assert 'SESSION_AUTH_PROBE_FAILED_AFTER_RETRIES' in boot_src
assert 'await client.disconnect()' in boot_src
assert 'await close_websocket_cache()' in boot_src
assert '.start(' not in boot_src
assert 'SendCode' in boot_src and 'SignIn' in boot_src  # documentation of forbidden path

# Exercise one transient GetState failure followed by success without importing
# the 50k-line runtime module.
class DummyLog:
    def __getattr__(self, _):
        return lambda *a, **k: None

class DummyCache:
    def __init__(self):
        self.calls = []
    def set_self_user(self, *args):
        self.calls.append(args)

class DummyClient:
    def __init__(self):
        self.connected = False
        self.connects = 0
        self.disconnects = 0
        self.probes = 0
        self._authorized = False
        self._self_id = None
        self._mb_entity_cache = DummyCache()
        self.session = SimpleNamespace(auth_key=SimpleNamespace(key=b'x' * 32))
    def is_connected(self):
        return self.connected
    async def connect(self):
        self.connects += 1
        self.connected = True
    async def disconnect(self):
        self.disconnects += 1
        self.connected = False
    async def __call__(self, _req):
        self.probes += 1
        if self.probes == 1:
            raise RuntimeError('temporary transport')
        return SimpleNamespace(pts=1, qts=2, seq=3)

class Updates:
    class GetStateRequest:
        pass
class Functions:
    updates = Updates

client = DummyClient()
closed = []
async def close_cache():
    closed.append(1)

orig_attempts = os.environ.get('ZIVO_SESSION_BOOT_ATTEMPTS')
orig_timeout = os.environ.get('ZIVO_SESSION_BOOT_PROBE_TIMEOUT')
os.environ['ZIVO_SESSION_BOOT_ATTEMPTS'] = '3'
os.environ['ZIVO_SESSION_BOOT_PROBE_TIMEOUT'] = '5'
ns: dict[str, Any] = {
    'asyncio': asyncio,
    'os': os,
    'Optional': Optional,
    'BaseException': BaseException,
    'client': client,
    'functions': Functions,
    'log': DummyLog(),
    'SELF_USER_ID': 49155489,
    'close_websocket_cache': close_cache,
}
mod = ast.Module(body=[node('safe_session_start')], type_ignores=[])
ast.fix_missing_locations(mod)
exec(compile(mod, str(MAIN), 'exec'), ns)
real_sleep = asyncio.sleep
async def fast_sleep(_delay):
    return None
ns['asyncio'].sleep = fast_sleep
try:
    asyncio.run(ns['safe_session_start']())
finally:
    ns['asyncio'].sleep = real_sleep
    if orig_attempts is None:
        os.environ.pop('ZIVO_SESSION_BOOT_ATTEMPTS', None)
    else:
        os.environ['ZIVO_SESSION_BOOT_ATTEMPTS'] = orig_attempts
    if orig_timeout is None:
        os.environ.pop('ZIVO_SESSION_BOOT_PROBE_TIMEOUT', None)
    else:
        os.environ['ZIVO_SESSION_BOOT_PROBE_TIMEOUT'] = orig_timeout
assert client.probes == 2, client.probes
assert client.disconnects == 1, client.disconnects
assert client._authorized is True
assert closed == [1], closed

# 2) Installer must not abort on the first systemd RestartSec/inactive window.
assert 'wait_service_ready(){' in INSTALLER
assert 'STARTUP WAIT | $label' in INSTALLER
assert 'STARTUP FAILED | $label' in INSTALLER
assert 'journalctl -u "$unit" --since "$start_ts"' in INSTALLER
assert 'systemctl status "$unit" --no-pager -l' in INSTALLER
assert 'wait_service_ready "$SERVICE" "$START_TS" "main" 60' in INSTALLER
assert 'wait_service_ready "$unit" "$account_start_ts" "$key" 60' in INSTALLER
assert 'SERVICE DID NOT START' not in INSTALLER
assert 'PREVIOUSLY-ACTIVE ACCOUNT DID NOT RESTART' not in INSTALLER

# 3) Full-source/installed-copy inventory must carry this startup regression test.
deploy_block = INSTALLER.split('DEPLOY_FILES=(', 1)[1].split('\n)', 1)[0]
assert 'check_zivo60_96_39_3_startup_cutover.py' in deploy_block
assert INSTALLER.count('check_zivo60_96_39_3_startup_cutover.py') >= 4

print('CHECK ZIVO60.96.39.3 STARTUP/CUTOVER RELIABILITY: PASS')
print('  existing-session boot retries transient GetState/connect failure: PASS')
print('  no interactive login path introduced: PASS')
print('  installer tolerates systemd RestartSec windows and waits for ready marker: PASS')
print('  startup failure dumps status + journal before rollback: PASS')
print('  startup regression test included in deployed QA inventory: PASS')
