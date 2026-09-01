#!/usr/bin/env python3
from __future__ import annotations
import ast
import asyncio
import re
from pathlib import Path
from typing import Any, List

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)

def fn_text(name: str) -> str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

for name in ('_group_send_error_upper','_group_text_send_unavailable','_group_link_send_forbidden','_restricted_copyable_text','send_copyable_command_text'):
    assert name in SRC
assert 'help-delivery=link-restricted-fallback' in SRC
assert 'settings-token=copy-noise-tolerant' in SRC
spans = fn_text('sequential_text_spans_utf16')
assert 'if pos < 0:' in spans and 'continue' in spans

class Log:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass
log=Log()

class InputPeerUser: pass
class Types:
    InputPeerUser=InputPeerUser
types=Types()

class Forbidden(Exception): pass

class FakeClient:
    def __init__(self): self.calls=[]
    async def send_message(self,target,text,**kwargs):
        self.calls.append((text,kwargs))
        if len(self.calls) <= 2:
            raise Forbidden('RPCError 403: CHAT_SEND_LINK_FORBIDDEN (caused by SendMessageRequest)')
        return 'ok'

ns={'BaseException':BaseException,'Any':Any,'List':List,'re':re,'types':types,'client':FakeClient(),'log':log,
    'command_code_entities':lambda text,commands:['entity'], 'send_private':None,
    'active_group_command_reply_id':lambda explicit=None:None}
for name in ('_group_send_error_upper','_group_text_send_unavailable','_group_link_send_forbidden','_restricted_copyable_text','send_copyable_command_text'):
    exec(fn_text(name),ns)

async def run():
    text='HEAD\n@ZIVOCMD\nhttps://splus.ir/ZIVOCMD\nTAIL'
    await ns['send_copyable_command_text'](object(),text,['HEAD'])
    calls=ns['client'].calls
    assert len(calls)==3, len(calls)
    assert 'https://' in calls[0][0]
    assert 'https://' not in calls[1][0]
    assert '@ZIVOCMD' in calls[1][0]
    assert 'https://' not in calls[2][0]
    assert '@ZIVOCMD' not in calls[2][0]
    assert 'ZIVOCMD' in calls[2][0]
asyncio.run(run())

# Settings parser accepts strict tokens with small copy noise but rejects malformed tokens.
sel=[]
for node in TREE.body:
    if isinstance(node,ast.FunctionDef) and node.name in {'_normalize_settings_command_text','parse_settings_copy_command'}:
        sel.append(node)
mini=compile(ast.Module(body=sel,type_ignores=[]),'<settings-parser>','exec')
persian_digits=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')
def norm_group(value):
    value=(value or '').strip().replace(chr(0x200c),' ').replace(chr(0x200f),'').replace(chr(0x200e),'')
    value=value.replace('ي','ی').replace('ك','ک')
    return ' '.join(value.split())
ns2={'re':re,'Optional':__import__('typing').Optional,'Dict':__import__('typing').Dict,'Any':Any,
     'SETTINGS_TOKEN_RE':re.compile(r'^ZIVOSET-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$',re.I),
     'normalize_group_command':norm_group,'normalize_moderation_digits':lambda x:(x or '').translate(persian_digits),
     'normalize_settings_section':lambda x:'all' if not x else None}
exec(mini,ns2)
assert ns2['parse_settings_copy_command']('🔑 ZIVOSET-ABCD-1234-EF90')['token']=='ZIVOSET-ABCD-1234-EF90'
assert ns2['parse_settings_copy_command']('`ZIVOSET-ABCD-1234-EF90`')['token']=='ZIVOSET-ABCD-1234-EF90'
assert ns2['parse_settings_copy_command']('ZIVOSET-ABCD-123-EF90') is None
print('CHECK ZIVO60.91 HELP PERMISSION + SETTINGS COPY NOISE: PASS')
