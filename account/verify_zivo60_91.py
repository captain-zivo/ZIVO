#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast, asyncio, hashlib, os, sqlite3, tempfile, time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional, List, Tuple

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'zivo60.py'; MULTI=ROOT/'zivo_multi_account.py'
src=MAIN.read_text(encoding='utf-8'); msrc=MULTI.read_text(encoding='utf-8')
assert 'VERSION = "zivo60.93"' in src
assert 'performance-router=scale-v37-help-permission-guard sqlite-main=autoclose' in src
assert 'campaign-media=config-dc-discovery+single-preupload+permission-aware+transport-matrix' in src
assert 'CAMPAIGN_MEDIA_TARGET_TIMEOUT_SECONDS' in src
assert 'factory=_ZivoSQLiteConnection' in src
assert 'class _ZivoSQLiteConnection(sqlite3.Connection)' in src
assert 'CREATE TABLE IF NOT EXISTS campaign_jobs' in msrc
assert 'transport-pending=cancelled-prune+reconnect-queue-clean' in src
assert 'help-delivery=link-restricted-fallback' in src
assert 'settings-token=copy-noise-tolerant' in src
assert 'def _restricted_copyable_text' in src
assert 'CHAT_SEND_LINK_FORBIDDEN' in src
assert 'def _prune_finished_transport_requests' in src
assert 'transport reconnect hygiene' in src
assert 'transport pending hygiene' in src

# Runtime Persian text lock advanced only for the requested v60.95 social UI additions.
def persian_literals(source: str):
    tree=ast.parse(source)
    return [n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str) and any('\u0600' <= c <= '\u06ff' for c in n.value)]
p=persian_literals(src)
assert len(p)>=3992, len(p)
assert all(any(x in item for item in p) for x in ('مالک','ادمین','ویژه','راهنما'))

# Protected high-value text paths remain byte-identical to zivo60.70+.
def fn_text(source: str, name: str) -> str:
    tree=ast.parse(source); lines=source.splitlines(True)
    node=next(x for x in ast.walk(tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name)
    return ''.join(lines[node.lineno-1:node.end_lineno])
expected={
    'send_default_join_message':'4aba7912f769c32fbd2c4b690c1004c9751b7b394f4ebe98c7233e24bbc49503',
    'pending_group_info_text':'38c5ac86bd16495dd0c86144eaa4749348daf39536103b63dce0441dde5111c8',
    # The protected speaker path advanced in the verified 96.49 welcome/speaker
    # release; pin that shipped implementation instead of the stale pre-96.49 hash.
    'maybe_handle_speaker_message':'e24e69f7d71c53347239030ed653b0d07b3599859394ea3bb2926c49d0f1bd9c',
    'process_private_inbound_tracked':'088d4da7fc803495bb2ee24f5c3915ca2c4b6a5a2783cd417558e21864a65c57',
    'telegram_admin_worker':'c798a194762d2c90011d79106bdc075720c89011eff60ff7c489b924e8d1605a',
    'tg_edit_text':'5e63612f8697c412adeb06cb15bc3d89e8771077a8126d490ba0434c1d2eed96',
}
for name,digest in expected.items():
    assert hashlib.sha256(fn_text(src,name).encode()).hexdigest()==digest, name

# 60.75 must preserve config-discovered media endpoints from authenticated GetConfig instead of
# guessing stale public file hostnames that can be unreachable from the VPS.
discover=fn_text(src,'_zivo_discover_upload_endpoints')
assert 'functions.help.GetConfigRequest()' in discover
assert 'dc_options' in discover
assert 'media_only' in discover
assert 'tcpo_only' in discover
assert 'current_host' in discover
assert '_zivo_upload_endpoint_cache' in discover
for stale in ('up.splus.ir','fs.splus.ir','fs2.splus.ir','storage.splus.ir','storage2.splus.ir'):
    assert stale not in src, stale

# Upload transport matrix uses server-advertised host/port/DC, dedicated sender
# with a real updates queue, and upload-flavoured InitConnection on first part.
upload=fn_text(src,'_zivo_upload_one_file')
assert 'ConnectionTcpObfuscated' in upload
assert 'ConnectionTcpAbridged' in upload
assert 'client._connection' in upload
assert 'updates_queue=asyncio.Queue()' in upload
assert 'endpoints = await _zivo_discover_upload_endpoints()' in upload
assert 'host, port, dc_id, flags' in upload
assert 'outgoing = init_for(request, profile) if first and wrap_first else request' in upload
assert 'media upload prepared from config endpoint' in upload
assert 'for host, port, dc_id, flags in endpoints[:8]' in upload
assert 'profiles = ZIVO_UPLOAD_PROFILES if is_current else (ZIVO_UPLOAD_PROFILES[0],)' in upload
assert 'for upload_host in ZIVO_UPLOAD_HOSTS' not in upload

# Failed short-lived senders/connections close both WebSocket and aiohttp caches.
close_sender=fn_text(src,'_close_zivo_upload_sender')
close_conn=fn_text(src,'_close_zivo_upload_connection')
assert '_close_zivo_upload_connection(connection)' in close_sender
assert 'for attr in ("_cached_session", "_session")' in close_conn
assert 'await asyncio.wait_for(ws.close()' in close_conn

# 60.75 campaign media: one upload per account campaign, no wasteful re-upload
# on hard peer media permissions, and one bounded retry on transient SendMedia.
media_local=fn_text(src,'_campaign_send_local_media')
assert '_zivo_upload_one_file(path)' in media_local
assert 'DEDICATED_UPLOAD_TIMEOUT_SECONDS' in media_local
assert '_campaign_send_uploaded_media(target, uploaded, kwargs, content_type)' in media_local
assert '_campaign_media_permission_rejected(upload_error, content_type)' in media_local
assert 'client.send_file(target, str(path), **kwargs)' not in media_local

prepared=fn_text(src,'_campaign_prepare_media_once')
assert '_zivo_upload_one_file(path)' in prepared
assert 'campaign media preupload PASS' in prepared
assert 'per-target upload enabled' in prepared

perm=fn_text(src,'_campaign_media_permission_rejected')
assert 'CHATSENDVOICESFORBIDDEN' in perm
assert 'CHATSENDPHOTOSFORBIDDEN' in perm
assert 'CHATSENDVIDEOSFORBIDDEN' in perm
assert 'CHATSENDDOCSFORBIDDEN' in perm

send_uploaded=fn_text(src,'_campaign_send_uploaded_media')
assert '_campaign_sendmedia_transient(exc)' in send_uploaded
assert 'await asyncio.sleep(0.35)' in send_uploaded
assert send_uploaded.count('client.send_file(target, uploaded, **kwargs)') == 2

broadcast=fn_text(src,'broadcast_send_target')
assert 'campaign media permission skip; no reupload' in broadcast
assert 'campaign prepared media failed; local reupload' in broadcast
assert 'return await _campaign_send_local_media(target, path, kwargs, content_type)' in broadcast
assert 'if not path.is_file()' in broadcast

# Content-type semantics remain explicit and are never silently converted.
kwargs_fn=fn_text(src,'_campaign_media_send_kwargs')
assert 'kwargs["voice_note"] = True' in kwargs_fn
assert 'kwargs["supports_streaming"] = True' in kwargs_fn
assert 'kwargs["force_document"] = False' in kwargs_fn

# Both single- and multi-account campaigns pre-upload once and keep the same
# InputFile handle instead of re-uploading after every blocked peer.
run_single=fn_text(src,'run_telegram_campaign')
run_multi=fn_text(src,'run_multi_account_campaign_job')
for body in (run_single, run_multi):
    assert 'CAMPAIGN_MEDIA_TARGET_TIMEOUT_SECONDS' in body
    assert 'prepared_media = await _campaign_prepare_media_once(path)' in body
    assert '_campaign_reusable_media(result)' not in body
assert 'multi-account campaign media PASS' in run_multi
assert 'multi-account campaign target failed' in run_multi
assert 'final_status = "failed" if content_type != "text" and attempted > 0 and success == 0 else "done"' in run_multi

# Focused behavioral test: a hard voice permission error is propagated without
# a second upload/send, while an RPC 500 gets exactly one retry.
tree=ast.parse(src)
selected=[]
for node in tree.body:
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {
        '_campaign_media_permission_rejected','_campaign_sendmedia_transient','_campaign_send_uploaded_media'
    }:
        selected.append(node)
mini_send=compile(ast.Module(body=selected,type_ignores=[]),'<campaign-send>','exec')
class VoiceBlocked(Exception): pass
VoiceBlocked.__name__='ChatSendVoicesForbiddenError'
class FakeSendClient:
    def __init__(self, errors): self.errors=list(errors); self.calls=0
    async def send_file(self,*a,**k):
        self.calls += 1
        if self.errors:
            err=self.errors.pop(0)
            if err: raise err
        return 'ok'
async def _run_send_case(errors):
    c=FakeSendClient(errors)
    ns={
        'Any':Any,'Dict':Dict,'BaseException':BaseException,'asyncio':asyncio,
        'client':c,'BROADCAST_SEND_TIMEOUT_SECONDS':2.0,
        '_is_group_inaccessible_error':lambda exc: False,
    }
    exec(mini_send,ns)
    try:
        out=await ns['_campaign_send_uploaded_media']('peer','file',{'voice_note':True},'voice')
        return c.calls,out,None
    except Exception as exc:
        return c.calls,None,exc
calls,out,err=asyncio.run(_run_send_case([VoiceBlocked('You cannot send voices results in this chat')]))
assert calls==1 and isinstance(err,VoiceBlocked), (calls,err)
class Rpc500(Exception): pass
calls,out,err=asyncio.run(_run_send_case([Rpc500('RPCError 500: INTERNAL_SERVER_ERROR'),None]))
assert calls==2 and out=='ok' and err is None, (calls,out,err)

# Telegram media ingestion remains intact.
download=fn_text(src,'tg_download_content')
assert 'TELEGRAM_MEDIA_EMPTY' in download
assert 'telegram campaign media downloaded' in download

# Dynamic endpoint-discovery test using fake GetConfig response.
tree=ast.parse(src)
selected=[]
for node in tree.body:
    if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {
        '_zivo_upload_option_field','_zivo_discover_upload_endpoints'
    }:
        selected.append(node)
mini=compile(ast.Module(body=selected,type_ignores=[]),'<upload-discovery>','exec')
class FakeLog:
    def info(self,*args,**kwargs): pass
class FakeOption:
    def __init__(self, id, ip, port, **kw):
        self.id=id; self.ip_address=ip; self.port=port
        for k,v in kw.items(): setattr(self,k,v)
class FakeSession:
    dc_id=2; server_address='185.60.137.29'; port=443
class FakeClient:
    session=FakeSession()
    async def __call__(self, req):
        return SimpleNamespace(dc_options=[
            FakeOption(3,'10.0.0.3',444,media_only=True),
            FakeOption(2,'10.0.0.2',445,media_only=True),
            FakeOption(2,'10.0.0.9',446),
        ])
class Help:
    class GetConfigRequest: pass
class Fns: help=Help
ns={
    'Any':Any,'List':List,'Tuple':Tuple,'time':time,'asyncio':asyncio,
    'client':FakeClient(),'functions':Fns,'safe_int':lambda x: int(x) if x is not None else None,
    'ZIVO_UPLOAD_CONFIG_TTL_SECONDS':900.0,'_zivo_upload_endpoint_cache':[],
    '_zivo_upload_endpoint_cache_at':0.0,'log':FakeLog(),
}
exec(mini,ns)
rows=asyncio.run(ns['_zivo_discover_upload_endpoints']())
assert rows[0][:3] == ('10.0.0.2',445,2), rows
assert rows[0][3].startswith('media'), rows
assert any(r[:3]==('185.60.137.29',443,2) and r[3]=='current' for r in rows), rows

# Main SQLite autoclose invariant remains intact.
tree=ast.parse(src); parents={}
for node in ast.walk(tree):
    for child in ast.iter_child_nodes(node): parents[child]=node
calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='db_connect']
assert len(calls)>=200, len(calls)
for call in calls:
    cur=call; ok=False
    for _ in range(5):
        cur=parents.get(cur)
        if cur is None: break
        if isinstance(cur,ast.withitem): ok=True; break
    assert ok, f'db_connect escape line {call.lineno}'
mod_ast=ast.parse(src); selected=[]
for node in mod_ast.body:
    if isinstance(node,ast.ClassDef) and node.name=='_ZivoSQLiteConnection': selected.append(node)
    if isinstance(node,ast.FunctionDef) and node.name=='db_connect': selected.append(node)
mini_db=compile(ast.Module(body=selected,type_ignores=[]),'<zivo-db-connect>','exec')
with tempfile.TemporaryDirectory() as td:
    nsdb={'sqlite3':sqlite3,'DB_PATH':Path(td)/'fd.db'}; exec(mini_db,nsdb)
    before=len(os.listdir('/proc/self/fd')) if Path('/proc/self/fd').exists() else 0
    for i in range(1000):
        with nsdb['db_connect']() as con:
            con.execute('CREATE TABLE IF NOT EXISTS t (x INTEGER)')
            con.execute('INSERT INTO t VALUES (?)',(i,))
    after=len(os.listdir('/proc/self/fd')) if Path('/proc/self/fd').exists() else before
    assert after-before <= 3, (before,after)

print('VERIFY ZIVO60.91: PASS')
print('PERSIAN_RUNTIME_LITERALS:',len(p))
print('CAMPAIGN_MEDIA_TIMEOUT: media-aware')
print('MEDIA_UPLOAD_ROUTING: GetConfig->dc_options->transport-matrix PASS')


# 60.76 command-core keeps 60.75 realtime turbo: reserve the realtime transport for private messages and
# recognized group commands while deferring background RPC work.
assert 'FOREGROUND_PRIORITY_HOT_SECONDS' in src
assert 'FOREGROUND_BACKGROUND_PENDING_SOFT' in src
assert 'ZIVO_FOREGROUND_PRIORITY_HOT_SECONDS", "3.0"' in src
assert 'ZIVO_FOREGROUND_BACKGROUND_PENDING_SOFT", "16"' in src
assert 'retry_delay=1' in src
assert 'ZIVO_PRIVATE_USER_CONCURRENCY", "4"' in src
assert 'ZIVO_PRIVATE_OVERFLOW_WORKERS", "3"' in src
assert 'ZIVO_COMMAND_OVERFLOW_WORKERS", "3"' in src
assert 'ZIVO_JOIN_NOTICE_WORKERS", "2"' in src
assert 'ZIVO_ACTIVATION_CARD_WORKERS", "2"' in src
assert 'background-rpc=foreground-reserved' in src
assert 'log-storm=rate-limited' in src
assert 'private-priority=eager+fairness' in src

priority_fn=fn_text(src,'_priority_traffic_is_hot')
yield_fn=fn_text(src,'_yield_background_to_realtime')
slot_fn=fn_text(src,'_wait_transport_background_slot')
assert '_last_priority_event_at' in priority_fn
assert '_private_overflow_queue' in priority_fn and '_command_overflow_queue' in priority_fn
assert 'FOREGROUND_BACKGROUND_PENDING_SOFT' in yield_fn
assert '_priority_traffic_is_hot()' in yield_fn
assert '_realtime_traffic_is_hot(BACKGROUND_REALTIME_QUIET_SECONDS)' in yield_fn
assert 'effective_limit = min(int(soft_limit), int(FOREGROUND_BACKGROUND_PENDING_SOFT))' in slot_fn
assert '_realtime_traffic_is_hot(BACKGROUND_REALTIME_QUIET_SECONDS)' in slot_fn

router=fn_text(src,'zivo_router')
assert 'global _last_inbound_event_at, _last_priority_event_at' in router
assert 'if is_private or priority_group_command:' in router
assert '_last_priority_event_at = time.monotonic()' in router

known=fn_text(src,'private_known_contact_poll_worker')
watchdog=fn_text(src,'private_inbox_watchdog')
pending_fast=fn_text(src,'pending_activation_fast_worker')
lifecycle=fn_text(src,'group_lifecycle_worker')
authority=fn_text(src,'schedule_group_authority_refresh')
for body in (known,watchdog,pending_fast,lifecycle,authority):
    assert '_priority_traffic_is_hot()' in body, body[:80]
assert 'FOREGROUND_BACKGROUND_PENDING_SOFT' in known
assert 'FOREGROUND_BACKGROUND_PENDING_SOFT' in watchdog
assert 'FOREGROUND_BACKGROUND_PENDING_SOFT' in pending_fast

# Command fast-lane heads are extended from the existing capability registry,
# so commands not present in the static hand-written head list still bypass
# ordinary group chatter without introducing/changing Persian runtime strings.
cap_heads=fn_text(src,'_capability_priority_command_heads')
assert 'ZIVO_CAPABILITY_REGISTRY' in cap_heads
assert 'command_details' in cap_heads and 'help_sections' in cap_heads
assert 'ZIVO_HELP_CATEGORIES' in cap_heads
assert 'PRIORITY_GROUP_COMMAND_HEADS = _capability_priority_command_heads()' in src

# Behavioral check for registry-derived head expansion.
tree=ast.parse(src)
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_capability_priority_command_heads')
mini_heads=compile(ast.Module(body=[node],type_ignores=[]),'<priority-heads>','exec')
ns_heads={
    'frozenset':frozenset,
    'PRIORITY_GROUP_COMMAND_HEADS':frozenset({'base'}),
    'ZIVO_CAPABILITY_REGISTRY':[
        {'help_command':'help topic','help_aliases':('guide topic',),
         'command_details':(('configure speaker','x'),),
         'help_sections':(('section',(('add trigger','x'),('status speaker','x'))),)},
    ],
    'ZIVO_HELP_CATEGORIES':[{'command':'help general','aliases':('guide general',)}],
}
exec(mini_heads,ns_heads)
heads=ns_heads['_capability_priority_command_heads']()
assert {'base','help','guide','configure','add','status'} <= set(heads), heads

# Log storm filter keeps the first useful warning but suppresses immediate
# duplicates for known non-fatal permission/activation noise.
tree=ast.parse(src)
node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='_TransportStormLogFilter')
mini_filter=compile(ast.Module(body=[node],type_ignores=[]),'<log-filter>','exec')
import logging, re
ns_filter={'logging':logging,'Dict':Dict,'time':time,'re':re}
exec(mini_filter,ns_filter)
f=ns_filter['_TransportStormLogFilter']()
r1=logging.LogRecord('x',logging.WARNING,'',0,'RPC error for msg 1: Chat admin privileges are required',(),None)
r2=logging.LogRecord('x',logging.WARNING,'',0,'RPC error for msg 2: Chat admin privileges are required',(),None)
assert f.filter(r1) is True
assert f.filter(r2) is False

# Priority helper behavior: a recent priority event or queued priority work is
# hot; an idle state is not.
tree=ast.parse(src)
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_priority_traffic_is_hot')
mini_priority=compile(ast.Module(body=[node],type_ignores=[]),'<priority-hot>','exec')
class Q:
    def __init__(self,n): self.n=n
    def qsize(self): return self.n
ns_pri={'Optional':Optional,'time':time,'FOREGROUND_PRIORITY_HOT_SECONDS':1.8,
        '_last_priority_event_at':0.0,'_private_overflow_queue':None,'_command_overflow_queue':None}
exec(mini_priority,ns_pri)
assert ns_pri['_priority_traffic_is_hot']() is False
ns_pri['_last_priority_event_at']=time.monotonic()
assert ns_pri['_priority_traffic_is_hot']() is True
ns_pri['_last_priority_event_at']=0.0; ns_pri['_private_overflow_queue']=Q(1)
assert ns_pri['_priority_traffic_is_hot']() is True

print('REALTIME_TURBO: foreground-reserve+fairness+adaptive-background PASS')


# 60.76 command-core recovery: a freshly joined/pending group must not stay
# help-only after a successful visible write, and a management command gets a
# bounded write-confirm -> activation -> replay path.
pending = fn_text(src,'handle_pending_group_ux')
promote = fn_text(src,'_promote_pending_group_after_write')
assert 'visible_reply_sent = False' in pending
assert '_promote_pending_group_after_write(group, int(group_id), "pending-visible-reply")' in pending
assert 'probe_group_send_access(group, marker="👀")' in pending
assert '_promote_pending_group_after_write(group, int(group_id), "pending-command")' in pending
assert 'if await handle_group_commands(event):' in pending
assert 'pending command replay PASS' in pending
assert '_group_join_notice_mark_probe' in promote
assert '_group_join_notice_complete' in promote
assert 'try_auto_activate_pending_group' in promote
assert 'pending-command=write-confirm+activate+replay' in src

# Settings-copy is now shared across isolated account DBs, with recovery for
# tokens created before the shared table existed. Token parsing also tolerates
# Unicode dash variants/invisible copy characters and localized digits.
settings_parse = fn_text(src,'parse_settings_copy_command')
settings_norm = fn_text(src,'_normalize_settings_command_text')
settings_get = fn_text(src,'get_settings_copy_snapshot')
settings_create = fn_text(src,'create_settings_copy_snapshot')
assert '_normalize_settings_command_text(text)' in settings_parse
assert 'normalize_moderation_digits(normalize_group_command(text))' in settings_norm
assert '0x2013' in settings_norm and '0xFF0D' in settings_norm and '0xFEFF' in settings_norm
assert 'multi_put_settings_snapshot' in settings_create
assert 'multi_get_settings_snapshot' in settings_get
assert 'multi_recover_settings_snapshot_from_accounts' in settings_get
assert 'settings-copy=shared-cross-account+legacy-recovery' in src
for needle in ('CREATE TABLE IF NOT EXISTS settings_snapshots','def put_settings_snapshot(','def get_settings_snapshot(','def recover_settings_snapshot_from_accounts('):
    assert needle in msrc, needle

# No protected Persian runtime copy changed after the intentional v60.95 advance.
p2=persian_literals(src)
assert len(p2)>=3992
assert all(any(x in item for item in p2) for x in ('مالک','ادمین','ویژه','راهنما'))

# Speaker accepts the natural enabled/disabled word order without changing any
# response copy.
speaker_src=(ROOT/'zivo_speaker.py').read_text(encoding='utf-8')
assert '"سخنگو فعال"' in speaker_src
assert '"سخنگو غیرفعال"' in speaker_src

print('COMMAND_CORE_RECOVERY: pending-activate+replay PASS')
print('SETTINGS_COPY_SHARED: cross-account+legacy-token-recovery PASS')
