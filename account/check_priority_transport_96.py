#!/usr/bin/env python3
"""Static regression checks for foreground group/private transport priority."""

import ast
import asyncio
import time
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
    assert 'ZIVO_FOREGROUND_PRIORITY_HOT_SECONDS", "3.0"' in SOURCE
    assert 'ZIVO_FOREGROUND_BACKGROUND_PENDING_SOFT", "16"' in SOURCE
    assert 'ZIVO_PRIVATE_FAST_POLL_PENDING_CEILING' in SOURCE
    assert "_priority_router_inflight = 0" in SOURCE
    priority_check = function_source("_priority_traffic_is_hot")
    assert 'globals().get("_priority_router_inflight", 0)' in priority_check
    priority_router = function_source("_zivo_priority_router_impl")
    assert "_priority_router_inflight += 1" in priority_router
    assert "await _zivo_router_impl(event)" in priority_router

    router = function_source("zivo_router")
    assert "_zivo_priority_router_impl(event)" in router
    overflow = function_source("command_overflow_queue_worker")
    assert "await _zivo_priority_router_impl(event)" in overflow

    known_poll = function_source("private_known_contact_poll_worker")
    assert "_priority_traffic_is_hot()" in known_poll
    fallback_poll = function_source("private_fast_dialog_poll_worker")
    assert "_priority_traffic_is_hot()" in fallback_poll

    yield_lane = function_source("_yield_background_to_realtime")
    slot_lane = function_source("_wait_transport_background_slot")
    assert "_realtime_traffic_is_hot(BACKGROUND_REALTIME_QUIET_SECONDS)" in yield_lane
    assert "_realtime_traffic_is_hot(BACKGROUND_REALTIME_QUIET_SECONDS)" in slot_lane
    assert "BACKGROUND_REALTIME_FAIR_INTERVAL_SECONDS" in slot_lane
    assert "_background_realtime_fair_last_at" in slot_lane

    join_worker = function_source("multi_account_join_worker")
    campaign_worker = function_source("multi_account_campaign_worker")
    cleanup = function_source("cleanup_target_campaign_banners")
    assert "_wait_transport_background_slot" in join_worker
    assert "PROCESS_RECOVERY_REQUEUE" in join_worker
    assert ("_wait_transport_background_slot" in campaign_worker
        or "_wait_campaign_transport_slot" in campaign_worker
        or ("claim=immediate" in campaign_worker and "multi_claim_next_job" in campaign_worker))
    assert "_routine_background_quiet_period_active" in campaign_worker
    assert "unavailable_groups" in cleanup
    assert "LIVE_TRAFFIC_DEFERRED" in cleanup
    assert "TARGET_CLEANUP_RETRY_MIN_SECONDS" in SOURCE

    # Continuous ordinary chatter gets one bounded fairness token, but a second
    # background RPC is denied immediately. This preserves features without
    # allowing maintenance bursts to reclaim the live sender.
    tree = ast.parse(SOURCE)
    slot_node = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_wait_transport_background_slot"
    )
    mini = compile(ast.Module(body=[slot_node], type_ignores=[]), "<background-slot>", "exec")
    namespace = {
        "asyncio": asyncio,
        "time": time,
        "client": object(),
        "FOREGROUND_BACKGROUND_PENDING_SOFT": 16,
        "BACKGROUND_REALTIME_QUIET_SECONDS": 1.25,
        "BACKGROUND_REALTIME_FAIR_INTERVAL_SECONDS": 5.0,
        "_background_realtime_fair_last_at": 0.0,
        "_transport_pending_request_count": lambda _client: 12,
        "_priority_traffic_is_hot": lambda: False,
        "_realtime_traffic_is_hot": lambda _window: True,
    }
    exec(mini, namespace)

    async def exercise_fairness() -> tuple[bool, bool]:
        first = await namespace["_wait_transport_background_slot"](soft_limit=16, max_wait=0.0)
        second = await namespace["_wait_transport_background_slot"](soft_limit=16, max_wait=0.0)
        return first, second

    assert asyncio.run(exercise_fairness()) == (True, False)
    print("CHECK ZIVO60.96.9 PRIORITY TRANSPORT: PASS")


if __name__ == "__main__":
    main()
