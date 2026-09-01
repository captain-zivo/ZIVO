#!/usr/bin/env python3
"""Static/adversarial invariants for the transactional 96.11 installer."""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


installer = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("install_zivo60.sh")
source = installer.read_text(encoding="utf-8")


def position(fragment: str, start: int = 0) -> int:
    result = source.find(fragment, start)
    assert result >= 0, f"installer fragment missing: {fragment!r}"
    return result


# Dependency work must happen before service discovery/snapshot/cutover. The
# installed-copy tests remain after copying but before the atomic venv switch.
stage_create = position('"$PYTHON" -m venv "$STAGE_VENV"')
stage_pip = position('"$STAGE_VENV/bin/python" -m pip install', stage_create)
source_compile = position('"$VALIDATE_PY" -m py_compile', stage_pip)
discover_call = position("\ndiscover_instance_units\n", source_compile)
pre_cutover = position(': > "$PRE_CUTOVER_READY"', discover_call)
cutover_stop = position("# Every template instance uses the shared code and venv.", pre_cutover)
db_snapshot = position(': > "$DB_MANIFEST"', cutover_stop)
snapshot_ready = position(': > "$SNAPSHOT_READY"', db_snapshot)
live_copy = position('install -m 600 "$SRC/zivo60.py" "$BASE/zivo60.py"', snapshot_ready)
installed_check = position('echo "INSTALLED COPY ZIVO60.96.11 FEATURE CHECKS: PASS"', live_copy)
venv_switch = position('mv -Tf -- "$VENV_LINK_TMP" "$BASE/venv"', installed_check)
assert stage_create < stage_pip < source_compile < discover_call < pre_cutover
assert pre_cutover < cutover_stop < db_snapshot < snapshot_ready < live_copy < installed_check < venv_switch
assert source.count(' -m venv "$STAGE_VENV"') == 1
assert source.count("pip install") == 1

# Signal rollback is manifest/state driven. Temporary dependency artifacts are
# removed even when the complete snapshot marker has not yet been written.
assert "VENV_PREVIOUS_MOVED" not in source
assert "VENV_SWITCHED" not in source
rollback_body = source[position("rollback(){") : position("abort_install(){")]
snapshot_guard = rollback_body.index('if [[ ! -f "$SNAPSHOT_READY" ]]')
assert rollback_body.index('rm -f -- "$VENV_LINK_TMP"') < snapshot_guard
no_snapshot_stage_cleanup = rollback_body.index('if [[ -d "$STAGE_VENV" ]]', snapshot_guard)
no_snapshot_return = rollback_body.index("return 0", no_snapshot_stage_cleanup)
assert snapshot_guard < no_snapshot_stage_cleanup < no_snapshot_return
assert 'grep -Fzxq -- "base/venv" "$ARTIFACT_MANIFEST"' in rollback_body
assert 'mv -- "$BACKUP/venv" "$BASE/venv"' in rollback_body
for signal, code in (("HUP", "129"), ("INT", "130"), ("TERM", "143")):
    assert f"trap 'abort_install {signal} {code}' {signal}" in source
assert "trap 'abort_install ERR $?' ERR" in source

# A failed stop during rollback must never be followed by replacing SQLite or
# deleting WAL sidecars under a still-live writer.
verify_writer = rollback_body.index('rollback_db_safe=1')
restore_guard = rollback_body.index('if [[ "$rollback_db_safe" == "1" ]]')
restore_call = rollback_body.index("restore_sqlite_snapshots", restore_guard)
assert verify_writer < restore_guard < restore_call
assert "SQLite restore skipped because at least one writer remained active" in rollback_body

# Every account DB declaration is discovered, including quoted paths and
# symlink-backed env files. Run the exact embedded parser against hostile input.
assert '{"ZIVO_DB", "ZIVO_MULTI_ACCOUNT_DB"}' in source
assert 'candidate="$(readlink -m -- "$candidate")"' in source
parser_match = re.search(
    r'done < <\("\$PYTHON" - "\$ACCOUNT_ENV_DIR" <<\'PY\'\n(?P<body>.*?)\nPY\n  \)',
    source,
    flags=re.DOTALL,
)
assert parser_match, "database env parser heredoc missing"
with tempfile.TemporaryDirectory() as temp_name:
    env_dir = Path(temp_name)
    primary = env_dir / "main.env"
    primary.write_text(
        "ZIVO_DB=\"/opt/zivo60/db with spaces.sqlite\"\n"
        "ZIVO_MULTI_ACCOUNT_DB='/opt/zivo60/shared db.sqlite'\n"
        "ZIVO_DB=/opt/zivo60/db with spaces.sqlite\n"
        "IGNORED=/tmp/nope.sqlite\n",
        encoding="utf-8",
    )
    try:
        (env_dir / "linked.env").symlink_to(primary)
    except OSError:
        pass
    parsed = subprocess.run(
        [sys.executable, "-c", parser_match.group("body"), str(env_dir)],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout.split(b"\0")
    parsed = [item.decode() for item in parsed if item]
    assert "/opt/zivo60/db with spaces.sqlite" in parsed
    assert "/opt/zivo60/shared db.sqlite" in parsed
    assert "/tmp/nope.sqlite" not in parsed

# Existing custom provider/TTS keys survive main.env reconciliation.
main_env = source[position("# Controller account:") : position("# Preconfigure the two requested accounts")]
assert 'MAIN_ENV_TMP="$(mktemp ' in main_env
assert "awk '" in main_env and 'mv -f -- "$MAIN_ENV_TMP" "$MAIN_ENV"' in main_env
assert 'cat > "$MAIN_ENV"' not in main_env
assert "ZIVO_TTS_" not in main_env
assert "ARZHAM_API_KEY" not in main_env

# Rollback owns only the three env files this installer can create; it must not
# delete unrelated files merely because an operator added them after snapshot.
rollback_env = rollback_body[rollback_body.index("# Delete only paths") : rollback_body.index("restore_sqlite_snapshots")]
assert 'done < "$ACCOUNT_ENV_CREATED_MANIFEST"' in rollback_env
assert "main.env|acc2.env|acc3.env" in rollback_env
assert 'find "$ACCOUNT_ENV_DIR"' not in rollback_env
assert "ACCOUNT_ENV_CREATED_MANIFEST" in source
assert "printf 'main.env\\0'" in source
assert "printf 'acc2.env\\0'" in source
assert "printf 'acc3.env\\0'" in source

# A secondary that was active before deployment must become active and emit its
# ready marker; intentionally disabled/stopped accounts remain stopped.
secondary_start = position("# Do not start secondary accounts")
secondary = source[secondary_start : position("for key in main acc2 acc3;", secondary_start)]
assert 'if [[ "$registry_enabled" != "1" ]]' in secondary
assert 'if [[ "$prior_active" == "1" ]]' in secondary
assert "PREVIOUSLY-ACTIVE ACCOUNT RESTART COMMAND FAILED" in secondary
assert 'wait_service_ready "$unit" "$account_start_ts" "$key" 60' in secondary
assert 'systemctl stop "$unit"' in secondary

print("CHECK INSTALLER TRANSACTION ZIVO60.96.11: PASS")
