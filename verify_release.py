#!/usr/bin/env python3
from pathlib import Path
import subprocess,sys
root=Path(__file__).resolve().parent
required=[
 'account/zivo60.py','account/zivo_premium.py','account/zivo_social_games.py','account/install_zivo60.sh',
 'account/check_zivo60_96_51_1_installer_regression.py',
 'account/check_zivo60_96_52_wallet_commerce.py','account/check_zivo60_96_52_installer_regression.py',
 'account/check_zivo60_96_53_tier_response_priority.py',
 'account/check_zivo60_96_51_campaign_group_delivery.py',
 'account/check_zivo60_96_50_cleanup_reliability.py','account/check_zivo60_96_49_receipt_welcome_speaker.py',
 'official/zivo_official22.py','official/test_zivo_official22.py','official/install.sh','official/zivo-official22.service',
 'install_all.sh','verify_low_disk_installer.py','verify_official_preflight_runtime.py','qa_payment_reversal_96_49.py','RELEASE_MANIFEST.txt'
]
for rel in required:
    assert (root/rel).is_file(), rel
core=(root/'account/zivo60.py').read_text(encoding='utf-8')
off=(root/'official/zivo_official22.py').read_text(encoding='utf-8')
acc=(root/'account/install_zivo60.sh').read_text(encoding='utf-8')
oi=(root/'official/install.sh').read_text(encoding='utf-8')
svc=(root/'official/zivo-official22.service').read_text(encoding='utf-8')
allsh=(root/'install_all.sh').read_text(encoding='utf-8')
assert 'VERSION = "zivo60.96.53"' in core
assert 'VERSION = "zivo-official22"' in off
for token in ('fetch_numeric_cleanup_history','await_late_delete_barrier','CLEANUP_RETRY_SPLIT_THRESHOLD','numeric-paged+timeout-barrier+adaptive-split+async-official','op == "control_enqueue"','op == "control_status"'):
    assert token in core, token
for token in ('ctl:jobstatus','control_enqueue','control_status','_last_control_job'):
    assert token in off, token
for token in ('def _premium_pay(', 'receipt:start:', 'پرداخت کردم · ارسال رسید'):
    assert token in off, token
for token in ('wallet:home','wallet:topup','walletadmin:confirm','create_wallet_topup','پرداخت فوری با کیف پول'):
    assert token in off, token
for token in ('_forwarded_user_profile','_recover_started_target','OFFICIAL_USERNAME_UNKNOWN','registry_recovered'):
    assert token in off, token
for token in ('TIER_RESPONSE_PRIORITY','asyncio.PriorityQueue','tier_response_eager_limit','_group_response_priority'):
    assert token in core, token
for token in ('_campaign_send_group_text', '_campaign_plain_text_forbidden'):
    assert token in core, token
assert 'DST=/opt/ZIVO_OFFICIAL_BOT22' in oi and 'SERVICE=zivo-official22.service' in oi
assert '/opt/ZIVO_OFFICIAL_BOT22/zivo_official22.py' in svc
assert 'zivo-official22.service' in allsh
checks=sorted(p.name for p in (root/'account').glob('check*.py'))
missing=[name for name in checks if name not in acc]
assert not missing, f'installer missing checks: {missing}'
assert acc.count('check_zivo60_96_39_3_startup_cutover.py')>=4
assert acc.count('check_zivo60_96_39_4_premium_schema_migration.py')>=4
assert acc.count('check_zivo60_96_13_live_regressions.py')>=4
assert acc.count('check_zivo60_96_51_1_installer_regression.py')>=4
assert acc.count('check_zivo60_96_52_wallet_commerce.py')>=4
assert acc.count('check_zivo60_96_52_installer_regression.py')>=4
assert acc.count('check_zivo60_96_53_tier_response_priority.py')>=4
assert acc.count('ZIVO_PROFANITY_TEST_MAX_SECONDS=20')>=2
for sh in ('account/install_zivo60.sh','official/install.sh','install_all.sh'):
    subprocess.run(['bash','-n',str(root/sh)],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_13_live_regressions.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_51_1_installer_regression.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_52_wallet_commerce.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_52_installer_regression.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_53_tier_response_priority.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_34_cleanup_reliability.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_51_campaign_group_delivery.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_50_cleanup_reliability.py')],check=True)
subprocess.run([sys.executable,str(root/'account/check_zivo60_96_49_receipt_welcome_speaker.py')],check=True)
subprocess.run([sys.executable,str(root/'qa_payment_reversal_96_49.py')],check=True)
print(f'ZIVO 96.53 + OFFICIAL22 MEOW START/TIER PRIORITY VERIFY: PASS | installer-checks={len(checks)}/{len(checks)}')
