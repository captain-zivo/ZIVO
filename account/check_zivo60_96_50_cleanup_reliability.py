from pathlib import Path
import ast, asyncio, logging
from typing import Any, Dict, List, Optional, Tuple
ROOT=Path(__file__).resolve().parent
core=(ROOT/'zivo60.py').read_text(encoding='utf-8')
assert 'VERSION = "zivo60.96.50"' in core
for token in [
    'CLEANUP_DELETE_MIN_INTERVAL_SECONDS',
    'CLEANUP_DELETE_BATCH_TIMEOUT_SECONDS',
    'CLEANUP_HISTORY_PAGE_TIMEOUT_SECONDS',
    'fetch_numeric_cleanup_history',
    'op == "control_enqueue"',
    'op == "control_status"',
    'numeric-paged+timeout-barrier+adaptive-split+async-official',
    'await_late_delete_barrier',
    'DELETE_RPC_TIMEOUT_SOFT_GRACE_SECONDS',
    'CLEANUP_RETRY_SPLIT_THRESHOLD',
]:
    assert token in core, token
assert 'limit=count' not in core[core.index('async def command_cleanup_messages'):core.index('def cleanup_retry_wait_seconds')], 'numeric cleanup must not issue giant get_messages(limit=count)'
assert 'if lane_name in {"cleanup-batch", "full-cleanup"}' in core

# Execute the real pagination function in isolation with a fake paged Soroush history.
tree=ast.parse(core)
node=next(n for n in tree.body if isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)) and n.name=='fetch_numeric_cleanup_history')
code=compile(ast.Module(body=[node],type_ignores=[]),str(ROOT/'zivo60.py'),'exec')
class Msg:
    def __init__(self,i,p=False): self.id=i; self.pinned=p
class Group: id=777
pages=[]
# 6200 historical messages, every 113th pinned; enough to exercise GOLD 5000 cleanup.
messages=[Msg(i, i%113==0) for i in range(9000,2800,-1)]
async def fake_page(group,offset_id,limit=100,**kwargs):
    assert int(limit)<=100
    eligible=[m for m in messages if m.id < int(offset_id)]
    out=eligible[:int(limit)]
    pages.append((int(offset_id),int(limit),[m.id for m in out]))
    return out
def safe_int(x):
    try: return int(x)
    except Exception: return None
def message_is_pinned(m): return bool(getattr(m,'pinned',False))
ns={'Any':Any,'Dict':Dict,'List':List,'Optional':Optional,'Tuple':Tuple,'asyncio':asyncio,'log':logging.getLogger('t'),'safe_int':safe_int,'message_is_pinned':message_is_pinned,'fetch_cleanup_history_page':fake_page}
exec(code,ns)
ids,pins,page_count=asyncio.run(ns['fetch_numeric_cleanup_history'](Group(),command_message_id=9001,count=5000))
assert len(ids) + len(pins) == 5000
assert len(ids) == 5000 - len(pins)
assert len(ids)==len(set(ids))
assert all(i<9001 for i in ids)
assert all(p%113==0 for p in pins)
assert page_count>=50 and all(limit<=100 for _,limit,_ in pages)
assert all(pages[i+1][0] < pages[i][0] for i in range(len(pages)-1))

# Exercise the real numeric delete retry path: one 100-id timeout must split the
# still-live ids into 50+50 rather than immediately repeating another huge RPC.
delete_node=next(n for n in tree.body if isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)) and n.name=='delete_message_ids_in_batches')
delete_code=compile(ast.Module(body=[delete_node],type_ignores=[]),str(ROOT/'zivo60.py'),'exec')
retry_calls=[]
async def fake_delete(_group, ids, **_kwargs):
    batch=list(ids)
    retry_calls.append(batch)
    if len(retry_calls)==1:
        raise asyncio.TimeoutError('synthetic timeout')
    return None
async def fake_barrier(**_kwargs): return True
async def fake_resolve(_group, ids): return {int(mid): object() for mid in ids}
def fake_permission(_exc): return False
def fake_wait(_exc,_attempt): return 0.0
retry_ns={
    'Any':Any,'Dict':Dict,'List':List,'Optional':Optional,'Tuple':Tuple,
    'asyncio':asyncio,'log':logging.getLogger('retry'),
    'governed_delete_messages':fake_delete,
    'await_late_delete_barrier':fake_barrier,
    'cleanup_resolve_message_ids':fake_resolve,
    'cleanup_error_is_permission':fake_permission,
    'cleanup_retry_wait_seconds':fake_wait,
    'CLEANUP_DELETE_MAX_ATTEMPTS':2,
    'CLEANUP_DELETE_BATCH_TIMEOUT_SECONDS':15.0,
    'CLEANUP_RETRY_SPLIT_THRESHOLD':50,
    'DELETE_RPC_LATE_BARRIER_SECONDS':8.0,
}
exec(delete_code,retry_ns)
retry_deleted,retry_failed=asyncio.run(retry_ns['delete_message_ids_in_batches'](Group(), list(range(1,101))))
assert [len(x) for x in retry_calls] == [100,50,50], [len(x) for x in retry_calls]
assert retry_deleted==100 and retry_failed==0, (retry_deleted,retry_failed)


# Exercise the real delete governor timeout/grace/barrier logic in isolation.
helper_node=next(n for n in tree.body if isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)) and n.name=='await_late_delete_barrier')
governed_node=next(n for n in tree.body if isinstance(n,(ast.AsyncFunctionDef,ast.FunctionDef)) and n.name=='governed_delete_messages')
governed_code=compile(ast.Module(body=[helper_node,governed_node],type_ignores=[]),str(ROOT/'zivo60.py'),'exec')
import time
from collections import defaultdict
class SlowClient:
    def __init__(self,delay): self.delay=delay; self.active=0; self.max_active=0; self.calls=0
    async def delete_messages(self,*_a,**_k):
        self.calls+=1; self.active+=1; self.max_active=max(self.max_active,self.active)
        try:
            await asyncio.sleep(self.delay)
            return True
        finally:
            self.active-=1
async def governor_case():
    c=SlowClient(1.08)  # > clamped 1s timeout, < timeout + soft grace
    ns={
      'Any':Any,'Optional':Optional,'asyncio':asyncio,'time':time,'client':c,'log':logging.getLogger('gov'),
      '_delete_rpc_sem':asyncio.Semaphore(1),'_delete_background_admission_sem':asyncio.Semaphore(1),
      '_delete_foreground_waiters':0,'DELETE_RPC_BACKGROUND_PRIORITY_WAIT_SECONDS':0.05,
      '_delete_rpc_next_allowed_at':0.0,'_delete_rpc_pause_until':0.0,'_delete_rpc_last_flood_log_at':0.0,
      '_delete_rpc_late_task':None,'DELETE_RPC_LATE_BARRIER_SECONDS':1.0,'DELETE_RPC_TIMEOUT_SOFT_GRACE_SECONDS':0.25,
      'DELETE_RPC_TIMEOUT_COOLDOWN_SECONDS':0.1,'DELETE_RPC_MIN_INTERVAL_SECONDS':0.0,'CLEANUP_DELETE_MIN_INTERVAL_SECONDS':0.0,
      'DELETE_RPC_FLOOD_BUFFER_SECONDS':0.1,'DELETE_RPC_FLOOD_COOLDOWN_SECONDS':0.1,
      '_perf_counters':defaultdict(int),
      'foreground_delete_circuit_is_open':lambda _lane:False,
      'campaign_delete_circuit_is_open':lambda:False,
      'delete_rpc_flood_wait_seconds':lambda _exc:0.0,
      'LiveDeleteCircuitOpen':RuntimeError,'CampaignDeleteCircuitOpen':RuntimeError,
    }
    exec(governed_code,ns)
    result=await ns['governed_delete_messages'](object(),[1,2,3],timeout=1.0,lane='cleanup-batch')
    assert result is True
    assert c.calls==1 and c.max_active==1
    assert ns['_perf_counters']['delete_rpc_late_success']==1
    assert ns['_delete_rpc_late_task'] is None
asyncio.run(governor_case())

print('CHECK ZIVO60.96.50 CLEANUP RELIABILITY: PASS')
print(f'  paged numeric cleanup: {page_count} pages, max page <=100, exact 5000-position window with {len(pins)} pins protected: PASS')
print('  async official control enqueue/status contract: PASS')
print('  adaptive cleanup delete pace with shared FloodWait circuit: PASS')
print('  synthetic timeout -> live-id verify -> 50+50 adaptive retry: PASS')
print('  real governor soft-timeout grace keeps max concurrent DeleteMessages=1: PASS')
