#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
[[ $EUID -eq 0 ]] || { echo "ERROR: run as root" >&2; exit 1; }

python3 -m py_compile \
  "$ROOT/account/zivo60.py" \
  "$ROOT/account/zivo_multi_account.py" \
  "$ROOT/account/zivo_ipc.py" \
  "$ROOT/account/zivo_premium.py" \
  "$ROOT/account/check_zivo60_96_13_live_regressions.py" \
  "$ROOT/account/check_zivo60_96_51_1_installer_regression.py" \
  "$ROOT/account/check_zivo60_96_52_wallet_commerce.py" \
  "$ROOT/account/check_zivo60_96_52_installer_regression.py" \
  "$ROOT/account/check_zivo60_96_53_tier_response_priority.py" \
  "$ROOT/account/check_zivo60_96_46_premium_tiers_existing_group_membership.py" \
  "$ROOT/account/check_zivo60_96_51_campaign_group_delivery.py" \
  "$ROOT/account/check_zivo60_96_50_cleanup_reliability.py" \
  "$ROOT/account/check_zivo60_96_49_receipt_welcome_speaker.py" \
  "$ROOT/account/check_zivo60_96_48_meow_commerce_lock_admin.py" \
  "$ROOT/account/check_zivo60_96_47_official_admin_campaign_meter.py" \
  "$ROOT/official/zivo_official22.py" \
  "$ROOT/official/zivo_official21.py" \
  "$ROOT/official/zivo_official20.py" \
  "$ROOT/official/zivo_official19.py" \
  "$ROOT/official/zivo_official18.py" \
  "$ROOT/official/zivo_official17.py" \
  "$ROOT/official/zivo_ipc.py" \
  "$ROOT/official/test_zivo_official22.py" \
  "$ROOT/official/test_zivo_official21.py" \
  "$ROOT/official/test_zivo_official20.py" \
  "$ROOT/official/test_zivo_official19.py" \
  "$ROOT/official/test_zivo_official18.py" \
  "$ROOT/official/test_zivo_official17.py"

bash -n "$ROOT/account/install_zivo60.sh"
bash -n "$ROOT/official/install.sh"
python3 "$ROOT/account/check_zivo60_96_13_live_regressions.py"
python3 "$ROOT/account/check_zivo60_96_51_1_installer_regression.py"
PYTHONPATH="$ROOT/account" python3 "$ROOT/account/check_zivo60_96_52_wallet_commerce.py"
python3 "$ROOT/account/check_zivo60_96_52_installer_regression.py"
PYTHONPATH="$ROOT/account" python3 "$ROOT/account/check_zivo60_96_53_tier_response_priority.py"
python3 "$ROOT/account/check_zivo60_96_46_premium_tiers_existing_group_membership.py"
python3 "$ROOT/account/check_zivo60_96_51_campaign_group_delivery.py"
python3 "$ROOT/account/check_zivo60_96_50_cleanup_reliability.py"
python3 "$ROOT/account/check_zivo60_96_49_receipt_welcome_speaker.py"
python3 "$ROOT/account/check_zivo60_96_48_meow_commerce_lock_admin.py"
python3 "$ROOT/account/check_zivo60_96_47_official_admin_campaign_meter.py"
[[ -f "$ROOT/verify_low_disk_installer.py" ]] && python3 "$ROOT/verify_low_disk_installer.py" || true

echo "OFFICIAL22 PREFLIGHT: DEFERRED | runtime test runs with selected requests-capable service venv"

bash "$ROOT/account/install_zivo60.sh"
systemctl restart zivo60.service zivo60@acc2.service zivo60@acc3.service
for i in $(seq 1 40); do
  [[ -S /run/zivo-ipc/main.sock && -S /run/zivo-ipc/acc2.sock && -S /run/zivo-ipc/acc3.sock ]] && break
  sleep 1
done
for key in main acc2 acc3; do
  [[ -S "/run/zivo-ipc/${key}.sock" ]] || { echo "ERROR: missing socket /run/zivo-ipc/${key}.sock" >&2; exit 1; }
done

bash "$ROOT/official/install.sh"

echo "ZIVO 96.53 + OFFICIAL22 MEOW START + TIER PRIORITY INSTALL COMPLETE"
systemctl status zivo60.service zivo60@acc2.service zivo60@acc3.service zivo-official22.service --no-pager -l || true
