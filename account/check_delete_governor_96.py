#!/usr/bin/env python3
"""Static regression checks for the shared FloodWait-safe delete lane."""

import ast
from pathlib import Path


SOURCE = Path(__file__).with_name("zivo60.py").read_text(encoding="utf-8")


def function_source(name: str) -> str:
    tree = ast.parse(SOURCE)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(SOURCE, node) or ""
    raise AssertionError(name)


def main() -> None:
    assert 'VERSION = "zivo60.96.9"' in SOURCE
    assert "DELETE_RPC_MIN_INTERVAL_SECONDS" in SOURCE
    assert "DELETE_RPC_FLOOD_BUFFER_SECONDS" in SOURCE
    assert "DELETE_RPC_FLOOD_COOLDOWN_SECONDS" in SOURCE
    assert "DELETE_RPC_TIMEOUT_COOLDOWN_SECONDS" in SOURCE
    assert "LIVE_DELETE_CIRCUIT_SECONDS" in SOURCE
    assert "CAMPAIGN_DELETE_CIRCUIT_SECONDS" in SOURCE
    assert "LOCK_DELETE_FAST_TIMEOUT_SECONDS" in SOURCE
    assert "_delete_rpc_sem = asyncio.Semaphore(1)" in SOURCE
    lane = function_source("governed_delete_messages")
    assert "client.delete_messages" in lane
    assert "delete_rpc_flood_wait_seconds" in lane
    assert "_delete_rpc_pause_until" in lane
    assert "asyncio.shield(delete_task)" in lane
    assert "delete_rpc_timeout" in lane
    assert "LiveDeleteCircuitOpen" in lane
    assert "CampaignDeleteCircuitOpen" in lane
    assert "foreground_delete_circuit_is_open" in lane

    for name in (
        "_retry_live_delete_worker",
        "_verify_live_delete_worker",
        "delete_live_message_fast",
    ):
        body = function_source(name)
        assert "live_delete_circuit_is_open" in body, name
        assert "arm_live_delete_circuit" in body, name

    campaign = function_source("cleanup_target_campaign_banners")
    assert "campaign_delete_circuit_is_open" in campaign
    assert "arm_campaign_delete_circuit" in campaign
    assert "asyncio.Semaphore(1)" in campaign

    locked = function_source("delete_locked_message")
    assert "LOCK_DELETE_FAST_TIMEOUT_SECONDS" in locked
    assert "arm_live_delete_circuit" in locked
    assert "_verify_group_lock_delete_worker" in locked

    for name in (
        "delete_locked_message",
        "delete_live_message_fast",
        "bot_message_cleanup_worker",
        "delete_full_cleanup_batch",
        "delete_filter_message_ids_verified",
        "cleanup_target_campaign_banners",
        "maybe_delete_warning_capped_message",
    ):
        body = function_source(name)
        assert "governed_delete_messages" in body, name
        assert "client.delete_messages" not in body, name

    print("CHECK ZIVO60.96.9 DELETE GOVERNOR: PASS")


if __name__ == "__main__":
    main()
