#!/usr/bin/env python3
from __future__ import annotations
import ast, asyncio, re, unicodedata
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
assert 'filter-history=recent100+verified-delete+evasion-normalize' in SRC
assert 'forward-lock=fast+multi-signal+verified-retry' in SRC
assert 'message-rate=atomic-deadline+async-native' in SRC
assert 'ZIVO_CONTENT_FILTER_SCAN_LIMIT' in SRC

def fn(name):
    n=next(x for x in ast.walk(TREE) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name)
    return ''.join(LINES[n.lineno-1:n.end_lineno])

# recent-100 filter purge stays intact
word=fn('purge_word_filter_history'); exact=fn('purge_exact_content_history')
assert 'limit=100' in word and 'history[:100]' in word and 'delete_filter_message_ids_verified' in word
assert 'EXACT_CONTENT_PURGE_SCAN_LIMIT' in exact and 'delete_filter_message_ids_verified' in exact

# Conservative normalization still catches obfuscated bio-check variants, but no longer
# promotes unrelated advertising/member/relationship phrases into the filtered-message lock.
sel=[]
for n in TREE.body:
    if isinstance(n,ast.FunctionDef) and n.name in {'normalize_filter_abuse_text','lock_text_matches_builtin_filter_normalized','lock_text_matches_builtin_filter'}:
        sel.append(n)
mini=compile(ast.Module(body=sel,type_ignores=[]),'<filter-norm>','exec')
needles=(
  'بیوچک','بیوچیک','بیوچکر','چکبیو','بیوروچک','بیوموچک','بیوشوچک','بیوتوچک',
  'چکبیوگرافی','بیوگرافیچک','biocheck','biochek','biochecker','biochck','biocek','checkbio'
)
ns={
 'Tuple':Tuple,'List':List,'re':re,'unicodedata':unicodedata,
 '_FILTER_INVISIBLE_RE':re.compile(r'[\u200b-\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]'),
 '_FILTER_REPEAT_RE':re.compile(r'(.)\1{2,}',re.DOTALL),
 'FILTER_BUILTIN_COMPACT_NEEDLES':needles,
}
exec(mini,ns)
match=ns['lock_text_matches_builtin_filter']
for sample in (
    'ب.ی.و.....چ.ک',
    'ب\u200cی\u200bو   چــــک',
    'بیووووو چک',
    'ＢＩＯＣＨＥＣＫ',
    'چک بیو',
    'بیوشو چک',
):
    assert match(sample), sample
for sample in (
    'امروز درباره مدیریت گروه صحبت می‌کنیم',
    'بیا کانالم عضو شو',
    'ممبر واقعی @sample',
    'تبادل ممبر',
    'دوستیابی',
    'خرید و فروش اکانت',
):
    assert not match(sample), sample

# The built-in lexicon itself must remain bio-check scoped; broad moderation categories
# belong to their independent locks and manual word filter.
assign=next(n for n in TREE.body if ((isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='FILTER_BUILTIN_COMPACT_PATTERNS' for t in n.targets)) or (isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='FILTER_BUILTIN_COMPACT_PATTERNS')))
assign_src=ast.get_source_segment(SRC,assign) or ''
for token in ('ممبرواقعی','تبادلممبر','دوستیابی','خریدوفروشاکانت','joinmygroup','جوینکانال'):
    assert token not in assign_src, token
for token in ('بیوچک','چکبیو','biocheck','checkbio'):
    assert token in assign_src, token
auto=next(n for n in TREE.body if ((isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='LOCK_DEFAULT_AUTO_BAN' for t in n.targets)) or (isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id=='LOCK_DEFAULT_AUTO_BAN')))
auto_src=ast.get_source_segment(SRC,auto) or ''
assert '"پیام‌های فیلترشده": False' in auto_src
assert 'performance-hotpath=enabled-locks+enabled-lock-set-cache+command-gate+filter-single-normalize+filter-precomputed-matchers+warning-cache+warning-ceiling+lock-notice-coalesce+exact-filter-presence+zero-rpc-cleanup' in SRC

# Forward detection uses both low-level fwd_from and SPlusthon forward property.
node=next(n for n in TREE.body if isinstance(n,ast.FunctionDef) and n.name=='message_is_forwarded')
code=compile(ast.Module(body=[node],type_ignores=[]),'<forward>','exec'); ns2={}; exec(code,ns2)
class M: pass
m=M(); m.fwd_from=object(); assert ns2['message_is_forwarded'](m)
m2=M(); m2.forward=object(); assert ns2['message_is_forwarded'](m2)
m3=M(); assert not ns2['message_is_forwarded'](m3)

# Atomic rate source contract: deadline is reserved before awaits; violation uses fast delete;
# native restriction is detached so it cannot delay deletion/return.
rate=fn('maybe_enforce_message_rate_limit')
assert '_message_rate_next_allowed[key] = now + interval' in rate
assert rate.index('_message_rate_next_allowed[key] = now + interval') < rate.index('await delete_live_message_fast')
assert 'asyncio.create_task(' in rate and '_message_rate_native_lock_worker' in rate
assert 'send_group_text' not in rate
assert 'delete_live_message_fast' in fn('maybe_enforce_forward_lock_fast')

# Router order 96.14: recognized command -> rate -> forward -> anti-spam/flood. Commands must not be swallowed by inherited old-group rate limits.
router=fn('_zivo_router_impl')
pos_rate=router.index('maybe_enforce_message_rate_limit')
pos_fwd=router.index('maybe_enforce_forward_lock_fast')
pos_cmd=router.index('handle_group_commands')
pos_core=router.index('consume_group_anti_spam_event')
pos_flood=router.index('consume_group_flood_guard_event')
pos_touch=router.index('touch_installed_group_activity')
assert pos_cmd < pos_rate < pos_fwd < pos_flood < pos_core < pos_touch

print('CHECK ZIVO60.91 FILTER/FORWARD/RATE/SPAM FAST PATH: PASS')

# Forward deletion stays fast but verifies server-side removal asynchronously.
forward_fast=fn('maybe_enforce_forward_lock_fast')
assert 'verify=True' in forward_fast
assert '_verify_live_delete_worker' in SRC
assert 'live delete verified PASS' in SRC

# Broad aggressive families are intentionally excluded from the fixed filtered-message lexicon in 60.91.
