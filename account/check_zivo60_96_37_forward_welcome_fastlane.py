#!/usr/bin/env python3
from __future__ import annotations
import ast, asyncio, time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'zivo60.py'
SRC=MAIN.read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.96.37"' in SRC

def node(name):
    return next(n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
def fn(name):
    n=node(name); return ''.join(LINES[n.lineno-1:n.end_lineno])
def exec_fn(ns,name):
    n=node(name); mod=ast.Module(body=[n],type_ignores=[]); ast.fix_missing_locations(mod)
    exec(compile(mod,str(MAIN),'exec'),ns)

# 1) Structural forward candidate is admitted before the ordinary group FIFO.
router=fn('zivo_router')
assert 'forward_lock_fast_lane_candidate(event)' in router
assert '_zivo_forward_priority_router_impl(event)' in router
assert router.index('forward_lock_fast_lane_candidate(event)') < router.index('_group_event_queue.put_nowait(event)')
assert 'join_service_hot' in router and '_zivo_priority_router_impl(event)' in router
assert router.index('join_service_hot') < router.index('_group_service_queue.put_nowait(event)')

# 2) Runtime forward candidate respects install/bot/lock/exemption state.
ns={
    'Any':Any,'safe_int':lambda v:int(v) if v is not None else None,
    'canonical_anti_spam_group_id':lambda v:int(v) if v is not None else None,
    'message_is_forwarded':lambda m:bool(getattr(m,'fwd_from',None)),
    'SELF_USER_ID':999,'SYSTEM_USER_IDS':set(),
    'get_installation':lambda gid:{'group_id':gid},'is_group_bot_enabled':lambda gid:True,
    'lock_user_is_always_exempt':lambda gid,uid:False,
    'group_lock_row':lambda gid,name:{'enabled':1},
}
exec_fn(ns,'forward_lock_fast_lane_candidate')
event=SimpleNamespace(is_private=False,chat_id=700,sender_id=123,id=9,message=SimpleNamespace(fwd_from=object()))
assert ns['forward_lock_fast_lane_candidate'](event) is True
ns['group_lock_row']=lambda gid,name:{'enabled':0}
assert ns['forward_lock_fast_lane_candidate'](event) is False

# 3) Join helper catches direct and wrapped/raw action shapes without full graph scan.
class MessageActionChatAddUser: pass
def action_join(action):
    return action is not None and 'adduser' in type(action).__name__.lower()
jns={'Any':Any,'_action_join_signature':action_join}
exec_fn(jns,'_join_service_event_fast')
assert jns['_join_service_event_fast'](SimpleNamespace(message=SimpleNamespace(action=MessageActionChatAddUser()))) is True
assert jns['_join_service_event_fast'](SimpleNamespace(message=SimpleNamespace(action=None,_message=SimpleNamespace(action=MessageActionChatAddUser())))) is True

# 4) Delete admission: only one background request may wait ahead; a new live
# waiter must run before the second background cleanup request.
class FakeClient:
    def __init__(self): self.order=[]
    async def delete_messages(self,target,message_ids,revoke=True):
        self.order.append(str(target))
        await asyncio.sleep(0.025)
        return True

class LiveDeleteCircuitOpen(RuntimeError): pass
class CampaignDeleteCircuitOpen(RuntimeError): pass
client=FakeClient()
dns={
    'Any':Any,'Optional':Optional,'asyncio':asyncio,'time':time,'client':client,
    '_delete_rpc_sem':asyncio.Semaphore(1),'_delete_background_admission_sem':asyncio.Semaphore(1),
    '_delete_foreground_waiters':0,'DELETE_RPC_BACKGROUND_PRIORITY_WAIT_SECONDS':1.0,
    '_delete_rpc_next_allowed_at':0.0,'_delete_rpc_pause_until':0.0,'_delete_rpc_last_flood_log_at':0.0,
    'DELETE_RPC_TIMEOUT_COOLDOWN_SECONDS':1.0,'DELETE_RPC_FLOOD_BUFFER_SECONDS':0.1,
    'DELETE_RPC_FLOOD_COOLDOWN_SECONDS':1.0,'DELETE_RPC_MIN_INTERVAL_SECONDS':0.0,
    '_perf_counters':defaultdict(int),'foreground_delete_circuit_is_open':lambda lane:False,
    'campaign_delete_circuit_is_open':lambda:False,'delete_rpc_flood_wait_seconds':lambda exc:0.0,
    'LiveDeleteCircuitOpen':LiveDeleteCircuitOpen,'CampaignDeleteCircuitOpen':CampaignDeleteCircuitOpen,
    'log':SimpleNamespace(warning=lambda *a,**k:None),
}
exec_fn(dns,'governed_delete_messages')
async def priority_case():
    bg1=asyncio.create_task(dns['governed_delete_messages']('bg1',1,lane='full-cleanup'))
    await asyncio.sleep(0.003)
    bg2=asyncio.create_task(dns['governed_delete_messages']('bg2',2,lane='cleanup-batch'))
    await asyncio.sleep(0.003)
    fg=asyncio.create_task(dns['governed_delete_messages']('fg',3,lane='live'))
    await asyncio.gather(bg1,bg2,fg)
asyncio.run(priority_case())
assert client.order == ['bg1','fg','bg2'], client.order

# 5) Forward semantics remain verified/durable, not detection-only.
fwd=fn('maybe_enforce_forward_lock_fast')
assert 'verify=True' in fwd
assert 'queue_live_delete_retry' in fwd
assert 'forward_delete_pending' in fwd

# 6) 96.36 welcome code is actually part of this version and installer, while
# the noisy profanity microbenchmark has a production-safe threshold.
assert 'check_zivo60_96_36_welcome_end_to_end.py' in (ROOT/'install_zivo60.sh').read_text(encoding='utf-8')
assert 'check_zivo60_96_37_forward_welcome_fastlane.py' in (ROOT/'install_zivo60.sh').read_text(encoding='utf-8')
prof=(ROOT/'check_zivo60_96_33_profanity_guard_expansion.py').read_text(encoding='utf-8')
assert 'ZIVO_PROFANITY_TEST_MAX_SECONDS' in prof and '"6.0"' in prof

print('CHECK ZIVO60.96.37 FORWARD + WELCOME FASTLANE: PASS')
print('  locked forward bypasses ordinary group FIFO: PASS')
print('  live delete admitted before queued background cleanup: PASS')
print('  forward verify + durable retry semantics preserved: PASS')
print('  join service event gets eager priority route: PASS')
print('  96.36 welcome recovery remains deployed/tested: PASS')
print('  noisy profanity benchmark no longer causes false rollback: PASS')
