#!/usr/bin/env python3
from __future__ import annotations
import ast
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC)
assert ('VERSION = "zivo60.96.21"' in SRC or 'VERSION = "zivo60.96.22"' in SRC)

def fn(name:str)->str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ast.get_source_segment(SRC,node) or ''

# Full-cleanup aliases must all route to the same destructive handler.
ns={'normalize_group_command':lambda x:x.strip()}
exec(fn('parse_full_cleanup_command'),ns)
for text in ('پاکسازی گپ','پاکسازی کل گپ','پاکسازی کامل گپ','پاکسازی کامل','پاکسازی کل'):
    got=ns['parse_full_cleanup_command'](text)
    assert got and got.get('action')=='full_cleanup', (text,got)

# Owner is never paywalled. Admin still needs an active PRO entitlement.
state={'role':'ادمین','pro':False}
ns2={
    'GLOBAL_BOT_OWNER_ID':49145577,
    'base_bot_role':lambda gid,uid: 'مالک' if uid==222 else state['role'],
    'is_group_pro_active':lambda gid: state['pro'],
}
exec(fn('is_group_pro_active_for_actor'),ns2)
check=ns2['is_group_pro_active_for_actor']
assert check(10,49145577) is True
assert check(10,222) is True
assert check(10,333) is False
state['pro']=True
assert check(10,333) is True

# Both immediate and scheduled full cleanup must use the owner-aware entitlement helper.
for name in ('command_full_chat_cleanup','command_cleanup_schedule','execute_cleanup_schedule'):
    src=fn(name)
    assert 'is_group_pro_active_for_actor' in src, name

assert 'مالک بدون PRO' in SRC
print('CHECK ZIVO60.96.21 OWNER FULL-CLEANUP ACCESS: PASS')
print('  full-cleanup Persian aliases: PASS')
print('  global owner bypasses PRO: PASS')
print('  group/internal owner bypasses PRO: PASS')
print('  admin still requires PRO: PASS')
print('  immediate + scheduled full cleanup use owner-aware entitlement: PASS')
