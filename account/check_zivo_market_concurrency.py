#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Network-free async single-flight and market failure-circuit checks."""

from __future__ import annotations

import ast
import asyncio as real_asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import time
from typing import Any, Dict, Optional, Tuple

import zivo_social_games as social


ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / "zivo60.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
RUNTIME_NAMES = {
    "_MARKET_ASYNC_CACHE_SECONDS",
    "_MARKET_ASYNC_FAILURE_COOLDOWN_SECONDS",
    "_MARKET_ASYNC_OUTER_TIMEOUT_SECONDS",
    "_market_snapshot_async_task",
    "_market_snapshot_async_task_loop",
    "_market_snapshot_async_cache",
    "_market_snapshot_async_failure_until",
    "_market_snapshot_async_timeout_logged",
}
FUNCTION_NAMES = {"_market_snapshot_task_done", "_market_snapshot_async"}


def _assigned_name(node: ast.AST) -> str:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return ""


selected = []
for node in TREE.body:
    if _assigned_name(node) in RUNTIME_NAMES:
        selected.append(node)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in FUNCTION_NAMES:
        selected.append(node)
module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
assert len(selected) == len(RUNTIME_NAMES) + len(FUNCTION_NAMES)


class _Log:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, message: str, *args: Any) -> None:
        self.warnings.append(message % args if args else message)


class _AsyncioFacade:
    Task = real_asyncio.Task
    AbstractEventLoop = real_asyncio.AbstractEventLoop
    CancelledError = real_asyncio.CancelledError
    TimeoutError = real_asyncio.TimeoutError
    calls = 0

    get_running_loop = staticmethod(real_asyncio.get_running_loop)
    create_task = staticmethod(real_asyncio.create_task)
    shield = staticmethod(real_asyncio.shield)
    wait_for = staticmethod(real_asyncio.wait_for)

    @staticmethod
    async def to_thread(function, /, *args, **kwargs):
        _AsyncioFacade.calls += 1
        return await real_asyncio.to_thread(function, *args, **kwargs)


provider: Dict[str, Any] = {}
fake_social = SimpleNamespace(market_snapshot_data=lambda: provider["call"]())
fake_log = _Log()
namespace: Dict[str, Any] = {
    "asyncio": _AsyncioFacade,
    "time": time,
    "deepcopy": deepcopy,
    "social_games": fake_social,
    "log": fake_log,
    "Any": Any,
    "Dict": Dict,
    "Optional": Optional,
    "Tuple": Tuple,
}
exec(compile(module, str(ROOT / "zivo60.py"), "exec"), namespace)


def reset_runtime() -> None:
    namespace["_market_snapshot_async_task"] = None
    namespace["_market_snapshot_async_task_loop"] = None
    namespace["_market_snapshot_async_cache"] = (0.0, {})
    namespace["_market_snapshot_async_failure_until"] = 0.0
    namespace["_market_snapshot_async_timeout_logged"] = None
    namespace["_MARKET_ASYNC_OUTER_TIMEOUT_SECONDS"] = 12.0
    _AsyncioFacade.calls = 0
    fake_log.warnings.clear()


async def check_single_flight() -> None:
    reset_runtime()

    def healthy_provider() -> Dict[str, Any]:
        time.sleep(0.06)
        return {"usd_toman": 100_000, "quotes": {"usd": {"toman": 100_000}}, "stale": False}

    provider["call"] = healthy_provider
    load = namespace["_market_snapshot_async"]
    results = await real_asyncio.gather(*(load() for _ in range(48)))
    assert _AsyncioFacade.calls == 1
    assert all(result["usd_toman"] == 100_000 for result in results)

    # The async TTL avoids even a cache-only provider thread, and deep copies
    # prevent one command from mutating another command's nested card payload.
    results[0]["quotes"]["usd"]["toman"] = -1
    cached = await load()
    assert _AsyncioFacade.calls == 1
    assert cached["quotes"]["usd"]["toman"] == 100_000


async def check_failure_cooldown() -> None:
    reset_runtime()

    def failed_provider() -> Dict[str, Any]:
        time.sleep(0.03)
        raise OSError("offline")

    provider["call"] = failed_provider
    load = namespace["_market_snapshot_async"]
    results = await real_asyncio.gather(*(load() for _ in range(32)))
    assert results == [{}] * 32
    assert _AsyncioFacade.calls == 1
    assert len([item for item in fake_log.warnings if "provider failed" in item]) == 1

    # Negative cache returns immediately and allocates no new executor job.
    assert await load() == {}
    assert _AsyncioFacade.calls == 1

    # Once the bounded circuit is explicitly expired, one fresh call may run.
    namespace["_market_snapshot_async_failure_until"] = 0.0
    provider["call"] = lambda: {"usd_toman": 101_000, "stale": False}
    recovered = await load()
    assert recovered["usd_toman"] == 101_000
    assert _AsyncioFacade.calls == 2


async def check_timeout_shield() -> None:
    reset_runtime()
    namespace["_MARKET_ASYNC_OUTER_TIMEOUT_SECONDS"] = 0.02

    def slow_provider() -> Dict[str, Any]:
        time.sleep(0.08)
        return {"usd_toman": 102_000, "stale": False}

    provider["call"] = slow_provider
    load = namespace["_market_snapshot_async"]
    assert await load() == {}
    retained = namespace["_market_snapshot_async_task"]
    assert retained is not None and not retained.cancelled()
    assert await load() == {}
    assert _AsyncioFacade.calls == 1
    assert len([item for item in fake_log.warnings if "timed out" in item]) == 1

    await real_asyncio.sleep(0.10)
    completed = await load()
    assert completed["usd_toman"] == 102_000
    assert _AsyncioFacade.calls == 1


async def main_async() -> None:
    await check_single_flight()
    await check_failure_cooldown()
    await check_timeout_shield()


def main() -> None:
    async_body = ast.get_source_segment(
        SOURCE,
        next(node for node in TREE.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "_market_snapshot_async"),
    ) or ""
    assert async_body.count("asyncio.to_thread") == 1
    assert "asyncio.shield(task)" in async_body
    assert social._MARKET_PROVIDER_HTTP_BUDGET_SECONDS < namespace["_MARKET_ASYNC_OUTER_TIMEOUT_SECONDS"]
    real_asyncio.run(main_async())
    print("CHECK ZIVO MARKET CONCURRENCY: PASS")


if __name__ == "__main__":
    main()
