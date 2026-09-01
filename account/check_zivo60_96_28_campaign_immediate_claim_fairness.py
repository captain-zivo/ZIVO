#!/usr/bin/env python3
from __future__ import annotations

import ast
import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / "zivo60.py").read_text(encoding="utf-8")
MULTI = (ROOT / "zivo_multi_account.py").read_text(encoding="utf-8")
INSTALLER_PATH = Path(os.environ.get("ZIVO_INSTALLER_UNDER_TEST", str(ROOT / "install_zivo60.sh")))
INSTALLER = INSTALLER_PATH.read_text(encoding="utf-8") if INSTALLER_PATH.is_file() else ""
TREE = ast.parse(SRC)

assert 'VERSION = "zivo60.96.28"' in SRC
assert "supersede_standard_jobs as multi_supersede_standard_jobs" in SRC
assert "def supersede_standard_jobs" in MULTI
assert "SUPERSEDED_BY_NEW_ADMIN_BATCH" in MULTI
assert "ORDER BY job_id DESC LIMIT 1" in MULTI
assert "CAMPAIGN_FOREGROUND_GRACE_SECONDS" in SRC
assert '"0.45"' in SRC
assert "CAMPAIGN_WORKER_IDLE_POLL_SECONDS" in SRC
assert '"0.20"' in SRC
assert "bounded fairness" in SRC
assert "claim=immediate" in SRC
assert "multi account campaign CLAIM" in SRC
assert "dialog-pagination=raw100+folder0+archive1" in SRC


def fn(name: str) -> str:
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(SRC, node) or ""

worker = fn("multi_account_campaign_worker")
waiter = fn("_wait_campaign_transport_slot")
scan = fn("campaign_live_dialog_targets")
assert "multi_claim_next_job" in worker
# Claim must happen before any transport wait so Telegram leaves queued promptly.
assert worker.index("multi_claim_next_job") < worker.find("run_multi_account_campaign_job")
assert "CAMPAIGN_START_PENDING_SOFT" not in worker
assert "return pending < limit" in waiter
assert "CAMPAIGN_FOREGROUND_GRACE_SECONDS" in waiter
assert "while _campaign_foreground_busy()" not in scan
assert "_wait_campaign_transport_slot" in scan
assert "CAMPAIGN_SCAN_PENDING_HARD" in scan

# Functional shared-DB regression: old standard jobs are superseded, while a
# target-growth job is preserved. A new standard job can then be claimed.
ns = {}
exec(compile(MULTI, str(ROOT / "zivo_multi_account.py"), "exec"), ns)
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "multi.db"
    ns["init_control_db"](db)
    old = ns["create_campaign_jobs"](
        db, batch_id="old", account_keys=["main"], scope="both",
        content={"type":"text","text":"old"}, repeat_count=1, interval_seconds=0,
    )[0]
    target = ns["create_campaign_jobs"](
        db, batch_id="target", account_keys=["main"], scope="groups",
        content={"type":"text","text":"target"}, repeat_count=1, interval_seconds=0,
        campaign_mode="target_growth",
    )[0]
    changed = ns["supersede_standard_jobs"](db, ["main"])
    assert changed == 1, changed
    old_row = ns["get_job"](db, old)
    target_row = ns["get_job"](db, target)
    assert old_row["status"] == "stopped" and int(old_row["stop_requested"]) == 1
    assert target_row["status"] == "queued" and int(target_row["stop_requested"]) == 0
    new = ns["create_campaign_jobs"](
        db, batch_id="new", account_keys=["main"], scope="both",
        content={"type":"text","text":"new"}, repeat_count=1, interval_seconds=0,
    )[0]
    claimed = ns["claim_next_job"](db, "main")
    # Newest explicit admin job wins the queue immediately; preserved older
    # target-growth work remains queued for later instead of blocking this batch.
    assert claimed is not None and int(claimed["job_id"]) == new, (claimed["job_id"] if claimed else None, new)

if INSTALLER:
    assert "check_zivo60_96_28_campaign_immediate_claim_fairness.py" in INSTALLER
    assert 'install -m 600 "$SRC/check_zivo60_96_28_campaign_immediate_claim_fairness.py" "$BASE/check_zivo60_96_28_campaign_immediate_claim_fairness.py"' in INSTALLER

print("CHECK ZIVO60.96.28 CAMPAIGN IMMEDIATE CLAIM + BOUNDED FAIRNESS: PASS")
print("  fresh admin campaign supersedes stale standard queue rows: PASS")
print("  worker claims before transport gate, so live panel leaves queued promptly: PASS")
print("  continuous foreground traffic gets grace but cannot starve campaign forever: PASS")
print("  raw exhaustive pagination remains enabled: PASS")
