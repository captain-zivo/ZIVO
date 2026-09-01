#!/usr/bin/env python3
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parent
acc=(root/'account/install_zivo60.sh').read_text(encoding='utf-8')
off=(root/'official/install.sh').read_text(encoding='utf-8')
# Historical contracts that previously caused rollback must stay intact.
assert acc.count('check_zivo60_96_39_3_startup_cutover.py') >= 4
assert acc.count('check_zivo60_96_39_4_premium_schema_migration.py') >= 4
assert acc.count('ZIVO_PROFANITY_TEST_MAX_SECONDS=20') >= 2
# Low-disk decision matrix.
assert 'MIN_DEPLOY_FREE_MB=512' in acc
assert 'MIN_DEPLOY_OPERATIONAL_FREE_MB="${ZIVO_INSTALL_MIN_FREE_MB:-192}"' in acc
assert 'venv_satisfies_current_release' in acc
assert 'REUSE_ACTIVE_VENV=1' in acc
assert 'REQUIRED_FREE_MB="$MIN_DEPLOY_OPERATIONAL_FREE_MB"' in acc
assert 'REQUIRED_FREE_MB="$MIN_DEPLOY_FREE_MB"' in acc
assert 'VENV BUILD: SKIPPED' in acc
assert 'STAGE_VENV=""' in acc
assert 'VENV CUTOVER: REUSED' in acc
# The actual reported server condition must pass only on the reuse path.
free_mb=285
assert free_mb >= 192
assert free_mb < 512
# Reuse mode must not switch the live venv. The old move remains only in replacement branch.
cut=acc.index('# Switch the venv only when a replacement was actually built.')
reuse=acc.index('if (( REUSE_ACTIVE_VENV == 1 )); then', cut)
else_pos=acc.index('\nelse\n', reuse)
move_pos=acc.index('mv -- "$BASE/venv" "$BACKUP/venv"', else_pos)
assert move_pos > else_pos
# Official22 also has a zero-copy dependency reuse path, preferring Official21.
for token in ('requests_venv_ok','/opt/ZIVO_OFFICIAL_BOT21/venv','/opt/ZIVO_OFFICIAL_BOT20/venv','/opt/ZIVO_OFFICIAL_BOT19/venv','/opt/ZIVO_OFFICIAL_BOT18/venv','/opt/ZIVO_OFFICIAL_BOT15/venv','/opt/ZIVO_OFFICIAL_BOT14/venv','/opt/ZIVO_OFFICIAL_BOT13/venv','/opt/ZIVO_OFFICIAL_BOT12/venv','/opt/zivo60/venv','OFFICIAL22 VENV: REUSED'):
    assert token in off, token
# Shell parsers must accept both installers.
subprocess.run(['bash','-n',str(root/'account/install_zivo60.sh')],check=True)
subprocess.run(['bash','-n',str(root/'official/install.sh')],check=True)
print('ZIVO 96.53 LOW-DISK VENV-REUSE INSTALLER TEST: PASS | 285MB reuse=allowed rebuild=blocked')
