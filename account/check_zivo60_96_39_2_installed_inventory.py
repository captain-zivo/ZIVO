from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
installer = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')
source = (ROOT / 'zivo60.py').read_text(encoding='utf-8')
assert any(v in source for v in ('VERSION = "zivo60.96.39.2"', 'VERSION = "zivo60.96.39.3"', 'VERSION = "zivo60.96.39.4"'))

block = installer.split('DEPLOY_FILES=(', 1)[1].split('\n)', 1)[0]
deploy_files = []
for line in block.splitlines():
    line = line.split('#', 1)[0].strip()
    if not line:
        continue
    deploy_files.extend(line.split())

deploy_checks = sorted({name for name in deploy_files if name.startswith('check') and name.endswith('.py')})
local_checks = sorted(path.name for path in ROOT.glob('check*.py'))

# Full Source and /opt/zivo60 must expose the exact same QA inventory declared by
# the transactional installer.  This catches the 96.39.1 failure where 59 tests
# shipped but only 38 were copied to the live tree.
assert set(local_checks) == set(deploy_checks), {
    'missing_from_installed_or_source': sorted(set(deploy_checks) - set(local_checks)),
    'not_declared_for_deploy': sorted(set(local_checks) - set(deploy_checks)),
}
assert len(local_checks) == len(set(local_checks))

# Representative zero-to-100 coverage sentinels: management, filtering, spam,
# transport, cleanup, welcome, economy/games, premium/payment and purchase UX.
required = {
    'check_command_core_91.py',
    'check_filter_rate_91.py',
    'check_moderation_security_91.py',
    'check_delete_governor_96.py',
    'check_smart_filter_speed_93.py',
    'check_speed_hotpath_96.py',
    'check_zivo60_95_social_games.py',
    'check_zivo60_96_20_admin_economy_gifts.py',
    'check_zivo60_96_31_live_transport_reliability.py',
    'check_zivo60_96_33_profanity_guard_expansion.py',
    'check_zivo60_96_34_cleanup_reliability.py',
    'check_zivo60_96_36_welcome_end_to_end.py',
    'check_zivo60_96_37_forward_welcome_fastlane.py',
    'check_zivo60_96_38_premium_payment_foundation.py',
    'check_zivo60_96_39_purchase_ux.py',
    'check_zivo60_96_39_1_full_core_audit.py',
    'check_zivo60_96_39_2_installed_inventory.py',
    'check_zivo60_96_39_3_startup_cutover.py',
    'check_zivo60_96_39_4_premium_schema_migration.py',
}
assert required.issubset(set(local_checks)), sorted(required - set(local_checks))

# Every declared file must actually be present in the current tree.
missing_files = [name for name in deploy_files if not (ROOT / name).is_file()]
assert not missing_files, missing_files

print('CHECK ZIVO60.96.39.2 INSTALLED QA INVENTORY: PASS')
print(f'  installer/source/installed check inventory aligned: {len(local_checks)} checks')
print('  management/filter/spam/cleanup/transport/welcome/economy/premium sentinels: PASS')
