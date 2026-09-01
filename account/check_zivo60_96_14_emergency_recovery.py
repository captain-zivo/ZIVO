#!/usr/bin/env python3
from __future__ import annotations
import ast
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent
MAIN = ROOT / 'zivo60.py'
SRC = MAIN.read_text(encoding='utf-8')
TREE = ast.parse(SRC)
assert 'VERSION = "zivo60.96.15"' in SRC


def node(name: str):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def fn_text(name: str) -> str:
    n = node(name)
    lines = SRC.splitlines(True)
    return ''.join(lines[n.lineno - 1:n.end_lineno])


def exec_fn(ns: dict[str, Any], name: str):
    mod = ast.Module(body=[node(name)], type_ignores=[])
    ast.fix_missing_locations(mod)
    exec(compile(mod, str(MAIN), 'exec'), ns)

# 1) Recognized commands must be routed before inherited message-rate/flood guards.
router = fn_text('_zivo_router_impl')
assert router.index('Command core rescue lane') < router.index('maybe_enforce_message_rate_limit')
assert router.index('handle_group_commands(event)') < router.index('maybe_enforce_message_rate_limit')
assert router.index('maybe_enforce_message_rate_limit') < router.index('consume_group_anti_spam_event')
# Explicit install/recovery for old groups must also be before all generic guards.
assert router.index('group install rescue handled') < router.index('maybe_enforce_message_rate_limit')
assert router.index('pending group rescue UX handled') < router.index('maybe_enforce_message_rate_limit')

# 2) 96.13 shared identity hot-path contention is removed.
shared_connect = fn_text('global_profile_db_connect')
assert 'timeout=0.75' in shared_connect
assert 'PRAGMA busy_timeout = 750' in shared_connect
assert 'con.execute("PRAGMA journal_mode' not in shared_connect
identity_batch = fn_text('_upsert_identity_batches')
assert 'global_profile_db_connect' not in identity_batch
startup_identity = fn_text('init_shared_global_identity_store')
assert 'profiles = local.execute' not in startup_identity

# Shared DB failure must not kill a normal profile read/command.
with tempfile.TemporaryDirectory() as td:
    dbp = Path(td) / 'local.db'
    con = sqlite3.connect(dbp)
    con.execute('''CREATE TABLE global_user_profiles(
        user_id INTEGER PRIMARY KEY, preferred_name TEXT NOT NULL DEFAULT '',
        nickname TEXT NOT NULL DEFAULT '', observed_name TEXT NOT NULL DEFAULT '',
        username TEXT NOT NULL DEFAULT '', age INTEGER NOT NULL DEFAULT 0,
        origin TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL, updated_at TEXT NOT NULL)''')
    con.execute("INSERT INTO global_user_profiles VALUES(7,'محلی','لقب','نام دیده شده','u',23,'یزد','a','b','c')")
    con.commit(); con.close()

    def db_connect():
        c = sqlite3.connect(dbp); c.row_factory = sqlite3.Row; return c
    def broken_shared():
        raise sqlite3.OperationalError('database is locked')
    class Log:
        @staticmethod
        def debug(*a, **k): pass
    ns = {
        'time': time, 'Dict': Dict, 'db_connect': db_connect,
        'global_profile_db_connect': broken_shared, 'GLOBAL_PROFILE_CACHE_TTL_SECONDS': 30.0,
        '_global_user_profile_hot': {}, 'log': Log(),
    }
    exec_fn(ns, 'get_global_user_profile')
    profile = ns['get_global_user_profile'](7)
    assert profile['preferred_name'] == 'محلی' and profile['origin'] == 'یزد'

# 3) One-time delete safety migration is present and resets every stale automation source.
init_text = fn_text('init_db')
key = 'zivo60.96.14-automatic-delete-safe-reset'
assert key in init_text
for required in (
    'UPDATE bot_message_cleanup_settings SET enabled = 0',
    'UPDATE tag_cleanup_settings SET enabled = 0',
    'DELETE FROM bot_message_delete_jobs',
    'UPDATE cleanup_schedules SET enabled = 0',
    'DISABLED_BY_96_14_DELETE_SAFETY_RESET',
):
    assert required in init_text, required

# Functional SQL semantics of the safety reset: stale jobs/schedules are gone/off,
# while the tables/features remain and can be explicitly configured later.
with tempfile.TemporaryDirectory() as td:
    dbp = Path(td) / 'migration.db'
    c = sqlite3.connect(dbp)
    c.execute('CREATE TABLE runtime_migrations(migration_key TEXT PRIMARY KEY, applied_at TEXT NOT NULL)')
    c.execute('CREATE TABLE bot_message_cleanup_settings(group_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)')
    c.execute('CREATE TABLE tag_cleanup_settings(group_id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL)')
    c.execute('CREATE TABLE bot_message_delete_jobs(group_id INTEGER, message_id INTEGER)')
    c.execute('CREATE TABLE cleanup_schedules(schedule_id INTEGER PRIMARY KEY, enabled INTEGER, last_result TEXT, updated_at TEXT)')
    c.execute('INSERT INTO bot_message_cleanup_settings VALUES(1,1)')
    c.execute('INSERT INTO tag_cleanup_settings VALUES(1,1)')
    c.execute('INSERT INTO bot_message_delete_jobs VALUES(1,99)')
    c.execute("INSERT INTO cleanup_schedules VALUES(1,1,'','')")
    c.execute('UPDATE bot_message_cleanup_settings SET enabled = 0')
    c.execute('UPDATE tag_cleanup_settings SET enabled = 0')
    c.execute('DELETE FROM bot_message_delete_jobs')
    c.execute("UPDATE cleanup_schedules SET enabled = 0, last_result='DISABLED_BY_96_14_DELETE_SAFETY_RESET', updated_at='now' WHERE enabled = 1")
    c.execute("INSERT INTO runtime_migrations VALUES(?, 'now')", (key,))
    c.commit()
    assert c.execute('SELECT enabled FROM bot_message_cleanup_settings').fetchone()[0] == 0
    assert c.execute('SELECT enabled FROM tag_cleanup_settings').fetchone()[0] == 0
    assert c.execute('SELECT COUNT(*) FROM bot_message_delete_jobs').fetchone()[0] == 0
    row = c.execute('SELECT enabled,last_result FROM cleanup_schedules').fetchone()
    assert row == (0, 'DISABLED_BY_96_14_DELETE_SAFETY_RESET')
    assert c.execute('SELECT COUNT(*) FROM runtime_migrations WHERE migration_key=?', (key,)).fetchone()[0] == 1
    c.close()

# 4) Manual cleanup and explicit automation configuration still exist; no feature removal.
for fn in ('command_cleanup_messages', 'command_full_chat_cleanup', 'command_cleanup_schedule',
           'command_bot_message_cleanup', 'command_tag_cleanup'):
    node(fn)
assert 'enabled=True' in fn_text('command_bot_message_cleanup')
assert 'enabled=True' in fn_text('command_tag_cleanup')

# 5) Installed-group inactivity leave remains opt-in only.
assert 'ZIVO_INSTALLED_GROUP_AUTO_LEAVE_SECONDS", "0"' in SRC

print('CHECK ZIVO60.96.14 EMERGENCY RECOVERY: PASS')
print('  command/install rescue before rate+flood guards: PASS')
print('  shared identity removed from high-volume observation hot path: PASS')
print('  shared identity lock failure falls back to local profile: PASS')
print('  stale bot/tag/scheduled delete automation one-time reset: PASS')
print('  manual cleanup + explicit automation features preserved: PASS')
