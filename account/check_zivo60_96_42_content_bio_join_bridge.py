#!/usr/bin/env python3
from __future__ import annotations
import ast, re, unicodedata
from pathlib import Path
from typing import List, Tuple

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC)
LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.96.42"' in SRC

def fn(name: str) -> str:
    n=next(x for x in ast.walk(TREE) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name)
    return ''.join(LINES[n.lineno-1:n.end_lineno])

# Exact content filter: one deterministic newest-100 snapshot, source reply is
# authoritative only if it is inside that snapshot, and deletion is verified.
exact=fn('purge_exact_content_history')
assert 'scan_limit = int(EXACT_CONTENT_PURGE_SCAN_LIMIT)' in exact
assert 'offset_id=0' in exact and 'limit=scan_limit' in exact
assert 'snapshot = list(history or [])[:scan_limit]' in exact
assert 'source_message_id' in exact and 'mid == int(source_message_id)' in exact
assert 'delete_filter_message_ids_verified' in exact
assert 'while scanned < EXACT_CONTENT_PURGE_SCAN_LIMIT' not in exact
command=fn('command_exact_content_filter')
assert 'source_message_id=int(source_message_id)' in command

# Official join gets transport priority before running the join RPC.
join_worker=fn('multi_account_join_worker')
assert 'global _last_priority_event_at' in join_worker
assert "_last_priority_event_at = time.monotonic()" in join_worker
assert 'priority=hot' in join_worker
assert join_worker.index('_last_priority_event_at = time.monotonic()') < join_worker.index('await run_multi_account_join_job')


# Mandatory Bio Guard cannot be bypassed by a legacy group having the generic
# filtered-message lock disabled; a matching bio family auto-enables it.
lock_src=fn('maybe_enforce_group_lock')
assert 'builtin_bio_match = lock_text_matches_builtin_filter' in lock_src
assert 'mandatory bio guard auto-enabled' in lock_src
assert 'set_group_lock_enabled(group_id, "پیام‌های فیلترشده", True, 0)' in lock_src

# Execute only the bio-guard normalization/matching subset.
needed_assigns={
    '_FILTER_INVISIBLE_RE','_FILTER_REPEAT_RE','FILTER_BUILTIN_COMPACT_PATTERNS',
    'BIO_GUARD_PERSIAN_BIO_ROOTS','BIO_GUARD_PERSIAN_ACTIONS',
    'BIO_GUARD_LATIN_BIO_ROOTS','BIO_GUARD_LATIN_ACTIONS',
    'FILTER_BUILTIN_COMPACT_NEEDLES',
}
body=[]
for n in TREE.body:
    name=None
    if isinstance(n,ast.Assign):
        for t in n.targets:
            if isinstance(t,ast.Name) and t.id in needed_assigns:
                name=t.id; break
    elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id in needed_assigns:
        name=n.target.id
    if name:
        body.append(n)
for n in TREE.body:
    if isinstance(n,ast.FunctionDef) and n.name in {
        'normalize_filter_abuse_text','lock_text_matches_builtin_filter_normalized','lock_text_matches_builtin_filter'
    }:
        body.append(n)
ns={'re':re,'unicodedata':unicodedata,'List':List,'Tuple':Tuple}
exec(compile(ast.Module(body=body,type_ignores=[]),'<bio-guard>','exec'),ns)
match=ns['lock_text_matches_builtin_filter']

blocked=(
    'بیو چک','چک بیو','ب.ی.و.....چ.ک','ب\u200cی\u200bو   چــــک','بیووووو چک',
    'بیوشو چک کن','چک کن بیوشو','بیو رو ببین','بایوشو نگاه کن','پروفایلشو چک کن',
    'چک پروفایل','بیوگرافی','بایوگرافی','بیوگرافی رو ببین','چک بیوگرافی',
    'BIO CHECK','b i o ... c h e c k','check bio','bio-checker','bi0 ch3ck','check biography',
    'biography','profile check','check-profile','view bio','look at bio',
)
for sample in blocked:
    assert match(sample), sample

clean=(
    'امروز درباره مدیریت گروه صحبت می‌کنیم',
    'فیلتر لینک فعال است',
    'این یک متن عادی فارسی است',
    'من کتاب زندگینامه یک دانشمند را خواندم',
    'profile settings updated',
    'check the server status',
    'bio',
    'بیو',
)
for sample in clean:
    assert not match(sample), sample

print('CHECK ZIVO60.96.42 CONTENT FILTER + BIO GUARD + JOIN PRIORITY: PASS')

# Behavioral newest-100 purge harness: exact match and replied source inside the
# snapshot are deleted; an older message beyond the returned 100 is untouched.
import asyncio
class Msg:
    def __init__(self, mid, fp, pinned=False):
        self.id=mid; self.fp=fp; self.pinned=pinned

purge_node=next(x for x in TREE.body if isinstance(x,ast.AsyncFunctionDef) and x.name=='purge_exact_content_history')
purge_ns={
    'Any':object,'Optional':__import__('typing').Optional,'Tuple':Tuple,'List':List,
    'EXACT_CONTENT_PURGE_SCAN_LIMIT':100,
    'safe_int':lambda x: int(x) if x is not None else None,
    'exact_content_descriptor':lambda m: {'fingerprint':m.fp} if m.fp else None,
    'exact_content_fingerprints_match':lambda a,b: a==b,
    'message_is_pinned':lambda m: bool(m.pinned),
    'increment_deleted_message_counter':lambda *a,**k: None,
}
class Log:
    def info(self,*a,**k): pass
    def warning(self,*a,**k): pass
purge_ns['log']=Log()
seen={}
async def fake_fetch(group, offset_id, limit):
    assert offset_id==0 and limit==100
    return group[:100]
async def fake_delete(group, ids):
    seen['ids']=list(ids)
    return len(ids),0
purge_ns['fetch_cleanup_history_page']=fake_fetch
purge_ns['delete_filter_message_ids_verified']=fake_delete
exec(compile(ast.Module(body=[purge_node],type_ignores=[]),'<purge-v42>','exec'),purge_ns)
history=[Msg(mid, 'target' if mid in {150,120} else 'other') for mid in range(200,100,-1)]
# 120 is within newest-100 and 90 would be outside because it isn't in snapshot.
scanned,deleted,failed,pinned=asyncio.run(purge_ns['purge_exact_content_history'](
    history, 1, 'target', source_message_id=120, exclude_message_ids=set()
))
assert scanned==100 and deleted==2 and failed==0
assert set(seen['ids'])=={150,120}

print('CHECK ZIVO60.96.42 NEWEST100 BEHAVIOR HARNESS: PASS')
