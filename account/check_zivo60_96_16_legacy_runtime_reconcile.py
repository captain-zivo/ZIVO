#!/usr/bin/env python3
from __future__ import annotations
import ast
import sqlite3
import tempfile
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / 'zivo60.py'
MULTI = ROOT / 'zivo_multi_account.py'
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.16"' in SRC


def node(name: str):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def fn_text(name: str) -> str:
    n = node(name); lines = SRC.splitlines(True)
    return ''.join(lines[n.lineno - 1:n.end_lineno])


def exec_fn(ns: dict[str, Any], name: str):
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), 'exec'), ns)

# 1) Startup historical claim seeding is one batch transaction and preserves foreign owners.
import zivo_multi_account as multi
multi_src = MULTI.read_text(encoding='utf-8')
assert 'def seed_group_claims_bulk' in multi_src
bulk_text = multi_src[multi_src.index('def seed_group_claims_bulk'):multi_src.index('def lookup_group_event_lease')]
assert bulk_text.count('BEGIN IMMEDIATE') == 1
with tempfile.TemporaryDirectory() as td:
    control = Path(td) / 'control.db'
    multi.init_control_db(control)
    ok, _ = multi.claim_group(control, group_id=10, account_key='acc3', self_id=3, status='active')
    assert ok
    groups = [
        {'group_id': i, 'group_title': f'g{i}', 'public_username': '', 'invite_fingerprint': ''}
        for i in range(1, 2001)
    ]
    started = time.monotonic()
    owned, conflicts = multi.seed_group_claims_bulk(control, account_key='main', self_id=1, groups=groups)
    elapsed = time.monotonic() - started
    assert owned == 1999 and conflicts == 1, (owned, conflicts)
    assert multi.lookup_group_claim(control, group_id=10)['account_key'] == 'acc3'
    assert multi.lookup_group_claim(control, group_id=2000)['account_key'] == 'main'
    assert elapsed < 8.0, elapsed

# 2) Startup function uses the batch helper rather than one claim_group call per group.
seed = fn_text('sync_local_multi_group_claims')
assert 'multi_seed_group_claims_bulk' in seed
assert 'for row in rows' in seed
assert 'multi_claim_group(' not in seed

# 3) Placeholder installation is privilege-safe and does not create cleanup automation.
with tempfile.TemporaryDirectory() as td:
    dbp = Path(td) / 'local.db'
    con = sqlite3.connect(dbp)
    con.executescript('''
      CREATE TABLE installations(
        group_id INTEGER PRIMARY KEY, group_title TEXT NOT NULL DEFAULT '', owner_user_id INTEGER NOT NULL,
        owner_username TEXT NOT NULL DEFAULT '', owner_access_hash INTEGER NOT NULL DEFAULT 0,
        invite_hash TEXT NOT NULL DEFAULT '', install_source TEXT NOT NULL DEFAULT '',
        default_locks_json TEXT NOT NULL DEFAULT '[]', installed_at TEXT NOT NULL,
        native_owner_user_id INTEGER NOT NULL DEFAULT 0, native_owner_username TEXT NOT NULL DEFAULT '',
        native_owner_access_hash INTEGER NOT NULL DEFAULT 0, owner_mode TEXT NOT NULL DEFAULT 'native'
      );
      CREATE TABLE group_lifecycle(
        group_id INTEGER PRIMARY KEY, group_title TEXT NOT NULL DEFAULT '', peer_kind TEXT NOT NULL DEFAULT 'channel',
        group_access_hash INTEGER NOT NULL DEFAULT 0, activated_at TEXT NOT NULL,
        last_activity_at TEXT NOT NULL, updated_at TEXT NOT NULL
      );
      CREATE TABLE cleanup_schedules(schedule_id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER, enabled INTEGER);
      CREATE TABLE bot_message_delete_jobs(job_id INTEGER PRIMARY KEY AUTOINCREMENT, group_id INTEGER);
    ''')
    con.commit(); con.close()
    def db_connect():
        c = sqlite3.connect(dbp); c.row_factory = sqlite3.Row; return c
    def get_installation(gid):
        c=db_connect(); r=c.execute('SELECT * FROM installations WHERE group_id=?',(gid,)).fetchone(); c.close(); return r
    ns = {
        'Any':Any, 'Dict':Dict, 'Path':Path, 'sqlite3':sqlite3,
        'datetime':datetime, 'timezone':timezone, 'db_connect':db_connect,
        'get_installation':get_installation, '_invalidate_group_after_legacy_recovery':lambda gid:None,
        'ACCOUNT_KEY':'main', 'log':type('L',(),{'warning':lambda *a,**k:None})(),
    }
    exec_fn(ns, 'create_legacy_live_placeholder_installation')
    assert ns['create_legacy_live_placeholder_installation'](777, 'legacy')
    c=sqlite3.connect(dbp)
    row=c.execute('SELECT owner_user_id, owner_mode, install_source FROM installations WHERE group_id=777').fetchone()
    assert row == (0, 'recovery', 'legacy-live-placeholder'), row
    assert c.execute('SELECT COUNT(*) FROM cleanup_schedules').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM bot_message_delete_jobs').fetchone()[0] == 0
    c.close()

# 4) A stale explicit local OFF is healed only by a newer explicit remote ON.
with tempfile.TemporaryDirectory() as td:
    local=Path(td)/'local.db'; remote=Path(td)/'remote.db'
    for p in (local,remote):
        c=sqlite3.connect(p)
        c.executescript('''
          CREATE TABLE installations(group_id INTEGER PRIMARY KEY, group_title TEXT, owner_user_id INTEGER, owner_username TEXT, owner_access_hash INTEGER, invite_hash TEXT, install_source TEXT, default_locks_json TEXT, installed_at TEXT);
          CREATE TABLE group_bot_power(group_id INTEGER PRIMARY KEY, enabled INTEGER, expires_at TEXT, expire_to_enabled INTEGER, peer_kind TEXT, group_access_hash INTEGER, updated_by INTEGER, updated_at TEXT);
        ''')
        c.execute("INSERT INTO installations VALUES(777,'g',1,'',0,'','legacy','[]','2026-01-01T00:00:00+00:00')")
        c.commit(); c.close()
    old='2026-01-01T00:00:00+00:00'; new='2026-08-28T00:00:00+00:00'
    c=sqlite3.connect(local); c.execute("INSERT INTO group_bot_power VALUES(777,0,NULL,NULL,'channel',0,1,?)",(old,)); c.commit(); c.close()
    c=sqlite3.connect(remote); c.execute("INSERT INTO group_bot_power VALUES(777,1,NULL,NULL,'channel',0,2,?)",(new,)); c.commit(); c.close()
    copied={'n':0}
    def local_state(gid): return {'enabled':False,'updated_at':old}
    def copy_state(gid,path): copied['n']+=1; return 3
    ns={
      'Any':Any,'Dict':Dict,'Optional':Optional,'Tuple':Tuple,'Path':Path,'sqlite3':sqlite3,'time':time,
      'datetime':datetime,'timezone':timezone,'ACCOUNT_KEY':'main','DB_PATH':local,
      '_legacy_group_power_reconcile_cache':{},'LEGACY_GROUP_POWER_RECONCILE_TTL':20.0,
      'get_group_bot_power_state':local_state,'_legacy_group_account_sources':lambda gid:[('main',str(local)),('acc3',str(remote))],
      '_copy_legacy_group_state_from_db':copy_state,'is_group_bot_enabled':lambda gid: True,
      'log':type('L',(),{'debug':lambda *a,**k:None,'warning':lambda *a,**k:None})(),
    }
    for name in ('_legacy_iso_epoch','_legacy_group_power_from_db','reconcile_legacy_group_power_if_stale'):
        exec_fn(ns,name)
    healed,key,n=ns['reconcile_legacy_group_power_if_stale'](777)
    assert healed and key=='acc3' and n==3 and copied['n']==1

# 5) Live command route supports both missing-state placeholder and existing-state reconciliation.
route = fn_text('prepare_legacy_group_command_route')
assert 'create_legacy_live_placeholder_installation' in route
assert 'reconcile_legacy_group_power_if_stale' in route
router = fn_text('_zivo_router_impl')
assert 'legacy command live route' in router
assert router.index('prepare_legacy_group_command_route') < router.index('command_candidate_hot = bool')
assert 'force_owner=True' in router

print('CHECK ZIVO60.96.16 LEGACY RUNTIME RECONCILE + FAST STARTUP: PASS')
print('  2000-group shared-claim batch seed: PASS')
print('  existing foreign claim preserved: PASS')
print('  safe owner=0 live placeholder: PASS')
print('  stale local OFF vs newer remote ON reconcile: PASS')
print('  live command diagnostics + authority refresh: PASS')
