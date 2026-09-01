#!/usr/bin/env python3
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / "zivo60.py").read_text(encoding="utf-8")
MULTI = (ROOT / "zivo_multi_account.py").read_text(encoding="utf-8")
INSTALLER_PATH = Path(os.environ.get("ZIVO_INSTALLER_UNDER_TEST", str(ROOT / "install_zivo60.sh")))
INSTALLER = INSTALLER_PATH.read_text(encoding="utf-8") if INSTALLER_PATH.is_file() else ""

assert any(f'VERSION = "zivo60.96.{v}"' in SRC for v in range(25, 100))
assert "async def campaign_live_dialog_targets" in SRC
assert ("client.iter_dialogs(limit=None)" in SRC) or ("iter_dialogs_exhaustive_raw" in SRC)
assert 'source="campaign-live-dialog"' in SRC
assert "can_broadcast=0" in SRC
assert 'not bool(getattr(entity, "bot", False))' in SRC
assert 'not bool(getattr(entity, "deleted", False))' in SRC
assert "await campaign_live_dialog_targets(scope, int(job_id))" in SRC

standard = SRC.split("async def run_multi_account_campaign_job(job_id: int) -> None:", 1)[1]
standard = standard.split("async def retry_partial_target_campaign_cleanup", 1)[0]
assert "telegram_group_targets()" not in standard
assert "telegram_private_targets()" not in standard
assert "multi_claim_campaign_target" in standard
assert "multi_release_campaign_target_claim" in standard

assert "CREATE TABLE IF NOT EXISTS campaign_target_claims" in MULTI
assert "def claim_campaign_target" in MULTI
assert "def release_campaign_target_claim" in MULTI

from zivo_multi_account import claim_campaign_target, release_campaign_target_claim, init_control_db

with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "control.db"
    init_control_db(db)
    assert claim_campaign_target(db, batch_id="b1", target_kind="group", target_id=100, account_key="main", job_id=1)
    assert claim_campaign_target(db, batch_id="b1", target_kind="group", target_id=100, account_key="main", job_id=1)
    assert not claim_campaign_target(db, batch_id="b1", target_kind="group", target_id=100, account_key="acc2", job_id=2)
    assert release_campaign_target_claim(db, batch_id="b1", target_kind="group", target_id=100, job_id=1)
    assert claim_campaign_target(db, batch_id="b1", target_kind="group", target_id=100, account_key="acc2", job_id=2)
    con = sqlite3.connect(db)
    try:
        assert con.execute("SELECT COUNT(*) FROM campaign_target_claims").fetchone()[0] == 1
    finally:
        con.close()

if INSTALLER:
    assert "check_zivo60_96_25_campaign_live_all_dialogs.py" in INSTALLER
    assert 'install -m 600 "$SRC/check_zivo60_96_25_campaign_live_all_dialogs.py" "$BASE/check_zivo60_96_25_campaign_live_all_dialogs.py"' in INSTALLER

print("CHECK ZIVO60.96.25 CAMPAIGN LIVE ALL DIALOGS: PASS")
print("  standard campaign live exhaustive dialog source: PASS")
print("  all real group/private dialogs sourced from session: PASS")
print("  private opt-out + bot/deleted exclusion preserved: PASS")
print("  cross-account batch target de-duplication: PASS")
