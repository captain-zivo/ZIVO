#!/usr/bin/env python3
from __future__ import annotations
import ast, sqlite3, tempfile
from pathlib import Path
from typing import List
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC)
assert any(f'VERSION = "zivo60.96.{v}"' in SRC for v in range(22, 100))
for token in (
    'FULL_DIALOG_INVENTORY_ENABLED',
    'iter_dialogs_exhaustive_raw',
    'full_dialog_inventory_sync',
    'full_dialog_inventory_worker',
    'request_full_inventory_sync_all',
    'coordination_private_user_ids',
    'full dialog inventory PASS',
    'z:syncall',
    '🔎 اسکن کامل شبکه',
):
    assert token in SRC, token

# 96.22 originally exposed coordination-PV wording. Newer releases may broaden
# the same scope to every real private dialog while preserving coordination PVs.
assert ('پیوی هماهنگی' in SRC) or ('همه پیوی‌های واقعی' in SRC), 'private inventory UI label'

def fn(name:str)->str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ast.get_source_segment(SRC,node) or ''

full=fn('full_dialog_inventory_sync')
assert 'iter_dialogs_exhaustive_raw' in full
assert 'TELEGRAM_PRIVATE_DISCOVERY_LIMIT' not in full
assert 'get_dialogs(limit=' not in full

coord=fn('coordination_private_user_ids')
assert 'pending_group_activations' in coord
assert 'join_jobs' in coord
assert 'social_private_starts' in coord

targets=fn('telegram_group_targets')
assert '_shared_group_claim_owner_map' in targets
assert 'ACCOUNT_KEY' in targets

td=Path(tempfile.mkdtemp())
local=td/'local.db'
con=sqlite3.connect(local); con.row_factory=sqlite3.Row
con.executescript("""
CREATE TABLE installations(group_id INTEGER PRIMARY KEY, group_title TEXT);
CREATE TABLE group_lifecycle(group_id INTEGER PRIMARY KEY, peer_kind TEXT, group_access_hash INTEGER, last_activity_at TEXT);
INSERT INTO installations VALUES(10,'A');
INSERT INTO installations VALUES(11,'B');
INSERT INTO group_lifecycle VALUES(10,'channel',1,'2026');
INSERT INTO group_lifecycle VALUES(11,'channel',2,'2026');
"""); con.commit(); con.close()
owner={10:'main',11:'acc2'}
def db_connect():
    c=sqlite3.connect(local); c.row_factory=sqlite3.Row; return c
ns={'List':List,'sqlite3':sqlite3,'db_connect':db_connect,'_shared_group_claim_owner_map':lambda gids:{g:owner.get(g,'') for g in gids},'ACCOUNT_KEY':'main'}
exec(targets,ns)
rows=ns['telegram_group_targets']()
assert [int(r['group_id']) for r in rows]==[10]

req=fn('request_full_inventory_sync_all')
reqdir=td/'requests'
class Row(dict):
    def __getitem__(self,k): return dict.__getitem__(self,k)
ns2={
    'List':List,'FULL_DIALOG_INVENTORY_REQUEST_DIR':reqdir,
    'multi_account_rows':lambda:[Row(account_key='main',enabled=1),Row(account_key='acc2',enabled=1),Row(account_key='acc3',enabled=0)],
    'datetime':datetime,'timezone':timezone,
}
exec(req,ns2)
keys=ns2['request_full_inventory_sync_all']()
assert keys==['main','acc2']
assert (reqdir/'main.request').exists() and (reqdir/'acc2.request').exists()
assert not (reqdir/'acc3.request').exists()

print('CHECK ZIVO60.96.22 FULL DIALOG INVENTORY: PASS')
print('  exhaustive full account scan (high-level or raw pagination): PASS')
print('  archived/all-dialog path has no 130/200 cap: PASS')
print('  coordination PV durable requester sources: PASS')
print('  shared-claim group de-duplication: PASS')
print('  all-enabled-account scan request fan-out: PASS')
