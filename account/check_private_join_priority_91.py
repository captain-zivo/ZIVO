#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import ast, hashlib, re
from pathlib import Path
from typing import Optional, Tuple

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
assert 'private-group-link=pre-rate-priority' in SRC

def fn_text(name: str) -> str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

# Keep the proven private receive/recovery infrastructure from 60.78/79 intact.
expected={
    '_schedule_private_group_link_install':'6eff840cba67e75e8a7fdcc8cca9fab77df135243c8b288070982f48546541a1',
    'process_private_inbound_tracked':'088d4da7fc803495bb2ee24f5c3915ca2c4b6a5a2783cd417558e21864a65c57',
    'private_known_contact_poll_worker':'7e97c6b2487fe5ea31b2136446f3e5157211ca1cc3252641d5fee41d24027f48',
    'private_inbox_watchdog':'57b80b75dc21f28c57911e2e601d1c335f2b66c800827bd3a8f563794f6fbd68',
    'private_startup_backfill_worker':'71409ab7299068c7b4f0a5623d615df5540572524875efc6ed2fed9f12c8aa12',
    'join_group_from_hash':'58f1c76bfd6243d1c92d962087d946cecd8df0eaecc3bf06e816ebe6e94c7101',
}
for name,digest in expected.items():
    got=hashlib.sha256(fn_text(name).encode()).hexdigest()
    assert got==digest,(name,got)

# Private live routing must return before any group-only message-rate/moderation work.
router=fn_text('_zivo_router_impl')
private_pos=router.index('if event_is_private_inbound')
private_return=router.index('            return', private_pos)
rate_pos=router.index('maybe_enforce_message_rate_limit')
assert private_pos < private_return < rate_pos

# Valid group links bypass the generic PM flood shield and enter the join lane first.
private=fn_text('process_private_inbound')
parse_pos=private.index('connection_target = parse_group_connection_target(text)')
schedule_pos=private.index('_schedule_private_group_link_install(', parse_pos)
shield_pos=private.index('if private_rate_limited(sender_id):')
assert parse_pos < schedule_pos < shield_pos
assert 'priority=private-install' in private

# Parser behavior for both supported group-link shapes.
GROUP_LINK_RE = re.compile(r'^(?:https?://)?(?:www\.)?(?:web\.)?splus\.ir/joingroup/([^/?#\s]+)(?:[/?#].*)?$', re.I)
PUBLIC_GROUP_LINK_RE = re.compile(r'^(?:https?://)?(?:www\.)?(?:web\.)?splus\.ir/(?:@)?([A-Za-z0-9_.]{3,64})(?:[/?#].*)?$', re.I)
PUBLIC_GROUP_USERNAME_RE = re.compile(r'^@([A-Za-z0-9_.]{3,64})$', re.I)
BOT_USERNAME='zivobot'
ns={'re':re,'Optional':Optional,'Tuple':Tuple,'GROUP_LINK_RE':GROUP_LINK_RE,
    'PUBLIC_GROUP_LINK_RE':PUBLIC_GROUP_LINK_RE,'PUBLIC_GROUP_USERNAME_RE':PUBLIC_GROUP_USERNAME_RE,
    'BOT_USERNAME':BOT_USERNAME}
for name in ('parse_group_invite','parse_public_group_username','parse_group_connection_target'):
    exec(fn_text(name),ns)
parse=ns['parse_group_connection_target']
assert parse('https://splus.ir/joingroup/AbCdEf123') == ('invite','AbCdEf123')
assert parse('https://splus.ir/MyGroup_123') == ('public','mygroup_123')
assert parse('https://example.com/not-a-group') is None

# Public/private join code still rejects broadcast channels after resolution.
for name in ('join_group_from_hash','install_from_invite','install_from_public_group'):
    body=fn_text(name)
    assert 'CHANNEL_LINK_NOT_ALLOWED' in body or 'broadcast' in body, name

# User-facing PM panel documents both routes instead of claiming private-only links.
panel=fn_text('private_welcome_text') + fn_text('ready_for_link_text')
assert 'joingroup' in panel and 'لینک عمومی' in panel

print('CHECK ZIVO60.91 PRIVATE JOIN PRIORITY: PASS')
print('  private live route before group guards: PASS')
print('  group link before PM flood shield: PASS')
print('  private+public group link parser: PASS')
print('  channel rejection contract: PASS')
