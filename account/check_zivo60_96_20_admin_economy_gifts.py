#!/usr/bin/env python3
from __future__ import annotations
import ast, os, sqlite3, tempfile, importlib.util
from pathlib import Path
from typing import Any, List, Tuple

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
SOCIAL=(ROOT/'zivo_social_games.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC)

assert any(f'VERSION = "zivo60.96.{v}"' in SRC for v in (20,21,22))
for token in (
    '🎁 اقتصاد و هدیه', 'z:gifts', 'z:gscope:user', 'z:gscope:group',
    'z:gscope:owners', 'z:gscope:groups', 'z:gscope:all', 'z:gconfirm',
    'telegram_gift_scope_user_ids', 'telegram_gift_preview_text',
): assert token in SRC, token
for token in (
    'UNLIMITED_MEOW_SENTINEL', 'social_unlimited_meow',
    'social_admin_gift_batches', 'social_admin_gift_items',
    'admin_gift_users', 'recent_admin_gifts', 'set_unlimited_meow',
): assert token in SOCIAL, token

os.environ['ZIVO_MULTI_ACCOUNT_DB']=str(Path(tempfile.mkdtemp())/'social.db')
spec=importlib.util.spec_from_file_location('social_9620', ROOT/'zivo_social_games.py')
mod=importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(mod)
mod.configure(Path(os.environ['ZIVO_MULTI_ACCOUNT_DB']), global_owner_id=49145577, bot_user_ids={49155489,49147566,49155452})
assert mod.is_unlimited_meow(49145577)
assert mod.balance(49145577)==mod.UNLIMITED_MEOW_SENTINEL
r=mod.admin_gift_users([1001,1002,1002,49155489,49145577], created_by=8609917300, scope='all', meow_amount=500, pet_spec='هاسکی')
assert r['targets']==3 and r['success']==3 and r['failed']==0, r
assert mod.balance(1001)==500 and mod.balance(49145577)==mod.UNLIMITED_MEOW_SENTINEL
r2=mod.admin_gift_users([1001], created_by=8609917300, scope='user', meow_amount=25, pet_spec='پرشین')
assert r2['partial']==1 and mod.balance(1001)==525, r2
r3=mod.admin_gift_users([1001], created_by=8609917300, scope='user', pet_spec='پرشین')
assert r3['skipped']==1, r3
assert len(mod.recent_admin_gifts(10))==3
assert '∞ میو' in mod.profile_section(49145577)

def fn(name:str)->str:
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ast.get_source_segment(SRC,node) or ''

td=Path(tempfile.mkdtemp())
main=td/'main.db'; acc2=td/'acc2.db'; shared=Path(os.environ['ZIVO_MULTI_ACCOUNT_DB'])
for path in (main,acc2):
    con=sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE installations(group_id INTEGER, owner_user_id INTEGER);
    CREATE TABLE stats_members(group_id INTEGER,user_id INTEGER,username TEXT,last_seen_at TEXT);
    CREATE TABLE bot_admins(group_id INTEGER,user_id INTEGER);
    CREATE TABLE bot_specials(group_id INTEGER,user_id INTEGER);
    CREATE TABLE private_contacts(user_id INTEGER);
    CREATE TABLE global_user_profiles(user_id INTEGER,username TEXT,last_seen_at TEXT);
    """)
    con.commit(); con.close()
con=sqlite3.connect(main)
con.executemany('INSERT INTO stats_members VALUES (?,?,?,?)',[(10,101,'u101','x'),(10,102,'u102','x'),(11,102,'u102','x')])
con.executemany('INSERT INTO installations VALUES (?,?)',[(10,900),(11,901)])
con.execute('INSERT INTO private_contacts VALUES (700)')
con.execute("INSERT INTO global_user_profiles VALUES (701,'known','x')")
con.commit(); con.close()
con=sqlite3.connect(acc2)
con.executemany('INSERT INTO stats_members VALUES (?,?,?,?)',[(10,102,'u102','x'),(10,103,'u103','x')])
con.execute('INSERT INTO installations VALUES (?,?)',(12,902)); con.commit(); con.close()

ns={
 'Path':Path,'List':List,'Tuple':Tuple,'Any':Any,'sqlite3':sqlite3,'DB_PATH':main,'MULTI_ACCOUNT_DB':shared,
 'SYSTEM_USER_IDS':{777000},'safe_int':lambda x:int(x) if x is not None else None,
 'normalize_moderation_digits':lambda x:str(x),
 'multi_account_rows':lambda:[{'db_path':str(main),'self_id':49155489},{'db_path':str(acc2),'self_id':49147566}],
}
for name in ('_telegram_gift_db_paths','_telegram_gift_query_ids','telegram_gift_resolve_user','telegram_gift_scope_user_ids'):
    exec(fn(name),ns)
assert ns['telegram_gift_scope_user_ids']('group','10')==[101,102,103,900]
assert ns['telegram_gift_scope_user_ids']('owners','')==[900,901,902]
groups=ns['telegram_gift_scope_user_ids']('groups','')
assert groups==[101,102,103,900,901,902], groups
all_users=ns['telegram_gift_scope_user_ids']('all','')
for expected in (101,102,103,700,701,900,901,902,1001,1002,49145577): assert expected in all_users, (expected,all_users)
assert ns['telegram_gift_resolve_user']('@known')==701

print('CHECK ZIVO60.96.20 ADMIN ECONOMY + GIFT CENTER: PASS')
print('  owner unlimited MIO wallet: PASS')
print('  single/group/owners/all-groups/all-users scopes: PASS')
print('  cross-account dedupe + bot-account exclusion: PASS')
print('  meow / pet / combo gift transactions: PASS')
print('  existing-pet skip without replacement: PASS')
print('  gift ledger/history persistence: PASS')
