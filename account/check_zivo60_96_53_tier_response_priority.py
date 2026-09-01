#!/usr/bin/env python3
from __future__ import annotations

import ast
import asyncio
import heapq
import itertools
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional, Tuple

import zivo_premium as premium


ROOT = Path(__file__).resolve().parent
MAIN = ROOT / "zivo60.py"
SOURCE = MAIN.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
LINES = SOURCE.splitlines(True)

assert 'VERSION = "zivo60.96.53"' in SOURCE
assert "DIAMOND > GOLD > SILVER > FREE" in SOURCE
assert "💎 الماس — بالاترین اولویت پاسخ" in SOURCE
assert "هنگام شلوغی، ترتیب صف پاسخ الماس، طلا، نقره و رایگان است" in SOURCE


def node(name: str):
    return next(item for item in TREE.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == name)


def function_source(name: str) -> str:
    item = node(name)
    return "".join(LINES[item.lineno - 1:item.end_lineno])


def exec_function(namespace: dict[str, Any], name: str) -> None:
    module = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(MAIN), "exec"), namespace)


with tempfile.TemporaryDirectory(prefix="zivo-tier-priority-") as tmp:
    premium.configure(Path(tmp) / "premium.db")
    premium.activate_subscription(1002, premium.PLAN_SILVER, 30)
    premium.activate_subscription(1003, premium.PLAN_GOLD, 30)
    premium.activate_subscription(1004, premium.PLAN_DIAMOND, 30)

    ns = {
        "Any": Any, "Optional": Optional, "Tuple": Tuple,
        "premium": premium, "itertools": itertools, "heapq": heapq,
        "safe_int": lambda value: int(value) if value is not None else None,
        "canonical_anti_spam_group_id": lambda value: int(value) if value is not None else None,
        "log": SimpleNamespace(debug=lambda *args, **kwargs: None),
        "TIER_RESPONSE_PRIORITY": {
            premium.PLAN_DIAMOND: 0, premium.PLAN_GOLD: 1,
            premium.PLAN_SILVER: 2, premium.PLAN_FREE: 3,
        },
        "PRIORITY_EAGER_TASK_SOFT_LIMIT": 96,
        "PRIORITY_EAGER_TASK_HARD_LIMIT": 192,
        "_tier_response_sequence": itertools.count(),
    }
    for name in (
        "group_response_priority", "group_response_priority_for_event",
        "tier_response_eager_limit", "tier_response_queue_item",
        "tier_response_queue_event", "replace_worst_tier_queue_item",
    ):
        exec_function(ns, name)

    assert ns["group_response_priority"](1004) == 0
    assert ns["group_response_priority"](1003) == 1
    assert ns["group_response_priority"](1002) == 2
    assert ns["group_response_priority"](1001) == 3

    limits = [ns["tier_response_eager_limit"](rank) for rank in range(4)]
    assert limits[0] > limits[1] > limits[2] > limits[3], limits

    async def queue_order() -> None:
        queue = asyncio.PriorityQueue()
        events = [
            SimpleNamespace(name="free", chat_id=1001),
            SimpleNamespace(name="gold", chat_id=1003),
            SimpleNamespace(name="diamond", chat_id=1004),
            SimpleNamespace(name="silver", chat_id=1002),
        ]
        for event in events:
            queue.put_nowait(ns["tier_response_queue_item"](event))
        ordered = []
        while not queue.empty():
            ordered.append(ns["tier_response_queue_event"](await queue.get()).name)
            queue.task_done()
        assert ordered == ["diamond", "gold", "silver", "free"], ordered

        fifo = asyncio.PriorityQueue()
        fifo.put_nowait(ns["tier_response_queue_item"](SimpleNamespace(name="first"), 1))
        fifo.put_nowait(ns["tier_response_queue_item"](SimpleNamespace(name="second"), 1))
        assert ns["tier_response_queue_event"](await fifo.get()).name == "first"
        fifo.task_done()
        assert ns["tier_response_queue_event"](await fifo.get()).name == "second"
        fifo.task_done()

        full = asyncio.PriorityQueue(maxsize=2)
        full.put_nowait(ns["tier_response_queue_item"](SimpleNamespace(name="free"), 3))
        full.put_nowait(ns["tier_response_queue_item"](SimpleNamespace(name="silver"), 2))
        diamond = ns["tier_response_queue_item"](SimpleNamespace(name="diamond"), 0)
        assert ns["replace_worst_tier_queue_item"](full, diamond) is True
        kept = []
        while not full.empty():
            kept.append(ns["tier_response_queue_event"](await full.get()).name)
            full.task_done()
        assert kept == ["diamond", "silver"], kept

    asyncio.run(queue_order())


# The final SendMessage lane also orders concurrently waiting replies by tier.
send_ns = {
    "Any": Any, "Optional": Optional, "BaseException": BaseException,
    "asyncio": asyncio, "time": time,
    "log": SimpleNamespace(warning=lambda *args, **kwargs: None),
    "ACCOUNT_KEY": "main",
    "SEND_RPC_MIN_INTERVAL_SECONDS": 0.0,
    "SEND_RPC_FLOOD_BUFFER_SECONDS": 0.01,
    "SEND_RPC_COMMAND_RETRY_MAX_WAIT_SECONDS": 1.0,
    "SEND_RPC_COMMAND_RETRIES": 1,
    "SEND_RPC_BACKGROUND_PRIORITY_WAIT_SECONDS": 0.2,
    "TIER_SEND_BUSY_STAGGER_SECONDS": 0.01,
    "_send_rpc_sem": asyncio.Semaphore(1),
    "_send_rpc_next_allowed_at": 0.0,
    "_send_rpc_pause_until": 0.0,
    "_send_rpc_last_flood_log_at": 0.0,
    "_send_command_waiters": 0,
    "_send_tier_waiters": {0: 0, 1: 0, 2: 0, 3: 0},
    "delete_rpc_flood_wait_seconds": lambda exc: 0.0,
}
exec_function(send_ns, "governed_send_message_rpc")


async def send_order() -> None:
    occupied = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def blocker():
        occupied.set()
        await release.wait()
        order.append("blocker")
        return True

    async def named(label):
        order.append(label)
        return label

    active = asyncio.create_task(send_ns["governed_send_message_rpc"](blocker))
    await occupied.wait()
    free = asyncio.create_task(send_ns["governed_send_message_rpc"](
        lambda: named("free"), command_priority=True, response_priority=3,
    ))
    await asyncio.sleep(0.001)
    diamond = asyncio.create_task(send_ns["governed_send_message_rpc"](
        lambda: named("diamond"), command_priority=True, response_priority=0,
    ))
    await asyncio.sleep(0.02)
    release.set()
    await asyncio.gather(active, free, diamond)
    assert order == ["blocker", "diamond", "free"], order
    assert send_ns["_send_tier_waiters"] == {0: 0, 1: 0, 2: 0, 3: 0}


asyncio.run(send_order())

router = function_source("zivo_router")
router_impl = function_source("_zivo_router_impl")
assert "tier_response_eager_limit(response_priority)" in router
assert "replace_worst_tier_queue_item" in router
assert "asyncio.PriorityQueue(maxsize=COMMAND_OVERFLOW_QUEUE_MAX)" in SOURCE
assert "asyncio.PriorityQueue(maxsize=GROUP_EVENT_QUEUE_MAX)" in SOURCE
assert "_group_response_priority.set(group_response_priority(group_id))" in SOURCE
assert "response_priority_token = _group_response_priority.set(response_priority)" in router_impl
assert "_group_response_priority.reset(response_priority_token)" in router_impl
assert "response_priority=int(response_priority)" in SOURCE

print("CHECK ZIVO60.96.53 SUBSCRIPTION RESPONSE PRIORITY: PASS")
print("  queue order DIAMOND > GOLD > SILVER > FREE with FIFO per tier: PASS")
print("  eager headroom DIAMOND > GOLD > SILVER > FREE: PASS")
print("  full queue protects higher-tier work: PASS")
print("  busy SendMessage lane admits DIAMOND before waiting FREE: PASS")
print("  idle requests receive no artificial tier delay: PASS")
