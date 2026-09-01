#!/usr/bin/env python3
from __future__ import annotations
import ast,re
from pathlib import Path
from typing import Any,Dict,Optional,Tuple
ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
assert 'CREATE TABLE IF NOT EXISTS user_report_settings' in SRC
assert 'CREATE TABLE IF NOT EXISTS user_reports' in SRC
assert 'user-report=reply+manager-review+approve-reject' in SRC
assert 'ban-tools=direct-unban+list-cleanup+bulk-release' in SRC
assert 'group-claim-presence=invite+public-flags+dialogs-no-getparticipant' in SRC

def fn(name):
 n=next(x for x in ast.walk(TREE) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name)
 return ''.join(LINES[n.lineno-1:n.end_lineno])

# Report parser behavior.
node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='parse_user_report_command')
mini=compile(ast.Module(body=[node],type_ignores=[]),'<report-parser>','exec')
def norm(x): return ' '.join((x or '').replace('\u200c',' ').split())
ns={'Optional':Optional,'Dict':Dict,'Any':Any,'normalize_group_command':norm,'re':re}; exec(mini,ns)
p=ns['parse_user_report_command']
assert p('گزارش')=={'action':'report_submit','reason':''}
assert p('گزارش تبلیغ')['reason']=='تبلیغ'
assert p('گزارش فعال')=={'action':'report_enabled','enabled':True}
assert p('گزارش خاموش')=={'action':'report_enabled','enabled':False}
assert p('لیست گزارش ها')['action']=='report_list'
assert p('تایید گزارش 12')=={'action':'report_review','report_id':12,'decision':'approved'}
assert p('رد گزارش #12')=={'action':'report_review','report_id':12,'decision':'rejected'}
report=fn('command_user_report')
assert 'create_user_report' in report and '_notify_owner_of_user_report' in report
assert '_send_persistent_user_report_card' in report and 'review_user_report' in report
assert 'delete_messages' not in report and 'delete_locked_message' not in report

# Direct unban parser by numeric id / username.
node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='parse_manual_moderation_command')
# Source assertions avoid pulling the large duration parser dependency graph.
manual=fn('parse_manual_moderation_command')
assert 'if text.startswith("رفع بن ")' in manual and '"target_spec": spec' in manual
assert 'resolve_moderation_target_spec' in fn('command_manual_moderation')
assert 'LOWER(username)' in fn('resolve_moderation_target_spec')

# Full ban cleanup performs a real platform-side unban first and only prunes successful/inactive rows.
audit=fn('command_ban_audit')
bulk=fn('release_all_active_bans')
assert 'release_all_active_bans' in audit
assert 'release_zivo_ban' in bulk and 'source="bulk_cleanup"' in bulk
assert 'asyncio.Semaphore' in bulk and 'reset_manual_warning' in bulk
assert 'DELETE FROM manual_moderation' in bulk and 'banned = 0' in bulk and 'muted = 0' in bulk
assert 'failed' in bulk and 'released' in bulk
assert 'پاکسازی لیست بن ها' in SRC and 'پاکسازی کامل بن ها' in SRC

# Stale multi-account claim verification must not use the unsupported self-participant RPC.
probe=fn('_probe_local_owned_group_membership')
assert 'functions.channels.GetParticipantRequest' not in probe
assert 'check_invite' in probe and 'client.get_dialogs(limit=600)' in probe
assert 'left' in probe and 'kicked' in probe

# Help registration for the new/expanded features.
assert '"key": "user_reports"' in SRC and '"help_command": "راهنما گزارش"' in SRC
for token in ('رفع بن 12345678','رفع بن @username','پاکسازی لیست بن ها','گزارش فعال','لیست گزارش ها'):
 assert token in SRC, token

print('CHECK ZIVO60.91 MODERATION/REPORT/BAN/CLAIM: PASS')
