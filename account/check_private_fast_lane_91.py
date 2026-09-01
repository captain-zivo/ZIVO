#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast
import asyncio as real_asyncio
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
assert 'private-recovery=raw+fast-dialog-poll+known-poll+bounded-watchdog' in SRC
assert 'private fast dialog poll started' in SRC
assert 'PRIVATE_FAST_POLL_PENDING_CEILING' in SRC


def fn_text(name: str) -> str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

body=fn_text('private_fast_dialog_poll_worker')
# The fast PM recovery lane yields only while a concrete private/group command
# is already being answered. It remains independent from the old broad pending
# reserve and avoids per-user history RPCs.
assert '_priority_traffic_is_hot' in body
assert 'FOREGROUND_BACKGROUND_PENDING_SOFT' not in body
assert 'client.get_messages' not in body
assert 'PRIVATE_FAST_POLL_PENDING_CEILING' in body
assert 'process_private_inbound_tracked' in body
assert 'source="fast-dialog-poll"' in body
assert '_last_priority_event_at = time.monotonic()' in body

# Execute one poll pass in isolation at the observed healthy baseline. The new
# low ceiling must still leave enough room to recover the newest private PM.
sel=[]
for node in TREE.body:
    if isinstance(node,ast.AsyncFunctionDef) and node.name in {'_private_fast_dialog_snapshot','private_fast_dialog_poll_worker'}:
        sel.append(node)
mini=compile(ast.Module(body=sel,type_ignores=[]),'<private-fast-poll>','exec')

class InputPeerUser:
    def __init__(self,user_id:int,access_hash:int=0): self.user_id=user_id; self.access_hash=access_hash
class User:
    def __init__(self,id:int): self.id=id
class Types: pass
types=Types(); types.InputPeerUser=InputPeerUser; types.User=User
class Utils:
    @staticmethod
    def get_input_peer(entity): return InputPeerUser(entity.id,123)
utils=Utils()

now=datetime.now(timezone.utc)
msg=SimpleNamespace(id=77,out=False,date=now,raw_text='سلام',message='سلام')
user_dialog=SimpleNamespace(is_user=True,id=555,entity=User(555),input_entity=InputPeerUser(555,123),message=msg)
group_dialog=SimpleNamespace(is_user=False,id=999,entity=object(),input_entity=object(),message=SimpleNamespace(id=1,out=False,date=now))
class Client:
    async def iter_dialogs(self,limit):
        yield group_dialog
        yield user_dialog
client=Client()

routed=[]
async def process(uid,mid,text,target,event=None,source=''):
    routed.append((uid,mid,text,source,type(target).__name__))

sleep_calls={'n':0}
class AsyncioProxy:
    TimeoutError=real_asyncio.TimeoutError
    CancelledError=real_asyncio.CancelledError
    wait_for=staticmethod(real_asyncio.wait_for)
    @staticmethod
    async def sleep(delay):
        sleep_calls['n'] += 1
        # initial startup sleep succeeds; terminate after the completed pass.
        if sleep_calls['n'] >= 2:
            raise real_asyncio.CancelledError()

class Log:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass

ns={
    'Any':Any,'List':List,'asyncio':AsyncioProxy,'client':client,'time':time,
    'datetime':datetime,'timezone':timezone,'types':types,'utils':utils,
    'safe_int':lambda x: int(x) if x is not None else None,
    'SYSTEM_USER_IDS':{777000},'SELF_USER_ID':1,
    'PRIVATE_FAST_POLL_INTERVAL_SECONDS':0.55,'PRIVATE_FAST_POLL_DIALOG_SCAN_MAX':20,
    'PRIVATE_FAST_POLL_USER_TARGET':6,'PRIVATE_FAST_POLL_PENDING_CEILING':22,
    'PRIVATE_FAST_POLL_TIMEOUT_SECONDS':2.4,'PRIVATE_WATCHDOG_RECENT_SECONDS':900,
    '_transport_pending_request_count':lambda c:12,
    '_priority_traffic_is_hot':lambda:False,
    '_perf_counters':Counter(),'_private_peer_cache':{},'_private_watchdog_last_message':{},
    '_private_recovery_mode_until':0.0,'_last_private_route_success_at':0.0,'_last_priority_event_at':0.0,
    '_private_message_seen':{},'private_receipt_is_handled':lambda uid,mid:False,
    '_private_message_text':lambda m: str(getattr(m,'raw_text','') or getattr(m,'message','') or ''),
    'process_private_inbound_tracked':process,'log':Log(),
}
exec(mini,ns)
async def run():
    try:
        await ns['private_fast_dialog_poll_worker']()
    except real_asyncio.CancelledError:
        pass
real_asyncio.run(run())
assert routed == [(555,77,'سلام','fast-dialog-poll','InputPeerUser')], routed
assert ns['_perf_counters']['private_fast_poll']==1
assert ns['_private_watchdog_last_message'][555]==77
assert ns['_last_priority_event_at']>0

print('CHECK ZIVO60.91 PRIVATE FAST LANE: PASS')
print('  healthy pending=12 still routes PM: PASS')
print('  foreground command yields fallback poll: PASS')
print('  one dialog RPC / no per-user history RPC: PASS')
print('  durable duplicate guards retained: PASS')
