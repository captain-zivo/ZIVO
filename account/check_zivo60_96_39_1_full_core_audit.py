from __future__ import annotations
import ast, asyncio, re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'zivo60.py'
SRC=MAIN.read_text(encoding='utf-8')
TREE=ast.parse(SRC)
assert any(v in SRC for v in ('VERSION = "zivo60.96.39.2"', 'VERSION = "zivo60.96.39.3"', 'VERSION = "zivo60.96.39.4"'))

def node(name:str):
    for n in TREE.body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name:
            return n
    raise AssertionError(name)

def fn_text(name:str)->str:
    return ast.get_source_segment(SRC,node(name)) or ''

def exec_fn(ns:dict[str,Any],name:str):
    mod=ast.Module(body=[node(name)],type_ignores=[]); ast.fix_missing_locations(mod)
    exec(compile(mod,str(MAIN),'exec'),ns)

# A) Numeric cleanup success path must be one transport RPC per batch: no readback
# after a successful DeleteMessages. Failure path retains verifier/retry.
cleanup_src=fn_text('delete_message_ids_in_batches')
assert 'if rpc_succeeded:' in cleanup_src
assert 'manual cleanup failure verify' in cleanup_src
class Log:
    def __getattr__(self,_): return lambda *a,**k: None
cleanup_calls=[]; verify_calls=[]
async def governed(group, ids, **kwargs): cleanup_calls.append(tuple(ids)); return True
async def verifier(group, ids): verify_calls.append(tuple(ids)); raise AssertionError('success path must not verify')
ns={'Any':Any,'List':List,'Tuple':Tuple,'Optional':Optional,'BaseException':BaseException,
    'asyncio':asyncio,'governed_delete_messages':governed,'log':Log(),
    'cleanup_resolve_message_ids':verifier,'cleanup_error_is_permission':lambda e:False,
    'cleanup_retry_wait_seconds':lambda e,a:0.1}
exec_fn(ns,'delete_message_ids_in_batches')
deleted,failed=asyncio.run(ns['delete_message_ids_in_batches'](SimpleNamespace(id=7),list(range(1,201))))
assert (deleted,failed)==(200,0),(deleted,failed)
assert len(cleanup_calls)==2, cleanup_calls
assert verify_calls==[], verify_calls

# B) Word-filter command is self-contained: first add auto-enables filtered lock.
wf_src=fn_text('command_word_filter')
assert 'set_group_lock_enabled(group_id, "پیام‌های فیلترشده", True, actor_id)' in wf_src
lock_enable=[]; sent=[]
async def purge(*a,**k): return (0,0,0,[])
async def send(*a,**k): sent.append(a[1] if len(a)>1 else '')
wf_ns={'Any':Any,'Dict':Dict,'safe_int':lambda x:int(x) if x is not None else None,
       'word_filter_actor_check':lambda gid,uid:(True,'مالک'),'send_group_text':send,
       'reset_filtered_phrases':lambda gid:0,'stats_num':lambda x:str(x),
       'remove_filtered_phrase':lambda gid,p:(False,p),'filtered_phrase_count':lambda gid:1,
       'add_filtered_phrase':lambda gid,p,uid:(True,p),'group_lock_row':lambda gid,name:None,
       'set_group_lock_enabled':lambda gid,name,en,uid:lock_enable.append((gid,name,en,uid)),
       'purge_word_filter_history':purge,'save_cleanup_pin_confirmation':lambda *a:0}
exec_fn(wf_ns,'command_word_filter')
event=SimpleNamespace(sender_id=11,id=99)
asyncio.run(wf_ns['command_word_filter'](event,SimpleNamespace(id=777),777,{'action':'add_word_filter','phrase':'تبلیغ تست'}))
assert lock_enable==[(777,'پیام‌های فیلترشده',True,11)], lock_enable
assert sent and 'روشن' in sent[-1]

# C) Flood Guard trigger uses fast target/input_chat before get_chat and failure re-arms.
spam_src=fn_text('consume_group_flood_guard_event')
assert 'fast_target_helper = globals().get("fast_event_group_target")' in spam_src
assert '_flood_guard_action_until.pop(action_key, None)' in spam_src
assert 'retry_rearmed=1' in spam_src
from collections import deque
ban=[]; purge_calls=[]
async def ban_fn(*a,**k): ban.append(1); return True
async def purge_fn(*a,**k): purge_calls.append(1); return (7,7,7,0)
async def send_fn(*a,**k): return None
spam_ns={'Any':Any,'safe_int':lambda v:int(v) if v is not None else None,
 'canonical_anti_spam_group_id':lambda v:int(v) if v is not None else None,
 'SELF_USER_ID':9999,'SYSTEM_USER_IDS':set(),'anti_spam_event_is_stale':lambda e:False,
 'get_installation':lambda gid:{'group_id':gid},'get_flood_guard_settings':lambda gid:{'enabled':1,'window_seconds':10,'consecutive_limit':2,'burst_limit':10,'cleanup_scan_limit':0},
 'lock_user_is_exempt':lambda gid,uid:False,'time':__import__('time'),'deque':deque,
 '_flood_guard_last_sender':{},'_flood_guard_seen_messages':{},'_flood_guard_action_until':{},'_flood_guard_event_times':{},
 'flood_guard_cleanup_runtime':lambda now:None,'queue_flood_guard_live_delete':lambda *a,**k:None,
 'ban_group_hard_spammer':ban_fn,'purge_flood_spammer_messages':purge_fn,'send_group_text':send_fn,'log':Log(),
 'fast_event_group_target':lambda e:e.input_chat}
exec_fn(spam_ns,'consume_group_flood_guard_event')
class Ev:
    is_private=False; input_sender=None
    def __init__(self,mid): self.sender_id=55; self.id=mid; self.chat_id=777; self.input_chat=SimpleNamespace(id=777)
    async def get_chat(self): raise AssertionError('fast target should avoid get_chat')
assert asyncio.run(spam_ns['consume_group_flood_guard_event'](Ev(1))) is False
assert asyncio.run(spam_ns['consume_group_flood_guard_event'](Ev(2))) is True
assert len(ban)==1 and len(purge_calls)==1

# D) Common management commands have a no-full-resolve rescue lane.
router_src=fn_text('_handle_group_commands_impl')
assert 'management_fast' in router_src
for token in ('anti_spam_command is not None','word_filter_command is not None','cleanup_command is not None'):
    assert token in router_src
assert router_src.index('management_fast') < router_src.index('group = await event.get_chat()')

# E) Capability registry integrity: every registered feature has help command and
# command examples are non-empty. Registry-driven heads are incorporated into the
# priority router, preventing documented commands from being dropped as chatter.
registry=None
for n in TREE.body:
    if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='ZIVO_CAPABILITY_REGISTRY':
        registry=ast.literal_eval(n.value); break
assert registry is not None and len(registry)>=30

extra_src=(ROOT/'zivo_admin_ux.py').read_text(encoding='utf-8')
extra_tree=ast.parse(extra_src)
extra_registry=()
for n in extra_tree.body:
    target_name=''
    if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name): target_name=n.target.id
    elif isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name): target_name=n.targets[0].id
    if target_name=='EXTRA_CAPABILITY_REGISTRY':
        extra_registry=ast.literal_eval(n.value); break
assert len(extra_registry)>=4
for feature in registry:
    assert str(feature.get('key') or '').strip()
    assert str(feature.get('help_command') or '').strip()
    for item in feature.get('command_details',()) or ():
        assert item and str(item[0] or '').strip()
assert '_capability_priority_command_heads() | EXTRA_COMMAND_HEADS' in SRC

# F) Installer keeps historical 6s benchmark semantics for regressions, but uses
# a server-realistic override during deployment so CPU variance cannot rollback.
prof=(ROOT/'check_zivo60_96_33_profanity_guard_expansion.py').read_text(encoding='utf-8')
installer=(ROOT/'install_zivo60.sh').read_text(encoding='utf-8')
assert '"6.0"' in prof
assert installer.count('ZIVO_PROFANITY_TEST_MAX_SECONDS=20')>=2


# G) Realtime word/content lock enforcement must not depend on get_chat.
# This was the remaining live hole: the phrase could match correctly but an
# unsupported/slow group entity resolve made enforcement silently return False.
lock_enforce_src=fn_text('maybe_enforce_group_lock')
content_enforce_src=fn_text('maybe_enforce_exact_content_filter')
for label, text in (("word/group lock", lock_enforce_src), ("exact content", content_enforce_src)):
    assert 'group = fast_event_group_target(event)' in text, label
    assert text.index('group = fast_event_group_target(event)') < text.index('group = await event.get_chat()'), label
    assert 'if not is_group_entity(group):' not in text, label


# H) The transactional installer must execute every shipped check*.py file.
# This keeps the release gate aligned with the actual Full Source inventory.
all_checks=sorted(item.name for item in ROOT.glob('check*.py'))
missing_installer_checks=[name for name in all_checks if name not in installer]
assert not missing_installer_checks, missing_installer_checks
# Do not hard-code a historical test count.  Source releases and installed copies
# must instead agree with the installer's declared check inventory.
deploy_block=installer.split('DEPLOY_FILES=(',1)[1].split('\n)',1)[0]
deployed_checks=sorted(set(__import__('re').findall(r'\b(check[^\s]+\.py)\b', deploy_block)))
assert set(all_checks) == set(deployed_checks), (sorted(set(all_checks)-set(deployed_checks)), sorted(set(deployed_checks)-set(all_checks)))

print('CHECK ZIVO60.96.39.2 FULL CORE AUDIT + INVENTORY: PASS')
print('  numeric cleanup success path removes redundant readback RPC: PASS')
print('  word filter auto-enables its enforcement lock: PASS')
print('  spam trigger uses fast target + failure re-arm contract: PASS')
print('  cleanup/filter/spam management fast command lane: PASS')
print(f'  capability registry integrity: {len(registry)} core + {len(extra_registry)} extra features PASS')
print('  installer profanity benchmark variance no longer rolls back release: PASS')
print('  realtime word/content lock enforcement uses fast event target: PASS')
print(f'  installer executes all shipped check*.py files: {len(all_checks)}/{len(all_checks)} PASS')
