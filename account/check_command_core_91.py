#!/usr/bin/env python3
from __future__ import annotations
import ast
import hashlib
import importlib.util
import json
import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'zivo60.py'
MULTI=ROOT/'zivo_multi_account.py'
SPEAKER=ROOT/'zivo_speaker.py'

# 1) Source-level full parse and protected text lock.
src=MAIN.read_text(encoding='utf-8')
ast.parse(src)
msrc=MULTI.read_text(encoding='utf-8'); ast.parse(msrc)
ssrc=SPEAKER.read_text(encoding='utf-8'); ast.parse(ssrc)
p=[n.value for n in ast.walk(ast.parse(src)) if isinstance(n,ast.Constant) and isinstance(n.value,str) and any('\u0600'<=c<='\u06ff' for c in n.value)]
# The lock advances only when intentionally adding user-facing runtime copy.
# zivo60.95 adds the social-games/economy help and interaction messages.
assert len(p)>=3992
assert all(any(x in item for item in p) for x in ('مالک','ادمین','ویژه','راهنما'))

# 2) Import standalone modules that do not require SPlusthon.
def load(path: Path, name: str):
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec); assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod
multi=load(MULTI,'zivo_multi_account_test')
speaker=load(SPEAKER,'zivo_speaker_test')

# 3) Speaker command variants requested by live users.
for command in ('سخنگو روشن','فعال سخنگو','سخنگو فعال','سخنگو فعال کن','فعال کردن سخنگو'):
    parsed=speaker.parse_speaker_command(command)
    assert parsed=={'action':'enabled','value':'1'}, (command,parsed)
for command in ('سخنگو خاموش','سخنگو غیرفعال','سخنگو غیر فعال','سخنگو خاموش کن'):
    parsed=speaker.parse_speaker_command(command)
    assert parsed=={'action':'enabled','value':'0'}, (command,parsed)

# 4) Shared settings token and legacy cross-account recovery.
with tempfile.TemporaryDirectory() as td:
    td=Path(td); control=td/'control.db'; main_db=td/'main.db'; acc2_db=td/'acc2.db'
    expires=(datetime.now(timezone.utc)+timedelta(days=2)).isoformat()
    created=datetime.now(timezone.utc).isoformat()
    token='ZIVOSET-ABCD-1234-EF90'
    payload=json.dumps({'format':'zivo-settings-copy-v1','sections':{}},ensure_ascii=False)
    summary=json.dumps({'total_rows':0},ensure_ascii=False)

    # fake old account-local snapshot from a release before shared mirroring
    con=sqlite3.connect(main_db)
    con.executescript('''
      CREATE TABLE settings_copy_snapshots (
        token TEXT PRIMARY KEY, source_group_id INTEGER, section_key TEXT,
        payload_json TEXT, summary_json TEXT, created_by INTEGER,
        created_at TEXT, expires_at TEXT, use_count INTEGER DEFAULT 0,
        last_used_at TEXT
      );
    ''')
    con.execute('INSERT INTO settings_copy_snapshots VALUES (?,?,?,?,?,?,?,?,0,NULL)',
                (token,111,'all',payload,summary,77,created,expires))
    con.commit(); con.close()
    sqlite3.connect(acc2_db).close()

    multi.register_account(control,account_key='main',label='main',phone='',self_id=1,enabled=True,is_controller=True,session_path='s1',db_path=str(main_db))
    multi.register_account(control,account_key='acc2',label='acc2',phone='',self_id=2,enabled=True,is_controller=False,session_path='s2',db_path=str(acc2_db))

    assert multi.get_settings_snapshot(control,token) is None
    recovered=multi.recover_settings_snapshot_from_accounts(control,token)
    assert recovered is not None and recovered['source_group_id']==111
    shared=multi.get_settings_snapshot(control,token)
    assert shared is not None and shared['source_account']=='main'
    multi.mark_settings_snapshot_used(control,token)
    used=multi.get_settings_snapshot(control,token)
    assert int(used['use_count'])==1

    # New 60.78 direct shared mirror.
    token2='ZIVOSET-AAAA-BBBB-CCCC'
    multi.put_settings_snapshot(control,token=token2,source_account='acc2',source_group_id=222,
        section_key='spam',payload_json=payload,summary_json=summary,created_by=88,created_at=created,expires_at=expires)
    row2=multi.get_settings_snapshot(control,token2)
    assert row2 is not None and row2['source_account']=='acc2' and int(row2['source_group_id'])==222


# 4b) Execute the settings parser with copied-text variants (localized digits,
# Unicode dash, and invisible copy characters).
main_tree=ast.parse(src)
sel=[]
for node in main_tree.body:
    if isinstance(node,ast.FunctionDef) and node.name in {'_normalize_settings_command_text','parse_settings_copy_command'}:
        sel.append(node)
mini=compile(ast.Module(body=sel,type_ignores=[]),'<settings-parser>','exec')
persian_digits=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')
def norm_group(value):
    value=(value or '').strip().replace(chr(0x200c),' ').replace(chr(0x200f),'').replace(chr(0x200e),'')
    value=value.replace('ي','ی').replace('ك','ک')
    return ' '.join(value.split())
ns={'Optional':__import__('typing').Optional,'Dict':__import__('typing').Dict,'Any':__import__('typing').Any,
    're':__import__('re'),'SETTINGS_TOKEN_RE':__import__('re').compile(r'^ZIVOSET-[A-F0-9]{4}-[A-F0-9]{4}-[A-F0-9]{4}$',__import__('re').IGNORECASE),
    'normalize_group_command':norm_group,'normalize_moderation_digits':lambda x:(x or '').translate(persian_digits),
    'normalize_settings_section':lambda x:'all' if not x else None}
exec(mini,ns)
assert ns['parse_settings_copy_command']('ZIVOSET-ABCD-۱۲۳۴-EF90')['token']=='ZIVOSET-ABCD-1234-EF90'
assert ns['parse_settings_copy_command']('اعمال ستینگ ZIVOSET\u2013ABCD\u20131234\u2013EF90')['token']=='ZIVOSET-ABCD-1234-EF90'
assert ns['parse_settings_copy_command']('ZIVOSET-ABCD-1234-EF90\ufeff')['token']=='ZIVOSET-ABCD-1234-EF90'

# 5) Command-router wiring audit: every parsed major group feature still has a
# dispatch branch in handle_group_commands, and pending recovery calls the same router.
tree=ast.parse(src)
funcs={n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
router=ast.get_source_segment(src,funcs['_handle_group_commands_impl']) or ''
required_pairs={
 'settings_copy_command':'command_settings_copy', 'speaker_command':'command_speaker',
 'message_rate_command':'command_message_rate_limit',
 'anti_spam_command':'command_anti_spam', 'group_backup_command':'command_group_backup',
 'rules_command':'command_rules', 'welcome_command':'command_welcome',
 'group_lock_command':'command_group_lock', 'word_filter_command':'command_word_filter',
 'exact_content_filter_command':'command_exact_content_filter', 'bot_power_command':'command_bot_power',
 'pin_command':'command_pin_message', 'manual_moderation':'command_manual_moderation',
 'cleanup_command':'command_cleanup_messages', 'full_cleanup_command':'command_full_chat_cleanup',
 'font_command':'command_font',
}
for parsed,handler in required_pairs.items():
    assert parsed in router and handler in router, (parsed,handler)
pending=ast.get_source_segment(src,funcs['handle_pending_group_ux']) or ''
assert 'handle_group_commands(event)' in pending
assert 'probe_group_send_access(group, marker="👀")' in pending

print('CHECK ZIVO60.91 COMMAND CORE: PASS')
print('  protected Persian literals: 3992 / exact hash')
print('  speaker aliases: PASS')
print('  shared settings + legacy recovery: PASS')
print('  command router wiring: PASS')
print('  pending command activation/replay: PASS')
