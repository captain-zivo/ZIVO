#!/usr/bin/env python3
from __future__ import annotations

import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
MULTI = (ROOT / 'zivo_multi_account.py').read_text(encoding='utf-8')
INSTALLER = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')

assert 'VERSION = "zivo60.96.40"' in CORE
assert 'OFFICIAL_CONTROL_ONLY' in CORE
assert 'remote_control_worker()' in CORE
assert 'run_remote_control_job' in CORE
assert '_RemoteControlEvent' in CORE
assert 'requester_user_id=int(row[\'requester_user_id\'] or 0)' in CORE
assert 'multi_recover_running_remote_control_jobs' in CORE
assert 'private account inbox disabled' in CORE
assert 'if not OFFICIAL_CONTROL_ONLY:' in CORE
assert 'private_inbox_watchdog()' in CORE
assert 'if is_private and OFFICIAL_CONTROL_ONLY:' in CORE
assert 'FLOOD_GUARD_DELETE_BATCH_SIZE' in CORE
assert 'ZIVO_FLOOD_GUARD_DELETE_BATCH", "50"' in CORE
assert 'schedule_flood_guard_history_cleanup' in CORE
assert 'queue_flood_guard_cached_delete_ids' in CORE
assert 'GROUP_ACTIVATION_PENDING' in CORE
assert 'age_seconds <= 45.0' in CORE
assert 'status="queued", result_code="", result_text=""' in CORE
assert 'ZIVO_OFFICIAL_CONTROL_ONLY=1' in INSTALLER
assert 'ZIVO_REMOTE_CONTROL_POLL_SECONDS=0.15' in INSTALLER
assert 'ZIVO_FLOOD_GUARD_DELETE_BATCH=50' in INSTALLER
assert 'ZIVO_FLOOD_GUARD_HISTORY_SCAN_CAP=1200' in INSTALLER
assert 'check_zivo60_96_40_official_control_bridge.py' in INSTALLER

# The realtime spam action must not synchronously await the old full purge after ban.
spam_start = CORE.index('async def consume_group_flood_guard_event')
spam_end = CORE.index('async def consume_group_anti_spam_event', spam_start)
spam_body = CORE[spam_start:spam_end]
assert 'await purge_flood_spammer_messages' not in spam_body
assert 'schedule_flood_guard_history_cleanup' in spam_body
assert 'queue_flood_guard_cached_delete_ids' in spam_body

# Raw join/service processing stays before the official-control PM kill-switch.
raw_start = CORE.index('async def zivo_raw_private_router')
raw_end = CORE.index('@client.on(events.NewMessage', raw_start)
raw_body = CORE[raw_start:raw_end]
assert raw_body.index('raw_group_join_payloads') < raw_body.index('if OFFICIAL_CONTROL_ONLY:')

assert 'CREATE TABLE IF NOT EXISTS remote_control_jobs' in MULTI
assert 'def create_remote_control_job' in MULTI
assert 'def claim_next_remote_control_job' in MULTI
assert 'def get_remote_control_job' in MULTI
assert 'def update_remote_control_job' in MULTI
assert 'def recover_running_remote_control_jobs' in MULTI

import sys
sys.path.insert(0, str(ROOT))
import zivo_multi_account as ma

with tempfile.TemporaryDirectory() as td:
    db = Path(td) / 'control.db'
    ma.init_control_db(db)
    jid = ma.create_remote_control_job(
        db,
        target_account='acc2', requester_user_id=123,
        group_id=777, command_text='قفل لینک', target_user_id=0,
        target_message_id=0,
    )
    row = ma.get_remote_control_job(db, jid)
    assert row is not None and row['status'] == 'queued'
    claimed = ma.claim_next_remote_control_job(db, 'acc2')
    assert claimed is not None and int(claimed['job_id']) == jid and claimed['status'] == 'running'
    ma.update_remote_control_job(db, jid, status='done', result_code='OK', result_text='done')
    row = ma.get_remote_control_job(db, jid)
    assert row is not None and row['status'] == 'done' and row['result_code'] == 'OK'

    jid2 = ma.create_remote_control_job(
        db, target_account='acc2', requester_user_id=123,
        group_id=777, command_text='پاکسازی 100',
    )
    assert ma.claim_next_remote_control_job(db, 'acc2') is not None
    assert ma.recover_running_remote_control_jobs(db, 'acc2') == 1
    row2 = ma.get_remote_control_job(db, jid2)
    assert row2 is not None and row2['status'] == 'queued'

print('ZIVO 60.96.40 OFFICIAL CONTROL BRIDGE CHECK: PASS')
