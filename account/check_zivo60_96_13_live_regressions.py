#!/usr/bin/env python3
from __future__ import annotations
import ast, asyncio, sqlite3, tempfile, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'zivo60.py'
SRC=MAIN.read_text(encoding='utf-8')
TREE=ast.parse(SRC)
assert 'VERSION = "zivo60.96.15"' in SRC


def node(name: str):
    return next(n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)

def fn_text(name: str) -> str:
    n=node(name); lines=SRC.splitlines(True); return ''.join(lines[n.lineno-1:n.end_lineno])

def exec_fns(ns: dict[str,Any], *names: str):
    mod=ast.Module(body=[node(n) for n in names], type_ignores=[]); ast.fix_missing_locations(mod)
    exec(compile(mod,str(MAIN),'exec'),ns); return ns

# 1) The origin wizard must run before rate/flood guards in group and PM paths.
group_router=fn_text('_zivo_router_impl')
assert group_router.index('origin_pending_hot') < group_router.index('maybe_enforce_message_rate_limit')
assert group_router.index('origin_pending_hot') < group_router.index('consume_group_anti_spam_event')
private_router=fn_text('process_private_inbound')
assert private_router.index('global_origin_registration_context_matches') < private_router.index('private_rate_limited')

# 2) Shared global identity really spans separate per-account DBs.
with tempfile.TemporaryDirectory() as td:
    td=Path(td); shared_path=td/'multi.db'; a_path=td/'a.db'; b_path=td/'b.db'
    def prep_local(path: Path, old_user: bool=False):
        c=sqlite3.connect(path)
        c.execute('''CREATE TABLE global_user_profiles(user_id INTEGER PRIMARY KEY, preferred_name TEXT NOT NULL DEFAULT '', nickname TEXT NOT NULL DEFAULT '', observed_name TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '', age INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        c.execute('''CREATE TABLE global_origin_registration(user_id INTEGER PRIMARY KEY, stage TEXT NOT NULL, preferred_name TEXT NOT NULL DEFAULT '', nickname TEXT NOT NULL DEFAULT '', age INTEGER NOT NULL DEFAULT 0, origin TEXT NOT NULL DEFAULT '', context_kind TEXT NOT NULL DEFAULT 'private', context_id INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL)''')
        if old_user:
            c.execute("INSERT INTO global_user_profiles VALUES(42,'قدیمی','لقب','','old',29,'یزدی','2020','2024','2024')")
        c.commit(); c.close()
    prep_local(a_path,True); prep_local(b_path,False)
    current=[a_path]
    def db_connect():
        c=sqlite3.connect(current[0]); c.row_factory=sqlite3.Row; return c
    def global_profile_db_connect():
        c=sqlite3.connect(shared_path); c.row_factory=sqlite3.Row; return c
    class Log:
        @staticmethod
        def warning(*a,**k): pass
    ns={'sqlite3':sqlite3,'datetime':datetime,'timezone':timezone,'db_connect':db_connect,
        'global_profile_db_connect':global_profile_db_connect,'log':Log(),'ACCOUNT_KEY':'test',
        'Any':Any,'Dict':Dict,'List':List,'Optional':Optional,'Tuple':Tuple,'time':time,'re':re,
        '_global_user_profile_hot':{},'_global_origin_registration_pending':{},
        'GLOBAL_PROFILE_CACHE_TTL_SECONDS':30.0,'GLOBAL_PROFILE_TEXT_MAX':64,
        'PERSIAN_ARABIC_TO_ASCII':str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')}
    exec_fns(ns,'init_shared_global_identity_store','safe_int','normalize_group_command','normalize_moderation_digits','_clean_global_profile_text','get_global_user_profile','_normalize_profile_age','global_origin_registration_context_matches','start_global_origin_registration','cancel_global_origin_registration','advance_global_origin_registration','global_origin_card_text')
    ns['init_shared_global_identity_store']()
    assert ns['get_global_user_profile'](42)['origin']=='یزدی'
    current[0]=b_path
    ns['init_shared_global_identity_store']()
    assert ns['get_global_user_profile'](42)['preferred_name']=='قدیمی'
    assert '1️⃣' in ns['start_global_origin_registration'](77,'group',900)
    assert ns['advance_global_origin_registration'](77,'کاربر تست','group',900)[1]
    msg,handled=ns['advance_global_origin_registration'](77,'ندارم','group',900); assert handled and '3️⃣' in msg
    assert ns['advance_global_origin_registration'](77,'۲۲','group',900)[1]
    done,handled=ns['advance_global_origin_registration'](77,'کرمانی','group',900); assert handled and 'اصل سراسری ثبت شد' in done
    current[0]=a_path; ns['_global_user_profile_hot'].clear()
    p=ns['get_global_user_profile'](77)
    assert p['preferred_name']=='کاربر تست' and p['nickname']=='' and int(p['age'])==22 and p['origin']=='کرمانی'

# 3) Bot-message cleanup is opt-in by default; explicit enable remains supported.
with tempfile.TemporaryDirectory() as td:
    dbp=Path(td)/'c.db'; c=sqlite3.connect(dbp)
    c.execute('''CREATE TABLE bot_message_cleanup_settings(group_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0, warning_seconds INTEGER NOT NULL DEFAULT 15, welcome_seconds INTEGER NOT NULL DEFAULT 45, general_seconds INTEGER NOT NULL DEFAULT 0, updated_by INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT '')'''); c.commit(); c.close()
    def cdb():
        x=sqlite3.connect(dbp); x.row_factory=sqlite3.Row; return x
    ns={'db_connect':cdb,'time':time,'datetime':datetime,'timezone':timezone,'Any':Any,'Dict':Dict,
        '_bot_message_cleanup_settings_hot_cache':{},'CLEANUP_SETTINGS_CACHE_TTL_SECONDS':300.0,
        'mark_group_backup_dirty':lambda *_:None}
    exec_fns(ns,'get_bot_message_cleanup_settings','upsert_bot_message_cleanup_settings')
    assert ns['get_bot_message_cleanup_settings'](1)['enabled'] is False
    assert ns['upsert_bot_message_cleanup_settings'](1,99,enabled=True)['enabled'] is True

# 4) Installed-group inactivity auto-leave is disabled by default, but capability remains opt-in.
ns={'GROUP_INACTIVITY_LEAVE_SECONDS':0,'datetime':datetime,'timezone':timezone,'timedelta':timedelta,
    'sqlite3':sqlite3,'List':List,'db_connect':lambda: (_ for _ in ()).throw(RuntimeError('DB_SHOULD_NOT_OPEN'))}
exec_fns(ns,'inactive_group_lifecycle_rows_due')
assert ns['inactive_group_lifecycle_rows_due']()==[]
assert 'ZIVO_INSTALLED_GROUP_AUTO_LEAVE_SECONDS", "0"' in SRC

# 5) Old groups that reject plain sends get one formatted fallback instead of router failure.
class PlainForbidden(Exception): pass
class DummyEntity:
    def __init__(self,offset:int,length:int): self.offset=offset; self.length=length
class DummyTypes: MessageEntityBlockquote=DummyEntity
class FakeSent: id=5
class FakeClient:
    def __init__(self): self.calls=[]
    async def send_message(self,*a,**k):
        self.calls.append(k)
        if len(self.calls)==1: raise PlainForbidden('You cannot send plain results in this chat')
        return FakeSent()
fc=FakeClient(); scheduled=[]
ns={'Any':Any,'Optional':Optional,'client':fc,'types':DummyTypes,'utf16_len':len,
    'active_group_command_reply_id':lambda x=None:x,'schedule_bot_message_cleanup':lambda g,m,c:scheduled.append((m.id,c)),
    'classify_bot_message_cleanup':lambda _:'general','log':type('L',(),{'info':staticmethod(lambda *a,**k:None)})()}
exec_fns(ns,'send_group_text')
asyncio.run(ns['send_group_text'](object(),'سلام'))
assert len(fc.calls)==2 and fc.calls[0]['formatting_entities']==[] and len(fc.calls[1]['formatting_entities'])==1
assert scheduled==[(5,'general')]

# 6) Plain-forbidden is a formatting restriction, not proof that the group is
# inaccessible.  The rich-text retry in section 5 must remain reachable and a
# healthy installation/claim must not be pruned.  Real no-write errors are still
# classified as inaccessible.
ns={}; exec_fns(ns,'_is_group_inaccessible_error')
assert not ns['_is_group_inaccessible_error'](PlainForbidden('You cannot send plain results in this chat'))
assert ns['_is_group_inaccessible_error'](RuntimeError('CHAT_WRITE_FORBIDDEN'))

# 7) Destructive schedules are disabled when their creator no longer has management authority.
with tempfile.TemporaryDirectory() as td:
    dbp=Path(td)/'sched.db'; c=sqlite3.connect(dbp)
    c.execute('CREATE TABLE cleanup_schedules(schedule_id INTEGER PRIMARY KEY, enabled INTEGER, next_run_at TEXT, last_result TEXT DEFAULT "", updated_at TEXT DEFAULT "")')
    c.execute("INSERT INTO cleanup_schedules VALUES(1,1,'2000','','')"); c.commit(); c.close()
    def sdb():
        x=sqlite3.connect(dbp); x.row_factory=sqlite3.Row; return x
    ns={'sqlite3':sqlite3,'asyncio':asyncio,'datetime':datetime,'timezone':timezone,'timedelta':timedelta,'time':time,
        'List':List,'db_connect':sdb,'get_installation':lambda _:{'group_id':1},'is_group_bot_enabled':lambda _:True,
        'base_bot_role':lambda *_:'کاربر','group_cleanup_is_active':lambda _:False,'is_group_pro_active_for_actor':lambda *_:True,
        '_group_cleanup_active':{},'_group_send_probe_retry_after':{},'_is_group_inaccessible_error':lambda _:False}
    exec_fns(ns,'execute_cleanup_schedule')
    asyncio.run(ns['execute_cleanup_schedule']({'schedule_id':1,'group_id':1,'cleanup_count':100,'created_by':55}))
    with sdb() as c:
        r=c.execute('SELECT enabled,last_result FROM cleanup_schedules WHERE schedule_id=1').fetchone()
    assert int(r['enabled'])==0 and r['last_result']=='CREATOR_NOT_AUTHORIZED_DISABLED'

# 8) Source-level stale-job pressure guards remain wired.
worker=fn_text('bot_message_cleanup_worker')
assert 'bot message auto-delete stale job dropped' in worker
assert '_is_group_inaccessible_error(exc)' in worker
schedule=fn_text('execute_cleanup_schedule')
assert 'GROUP_INACCESSIBLE_DISABLED' in schedule and 'CREATOR_NOT_AUTHORIZED_DISABLED' in schedule

print('CHECK ZIVO60.96.13 LIVE BUG REGRESSIONS: PASS')
print('  origin conversation priority + ندارم continuation: PASS')
print('  shared identity across separate account DBs: PASS')
print('  bot-message cleanup default opt-in: PASS')
print('  installed-group inactivity auto-leave default disabled: PASS')
print('  old-group plain-send formatted fallback: PASS')
print('  plain-send restriction does not prune a healthy group: PASS')
print('  destructive stale schedule authorization guard: PASS')
