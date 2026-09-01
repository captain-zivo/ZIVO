#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast
import asyncio
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SRC = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
LINES = SRC.splitlines(True)

def fn_text(name: str) -> str:
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

assert 'VERSION = "zivo60.93"' in SRC
assert 'performance-router=scale-v37-help-permission-guard' in SRC
assert 'transport-pending=cancelled-prune+reconnect-queue-clean' in SRC

# Execute the small hygiene helpers in isolation.
class _Log:
    def debug(self, *args, **kwargs):
        pass

ns = {
    'Any': Any,
    'log': _Log(),
    '_transport_pruned_pending_total': 0,
    '_transport_pruned_queue_total': 0,
}
exec(fn_text('_request_state_future_finished'), ns)
exec(fn_text('_prune_finished_transport_requests'), ns)
prune = ns['_prune_finished_transport_requests']

class State:
    def __init__(self, future):
        self.future = future

class Ready:
    def __init__(self): self.cleared = False
    def clear(self): self.cleared = True

async def check_prune():
    loop = asyncio.get_running_loop()
    live = loop.create_future()
    cancelled = loop.create_future(); cancelled.cancel()
    done = loop.create_future(); done.set_result('ok')
    q_live = loop.create_future()
    q_cancel = loop.create_future(); q_cancel.cancel()
    q_done = loop.create_future(); q_done.set_result('ok')
    ready = Ready()
    sender = type('Sender', (), {})()
    sender._pending_state = {11: State(live), 12: State(cancelled), 13: State(done)}
    packer = type('Packer', (), {})()
    packer._deque = deque([State(q_cancel), State(q_live), State(q_done)])
    packer._ready = ready
    sender._send_queue = packer
    client = type('Client', (), {'_sender': sender})()

    rp, rq = prune(client)
    assert (rp, rq) == (2, 2), (rp, rq)
    assert list(sender._pending_state) == [11], sender._pending_state
    assert len(packer._deque) == 1 and packer._deque[0].future is q_live
    assert live.cancelled() is False and live.done() is False
    assert q_live.cancelled() is False and q_live.done() is False
    assert ns['_transport_pruned_pending_total'] == 2
    assert ns['_transport_pruned_queue_total'] == 2
    rp2, rq2 = prune(client)
    assert (rp2, rq2) == (0, 0)
    live.cancel(); q_live.cancel()
    rp3, rq3 = prune(client)
    assert (rp3, rq3) == (1, 1)
    assert not sender._pending_state and not packer._deque
    assert ready.cleared is True

asyncio.run(check_prune())

reconnect = fn_text('_handle_auto_reconnect')
assert '_prune_finished_transport_requests(self)' in reconnect
assert 'transport reconnect hygiene' in reconnect
health = fn_text('transport_health_worker')
assert '_prune_finished_transport_requests(client)' in health
assert 'transport pending hygiene' in health
heartbeat = fn_text('performance_heartbeat_worker')
assert 'transport_pruned=%s/%s' in heartbeat

mentions = fn_text('send_group_text_with_mentions')
for token in ('CHATSENDPLAINFORBIDDEN', 'CHATWRITEFORBIDDEN', 'CHANNELPRIVATE'):
    assert token in mentions
assert 'guaranteed to fail again' in mentions

lock = fn_text('maybe_enforce_group_lock')
assert 'lock violation notice skipped unavailable' in lock
exact = fn_text('maybe_enforce_exact_content_filter')
assert 'exact content notice skipped unavailable' in exact

print('CHECK ZIVO60.91 TRANSPORT PENDING HYGIENE: PASS')
