#!/usr/bin/env python3
from __future__ import annotations
import ast
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / 'zivo60.py'
MULTI = ROOT / 'zivo_multi_account.py'
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.15"' in SRC


def node(name: str):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def fn_text(name: str) -> str:
    n = node(name); lines = SRC.splitlines(True)
    return ''.join(lines[n.lineno - 1:n.end_lineno])


def exec_fn(ns: dict[str, Any], name: str):
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), 'exec'), ns)

# 1) Multi-account live lease is atomic and live evidence can replace stale static ownership.
import zivo_multi_account as multi
with tempfile.TemporaryDirectory() as td:
    control = Path(td) / 'control.db'
    multi.init_control_db(control)
    owned, claim = multi.claim_group(control, group_id=777, account_key='acc3', self_id=3, status='active')
    assert owned and claim['account_key'] == 'acc3'
    won, lease = multi.acquire_group_event_lease(control, group_id=777, account_key='acc2', message_id=55, ttl_seconds=4)
    assert won and lease['account_key'] == 'acc2'
    won2, lease2 = multi.acquire_group_event_lease(control, group_id=777, account_key='acc3', message_id=55, ttl_seconds=4)
    assert not won2 and lease2['account_key'] == 'acc2'
    adopted = multi.adopt_group_claim_from_live_event(control, group_id=777, account_key='acc2', self_id=2, group_title='قدیمی')
    assert adopted is not None and adopted['account_key'] == 'acc2' and int(adopted['self_id']) == 2

# 2) Recovery copies safe durable configuration but NEVER stale cleanup schedules/jobs.
assign = next(n for n in TREE.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == 'LEGACY_GROUP_RECOVERY_TABLES')
RECOVERY_TABLES = ast.literal_eval(assign.value)
assert 'installations' in RECOVERY_TABLES
assert 'bot_admins' in RECOVERY_TABLES
assert 'group_bot_power' in RECOVERY_TABLES
assert 'cleanup_schedules' not in RECOVERY_TABLES
assert 'bot_message_delete_jobs' not in RECOVERY_TABLES

with tempfile.TemporaryDirectory() as td:
    srcp = Path(td) / 'src.db'; dstp = Path(td) / 'dst.db'
    schema = [
        '''CREATE TABLE installations(group_id INTEGER PRIMARY KEY, group_title TEXT, owner_user_id INTEGER, owner_username TEXT, owner_access_hash INTEGER, invite_hash TEXT, install_source TEXT, default_locks_json TEXT, installed_at TEXT)''',
        '''CREATE TABLE bot_admins(group_id INTEGER, user_id INTEGER, username TEXT, access_hash INTEGER, added_by INTEGER, added_at TEXT, source TEXT, PRIMARY KEY(group_id,user_id))''',
        '''CREATE TABLE group_bot_power(group_id INTEGER PRIMARY KEY, enabled INTEGER, expires_at TEXT, expire_to_enabled INTEGER, peer_kind TEXT, group_access_hash INTEGER, updated_by INTEGER, updated_at TEXT)''',
        '''CREATE TABLE cleanup_schedules(schedule_id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, enabled INTEGER)''',
    ]
    for path in (srcp, dstp):
        c = sqlite3.connect(path)
        for sql in schema: c.execute(sql)
        c.commit(); c.close()
    c = sqlite3.connect(srcp)
    c.execute("INSERT INTO installations VALUES(777,'Old',10,'u',0,'h','legacy','[]','now')")
    c.execute("INSERT INTO bot_admins VALUES(777,20,'admin',0,10,'now','manual')")
    c.execute("INSERT INTO group_bot_power VALUES(777,1,NULL,NULL,'channel',0,10,'now')")
    c.execute("INSERT INTO cleanup_schedules(group_id,enabled) VALUES(777,1)")
    c.commit(); c.close()

    def db_connect():
        con = sqlite3.connect(dstp, timeout=1); con.row_factory = sqlite3.Row; return con
    ns = {
        'Path': Path, 'sqlite3': sqlite3, 'DB_PATH': dstp,
        'LEGACY_GROUP_RECOVERY_TABLES': RECOVERY_TABLES,
        'db_connect': db_connect,
        '_invalidate_group_after_legacy_recovery': lambda gid: None,
    }
    exec_fn(ns, '_copy_legacy_group_state_from_db')
    copied = ns['_copy_legacy_group_state_from_db'](777, str(srcp))
    assert copied == 3, copied
    c = sqlite3.connect(dstp)
    assert c.execute('SELECT group_title FROM installations WHERE group_id=777').fetchone()[0] == 'Old'
    assert c.execute('SELECT user_id FROM bot_admins WHERE group_id=777').fetchone()[0] == 20
    assert c.execute('SELECT enabled FROM group_bot_power WHERE group_id=777').fetchone()[0] == 1
    assert c.execute('SELECT COUNT(*) FROM cleanup_schedules WHERE group_id=777').fetchone()[0] == 0
    c.close()

# 3) Router performs old-group recovery before install gating/rate/flood handling.
router = fn_text('_zivo_router_impl')
assert router.index('prepare_legacy_group_command_route') < router.index('command_candidate_hot = bool')
assert router.index('prepare_legacy_group_command_route') < router.index('maybe_enforce_message_rate_limit')
assert router.index('prepare_legacy_group_command_route') < router.index('consume_group_anti_spam_event')
assert 'legacy duplicate group command suppressed' in fn_text('prepare_legacy_group_command_route')
assert 'recover_legacy_group_installation' in fn_text('prepare_legacy_group_command_route')

# 4) Functional command-route decision: lease winner recovers; loser suppresses duplicate reply.
class Log:
    def warning(self,*a,**k): pass
    def info(self,*a,**k): pass
    def debug(self,*a,**k): pass

state = {'installed': None, 'adopted': None}
def get_installation(gid): return state['installed']
def lookup(*a, **k): return {'account_key':'acc3'}
def lease_win(*a, **k): return True, {'account_key':'acc2'}
def recover(gid):
    state['installed'] = {'group_title':'Recovered'}
    return True, 'acc3', 12
def adopt(*a, **k): state['adopted'] = k; return {'account_key':'acc2'}
ns = {
    'Any': Any, 'Dict': Dict, 'ACCOUNT_KEY':'acc2', 'SELF_USER_ID':2,
    'MULTI_ACCOUNT_DB':Path('/tmp/nope'), 'get_installation':get_installation,
    'multi_lookup_group_claim':lookup, '_legacy_group_account_sources':lambda gid:[],
    'multi_acquire_group_event_lease':lease_win, 'recover_legacy_group_installation':recover,
    'multi_adopt_group_claim_from_live_event':adopt, 'log':Log(),
}
exec_fn(ns, 'prepare_legacy_group_command_route')
result = ns['prepare_legacy_group_command_route'](777, 99)
assert result['handle'] and result['recovered'] and result['source'] == 'acc3'
assert state['adopted']['account_key'] == 'acc2'

state2 = {'installed': {'group_title':'Local'}}
ns2 = {
    'Any': Any, 'Dict': Dict, 'ACCOUNT_KEY':'acc3', 'SELF_USER_ID':3,
    'MULTI_ACCOUNT_DB':Path('/tmp/nope'), 'get_installation':lambda gid:state2['installed'],
    'multi_lookup_group_claim':lambda *a,**k:{'account_key':'acc2'}, '_legacy_group_account_sources':lambda gid:[],
    'multi_acquire_group_event_lease':lambda *a,**k:(False, {'account_key':'acc2'}),
    'recover_legacy_group_installation':lambda gid:(False,'',0),
    'multi_adopt_group_claim_from_live_event':lambda *a,**k:None, 'log':Log(),
}
exec_fn(ns2, 'prepare_legacy_group_command_route')
result2 = ns2['prepare_legacy_group_command_route'](777, 99)
assert result2['handle'] is False and result2['owner'] == 'acc2'

# 5) Startup conflict is informational; live lease is authoritative.
seed = fn_text('sync_local_multi_group_claims')
assert 'shared group seed historical duplicate' in seed
assert 'live_lease=authoritative' in seed
assert 'log.warning(\n                    "shared group seed conflict' not in seed

print('CHECK ZIVO60.96.15 LEGACY MULTI-ACCOUNT GROUP RECOVERY: PASS')
print('  atomic live command lease across main/acc2/acc3: PASS')
print('  stale static owner replaced by real inbound-event owner: PASS')
print('  safe legacy DB config/roles recovery: PASS')
print('  stale cleanup automation excluded from recovery: PASS')
print('  recovery before rate/flood/install command gates: PASS')
print('  duplicate old-account command reply suppression: PASS')
