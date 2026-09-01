#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast, asyncio
from pathlib import Path
from typing import Any, Optional

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
assert 'private-membership=notice-only-once+no-membership-rpc' in SRC
assert 'CREATE TABLE IF NOT EXISTS private_channel_notice_v83' in SRC
assert 'REQUIRED_MAIN_CHANNEL_LINK = "@ZIVOHELP"' in SRC


def fn_text(name: str) -> str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

# The runtime gate must be pure onboarding. It must never ask Soroush about
# membership, participants, admin logs, or required-channel state.
gate_src=fn_text('maybe_gate_private_membership')
for forbidden in (
    'check_required_membership', 'check_channel_membership',
    'direct_channel_participant_state', 'GetParticipantRequest',
    'GetParticipantsRequest', 'GetAdminLogRequest', 'MEMBERSHIP_CACHE',
):
    assert forbidden not in gate_src, forbidden
assert '_private_channel_notice_v83_seen' in gate_src
assert '_mark_private_channel_notice_v83' in gate_src
assert 'send_private_from_event' in gate_src

# Existing 60.82 membership helpers may remain as dormant compatibility code,
# but process_private_inbound is wired only through the no-RPC notice gate.
private_src=fn_text('process_private_inbound')
assert 'maybe_gate_private_membership(sender_id, target, event)' in private_src
assert private_src.index('maybe_gate_private_membership') < private_src.index('parse_group_connection_target(text)')

# First PM is consumed by the notice. Second and later PMs pass normally.
node=next(n for n in TREE.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='maybe_gate_private_membership')
mini=compile(ast.Module(body=[node],type_ignores=[]),'<private-notice>','exec')
state={'seen':False,'sends':0,'marks':0,'fail':False}

def seen(uid): return bool(state['seen'])
def mark(uid): state['seen']=True; state['marks'] += 1
async def send(event,target,text):
    state['sends'] += 1
    assert '@ZIVOHELP' in text
    if state['fail']:
        raise RuntimeError('temporary send failure')
class Log:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass
ns={'Any':Any,'Optional':Optional,'_private_channel_notice_v83_seen':seen,
    '_mark_private_channel_notice_v83':mark,'send_private_from_event':send,
    'private_membership_join_notice_text':lambda:'اول عضو شو @ZIVOHELP','log':Log()}
exec(mini,ns)
gate=ns['maybe_gate_private_membership']

async def cases():
    state.update(seen=False,sends=0,marks=0,fail=False)
    assert await gate(123,object(),None) is True
    assert state == {'seen':True,'sends':1,'marks':1,'fail':False}
    assert await gate(123,object(),None) is False
    assert state['sends']==1 and state['marks']==1

    # If notice delivery fails, keep the PM blocked but do not mark it. The
    # next PM retries instead of silently bypassing the onboarding notice.
    state.update(seen=False,sends=0,marks=0,fail=True)
    assert await gate(456,object(),None) is True
    assert state['seen'] is False and state['marks']==0 and state['sends']==1
    state['fail']=False
    assert await gate(456,object(),None) is True
    assert state['seen'] is True and state['marks']==1 and state['sends']==2
    assert await gate(456,object(),None) is False
asyncio.run(cases())

notice=fn_text('private_membership_join_notice_text')
assert 'REQUIRED_MAIN_CHANNEL_LINK' in notice
assert '@ZIVOCMD' in notice
assert 'REQUIRED_MAIN_CHANNEL_LINK = "@ZIVOHELP"' in SRC
assert 'AWkuvaZkdIhNuR4bm6stog' not in SRC

print('CHECK ZIVO60.91 PRIVATE NOTICE-ONLY ONBOARDING: PASS')
print('  no membership RPC in PM gate: PASS')
print('  old users get fresh v83 notice table: PASS')
print('  first PM consumed, later PMs pass: PASS')
print('  failed notice retries safely: PASS')
print('  public/private group-link path remains after gate: PASS')
