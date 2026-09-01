#!/usr/bin/env python3
from __future__ import annotations
import ast, asyncio, sqlite3, tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

ROOT=Path(__file__).resolve().parent
MAIN=ROOT/'zivo60.py'
SRC=MAIN.read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.96.36"' in SRC

def node(name):
    return next(n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
def fn(name):
    n=node(name); return ''.join(LINES[n.lineno-1:n.end_lineno])
def exec_fn(ns,name):
    mod=ast.Module(body=[node(name)],type_ignores=[]); ast.fix_missing_locations(mod)
    exec(compile(mod,str(MAIN),'exec'),ns)

class FakeLog:
    def info(self,*a,**k): pass
    def debug(self,*a,**k): pass
    def warning(self,*a,**k): pass
    def exception(self,*a,**k): pass

# 1. Multi-shape join detector including direct raw MessageService.
class PeerChannel:
    def __init__(self, channel_id): self.channel_id=channel_id
class PeerChat:
    def __init__(self, chat_id): self.chat_id=chat_id
class PeerUser:
    def __init__(self, user_id): self.user_id=user_id
class MessageActionChatAddUser:
    def __init__(self, users): self.users=users
class StrangeJoinAction:
    joined=True
    def __init__(self, member_id): self.member_id=member_id

raw_types=SimpleNamespace(PeerChannel=PeerChannel,PeerChat=PeerChat)
join_ns={
    'Any':Any,'List':List,'Tuple':Tuple,'Optional':Optional,'SimpleNamespace':SimpleNamespace,
    'safe_int':lambda v:int(v) if v is not None else None,
    'SELF_USER_ID':9999,'SYSTEM_USER_IDS':set(),'types':raw_types,
    'multi_list_accounts':lambda db:[{'self_id':8888},{'self_id':7777}], 'MULTI_ACCOUNT_DB':'x',
}
for name in ('_join_object_graph','_action_join_signature','_joined_user_ids_from_event','_service_message_group_id','raw_group_join_payloads'):
    exec_fn(join_ns,name)

raw_message=SimpleNamespace(id=55,peer_id=PeerChannel(777),from_id=SimpleNamespace(user_id=456),action=MessageActionChatAddUser([123]),message='')
# Direct message object (old code missed this shape).
payloads=join_ns['raw_group_join_payloads'](raw_message)
assert len(payloads)==1 and payloads[0][0]==777 and payloads[0][1] is raw_message, payloads
# Deep wrapper.
wrapped=SimpleNamespace(original_update=SimpleNamespace(payload=SimpleNamespace(message_update=raw_message)))
payloads=join_ns['raw_group_join_payloads'](wrapped)
assert len(payloads)==1 and payloads[0][0]==777, payloads
# Generic Soroush-style action with explicit joined flag/member_id.
weird=SimpleNamespace(message=SimpleNamespace(id=56,peer_id=PeerChat(778),from_id=SimpleNamespace(user_id=321),action=StrangeJoinAction(222)))
assert join_ns['_joined_user_ids_from_event'](weird)==[222]
# All ZIVO sibling accounts are excluded from welcome.
bot_join=SimpleNamespace(message=SimpleNamespace(id=57,peer_id=PeerChat(778),from_id=SimpleNamespace(user_id=321),action=MessageActionChatAddUser([8888,123])))
assert join_ns['_joined_user_ids_from_event'](bot_join)==[123]

# 2. Router must probe join shape without requiring message.action directly.
router=fn('_zivo_router_impl')
pos=router.index('await maybe_handle_group_join_welcome(event)')
window=router[max(0,pos-500):pos+120]
assert 'getattr(message_obj, "action", None) is not None' not in window
assert pos < router.index('await maybe_enforce_message_rate_limit')

# 3. get_chat failure must not kill private-group welcome; public ref must disable reply-to-service.
class FailingEvent:
    is_private=False
    sender_id=456
    id=91
    chat_id=700
    input_chat='INPUT-GROUP'
    message=SimpleNamespace(id=91,peer_id=PeerChat(700),action=MessageActionChatAddUser([123]),from_id=SimpleNamespace(user_id=456))
    async def get_chat(self): raise RuntimeError('NO_ENTITY')

calls=[]; marked=[]; joins=[]
async def resolve(event,group,gid,uid):
    return {'name':'عضو جدید','username':'newuser','bio':'bio','id':uid,'access_hash':0}
async def send_welcome(group,text,service_message_id,profile,reply_to_service=True):
    calls.append((group,text,service_message_id,reply_to_service)); return SimpleNamespace(id=900)
async def speaker(*a,**k): return None
async def rules(*a,**k): return None

def run_handler(invite_hash):
    calls.clear(); marked.clear(); joins.clear()
    install={'group_id':700,'group_title':'گپ تست','invite_hash':invite_hash}
    ns={
        'Any':Any,'Optional':Optional,'Dict':Dict,'Tuple':Tuple,'asyncio':asyncio,
        'datetime':datetime,'IRAN_TZ':timezone.utc,'jalali_parts':lambda dt:(1405,6,8),
        'safe_int':lambda v:int(v) if v is not None else None,
        'canonical_anti_spam_group_id':lambda v:int(v) if v is not None else None,
        '_service_message_group_id':lambda m:700,
        '_joined_user_ids_from_event':lambda e:[123],
        'get_installation':lambda gid:install,'recover_legacy_group_installation':lambda gid:(False,'',0),
        'is_group_bot_enabled':lambda gid:True,
        'reconcile_welcome_settings_from_accounts':lambda gid:{'enabled':True,'custom_text':'سلام {نام}','gif_local_path':'','gif_source_message_id':0},
        '_welcome_event_already_sent':lambda *a:False,
        '_resolve_welcome_profile':resolve,'record_welcome_join':lambda *a:joins.append(a),
        'render_welcome_text':lambda template,values:template.replace('{نام}',values['name']),
        '_send_welcome_text_reply':send_welcome,'get_group_rules_settings':lambda gid:{'rules_text':'','show_in_welcome':False},
        'send_rules_message':rules,'maybe_speaker_join':speaker,
        '_mark_welcome_event_sent':lambda *a:marked.append(a),'_send_welcome_gif':None,
        '_welcome_public_group':lambda group,installation:str(installation.get('invite_hash','')).startswith('public:'),
        'log':FakeLog(),
    }
    exec_fn(ns,'maybe_handle_group_join_welcome')
    assert asyncio.run(ns['maybe_handle_group_join_welcome'](FailingEvent())) is True
    assert joins and marked and calls
    return calls[-1]

private_call=run_handler('privatehash')
assert private_call[3] is True, private_call
public_call=run_handler('public:mygroup')
assert public_call[3] is False, public_call

# 4. Failed welcome send is not marked as delivered, allowing raw retry.
async def fail_send(*a,**k): raise RuntimeError('WRITE_FAIL')
marked2=[]
ns2={
    'Any':Any,'Optional':Optional,'Dict':Dict,'Tuple':Tuple,'asyncio':asyncio,
    'datetime':datetime,'IRAN_TZ':timezone.utc,'jalali_parts':lambda dt:(1405,6,8),
    'safe_int':lambda v:int(v) if v is not None else None,'canonical_anti_spam_group_id':lambda v:int(v),
    '_service_message_group_id':lambda m:700,'_joined_user_ids_from_event':lambda e:[123],
    'get_installation':lambda gid:{'group_id':700,'group_title':'x','invite_hash':''},
    'recover_legacy_group_installation':lambda gid:(False,'',0),'is_group_bot_enabled':lambda gid:True,
    'reconcile_welcome_settings_from_accounts':lambda gid:{'enabled':True,'custom_text':'سلام','gif_local_path':'','gif_source_message_id':0},
    '_welcome_event_already_sent':lambda *a:False,'_resolve_welcome_profile':resolve,'record_welcome_join':lambda *a:None,
    'render_welcome_text':lambda t,v:t,'_send_welcome_text_reply':fail_send,
    'get_group_rules_settings':lambda gid:{'rules_text':'','show_in_welcome':False},'send_rules_message':rules,
    'maybe_speaker_join':speaker,'_mark_welcome_event_sent':lambda *a:marked2.append(a),
    '_welcome_public_group':lambda *a:False,'log':FakeLog(),
}
exec_fn(ns2,'maybe_handle_group_join_welcome')
assert asyncio.run(ns2['maybe_handle_group_join_welcome'](FailingEvent())) is True
assert marked2==[]

# 5. Newest cross-account welcome config is reconciled (avoids local default-off drift).
with tempfile.TemporaryDirectory(prefix='zivo96_36_welcome_') as td:
    td=Path(td); local=td/'main.db'; remote=td/'acc2.db'
    schema='''CREATE TABLE welcome_settings(group_id INTEGER PRIMARY KEY, enabled INTEGER, custom_text TEXT, gif_source_message_id INTEGER, gif_local_path TEXT, gif_fingerprint TEXT, updated_by INTEGER, updated_at TEXT)'''
    for db in (local,remote):
        with sqlite3.connect(db) as c: c.execute(schema); c.commit()
    with sqlite3.connect(local) as c:
        c.execute("INSERT INTO welcome_settings VALUES(700,0,'',0,'','',1,'2026-08-20T00:00:00+00:00')"); c.commit()
    with sqlite3.connect(remote) as c:
        c.execute("INSERT INTO welcome_settings VALUES(700,1,'سلام جدید',0,'','',2,'2026-08-29T00:00:00+00:00')"); c.commit()
    def db_connect():
        c=sqlite3.connect(local); c.row_factory=sqlite3.Row; return c
    def get_settings(gid):
        with db_connect() as c: r=c.execute('SELECT * FROM welcome_settings WHERE group_id=?',(gid,)).fetchone()
        return {'enabled':bool(r['enabled']),'custom_text':r['custom_text'],'gif_source_message_id':r['gif_source_message_id'],'gif_local_path':r['gif_local_path'],'gif_fingerprint':r['gif_fingerprint']}
    def copy_state(gid,path):
        src=sqlite3.connect(path); src.row_factory=sqlite3.Row
        r=src.execute('SELECT * FROM welcome_settings WHERE group_id=?',(gid,)).fetchone(); src.close()
        with db_connect() as dst:
            dst.execute('INSERT OR REPLACE INTO welcome_settings VALUES(?,?,?,?,?,?,?,?)',tuple(r)); dst.commit()
        return 1
    rns={'Any':Any,'Dict':Dict,'Optional':Optional,'Tuple':Tuple,'Path':Path,'sqlite3':sqlite3,
         'DB_PATH':local,'ACCOUNT_KEY':'main','_legacy_iso_epoch':lambda v:datetime.fromisoformat(v).timestamp() if v else 0.0,
         '_legacy_group_account_sources':lambda gid:[('main',str(local)),('acc2',str(remote))],
         '_copy_legacy_group_state_from_db':copy_state,'get_welcome_settings':get_settings,'log':FakeLog()}
    exec_fn(rns,'_welcome_state_from_db'); exec_fn(rns,'reconcile_welcome_settings_from_accounts')
    out=rns['reconcile_welcome_settings_from_accounts'](700)
    assert out['enabled'] is True and out['custom_text']=='سلام جدید', out

# 6. User-facing diagnostic command/help is wired.
assert '"تست خوشامد": {"action": "test_welcome"}' in fn('parse_welcome_command')
assert 'action == "test_welcome"' in fn('command_welcome')
assert '("تست خوشامد", "همان مسیر واقعی ارسال متن/گیف خوشامد را همین حالا برای مدیر تست می‌کند.")' in SRC

print('CHECK ZIVO60.96.36 WELCOME END-TO-END RECOVERY: PASS')
print('  direct raw MessageService + deep wrappers: PASS')
print('  generic join action shapes + sibling bot exclusion: PASS')
print('  router pre-rate join probe without direct action gate: PASS')
print('  get_chat failure fallback + private/public delivery: PASS')
print('  failed send remains retryable: PASS')
print('  cross-account newest welcome settings reconciliation: PASS')
print('  test welcome command/help wiring: PASS')
