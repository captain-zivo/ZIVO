#!/usr/bin/env python3
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = (HERE / 'zivo60.py').read_text(encoding='utf-8')
MULTI = HERE / 'zivo_multi_account.py'

ast.parse(SRC)
assert 'VERSION = "zivo60.96.41"' in SRC

worker_start = SRC.index('async def multi_account_join_worker()')
worker_end = SRC.index('\n\nclass _RemoteControlReply', worker_start)
worker = SRC[worker_start:worker_end]
assert "urgent = str(row['source_account'] or '').strip().lower() == 'official_bot'" in worker
assert worker.index('multi_claim_next_join_job') < worker.index('_wait_transport_background_slot')
assert "await asyncio.sleep(0.03)" in worker
assert 'official join foreground claim' in worker

join_start = SRC.index('async def run_multi_account_join_job')
join_end = SRC.index('\n\nasync def multi_account_join_worker', join_start)
join = SRC[join_start:join_end]
for code in ('joined_full', 'joined_basic', 'joined_pending'):
    assert code in join
assert 'activation_ready = await _stage_remote_join_after_confirmed_join' in join
assert 'runtime_group_access_state(group, force=True)' in join

private_start = SRC.index('async def send_private(')
private_send_pos = SRC.index('await client.send_message', private_start)
assert SRC.index('if OFFICIAL_CONTROL_ONLY:', private_start, private_send_pos) < private_send_pos
private_event_start = SRC.index('async def send_private_from_event(')
private_event_send = SRC.index('responder(text', private_event_start)
assert SRC.index('if OFFICIAL_CONTROL_ONLY:', private_event_start, private_event_send) < private_event_send

# Verify the real shared DB queue preserves the official foreground source.
import sys
sys.path.insert(0, str(HERE))
import zivo_multi_account as ma
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / 'control.db'
    ma.init_control_db(db)
    jid = ma.create_join_job(
        db,
        source_account='official_bot',
        target_account='acc3',
        requester_user_id=123,
        source_message_id=456,
        link_kind='invite',
        link_value='abc',
    )
    row = ma.claim_next_join_job(db, 'acc3')
    assert row is not None
    assert int(row['job_id']) == jid
    assert str(row['source_account']) == 'official_bot'
    assert str(row['status']) == 'running'

print('CHECK ZIVO60.96.41 INSTANT OFFICIAL JOIN: PASS')
print('  official join claims before background transport gate: PASS')
print('  30ms idle polling + foreground source detection: PASS')
print('  join result differentiates FULL/BASIC/PENDING: PASS')
print('  account private outbound disabled in official-only mode: PASS')
print('  shared SQLite official join job contract: PASS')
