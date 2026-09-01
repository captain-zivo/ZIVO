#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static regression checks for the v60.96 latency hot-path changes."""

from pathlib import Path


SOURCE = Path(__file__).with_name("zivo60.py").read_text(encoding="utf-8")


def function_source(name: str) -> str:
    plain = SOURCE.find(f"def {name}(")
    async_start = SOURCE.find(f"async def {name}(")
    start = max(plain, async_start)
    assert start >= 0, name
    next_def = SOURCE.find("\ndef ", start + 1)
    next_async = SOURCE.find("\nasync def ", start + 1)
    ends = [value for value in (next_def, next_async) if value >= 0]
    return SOURCE[start:min(ends) if ends else len(SOURCE)]


def main() -> None:
    assert 'VERSION = "zivo60.96.1"' in SOURCE
    assert "PENDING_GROUP_ACTIVATION_CACHE_TTL" in SOURCE
    assert "_pending_group_activation_hot_cache" in SOURCE
    assert "SOCIAL_PRIVATE_START_FLUSH_INTERVAL_SECONDS" in SOURCE
    assert "GROUP_EVENT_WORKERS = max(4, min(16" in SOURCE
    assert '"96"' in SOURCE and '"192"' in SOURCE

    pending = function_source("get_pending_group_activation")
    assert "_pending_group_activation_hot_cache.get" in pending
    assert "dict(row) if row is not None else None" in pending

    private = function_source("process_private_inbound")
    assert "queue_social_private_start(sender_id)" in private
    assert "await asyncio.to_thread(social_games.mark_private_started" not in private

    identity = function_source("identity_persist_worker")
    assert "social_games.mark_private_started_batch" in identity
    assert "_social_private_start_pending.update" in identity

    print("CHECK ZIVO60.96 SPEED HOTPATH: PASS")


if __name__ == "__main__":
    main()
