from pathlib import Path
import ast
SRC = Path(__file__).with_name('zivo60.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC); LINES=SRC.splitlines(True)
assert 'VERSION = "zivo60.93"' in SRC
assert 'CREATE TABLE IF NOT EXISTS private_join_legacy_notice_v89' in SRC
assert 'LEGACY_PRIVATE_JOIN_FALSE_FAILURE_TEXT' in SRC
assert 'legacy-join-success-v89' in SRC
assert 'legacy-error-recovery=hot-peer+durable-evidence+once-per-user' in SRC

def fn(name):
    node=next(n for n in ast.walk(TREE) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ''.join(LINES[node.lineno-1:node.end_lineno])

evidence=fn('_legacy_false_failure_was_actually_sent')
assert 'client.get_messages' in evidence
assert '_legacy_join_error_text_matches' in evidence
assert '_legacy_join_probe_status' in evidence
assert '_mark_legacy_join_probe' in evidence
assert 'outgoing' in evidence
recover=fn('_recover_historical_join_row')
assert '_private_peer_cache.get' in recover
assert 'target = await resolve_private_target(None' not in recover
assert 'if not await _legacy_false_failure_was_actually_sent' in recover
notify=fn('_send_historical_join_success_once')
assert '_legacy_join_notice_already_sent' in notify
assert '_mark_legacy_join_notice_sent' in notify
worker=fn('historical_failed_join_recovery_worker')
assert 'multi_historical_unfinished_join_requests' in worker
print('CHECK ZIVO60.91 LEGACY FALSE-FAILURE RECOVERY: PASS')
