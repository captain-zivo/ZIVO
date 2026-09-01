from pathlib import Path
import ast

SRC = Path(__file__).with_name('zivo60.py').read_text(encoding='utf-8')
TREE = ast.parse(SRC)
LINES = SRC.splitlines(True)

assert 'VERSION = "zivo60.93"' in SRC
assert 'CREATE TABLE IF NOT EXISTS private_join_legacy_probe_v91' in SRC
assert 'GROUP_LOCK_NOTICE_INTERVAL_SECONDS' in SRC
assert 'GROUP_LOCK_LOG_INTERVAL_SECONDS' in SRC
assert 'ban-tools=direct-unban+list-cleanup+bulk-release+retry-backoff' in SRC
assert 'warning-ceiling+lock-notice-coalesce' in SRC
assert 'legacy-error-recovery=hot-peer+durable-evidence+once-per-user' in SRC

def fn(name):
    node = next(n for n in ast.walk(TREE) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

bounded = fn('increment_manual_warning_bounded')
assert 'warning_total < ?' in bounded
assert 'if current >= ceiling' in bounded
assert '_manual_warning_count_hot_cache' in bounded

punish = fn('apply_group_lock_punishment')
assert 'increment_manual_warning_bounded' in punish
assert 'increment_manual_warning(' not in punish

lock_route = fn('maybe_enforce_group_lock')
assert 'should_send_group_lock_notice' in lock_route
assert 'should_log_group_lock_enforced' in lock_route
assert 'delete_locked_message' in lock_route

recover = fn('_recover_historical_join_row')
assert '_private_peer_cache.get' in recover
assert 'target = await resolve_private_target(None' not in recover
assert 'access_hash' in recover

evidence = fn('_legacy_false_failure_was_actually_sent')
assert '_legacy_join_probe_status' in evidence
assert '_mark_legacy_join_probe' in evidence
assert 'checked_no_match' in evidence
assert 'unavailable' in evidence

release_worker = fn('process_pending_ban_release_notices')
assert 'touch_ban_release_retry(group_id, user_id, 1800)' in release_worker
assert 'retry_delay = 300' in release_worker

moderation = fn('apply_manual_banned_rights')
assert 'CHANNELPRIVATE' in moderation
assert 'YOU LACK PERMISSION' in moderation

print('CHECK ZIVO60.91 RUNTIME LOG HYGIENE: PASS')
