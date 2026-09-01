#!/usr/bin/env python3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Tuple
import ast
import asyncio

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
SETUP = (ROOT / 'setup_zivo_accounts.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)

def fn_source(name: str) -> str:
    for node in ast.walk(TREE):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SRC, node) or ''
    raise AssertionError(f'missing function: {name}')

m = __import__('re').search(r'VERSION = \"zivo60\.96\.(\d+)\"', SRC)
assert m and int(m.group(1)) >= 19

authority = fn_source('ensure_runtime_actor_authority')
assert '_verified_requester_admin_from_group' in authority
assert '_native_admin_for_user' in authority
assert 'admin_list_creator' in authority
assert 'admin_list_admin' in authority
assert 'runtime actor authority fallback PASS' in authority
assert 'ChannelParticipantCreator' in authority and 'ChatParticipantCreator' in authority

reply_target = fn_source('require_role_reply_target')
assert 'moderation_reply_target' in reply_target
assert 'role target reply proof accepted' in reply_target
assert 'role_target_group_membership_proven' not in reply_target

explicit = fn_source('resolve_moderation_target_spec')
assert 'role_target_group_membership_proven' in explicit
assert 'strict_group_member' in explicit

admin = fn_source('command_set_admin')
special = fn_source('command_set_special')
assert 'base_bot_role' in admin and 'BOT_ROLE_OWNER' in admin and 'upsert_bot_admin' in admin
assert 'base_bot_role' in special and 'upsert_bot_special' in special

assert 'connection_retries=2' in SETUP
assert 'request_retries=2' in SETUP
assert 'timeout=20' in SETUP
assert 'timedelta' not in SETUP

# Dynamic branch checks for the two live regressions.
class FakeCreator: pass
class FakeAdmin: pass
class FakeChatCreator: pass
class FakeChatAdmin: pass
class DummyLog:
    def debug(self, *a, **k): pass
    def info(self, *a, **k): pass

async def run_actor_fallback(participant: Any, expected: str) -> None:
    state = {'role': 'کاربر عادی', 'reclaimed': 0, 'admin_upsert': 0}
    async def direct(*a, **k): return None, 'requester_direct_unavailable', False
    async def broad(*a, **k): return SimpleNamespace(id=9001, username='actor', access_hash=77, participant=participant)
    def base(*a, **k): return state['role']
    def reclaim(*a, **k):
        state['reclaimed'] += 1
        state['role'] = 'مالک'
    def upsert(*a, **k):
        state['admin_upsert'] += 1
        state['role'] = 'ادمین'
    ns = {
        'Any': Any, 'asyncio': asyncio, 'safe_int': lambda x: int(x) if x is not None else None,
        'SELF_USER_ID': 49155489, 'SYSTEM_USER_IDS': set(), 'base_bot_role': base,
        'role_level': lambda r: {'مالک':3,'ادمین':2,'ویژه':1,'کاربر عادی':0}.get(r,0),
        'input_peer_access_hash': lambda x: 0, '_verified_requester_admin_from_group': direct,
        '_native_admin_for_user': broad, 'RUNTIME_GROUP_AUTHORITY_TIMEOUT': 0.5,
        'types': SimpleNamespace(ChannelParticipantCreator=FakeCreator, ChatParticipantCreator=FakeChatCreator),
        'get_installation': lambda gid: {'owner_user_id':0,'native_owner_user_id':0,'owner_mode':'runtime'},
        'reclaim_bot_ownership_for_real_group_owner': reclaim, 'upsert_bot_admin': upsert,
        'db_connect': lambda: None, 'invalidate_group_hot_caches': lambda *a: None,
        'refresh_role_membership_cache': lambda *a: None, 'log': DummyLog(),
    }
    exec(authority, ns)
    event = SimpleNamespace(sender_id=9001, input_sender=None)
    result = await ns['ensure_runtime_actor_authority'](event, object(), 123)
    assert result == expected, (result, expected)
    if expected == 'مالک':
        assert state['reclaimed'] == 1 and state['admin_upsert'] == 0
    else:
        assert state['admin_upsert'] == 1 and state['reclaimed'] == 0

async def run_reply_proof() -> None:
    membership_calls = {'n': 0}
    async def moderation(*a, **k): return (7007, 55, 'target')
    async def resolve(*a, **k): raise AssertionError('explicit resolver must not run for reply-only test')
    async def forbidden_membership(*a, **k):
        membership_calls['n'] += 1
        raise AssertionError('reply target must not be re-probed')
    async def send(*a, **k): pass
    ns = {
        'Any': Any, 'Optional': Optional, 'Tuple': Tuple,
        'resolve_moderation_target_spec': resolve, 'moderation_reply_target': moderation,
        'role_target_group_membership_proven': forbidden_membership,
        'send_group_text': send, 'role_target_unresolved': lambda x: x,
        'role_target_usage': lambda x: x, 'role_system_target_denied': lambda: 'no',
        'SELF_USER_ID': 49155489, 'SYSTEM_USER_IDS': set(), 'log': DummyLog(),
    }
    exec(reply_target, ns)
    event = SimpleNamespace(is_reply=True)
    result = await ns['require_role_reply_target'](event, object(), 'ادمین', 123, '')
    assert result == (7007, 55, 'target')
    assert membership_calls['n'] == 0

asyncio.run(run_actor_fallback(FakeCreator(), 'مالک'))
asyncio.run(run_actor_fallback(FakeAdmin(), 'ادمین'))
asyncio.run(run_reply_proof())

print('CHECK ZIVO60.96.19 ADMIN/SPECIAL LIVE ROLE RECOVERY: PASS')
print('  reply-message target bypasses unsupported participant re-probe: PASS')
print('  native actor direct -> admin-list authority fallback: PASS')
print('  native creator restores owner; native admin restores admin: PASS')
print('  explicit ID/username target remains strict-membership guarded: PASS')
print('  dynamic creator/admin fallback branches: PASS')
print('  dynamic reply-target no-reprobe branch: PASS')
print('  secondary login retries bounded with numeric timeout: PASS')
