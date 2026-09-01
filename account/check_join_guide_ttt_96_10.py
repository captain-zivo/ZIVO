#!/usr/bin/env python3
from __future__ import annotations

import ast
import tempfile
from pathlib import Path

import zivo_social_games as social


ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / "zivo60.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def function_source(name: str) -> str:
    node = next(
        item for item in ast.walk(TREE)
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name
    )
    return ast.get_source_segment(SOURCE, node) or ""


def main() -> None:
    assert 'VERSION = "zivo60.96.10"' in SOURCE

    fast = function_source("_fast_post_join_write_and_activation")
    assert fast.index("probe_group_send_access") < fast.index("try_auto_activate_pending_group")
    assert fast.index("try_auto_activate_pending_group") < fast.index("_group_join_notice_complete")
    assert "PENDING_ACTIVATION_NOT_READY" in fast
    assert "send_group_join_guide_receipt" not in fast
    assert "deliver_card_inline=True" in fast

    durable = function_source("_process_group_join_notice_job")
    assert durable.index("probe_group_send_access") < durable.index("try_auto_activate_pending_group")
    assert durable.index("try_auto_activate_pending_group") < durable.index("_group_join_notice_complete")
    assert "PENDING_ACTIVATION_NOT_READY" in durable
    assert "send_group_join_guide_receipt" not in durable
    assert "deliver_card_inline=True" in durable

    activation = function_source("try_auto_activate_pending_group")
    assert 'fresh_row["group_notice_probe_sent"]' in activation
    assert 'fresh_row["group_notice_sent"]' not in activation

    background = function_source("_background_try_auto_activate")
    assert 'row["group_notice_probe_sent"]' in background
    assert 'row["group_notice_sent"]' not in background

    queue = function_source("_post_activation_card_task")
    assert "_activation_card_job_upsert" in queue
    assert "_process_activation_card_job" in queue
    assert "deliver_inline" in queue
    delivery = function_source("_process_activation_card_job")
    assert "send_default_join_message" in delivery
    assert "_activation_card_complete" in delivery

    for mutation in (
        "_queue_group_join_notice",
        "_group_join_notice_mark_probe",
        "_group_join_notice_complete",
        "_group_join_notice_defer",
    ):
        assert "_pending_group_activation_hot_cache.pop" in function_source(mutation), mutation

    worker = function_source("group_join_notice_worker")
    assert 'int(row.get("group_notice_attempt_count") or 0) <= 2' in worker

    with tempfile.TemporaryDirectory() as raw:
        social.configure(Path(raw) / "social.db", global_owner_id=9001, bot_user_ids={9999})
        social._TTT_GAMES.clear()
        opened = social.tic_tac_toe(701, 10, "قرمز", "start")
        assert "❌" in opened and "🟢" in opened and "⭕" not in opened
        joined = social.tic_tac_toe(701, 20, "سبز", "join")
        assert "❌ قرمز" in joined and "🟢 سبز" in joined and "⭕" not in joined
        social.tic_tac_toe(701, 10, "قرمز", "move", 1)
        green_move = social.tic_tac_toe(701, 20, "سبز", "move", 4)
        assert "🟢" in green_move and "⭕" not in green_move
        social.tic_tac_toe(701, 10, "قرمز", "move", 2)
        social.tic_tac_toe(701, 20, "سبز", "move", 5)
        result = social.tic_tac_toe(701, 10, "قرمز", "move", 3)
        assert "برنده: قرمز ❌" in result
        help_text = social.social_help_text()
        assert "سازنده ❌ قرمز" in help_text and "بازیکن دوم 🟢 سبز" in help_text

    print("CHECK ZIVO60.96.10 JOIN ACTIVE CARD + TTT COLORS: PASS")
    print("  eyes -> one full durable ACTIVE card: PASS")
    print("  short group info/help receipt is not sent: PASS")
    print("  tic-tac-toe red/green players: PASS")


if __name__ == "__main__":
    main()
