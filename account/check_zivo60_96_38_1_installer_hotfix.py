from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
installer = (ROOT / 'install_zivo60.sh').read_text(encoding='utf-8')

m = re.search(r'DEPLOY_FILES=\(\n(.*?)\n\)', installer, re.S)
assert m, 'DEPLOY_FILES block missing'
tokens = re.findall(r'(?<![\w./-])([A-Za-z0-9_@.+-]+\.(?:py|sh))(?![\w./-])', m.group(1))
declared = set(tokens)
required = {
    'install_zivo60.sh',
    'zivo60.py',
    'zivo_premium.py',
    'setup_zivo_payment_domain.sh',
    'check_zivo60_96_31_live_transport_reliability.py',
    'check_zivo60_96_32_owner_zero_recovery.py',
    'check_zivo60_96_33_profanity_guard_expansion.py',
    'check_zivo60_96_34_cleanup_reliability.py',
    'check_zivo60_96_35_owner_multigroup_recovery.py',
    'check_zivo60_96_36_welcome_end_to_end.py',
    'check_zivo60_96_37_forward_welcome_fastlane.py',
    'check_zivo60_96_38_premium_payment_foundation.py',
    'check_zivo60_96_38_1_installer_hotfix.py',
}
missing_declared = sorted(required - declared)
assert not missing_declared, f'required deploy files not declared: {missing_declared}'

missing_source = sorted(f for f in declared if not (ROOT / f).is_file())
assert not missing_source, f'declared deploy source files absent: {missing_source}'

assert 'for f in "${DEPLOY_FILES[@]}"; do' in installer, 'single-source deploy loop missing'
assert 'install -m "$mode" "$SRC/$f" "$BASE/$f"' in installer, 'generic deploy install missing'
assert 'INSTALL FAILED: source deploy file missing' in installer
assert 'INSTALL FAILED: deployed file missing after cutover' in installer
assert 'install_zivo60.sh|setup_zivo_payment_domain.sh|setup_zivo_accounts.py' in installer

# The installed-copy premium test reads ROOT/install_zivo60.sh directly, so the
# installer itself must be part of the deployed live tree.
assert 'install_zivo60.sh' in declared
assert 'check_zivo60_96_38_premium_payment_foundation.py' in declared

print('CHECK ZIVO60.96.38.1 INSTALLER HOTFIX: PASS')
print('  DEPLOY_FILES is the single cutover source of truth: PASS')
print('  installer itself deployed for installed-copy premium validation: PASS')
print('  96.31-96.38 regression checks cannot drift out of cutover: PASS')
