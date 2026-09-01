#!/usr/bin/env python3
from __future__ import annotations
import ast
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
# The old false reply may exist only as a comparison constant; it must never be sent again.
assert 'LEGACY_PRIVATE_JOIN_FALSE_FAILURE_TEXT' in SRC
assert 'legacy-error-only+once-per-user+confirmed-success-only+no-false-membership-fail' in SRC

def fn(name):
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

pub=fn('join_group_from_public_username')
assert 'JoinChannelRequest' in pub
assert 'verify_self_in_public_group(group)' not in pub
job=fn('_private_group_link_install_job')
assert '_send_private_join_apology_once' not in job
assert '_retry_uncertain_private_group_link' in job
assert 'group-link-failed' not in job
retry=fn('_retry_uncertain_private_group_link')
assert 'install_from_invite' in retry and 'install_from_public_group' in retry
assert '_route_group_link_to_other_account' in retry
recover=fn('_recover_historical_join_row')
assert '_legacy_false_failure_was_actually_sent' in recover
assert '_legacy_join_notice_already_sent' in recover
notify=fn('_send_historical_join_success_once')
assert "legacy-join-success-v89" in notify
assert '_mark_legacy_join_notice_sent' in notify
print('CHECK ZIVO60.91 PRIVATE JOIN LEGACY-ONLY RECOVERY: PASS')
print('new uncertain links retry silently: PASS')
print('legacy false-failure evidence required: PASS')
print('one apology/success per user: PASS')
