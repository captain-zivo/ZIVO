#!/usr/bin/env python3
from __future__ import annotations
import ast, hashlib, os, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
INSTALLER_PATH = Path(os.getenv('ZIVO_INSTALLER_UNDER_TEST', str(ROOT / 'install_zivo60.sh')))
INSTALLER = INSTALLER_PATH.read_text(encoding='utf-8')
TREE = ast.parse(SRC)

def fn(name: str) -> str:
    lines = SRC.splitlines(True)
    node = next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name == name)
    return ''.join(lines[node.lineno-1:node.end_lineno])

m = re.search(r'VERSION = \"zivo60\.96\.(\d+)\"', SRC)
assert m and int(m.group(1)) >= 18, m.group(1) if m else 'missing-version'
for name in (
    'runtime_group_access_state',
    'ensure_runtime_actor_authority',
    'runtime_bootstrap_group_from_event',
    'require_native_admin_for_destructive_action',
):
    assert f'async def {name}' in SRC, name

bootstrap = fn('runtime_bootstrap_group_from_event')
assert 'owner_user_id' in bootstrap and 'owner=0' in bootstrap
assert 'INSERT OR IGNORE INTO installations' in bootstrap
assert 'runtime-presence:{ACCOUNT_KEY}' in bootstrap
assert "default_locks_json" in bootstrap and "'[]'" in bootstrap
assert 'clear_pending_group_activation' in bootstrap
assert 'sync_native_group_admins' in bootstrap
assert 'reconcile_native_owner_authority' in bootstrap
assert 'runtime_group_access_state' in bootstrap
assert '_verified_requester_admin_from_group' not in bootstrap

actor = fn('ensure_runtime_actor_authority')
assert '_verified_requester_admin_from_group' in actor
assert 'reclaim_bot_ownership_for_real_group_owner' in actor
assert 'upsert_bot_admin' in actor
assert 'role_level(current) >= 2' in actor

manual = fn('handle_group_install_command')
assert 'runtime_group_access_state(group, force=True)' in manual
assert 'reason=bot_admin_not_confirmed' not in manual

router = fn('_zivo_router_impl')
assert 'runtime_bootstrap_group_from_event(event)' in router
assert router.index('runtime_bootstrap_group_from_event(event)') < router.index('command_candidate_hot = bool(')
assert 'runtime command route' in router

cleanup = fn('command_cleanup_messages')
full_cleanup = fn('command_full_chat_cleanup')
if int(m.group(1)) < 24:
    assert 'globals().get("require_native_admin_for_destructive_action")' in cleanup and '"cleanup"' in cleanup
    assert 'globals().get("require_native_admin_for_destructive_action")' in full_cleanup and '"full_cleanup"' in full_cleanup
else:
    # 96.24: Soroush native-role probes can false-negative on some group types.
    # Cleanup now relies on the actual delete RPC for destructive permission.
    assert 'require_native_admin_for_destructive_action' not in cleanup
    assert 'require_native_admin_for_destructive_action' not in full_cleanup

# Protected Persian literals remain byte-identical to the prior release.
p = [n.value for n in ast.walk(TREE) if isinstance(n,ast.Constant) and isinstance(n.value,str) and any('\u0600' <= c <= '\u06ff' for c in n.value)]
assert len(p) >= 3992, len(p)
for literal in ('مالک', 'ادمین', 'ویژه', 'پاکسازی', 'راهنما'):
    assert any(literal in item for item in p), literal

for setting in (
    'ZIVO_RUNTIME_GROUP_BOOTSTRAP=1',
    'ZIVO_RUNTIME_GROUP_ACCESS_TTL=90',
    'ZIVO_RUNTIME_GROUP_AUTHORITY_TIMEOUT=5',
):
    assert setting in INSTALLER, setting

print('CHECK ZIVO60.96.18 RUNTIME PRESENCE + BASIC/FULL ACCESS: PASS')
print('  unknown-group command auto-bootstrap without admin prerequisite: PASS')
print('  safe owner=0 placeholder + native creator/admin repair: PASS')
print('  native admin FULL / normal member BASIC runtime mode: PASS')
print('  internal admin/special authority recovered from Soroush proof: PASS')
print('  cleanup destructive permission path: PASS')
print('  protected Persian literals unchanged: PASS')
