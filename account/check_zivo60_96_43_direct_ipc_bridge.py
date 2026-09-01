from pathlib import Path
import ast
p=Path(__file__).with_name("zivo60.py")
s=p.read_text(encoding="utf-8")
assert 'VERSION = "zivo60.96.43"' in s
for token in (
    'async def start_account_ipc_server()',
    'async def _account_ipc_dispatch(',
    '"op" == "join"',
    'source_account="official_socket"',
    'multi_create_remote_control_job(',
    'official socket join result',
    'official socket control result',
    'full private/dialog inventory disabled',
    'CHAT_WRITE_FORBIDDEN_BACKOFF',
):
    if token == '"op" == "join"':
        # Source uses variable comparison form.
        assert 'if op == "join":' in s
    else:
        assert token in s, token
ast.parse(s)
print("ZIVO 96.43 DIRECT IPC BRIDGE STATIC TEST: PASS")
