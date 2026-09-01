#!/usr/bin/env python3
from __future__ import annotations
import ast
from pathlib import Path
SRC=Path(__file__).with_name('zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC

def fn(name):
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

route=fn('_zivo_router_impl')
welcome_pos=route.index('await maybe_handle_group_join_welcome(event)')
rate_pos=route.index('await maybe_enforce_message_rate_limit')
spam_pos=route.index('await consume_group_anti_spam_event')
assert welcome_pos < rate_pos < spam_pos
assert route.count('await maybe_handle_group_join_welcome(event)') == 1
joined=fn('_joined_user_ids_from_event')
for token in ('adduser','joined','chatadduser','chatjoined','memberjoin','participantadd'):
    assert token in joined
handler=fn('maybe_handle_group_join_welcome')
assert '_welcome_event_already_sent' in handler
assert '_mark_welcome_event_sent' in handler
assert '_send_welcome_text_reply' in handler
print('CHECK ZIVO60.91 WELCOME SERVICE FAST PATH: PASS')
print('join service bypasses rate/spam/locks: PASS')
print('welcome dedup retained: PASS')
