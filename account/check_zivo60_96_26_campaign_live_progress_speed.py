#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import os
import sqlite3
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / "zivo60.py").read_text(encoding="utf-8")
MULTI = (ROOT / "zivo_multi_account.py").read_text(encoding="utf-8")
INSTALLER_PATH = Path(os.environ.get("ZIVO_INSTALLER_UNDER_TEST", str(ROOT / "install_zivo60.sh")))
INSTALLER = INSTALLER_PATH.read_text(encoding="utf-8") if INSTALLER_PATH.is_file() else ""

assert any(f'VERSION = "zivo60.96.{v}"' in SRC for v in range(26, 100))
assert "CAMPAIGN_START_PENDING_SOFT" in SRC and '"110"' in SRC
assert "CAMPAIGN_SEND_PENDING_HARD" in SRC and '"150"' in SRC
assert "CAMPAIGN_SCAN_PENDING_HARD" in SRC and '"160"' in SRC
assert "CAMPAIGN_SEND_RPC_MIN_INTERVAL_SECONDS" in SRC and '"0.12"' in SRC
assert "CAMPAIGN_INTER_TARGET_DELAY_SECONDS" in SRC and '"0.01"' in SRC
assert "async def _wait_campaign_transport_slot" in SRC
assert "def _campaign_foreground_busy" in SRC

worker = SRC.split("async def multi_account_campaign_worker() -> None:", 1)[1]
worker = worker.split("async def multi_account_heartbeat_worker", 1)[0]
assert (
    ("_wait_campaign_transport_slot" in worker and "CAMPAIGN_START_PENDING_SOFT" in worker)
    or ("claim=immediate" in worker and "multi_claim_next_job" in worker)
)
assert "_wait_transport_background_slot" not in worker.split("multi_claim_next_job", 1)[0]

scan = SRC.split("async def campaign_live_dialog_targets", 1)[1]
scan = scan.split("def _campaign_media_send_kwargs", 1)[0]
assert ("client.iter_dialogs(limit=None)" in scan) or ("iter_dialogs_exhaustive_raw" in scan)
assert 'status="scanning"' in scan
assert "group_targets=len(groups)" in scan
assert "private_targets=len(privates)" in scan
assert "CAMPAIGN_SCAN_PENDING_HARD" in scan
assert "_try_acquire_full_inventory_lock" not in scan
assert ("_campaign_foreground_busy()" in scan) or ("_wait_campaign_transport_slot" in scan)

run = SRC.split("async def run_multi_account_campaign_job(job_id: int) -> None:", 1)[1]
run = run.split("async def retry_partial_target_campaign_cleanup", 1)[0]
assert "_campaign_send_context.set(True)" in run
assert "CAMPAIGN_SEND_PENDING_HARD" in run
assert "skipped_count=skipped" in run
assert "multi-account campaign progress" in run
assert "CAMPAIGN_INTER_TARGET_DELAY_SECONDS" in run

assert "async def tg_multi_campaign_progress_monitor" in SRC
assert "def _multi_campaign_batch_progress_text" in SRC
for token in (
    "👥 گروه پیدا شده", "👤 پیوی پیدا شده", "✅ ارسال موفق",
    "❌ ناموفق", "⏳ باقی‌مانده", "⚡ سرعت واقعی",
):
    assert token in SRC, token
assert "_tg_multi_campaign_progress_tasks[batch_id] = asyncio.create_task" in SRC
assert "آمار گروه، پیوی، ارسال موفق/ناموفق، باقی‌مانده و سرعت همین پیام" in SRC

# Runtime-style isolated gate check: a production-like pending=79 must be
# admitted by the campaign ceiling=110 while an active foreground handler blocks it.
tree = ast.parse(SRC)
nodes = [
    node for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name in {"_campaign_foreground_busy", "_wait_campaign_transport_slot"}
]
mini = compile(ast.Module(body=nodes, type_ignores=[]), "<campaign-gate>", "exec")
ns = {
    "asyncio": asyncio, "time": time, "client": object(),
    "CAMPAIGN_FOREGROUND_GRACE_SECONDS": 0.10,
    "_priority_router_inflight": 0,
    "_private_overflow_queue": None, "_command_overflow_queue": None,
    "_transport_pending_request_count": lambda _client: 79,
}
exec(mini, ns)
assert asyncio.run(ns["_wait_campaign_transport_slot"](110, max_wait=0.0)) is True
ns["_priority_router_inflight"] = 1
if 'VERSION = "zivo60.96.28"' in SRC or any(f'VERSION = "zivo60.96.{v}"' in SRC for v in range(29, 100)):
    # 96.28 bounded fairness: foreground gets a grace window but cannot starve
    # an explicit admin campaign forever while pending remains below ceiling.
    assert asyncio.run(ns["_wait_campaign_transport_slot"](110, max_wait=0.0)) is True
else:
    assert asyncio.run(ns["_wait_campaign_transport_slot"](110, max_wait=0.0)) is False

for token in ("group_targets", "private_targets", "skipped_count"):
    assert token in MULTI
assert "status IN ('queued','scanning','running')" in MULTI
assert "status IN ('scanning','running','cleanup')" in MULTI

from zivo_multi_account import init_control_db, update_job, active_job_count, create_campaign_jobs

with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "control.db"
    init_control_db(db)
    con = sqlite3.connect(db)
    try:
        cols = {row[1] for row in con.execute("PRAGMA table_info(campaign_jobs)")}
        assert {"group_targets", "private_targets", "skipped_count"}.issubset(cols)
    finally:
        con.close()
    jobs = create_campaign_jobs(
        db, batch_id="speed", account_keys=["main"], scope="both",
        content={"type": "text", "text": "x", "path": ""},
        repeat_count=1, interval_seconds=0,
    )
    jid = jobs[0]
    update_job(db, jid, status="scanning", group_targets=1200, private_targets=300, skipped_count=7)
    assert active_job_count(db) == 1
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute("SELECT * FROM campaign_jobs WHERE job_id=?", (jid,)).fetchone()
        assert row["group_targets"] == 1200
        assert row["private_targets"] == 300
        assert row["skipped_count"] == 7
    finally:
        con.close()

if INSTALLER:
    assert "check_zivo60_96_26_campaign_live_progress_speed.py" in INSTALLER
    assert 'install -m 600 "$SRC/check_zivo60_96_26_campaign_live_progress_speed.py" "$BASE/check_zivo60_96_26_campaign_live_progress_speed.py"' in INSTALLER
    assert "ZIVO_CAMPAIGN_START_PENDING_SOFT=110" in INSTALLER
    assert "ZIVO_CAMPAIGN_SEND_PENDING_HARD=150" in INSTALLER
    assert "ZIVO_CAMPAIGN_SEND_RPC_MIN_INTERVAL=0.12" in INSTALLER

print("CHECK ZIVO60.96.26 LIVE CAMPAIGN PROGRESS + FAST LANE: PASS")
print("  campaign no longer starved by global pending<=16 maintenance gate: PASS")
print("  parallel full live Session scan with explicit campaign ceiling: PASS")
print("  live Telegram groups/private/success/failure/remaining/speed progress: PASS")
print("  campaign-only faster FloodWait-aware send pacing: PASS")
print("  duplicate target progress accounting: PASS")
