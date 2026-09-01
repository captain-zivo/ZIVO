#!/usr/bin/env python3
from __future__ import annotations
import ast, asyncio, os, re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
m = re.search(r'VERSION = \"zivo60\.96\.(\d+)\"', SRC)
assert m and int(m.group(1)) >= 24

installer_env = os.environ.get('ZIVO_INSTALLER_UNDER_TEST', '').strip()
installer_path = Path(installer_env) if installer_env else (ROOT / 'install_zivo60.sh')
INSTALLER = installer_path.read_text(encoding='utf-8')
for token in (
    'check_zivo60_96_24_cleanup_private_inventory.py',
    'ZIVO_FULL_DIALOG_INVENTORY_REGISTER_ALL_PRIVATE=1',
    'INSTALLED COPY ZIVO60.96.24 CLEANUP/ALL-PRIVATE INVENTORY CHECKS: PASS',
):
    assert token in INSTALLER, token
assert 'install -m 600 "$SRC/check_zivo60_96_24_cleanup_private_inventory.py" "$BASE/check_zivo60_96_24_cleanup_private_inventory.py"' in INSTALLER


def fn(name: str) -> str:
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SRC, node) or ''

# --- cleanup recovery ---
num = fn('command_cleanup_messages')
fullcmd = fn('command_full_chat_cleanup')
assert 'require_native_admin_for_destructive_action' not in num
assert 'require_native_admin_for_destructive_action' not in fullcmd
assert 'is_group_pro_active_for_actor' in fullcmd

batch_src = fn('delete_full_cleanup_batch')
assert 'preverified_unpinned' in batch_src
assert 'if preverified_unpinned:' in batch_src
assert 'return already_absent + verified_deleted + len(remaining), protected' in batch_src
full_exec = fn('execute_full_chat_cleanup')
assert full_exec.count('preverified_unpinned=True') >= 2

# Dynamic proof: preverified history IDs delete without any resolve/get-message RPC.
resolve_calls = {'n': 0}
delete_calls: List[List[int]] = []
async def forbidden_resolve(group, ids):
    resolve_calls['n'] += 1
    raise AssertionError('resolve must not be called for preverified ids')
async def fake_delete(group, ids, **kwargs):
    delete_calls.append(list(ids))
class Log:
    def warning(self, *a, **k): pass
    def info(self, *a, **k): pass
ns = {
    'Any': Any, 'List': List, 'Tuple': tuple, 'asyncio': asyncio, 'log': Log(),
    'cleanup_resolve_message_ids': forbidden_resolve,
    'governed_delete_messages': fake_delete,
    'message_is_pinned': lambda m: False,
    'cleanup_retry_wait_seconds': lambda exc, attempt: 0.0,
    'cleanup_error_is_permission': lambda exc: False,
}
exec(batch_src, ns)
res = asyncio.run(ns['delete_full_cleanup_batch'](object(), [11, 12, 13], preverified_unpinned=True))
assert res == (3, 0), res
assert resolve_calls['n'] == 0
assert delete_calls == [[11, 12, 13]]

# --- all-private full inventory ---
sync_src = fn('full_dialog_inventory_sync')
assert 'FULL_DIALOG_INVENTORY_REGISTER_ALL_PRIVATE' in sync_src
assert 'source="coordination" if int(uid) in coordination_ids else "dialog-inventory"' in sync_src
assert 'stats["private_registered"] += 1' in sync_src
assert 'private_bot_skipped' in sync_src
assert ('iter_dialogs(limit=None)' in sync_src) or ('iter_dialogs_exhaustive_raw' in sync_src)

class FakeUser:
    def __init__(self, uid: int, *, bot: bool=False, deleted: bool=False, access_hash: int=1):
        self.id=uid; self.bot=bot; self.deleted=deleted; self.access_hash=access_hash
class FakeGroup:
    def __init__(self, gid: int):
        self.id=gid; self.title='G'; self.broadcast=False; self.access_hash=99; self.username=None
class FakeDialog:
    def __init__(self, entity): self.entity=entity; self.title=getattr(entity,'title','')
class FakeClient:
    async def iter_dialogs(self, limit=None):
        assert limit is None
        for d in [FakeDialog(FakeGroup(10)), FakeDialog(FakeUser(101, access_hash=1001)), FakeDialog(FakeUser(102, access_hash=1002)), FakeDialog(FakeUser(103, bot=True))]:
            yield d
class FakeTypes:
    User=FakeUser
    Chat=FakeGroup
class Utils:
    @staticmethod
    def get_input_peer(entity): return entity
registered=[]
def register(uid, mid=0, target=None, source='inbound'):
    registered.append((uid, source, getattr(target,'access_hash',0)))
class DummyDB:
    def __enter__(self): return self
    def __exit__(self,*a): pass
    def execute(self, *a, **k): return []
class Log2:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass
async def no_checkpoint(n): pass
async def fake_to_thread_result(*a, **k): return {'created':1,'updated':0,'conflicts':0}
# preserve real asyncio but override to_thread via wrapper
class AioProxy:
    @staticmethod
    async def to_thread(func, *args, **kwargs): return {'created':1,'updated':0,'conflicts':0}
async def fake_exhaustive(_reason='test'):
    async for d in FakeClient().iter_dialogs(limit=None):
        yield d
ns2 = {
    'Dict': Dict, 'List': List, 'types': FakeTypes, 'utils': Utils, 'client': FakeClient(),
    'iter_dialogs_exhaustive_raw': fake_exhaustive,
    'SYSTEM_USER_IDS': set(), 'SELF_USER_ID': 999, 'ACCOUNT_KEY':'main',
    'FULL_DIALOG_INVENTORY_REGISTER_ALL_PRIVATE': True,
    'FULL_DIALOG_INVENTORY_PAGE_SIZE_HINT': 100,
    'coordination_private_user_ids': lambda: {102},
    'db_connect': lambda: DummyDB(), 'safe_int': lambda x: int(x) if x is not None else None,
    'is_group_entity': lambda e: isinstance(e, FakeGroup),
    'register_private_contact': register, '_full_inventory_low_priority_checkpoint': no_checkpoint,
    '_persist_full_dialog_groups': lambda rows: {'created':1,'updated':0,'conflicts':0},
    'asyncio': AioProxy, 'log': Log2(),
}
exec(sync_src, ns2)
stats = asyncio.run(ns2['full_dialog_inventory_sync']('test'))
assert stats['groups_seen'] == 1
assert stats['private_seen'] == 3
assert stats['private_registered'] == 2
assert stats['private_bot_skipped'] == 1
assert {x[0] for x in registered} == {101,102}
assert dict((uid,src) for uid,src,_ in registered)[101] == 'dialog-inventory'
assert dict((uid,src) for uid,src,_ in registered)[102] == 'coordination'

print('CHECK ZIVO60.96.24 CLEANUP + ALL PRIVATE DIALOG INVENTORY: PASS')
print('  cleanup native-probe false-negative removed: PASS')
print('  full cleanup no duplicate resolve for history-fetched unpinned ids: PASS')
print('  owner/PRO entitlement logic preserved: PASS')
print('  every real private User dialog persisted: PASS')
print('  bot/deleted private dialogs excluded: PASS')
print('  coordination PV source preserved: PASS')
