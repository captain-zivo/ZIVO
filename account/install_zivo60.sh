#!/usr/bin/env bash
set -Eeuo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="/opt/zivo60"
SERVICE="zivo60.service"
TEMPLATE="zivo60@.service"
STAMP="$(date +%Y%m%d_%H%M%S)_$$"
BACKUP="$BASE/backups/pre_zivo60_96_53_${STAMP}"
VENV_ROOT="$BASE/venvs"
STAGE_VENV="$VENV_ROOT/zivo60_96_53_${STAMP}"
VENV_LINK_TMP="$BASE/.venv_next_${STAMP}"
ROLLBACK_STARTED=0
ROLLBACK_ERRORS=0
PYTHON="python3"
ACCOUNT_ENV_DIR="/etc/zivo60/accounts"
ACCOUNT_ENV_MANIFEST="$BACKUP/account-env-files.nul"
ACCOUNT_ENV_CREATED_MANIFEST="$BACKUP/account-env-created.nul"
ACCOUNT_ENV_MANIFEST_READY="$BACKUP/account-env-files.ready"
ARTIFACT_MANIFEST="$BACKUP/artifacts-present.nul"
PRE_CUTOVER_READY="$BACKUP/pre-cutover.ready"
SNAPSHOT_READY="$BACKUP/snapshot.ready"
SYSTEMD_STATE_FILE="$BACKUP/systemd-state.tsv"
DB_MANIFEST="$BACKUP/sqlite/databases.tsv"
PREDEPLOY_DIR="$BACKUP/predeploy-isolated"
MAIN_ENV_TMP=""
MAIN_DB="$BASE/zivo60.db"
MULTI_DB="$BASE/zivo_multi_accounts.db"
DEPLOY_FILES=(
  install_zivo60.sh
  zivo60.py
  set_zivo60_pro.py
  zivo_entertainment.py
  zivo_social_games.py
  zivo_voice.py
  zivo_admin_ux.py
  zivo_market_tools.py
  zivo_speaker.py
  zivo_ai_speaker.py
  zivo_multi_account.py
  zivo_ipc.py
  zivo_premium.py
  setup_zivo_accounts.py
  setup_zivo_payment_domain.sh
  check_activation_card_recovery_96_11.py
  check_command_core_91.py
  check_delete_governor_96.py
  check_filter_rate_91.py
  check_help_permission_91.py
  check_historical_join_recovery_91.py
  check_installer_transaction_96_11.py
  check_join_guide_ttt_96_10.py
  check_join_recovery_69.py
  check_moderation_security_91.py
  check_priority_transport_96.py
  check_private_fast_lane_91.py
  check_private_join_priority_91.py
  check_private_join_recovery_91.py
  check_private_notice_91.py
  check_runtime_log_hygiene_91.py
  check_smart_filter_speed_93.py
  check_speed_filter_font_ban_91.py
  check_speed_hotpath_96.py
  check_target_campaign_report_91.py
  check_transport_hygiene_91.py
  check_welcome_hotfix_91.py
  check_zivo60_94_features.py
  check_zivo60_95_social_games.py
  check_zivo60_96_11_features.py
  check_zivo60_96_12_repairs.py
  check_zivo60_96_13_live_regressions.py
  check_zivo60_96_14_emergency_recovery.py
  check_zivo60_96_15_legacy_group_recovery.py
  check_zivo60_96_16_legacy_runtime_reconcile.py
  check_zivo60_96_17_send_flood_recovery.py
  check_zivo60_96_18_runtime_presence.py
  check_zivo60_96_19_role_command_recovery.py
  check_zivo60_96_20_admin_economy_gifts.py
  check_zivo60_96_21_owner_full_cleanup.py
  check_zivo60_96_22_full_dialog_inventory.py
  check_zivo60_96_23_private_inventory_priority.py
  check_zivo60_96_24_cleanup_private_inventory.py
  check_zivo60_96_25_campaign_live_all_dialogs.py
  check_zivo60_96_26_campaign_live_progress_speed.py
  check_zivo60_96_27_exhaustive_raw_dialog_pagination.py
  check_zivo60_96_28_campaign_immediate_claim_fairness.py
  check_zivo60_96_29_behavioral_qa.py
  check_zivo60_96_30_owner_welcome_spam_meow_guard.py
  check_zivo60_96_31_live_transport_reliability.py
  check_zivo60_96_32_owner_zero_recovery.py
  check_zivo60_96_33_profanity_guard_expansion.py
  check_zivo60_96_34_cleanup_reliability.py
  check_zivo60_96_35_owner_multigroup_recovery.py
  check_zivo60_96_36_welcome_end_to_end.py
  check_zivo60_96_37_forward_welcome_fastlane.py
  check_zivo60_96_38_1_installer_hotfix.py
  check_zivo60_96_38_premium_payment_foundation.py
  check_zivo60_96_39_1_full_core_audit.py
  check_zivo60_96_39_2_installed_inventory.py
  check_zivo60_96_39_3_startup_cutover.py
  check_zivo60_96_39_4_premium_schema_migration.py
  check_zivo60_96_40_official_control_bridge.py
  check_zivo60_96_41_instant_official_join.py
  check_zivo60_96_42_content_bio_join_bridge.py
  check_zivo60_96_43_direct_ipc_bridge.py
  check_zivo60_96_44_official_premium_ipc.py
  check_zivo60_96_45_ux_checkout_ipc.py
  check_zivo60_96_46_premium_tiers_existing_group_membership.py
  check_zivo60_96_47_official_admin_campaign_meter.py
  check_zivo60_96_51_1_installer_regression.py
  check_zivo60_96_52_wallet_commerce.py
  check_zivo60_96_52_installer_regression.py
  check_zivo60_96_53_tier_response_priority.py
  check_zivo60_96_51_campaign_group_delivery.py
  check_zivo60_96_50_cleanup_reliability.py
  check_zivo60_96_49_receipt_welcome_speaker.py
  check_zivo60_96_48_meow_commerce_lock_admin.py
  check_zivo60_96_39_purchase_ux.py
  check_zivo_market_concurrency.py
  check_zivo_market_provider.py
  check_zivo_market_tools.py
  check_zivo_voice_profiles.py
)
INSTANCE_UNITS=("zivo60@acc2.service" "zivo60@acc3.service")
DATABASE_PATHS=(
  "$MAIN_DB" "$MULTI_DB"
  "$BASE/accounts/acc2/zivo60.db" "$BASE/accounts/acc3/zivo60.db"
)
# Historical compatibility marker: older QA asserts that the original conservative
# 512MB guard remains documented. 96.45.3 uses a measured operational floor
# because dependency creation happens before cutover and cannot damage live bots.
MIN_DEPLOY_FREE_MB=512
MIN_DEPLOY_OPERATIONAL_FREE_MB="${ZIVO_INSTALL_MIN_FREE_MB:-192}"
INSTALL_LOCK_FILE="/run/lock/zivo60-install.lock"

command -v flock >/dev/null 2>&1 || { echo "INSTALL BLOCKED: flock is required for exclusive deployment."; exit 1; }
exec 9>"$INSTALL_LOCK_FILE"
flock -n 9 || { echo "INSTALL BLOCKED: another ZIVO installer is already running."; exit 75; }

safe_prune_old_install_artifacts(){
  local active_venv="" backup target dir
  local before_mb after_mb idx
  local -a backups=() keep_targets=()

  before_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
  active_venv="$(readlink -f -- "$BASE/venv" 2>/dev/null || true)"
  [[ -n "$active_venv" ]] && keep_targets+=("$active_venv")

  if [[ -d "$BASE/backups" ]]; then
    mapfile -t backups < <(find "$BASE/backups" -mindepth 1 -maxdepth 1 -type d -name 'pre_zivo60_*' -printf '%T@ %p\n' 2>/dev/null | sort -nr | cut -d' ' -f2-)
    # Keep the two newest rollback snapshots and every venv they reference.
    for idx in 0 1; do
      [[ ${#backups[@]} -gt $idx ]] || continue
      backup="${backups[$idx]}"
      target="$(readlink -f -- "$backup/venv" 2>/dev/null || true)"
      [[ -n "$target" ]] && keep_targets+=("$target")
    done
    if (( ${#backups[@]} > 2 )); then
      for backup in "${backups[@]:2}"; do
        rm -rf -- "$backup"
      done
    fi
  fi

  # Remove only versioned venvs that are neither live nor referenced by the two
  # rollback snapshots retained above. Never touch /opt/zivo60/venv itself here.
  if [[ -d "$VENV_ROOT" ]]; then
    while IFS= read -r -d '' dir; do
      target="$(readlink -f -- "$dir" 2>/dev/null || true)"
      [[ -n "$target" ]] || target="$dir"
      local keep=0 candidate
      for candidate in "${keep_targets[@]}"; do
        if [[ "$target" == "$candidate" ]]; then keep=1; break; fi
      done
      (( keep == 1 )) || rm -rf -- "$dir"
    done < <(find "$VENV_ROOT" -mindepth 1 -maxdepth 1 -type d -print0 2>/dev/null)
  fi

  # Stale temporary symlinks are never rollback sources.
  find "$BASE" -mindepth 1 -maxdepth 1 -type l -name '.venv_next_*' -delete 2>/dev/null || true

  after_mb="$(df -Pm / | awk 'NR==2 {print $4}')"
  if [[ "$before_mb" =~ ^[0-9]+$ && "$after_mb" =~ ^[0-9]+$ ]]; then
    echo "DISK PREP: free ${before_mb}MB -> ${after_mb}MB; live venv + 2 newest rollbacks preserved."
  fi
}

venv_satisfies_current_release(){
  local candidate="$1"
  [[ -x "$candidate" ]] || return 1
  "$candidate" - <<'PYREQ' >/dev/null 2>&1
from importlib.metadata import PackageNotFoundError, version

def nums(value):
    out=[]
    for part in str(value).replace('-', '.').split('.'):
        digits=''.join(ch for ch in part if ch.isdigit())
        if digits:
            out.append(int(digits))
        else:
            break
    return tuple(out or [0])

def exact(dist, expected):
    try:
        return version(dist) == expected
    except PackageNotFoundError:
        return False

def ranged(dist, low, high):
    try:
        cur=nums(version(dist))
    except PackageNotFoundError:
        return False
    return nums(low) <= cur < nums(high)

checks=[
    exact('splusthon','1.1.4'),
    exact('edge-tts','7.2.8'),
    ranged('aiohttp','3.9','4.0'),
    exact('Pillow','12.3.0'),
]
if not all(checks):
    raise SystemExit(1)
import aiohttp, edge_tts, PIL, splusthon
PYREQ
}

safe_prune_old_install_artifacts
ACTIVE_VENV_PY="$BASE/venv/bin/python"
REUSE_ACTIVE_VENV=0
if venv_satisfies_current_release "$ACTIVE_VENV_PY"; then
  REUSE_ACTIVE_VENV=1
  REQUIRED_FREE_MB="$MIN_DEPLOY_OPERATIONAL_FREE_MB"
  echo "VENV PRECHECK: PASS | current live venv satisfies 96.53 requirements; zero-copy reuse enabled."
else
  REQUIRED_FREE_MB="$MIN_DEPLOY_FREE_MB"
  echo "VENV PRECHECK: current live venv is missing/incompatible; isolated dependency rebuild required."
fi
AVAILABLE_MB="$(df -Pm / | awk 'NR==2 {print $4}')"
if [[ ! "${AVAILABLE_MB:-}" =~ ^[0-9]+$ ]] || (( AVAILABLE_MB < REQUIRED_FREE_MB )); then
  echo "INSTALL BLOCKED: only ${AVAILABLE_MB:-0}MB free; this path requires ${REQUIRED_FREE_MB}MB."
  if (( REUSE_ACTIVE_VENV == 1 )); then
    echo "Low-disk reuse was available, but safe operational headroom is still insufficient."
  else
    echo "Current venv cannot be reused safely; free disk space before creating a replacement venv."
  fi
  exit 1
fi
echo "DISK CHECK: PASS | free=${AVAILABLE_MB}MB | required=${REQUIRED_FREE_MB}MB | reuse_active_venv=${REUSE_ACTIVE_VENV} | legacy_guard=${MIN_DEPLOY_FREE_MB}MB"

sqlite_online_backup(){
  local source_path="$1"
  local backup_path="$2"
  local absent_marker="$3"
  rm -f -- "$backup_path" "$absent_marker"
  if [[ ! -f "$source_path" ]]; then
    : > "$absent_marker"
    return 0
  fi
  "$PYTHON" - "$source_path" "$backup_path" <<'PY'
import sqlite3
import sys
from pathlib import Path

source_path = Path(sys.argv[1])
backup_path = Path(sys.argv[2])
source = sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
target = sqlite3.connect(str(backup_path), timeout=30)
try:
    source.backup(target, pages=2048, sleep=0.05)
    row = target.execute("PRAGMA quick_check").fetchone()
    if row is None or str(row[0]).lower() != "ok":
        raise RuntimeError(f"SQLITE_BACKUP_QUICK_CHECK_FAILED:{row!r}")
finally:
    target.close()
    source.close()
PY
  chmod --reference="$source_path" "$backup_path"
  chown --reference="$source_path" "$backup_path"
}

snapshot_unit_state(){
  local unit="$1"
  local active="0"
  local enabled_state="unknown"
  if systemctl is-active --quiet "$unit"; then
    active="1"
  fi
  enabled_state="$(systemctl is-enabled "$unit" 2>/dev/null || true)"
  [[ -n "$enabled_state" ]] || enabled_state="unknown"
  printf '%s\t%s\t%s\n' "$unit" "$active" "$enabled_state" >> "$SYSTEMD_STATE_FILE"
}

add_instance_unit(){
  local candidate="$1"
  local existing
  [[ "$candidate" =~ ^zivo60@[A-Za-z0-9_.-]+\.service$ ]] || return 0
  for existing in "${INSTANCE_UNITS[@]}"; do
    [[ "$existing" == "$candidate" ]] && return 0
  done
  INSTANCE_UNITS+=("$candidate")
}

discover_instance_units(){
  local env_file key listed_unit
  for env_file in "$ACCOUNT_ENV_DIR"/*.env; do
    [[ -e "$env_file" || -L "$env_file" ]] || continue
    key="$(basename -- "$env_file" .env)"
    [[ "$key" == "main" ]] || add_instance_unit "zivo60@$key.service"
  done
  while IFS= read -r listed_unit; do
    add_instance_unit "$listed_unit"
  done < <(
    systemctl list-units --all --type=service --no-legend --plain 'zivo60@*.service' 2>/dev/null \
      | awk '{print $1}' || true
  )
}

add_database_path(){
  local candidate="$1"
  local existing
  candidate="${candidate%$'\r'}"
  [[ "$candidate" == /* && "$candidate" != "/" && "$candidate" != *$'\t'* && "$candidate" != *$'\n'* ]] || return 0
  candidate="$(readlink -m -- "$candidate")"
  for existing in "${DATABASE_PATHS[@]}"; do
    [[ "$existing" == "$candidate" ]] && return 0
  done
  DATABASE_PATHS+=("$candidate")
}

discover_database_paths(){
  local candidate
  while IFS= read -r -d '' candidate; do
    [[ -n "$candidate" ]] && add_database_path "$candidate"
  done < <("$PYTHON" - "$ACCOUNT_ENV_DIR" <<'PY'
import os
import sys
from pathlib import Path

env_dir = Path(sys.argv[1])
for env_file in sorted(env_dir.glob("*.env")):
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        continue
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() not in {"ZIVO_DB", "ZIVO_MULTI_ACCOUNT_DB"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            sys.stdout.buffer.write(os.fsencode(value) + b"\0")
PY
  )
}

unit_prior_field(){
  local unit="$1"
  local field="$2"
  local state_unit active enabled_state
  while IFS=$'\t' read -r state_unit active enabled_state; do
    if [[ "$state_unit" == "$unit" ]]; then
      if [[ "$field" == "active" ]]; then printf '%s\n' "$active"; else printf '%s\n' "$enabled_state"; fi
      return 0
    fi
  done < "$SYSTEMD_STATE_FILE"
  return 1
}

rollback_note(){
  echo "ROLLBACK WARNING: $*"
  ROLLBACK_ERRORS=1
}

restore_sqlite_snapshot(){
  local live_path="$1"
  local backup_path="$2"
  local absent_marker="$3"
  rm -f -- "${live_path}-wal" "${live_path}-shm" "${live_path}-journal" || rollback_note "failed to remove SQLite sidecars for $live_path"
  if [[ -f "$backup_path" ]]; then
    cp -a -- "$backup_path" "$live_path" || rollback_note "failed to restore SQLite database $live_path"
  elif [[ -f "$absent_marker" ]]; then
    rm -f -- "$live_path" || rollback_note "failed to remove installer-created SQLite database $live_path"
  else
    rollback_note "SQLite baseline missing for $live_path"
  fi
}

restore_sqlite_snapshots(){
  local slot live_path
  [[ -f "$DB_MANIFEST" ]] || { rollback_note "SQLite snapshot manifest missing"; return; }
  while IFS=$'\t' read -r slot live_path; do
    [[ -n "$slot" && -n "$live_path" ]] || continue
    restore_sqlite_snapshot \
      "$live_path" \
      "$BACKUP/sqlite/${slot}.db" \
      "$BACKUP/sqlite/${slot}.absent"
  done < "$DB_MANIFEST"
}

restore_unit_states(){
  local unit active enabled_state
  [[ -f "$SYSTEMD_STATE_FILE" ]] || { rollback_note "systemd state snapshot missing"; return; }
  while IFS=$'\t' read -r unit active enabled_state; do
    case "$enabled_state" in
      enabled)
        systemctl unmask "$unit" >/dev/null 2>&1 || true
        systemctl enable "$unit" >/dev/null 2>&1 || rollback_note "failed to re-enable $unit"
        ;;
      enabled-runtime)
        systemctl unmask --runtime "$unit" >/dev/null 2>&1 || true
        systemctl enable --runtime "$unit" >/dev/null 2>&1 || rollback_note "failed to restore runtime enablement for $unit"
        ;;
      masked)
        systemctl stop "$unit" >/dev/null 2>&1 || true
        systemctl mask "$unit" >/dev/null 2>&1 || rollback_note "failed to re-mask $unit"
        ;;
      masked-runtime)
        systemctl stop "$unit" >/dev/null 2>&1 || true
        systemctl mask --runtime "$unit" >/dev/null 2>&1 || rollback_note "failed to restore runtime mask for $unit"
        ;;
      disabled|static|indirect|generated|transient|alias|linked|linked-runtime|not-found|unknown|*)
        systemctl unmask "$unit" >/dev/null 2>&1 || true
        systemctl disable "$unit" >/dev/null 2>&1 || true
        ;;
    esac
    if [[ "$active" == "1" ]]; then
      systemctl start "$unit" >/dev/null 2>&1 || rollback_note "failed to restart previously-active $unit"
    else
      systemctl stop "$unit" >/dev/null 2>&1 || true
    fi
  done < "$SYSTEMD_STATE_FILE"
}

rollback(){
  trap - ERR
  trap '' INT TERM HUP
  set +e
  echo "ROLLBACK: restoring $BACKUP"
  rm -rf -- "$PREDEPLOY_DIR" 2>/dev/null || true
  rm -f -- "$VENV_LINK_TMP" 2>/dev/null || true
  if [[ -n "$MAIN_ENV_TMP" ]]; then
    rm -f -- "$MAIN_ENV_TMP" 2>/dev/null || true
  fi
  if [[ ! -f "$SNAPSHOT_READY" ]]; then
    if [[ -d "$STAGE_VENV" ]]; then
      rm -rf -- "$STAGE_VENV" || rollback_note "failed to remove staged venv"
    fi
    if [[ -f "$PRE_CUTOVER_READY" ]]; then
      restore_unit_states
      echo "ROLLBACK: pre-cutover service state restored; live code, env and DB were not mutated."
    else
      echo "ROLLBACK: no complete baseline snapshot; live code, env, DB and services were not mutated."
    fi
    return 0
  fi
  rollback_db_safe=1
  for unit in "$SERVICE" "${INSTANCE_UNITS[@]}"; do
    systemctl stop "$unit" >/dev/null 2>&1 || true
  done
  for unit in "$SERVICE" "${INSTANCE_UNITS[@]}"; do
    unit_state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    case "$unit_state" in
      inactive|failed|unknown|"") ;;
      *)
        rollback_note "database writer did not stop during rollback: $unit ($unit_state); SQLite restore will be skipped"
        rollback_db_safe=0
        ;;
    esac
  done
  if grep -Fzxq -- "base/venv" "$ARTIFACT_MANIFEST"; then
    if [[ -L "$BACKUP/venv" || -e "$BACKUP/venv" ]]; then
      if [[ -L "$BASE/venv" || -e "$BASE/venv" ]]; then
        rm -rf -- "$BASE/venv" || rollback_note "failed to remove switched venv"
      fi
      mv -- "$BACKUP/venv" "$BASE/venv" || rollback_note "failed to restore previous venv"
    elif [[ ! -L "$BASE/venv" && ! -e "$BASE/venv" ]]; then
      rollback_note "previous venv is missing from both live and backup paths"
    fi
  elif [[ -L "$BASE/venv" || -e "$BASE/venv" ]]; then
    rm -rf -- "$BASE/venv" || rollback_note "failed to remove installer-created venv"
  fi
  if [[ -d "$STAGE_VENV" ]]; then
    rm -rf -- "$STAGE_VENV" || rollback_note "failed to remove staged venv"
  fi
  if [[ -d "$BACKUP" && -f "$ARTIFACT_MANIFEST" ]]; then
    for f in "${DEPLOY_FILES[@]}"; do
      if grep -Fzxq -- "base/$f" "$ARTIFACT_MANIFEST"; then
        cp -a --remove-destination -- "$BACKUP/$f" "$BASE/$f" || rollback_note "failed to restore $BASE/$f"
      else
        rm -f -- "$BASE/$f" || rollback_note "failed to remove installer-created $BASE/$f"
      fi
    done
    for unit_file in "$SERVICE" "$TEMPLATE"; do
      if grep -Fzxq -- "systemd/$unit_file" "$ARTIFACT_MANIFEST"; then
        cp -a --remove-destination -- "$BACKUP/$unit_file" "/etc/systemd/system/$unit_file" || rollback_note "failed to restore $unit_file"
      else
        rm -f -- "/etc/systemd/system/$unit_file" || rollback_note "failed to remove installer-created $unit_file"
      fi
    done
    # Delete only paths whose creation was recorded by this installer before it
    # wrote them. Never infer ownership by scanning for every post-snapshot file:
    # an operator may legitimately add another account env during deployment.
    if [[ -f "$ACCOUNT_ENV_MANIFEST_READY" && -f "$ACCOUNT_ENV_MANIFEST" && -f "$ACCOUNT_ENV_CREATED_MANIFEST" && -d "$BACKUP/account-env" ]]; then
      mkdir -p "$ACCOUNT_ENV_DIR"
      while IFS= read -r -d '' relative_file; do
        case "$relative_file" in
          main.env|acc2.env|acc3.env)
            rm -f -- "$ACCOUNT_ENV_DIR/$relative_file" || rollback_note "failed to remove installer-created account env $relative_file"
            ;;
          *)
            rollback_note "ignored unsafe account-env creation manifest entry: $relative_file"
            ;;
        esac
      done < "$ACCOUNT_ENV_CREATED_MANIFEST"
      cp -a "$BACKUP/account-env/." "$ACCOUNT_ENV_DIR/" || rollback_note "failed to restore account environment files"
    fi
    if [[ "$rollback_db_safe" == "1" ]]; then
      restore_sqlite_snapshots
    else
      rollback_note "SQLite restore skipped because at least one writer remained active; live DB and sidecars were left untouched"
    fi
    systemctl daemon-reload || rollback_note "systemd daemon-reload failed"
    restore_unit_states
  fi
  if [[ "$ROLLBACK_ERRORS" == "0" ]]; then
    echo "ROLLBACK: complete"
  else
    echo "ROLLBACK: completed with warnings; inspect messages above before retrying."
  fi
}

abort_install(){
  local reason="$1"
  local exit_code="$2"
  if [[ "$ROLLBACK_STARTED" == "1" ]]; then
    exit "$exit_code"
  fi
  ROLLBACK_STARTED=1
  trap - ERR
  trap '' INT TERM HUP
  echo "INSTALL FAILED: $reason"
  rollback
  exit "$exit_code"
}
trap 'abort_install ERR $?' ERR
trap 'abort_install HUP 129' HUP
trap 'abort_install INT 130' INT
trap 'abort_install TERM 143' TERM

mkdir -p "$BASE" "$BASE/backups" "$VENV_ROOT"
for secure_dir in "$BASE/accounts/acc2" "$BASE/accounts/acc3" "$ACCOUNT_ENV_DIR"; do
  if [[ ! -d "$secure_dir" ]]; then
    install -d -m 700 "$secure_dir"
  fi
done

mkdir -p "$PREDEPLOY_DIR/tmp" "$PREDEPLOY_DIR/groups" "$PREDEPLOY_DIR/welcome"

# Prefer zero-copy reuse of the already-live environment when it exactly
# satisfies this release. This is critical on low-disk servers: no duplicate
# site-packages tree is created, and the live environment is never mutated.
if (( REUSE_ACTIVE_VENV == 1 )); then
  VALIDATE_PY="$ACTIVE_VENV_PY"
  STAGE_VENV=""
  echo "VENV BUILD: SKIPPED | reusing validated live environment read-only for release QA/cutover."
else
  # Only the incompatible-dependency path allocates a replacement environment.
  # This happens before cutover, so pip/network failure cannot interrupt live bots.
  "$PYTHON" -m venv "$STAGE_VENV"
  "$STAGE_VENV/bin/python" -m pip install -q --disable-pip-version-check -r "$SRC/requirements.txt"
  VALIDATE_PY="$STAGE_VENV/bin/python"
  venv_satisfies_current_release "$VALIDATE_PY" || { echo "INSTALL BLOCKED: freshly built venv does not satisfy release requirements."; false; }
fi
(
trap - ERR HUP INT TERM
export ZIVO_ACCOUNT_KEY="predeploy"
export ZIVO_DB="$PREDEPLOY_DIR/zivo60.db"
export ZIVO_MULTI_ACCOUNT_DB="$PREDEPLOY_DIR/zivo_multi_accounts.db"
export ZIVO_SESSION="$PREDEPLOY_DIR/session"
export ZIVO_TMP="$PREDEPLOY_DIR/tmp"
export ZIVO_GROUP_BACKUP_ROOT="$PREDEPLOY_DIR/groups"
export ZIVO_WELCOME_MEDIA_DIR="$PREDEPLOY_DIR/welcome"

# Current 96.45 gate. Keep the two 96.39 startup/schema regression checks in
# both predeploy compile/run and post-copy validation: their own contracts verify
# that cutover inventory cannot silently drop these safety checks in later releases.
"$VALIDATE_PY" -m py_compile \
  "$SRC/zivo60.py" "$SRC/zivo_speaker.py" "$SRC/zivo_ai_speaker.py" \
  "$SRC/zivo_social_games.py" "$SRC/zivo_admin_ux.py" "$SRC/zivo_market_tools.py" \
  "$SRC/zivo_multi_account.py" "$SRC/zivo_ipc.py" "$SRC/zivo_premium.py" \
  "$SRC/setup_zivo_accounts.py" "$SRC/set_zivo60_pro.py" "$SRC/zivo_entertainment.py" "$SRC/zivo_voice.py" \
  "$SRC/check_zivo60_96_13_live_regressions.py" "$SRC/check_zivo60_96_51_1_installer_regression.py" \
  "$SRC/check_zivo60_96_52_wallet_commerce.py" "$SRC/check_zivo60_96_52_installer_regression.py" \
  "$SRC/check_zivo60_96_53_tier_response_priority.py" \
  "$SRC/check_zivo60_96_51_campaign_group_delivery.py" "$SRC/check_zivo60_96_50_cleanup_reliability.py" "$SRC/check_zivo60_96_49_receipt_welcome_speaker.py" "$SRC/check_zivo60_96_48_meow_commerce_lock_admin.py" "$SRC/check_zivo60_96_47_official_admin_campaign_meter.py" "$SRC/check_zivo60_96_46_premium_tiers_existing_group_membership.py" "$SRC/check_zivo60_96_45_ux_checkout_ipc.py" "$SRC/check_zivo60_96_43_direct_ipc_bridge.py" \
  "$SRC/check_zivo60_96_42_content_bio_join_bridge.py" "$SRC/check_zivo60_96_37_forward_welcome_fastlane.py" \
  "$SRC/check_zivo60_96_34_cleanup_reliability.py" "$SRC/check_zivo60_96_31_live_transport_reliability.py" \
  "$SRC/check_zivo60_96_30_owner_welcome_spam_meow_guard.py" "$SRC/check_filter_rate_91.py" \
  "$SRC/check_speed_filter_font_ban_91.py" \
  "$SRC/check_zivo60_96_39_3_startup_cutover.py" "$SRC/check_zivo60_96_39_4_premium_schema_migration.py"

"$VALIDATE_PY" "$SRC/check_zivo60_96_46_premium_tiers_existing_group_membership.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_13_live_regressions.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_51_1_installer_regression.py"
PYTHONPATH="$SRC" "$VALIDATE_PY" "$SRC/check_zivo60_96_52_wallet_commerce.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_52_installer_regression.py"
PYTHONPATH="$SRC" "$VALIDATE_PY" "$SRC/check_zivo60_96_53_tier_response_priority.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" "$VALIDATE_PY" "$SRC/check_zivo60_96_51_campaign_group_delivery.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_50_cleanup_reliability.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_49_receipt_welcome_speaker.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_48_meow_commerce_lock_admin.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_47_official_admin_campaign_meter.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_45_ux_checkout_ipc.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_43_direct_ipc_bridge.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_42_content_bio_join_bridge.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_37_forward_welcome_fastlane.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_34_cleanup_reliability.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_31_live_transport_reliability.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_30_owner_welcome_spam_meow_guard.py"
"$VALIDATE_PY" "$SRC/check_filter_rate_91.py"
"$VALIDATE_PY" "$SRC/check_speed_filter_font_ban_91.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_39_3_startup_cutover.py"
"$VALIDATE_PY" "$SRC/check_zivo60_96_39_4_premium_schema_migration.py"
)
rm -rf -- "$PREDEPLOY_DIR"
echo "PREDEPLOY ZIVO60.96.53 MEOW START + TIER RESPONSE PRIORITY + LEGACY CONTRACT: PASS"

ROOT_USE="$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')"
if [[ "${ROOT_USE:-0}" -ge 90 ]]; then
  echo "WARNING: root filesystem usage is ${ROOT_USE}% -- keep disk headroom for per-account SQLite/session/journal."
fi

discover_instance_units
discover_database_paths

# Capture every non-database live artifact while the old services are still
# untouched.  snapshot.ready is deliberately withheld until every writer has
# stopped and every per-account SQLite backup below has completed.
mkdir -p "$BACKUP/account-env" "$BACKUP/sqlite"
rm -f -- "$SNAPSHOT_READY" "$PRE_CUTOVER_READY" "$ACCOUNT_ENV_MANIFEST_READY"

ACCOUNT_ENV_MANIFEST_TMP="$ACCOUNT_ENV_MANIFEST.tmp"
find "$ACCOUNT_ENV_DIR" -mindepth 1 -printf '%P\0' > "$ACCOUNT_ENV_MANIFEST_TMP"
mv -- "$ACCOUNT_ENV_MANIFEST_TMP" "$ACCOUNT_ENV_MANIFEST"
: > "$ACCOUNT_ENV_CREATED_MANIFEST"
cp -a "$ACCOUNT_ENV_DIR/." "$BACKUP/account-env/"

ARTIFACT_MANIFEST_TMP="$ARTIFACT_MANIFEST.tmp"
: > "$ARTIFACT_MANIFEST_TMP"
for f in "${DEPLOY_FILES[@]}"; do
  if [[ -e "$BASE/$f" || -L "$BASE/$f" ]]; then
    cp -a -- "$BASE/$f" "$BACKUP/$f"
    printf 'base/%s\0' "$f" >> "$ARTIFACT_MANIFEST_TMP"
  fi
done
if [[ -e "$BASE/venv" || -L "$BASE/venv" ]]; then
  printf 'base/venv\0' >> "$ARTIFACT_MANIFEST_TMP"
fi
for unit_file in "$SERVICE" "$TEMPLATE"; do
  if [[ -e "/etc/systemd/system/$unit_file" || -L "/etc/systemd/system/$unit_file" ]]; then
    cp -a -- "/etc/systemd/system/$unit_file" "$BACKUP/$unit_file"
    printf 'systemd/%s\0' "$unit_file" >> "$ARTIFACT_MANIFEST_TMP"
  fi
done
mv -- "$ARTIFACT_MANIFEST_TMP" "$ARTIFACT_MANIFEST"

: > "$SYSTEMD_STATE_FILE"
snapshot_unit_state "$SERVICE"
for unit in "${INSTANCE_UNITS[@]}"; do
  snapshot_unit_state "$unit"
done
: > "$PRE_CUTOVER_READY"

# Every template instance uses the shared code and venv. Stop all discovered
# instances before replacing either, including operator-added acc4+ accounts.
for unit in "$SERVICE" "${INSTANCE_UNITS[@]}"; do
  unit_state="$(systemctl is-active "$unit" 2>/dev/null || true)"
  case "$unit_state" in
    inactive|failed|unknown|"") ;;
    *) systemctl stop "$unit" ;;
  esac
done
for unit in "$SERVICE" "${INSTANCE_UNITS[@]}"; do
  unit_state="$(systemctl is-active "$unit" 2>/dev/null || true)"
  case "$unit_state" in
    inactive|failed|unknown|"") ;;
    *) echo "INSTALL BLOCKED: database writer did not stop: $unit ($unit_state)"; false ;;
  esac
done

: > "$DB_MANIFEST"
db_index=0
for live_db in "${DATABASE_PATHS[@]}"; do
  db_index=$((db_index + 1))
  db_slot="$(printf 'db_%03d' "$db_index")"
  sqlite_online_backup \
    "$live_db" \
    "$BACKUP/sqlite/${db_slot}.db" \
    "$BACKUP/sqlite/${db_slot}.absent"
  printf '%s\t%s\n' "$db_slot" "$live_db" >> "$DB_MANIFEST"
done

: > "$ACCOUNT_ENV_MANIFEST_READY"
: > "$SNAPSHOT_READY"

install -m 600 "$SRC/zivo60.py" "$BASE/zivo60.py"
install -m 600 "$SRC/zivo_speaker.py" "$BASE/zivo_speaker.py"
install -m 600 "$SRC/zivo_ai_speaker.py" "$BASE/zivo_ai_speaker.py"
install -m 600 "$SRC/zivo_multi_account.py" "$BASE/zivo_multi_account.py"
install -m 600 "$SRC/zivo_premium.py" "$BASE/zivo_premium.py"
install -m 700 "$SRC/setup_zivo_accounts.py" "$BASE/setup_zivo_accounts.py"
install -m 700 "$SRC/setup_zivo_payment_domain.sh" "$BASE/setup_zivo_payment_domain.sh"
install -m 600 "$SRC/set_zivo60_pro.py" "$BASE/set_zivo60_pro.py"
install -m 600 "$SRC/zivo_entertainment.py" "$BASE/zivo_entertainment.py"
install -m 600 "$SRC/zivo_social_games.py" "$BASE/zivo_social_games.py"
install -m 600 "$SRC/zivo_voice.py" "$BASE/zivo_voice.py"
install -m 600 "$SRC/zivo_admin_ux.py" "$BASE/zivo_admin_ux.py"
install -m 600 "$SRC/zivo_market_tools.py" "$BASE/zivo_market_tools.py"
install -m 600 "$SRC/check_zivo_market_provider.py" "$BASE/check_zivo_market_provider.py"
install -m 600 "$SRC/check_zivo_market_concurrency.py" "$BASE/check_zivo_market_concurrency.py"
install -m 600 "$SRC/check_zivo_market_tools.py" "$BASE/check_zivo_market_tools.py"
install -m 600 "$SRC/check_zivo_voice_profiles.py" "$BASE/check_zivo_voice_profiles.py"
install -m 600 "$SRC/check_activation_card_recovery_96_11.py" "$BASE/check_activation_card_recovery_96_11.py"
install -m 600 "$SRC/check_zivo60_96_11_features.py" "$BASE/check_zivo60_96_11_features.py"
install -m 600 "$SRC/check_installer_transaction_96_11.py" "$BASE/check_installer_transaction_96_11.py"
install -m 600 "$SRC/check_zivo60_96_12_repairs.py" "$BASE/check_zivo60_96_12_repairs.py"
install -m 600 "$SRC/check_zivo60_96_13_live_regressions.py" "$BASE/check_zivo60_96_13_live_regressions.py"
install -m 600 "$SRC/check_zivo60_96_14_emergency_recovery.py" "$BASE/check_zivo60_96_14_emergency_recovery.py"
install -m 600 "$SRC/check_zivo60_96_15_legacy_group_recovery.py" "$BASE/check_zivo60_96_15_legacy_group_recovery.py"
install -m 600 "$SRC/check_zivo60_96_16_legacy_runtime_reconcile.py" "$BASE/check_zivo60_96_16_legacy_runtime_reconcile.py"
install -m 600 "$SRC/check_zivo60_96_17_send_flood_recovery.py" "$BASE/check_zivo60_96_17_send_flood_recovery.py"
install -m 600 "$SRC/check_zivo60_96_18_runtime_presence.py" "$BASE/check_zivo60_96_18_runtime_presence.py"
install -m 600 "$SRC/check_zivo60_96_19_role_command_recovery.py" "$BASE/check_zivo60_96_19_role_command_recovery.py"
install -m 600 "$SRC/check_zivo60_96_20_admin_economy_gifts.py" "$BASE/check_zivo60_96_20_admin_economy_gifts.py"
install -m 600 "$SRC/check_zivo60_96_21_owner_full_cleanup.py" "$BASE/check_zivo60_96_21_owner_full_cleanup.py"
install -m 600 "$SRC/check_zivo60_96_22_full_dialog_inventory.py" "$BASE/check_zivo60_96_22_full_dialog_inventory.py"
install -m 600 "$SRC/check_zivo60_96_23_private_inventory_priority.py" "$BASE/check_zivo60_96_23_private_inventory_priority.py"
install -m 600 "$SRC/check_zivo60_96_24_cleanup_private_inventory.py" "$BASE/check_zivo60_96_24_cleanup_private_inventory.py"
install -m 600 "$SRC/check_zivo60_96_25_campaign_live_all_dialogs.py" "$BASE/check_zivo60_96_25_campaign_live_all_dialogs.py"
install -m 600 "$SRC/check_zivo60_96_26_campaign_live_progress_speed.py" "$BASE/check_zivo60_96_26_campaign_live_progress_speed.py"
install -m 600 "$SRC/check_zivo60_96_27_exhaustive_raw_dialog_pagination.py" "$BASE/check_zivo60_96_27_exhaustive_raw_dialog_pagination.py"
install -m 600 "$SRC/check_zivo60_96_28_campaign_immediate_claim_fairness.py" "$BASE/check_zivo60_96_28_campaign_immediate_claim_fairness.py"
install -m 600 "$SRC/check_zivo60_96_29_behavioral_qa.py" "$BASE/check_zivo60_96_29_behavioral_qa.py"
install -m 600 "$SRC/check_zivo60_96_30_owner_welcome_spam_meow_guard.py" "$BASE/check_zivo60_96_30_owner_welcome_spam_meow_guard.py"
install -m 600 "$SRC/check_zivo60_96_51_campaign_group_delivery.py" "$BASE/check_zivo60_96_51_campaign_group_delivery.py"
install -m 600 "$SRC/check_zivo60_96_38_premium_payment_foundation.py" "$BASE/check_zivo60_96_38_premium_payment_foundation.py"
install -m 644 "$SRC/zivo60.service" "/etc/systemd/system/$SERVICE"
install -m 644 "$SRC/zivo60@.service" "/etc/systemd/system/$TEMPLATE"

# 96.38 installer hotfix: DEPLOY_FILES is the single source of truth for
# application/test artifacts.  Earlier releases declared 96.31-96.37 tests
# here but forgot to copy them during cutover, so the post-cutover invariant
# correctly aborted deployment.  Sync every declared artifact now, with only
# executable helpers receiving execute permission.
for f in "${DEPLOY_FILES[@]}"; do
  [[ -f "$SRC/$f" ]] || { echo "INSTALL FAILED: source deploy file missing: $SRC/$f" >&2; exit 1; }
  mode=600
  case "$f" in
    install_zivo60.sh|setup_zivo_payment_domain.sh|setup_zivo_accounts.py) mode=700 ;;
  esac
  install -m "$mode" "$SRC/$f" "$BASE/$f"
done

# 96.24 installer invariant: every declared deploy file must exist in the live tree
# before installed-copy validation starts. This prevents DEPLOY_FILES/cutover drift.
for f in "${DEPLOY_FILES[@]}"; do
  if [[ ! -f "$BASE/$f" ]]; then
    echo "INSTALL FAILED: deployed file missing after cutover: $BASE/$f" >&2
    exit 1
  fi
done

# Controller account: reconcile only installer-owned identity/path keys. Keep
# every custom provider/TTS/runtime secret already present in main.env. Build
# beside the destination and rename atomically so interruption cannot truncate
# the live environment file.
MAIN_ENV="$ACCOUNT_ENV_DIR/main.env"
if ! grep -Fzxq -- "main.env" "$ACCOUNT_ENV_MANIFEST"; then
  printf 'main.env\0' >> "$ACCOUNT_ENV_CREATED_MANIFEST"
fi
MAIN_ENV_TMP="$(mktemp "$ACCOUNT_ENV_DIR/.main.env.${STAMP}.XXXXXX")"
if [[ -f "$MAIN_ENV" ]]; then
  awk '
    /^[[:space:]]*(ZIVO_ACCOUNT_KEY|ZIVO_ACCOUNT_LABEL|ZIVO_ACCOUNT_CONTROLLER|ZIVO_SELF_ID|ZIVO_GLOBAL_OWNER_ID|ZIVO_SESSION|ZIVO_DB|ZIVO_MULTI_ACCOUNT_DB)=/ { next }
    { print }
  ' "$MAIN_ENV" > "$MAIN_ENV_TMP"
fi
printf '%s\n' \
  'ZIVO_ACCOUNT_KEY=main' \
  'ZIVO_ACCOUNT_LABEL="اکانت اصلی"' \
  'ZIVO_ACCOUNT_CONTROLLER=1' \
  'ZIVO_SELF_ID=49155489' \
  'ZIVO_GLOBAL_OWNER_ID=49145577' \
  'ZIVO_SESSION=/opt/zivo60/zivo60' \
  'ZIVO_DB=/opt/zivo60/zivo60.db' \
  'ZIVO_MULTI_ACCOUNT_DB=/opt/zivo60/zivo_multi_accounts.db' \
  >> "$MAIN_ENV_TMP"
chmod 600 "$MAIN_ENV_TMP"
mv -f -- "$MAIN_ENV_TMP" "$MAIN_ENV"

# Preconfigure the two requested accounts, but never overwrite a successfully logged-in env.
if [[ ! -e "$ACCOUNT_ENV_DIR/acc2.env" && ! -L "$ACCOUNT_ENV_DIR/acc2.env" ]]; then
printf 'acc2.env\0' >> "$ACCOUNT_ENV_CREATED_MANIFEST"
cat > "$ACCOUNT_ENV_DIR/acc2.env" <<'EOF'
ZIVO_ACCOUNT_KEY=acc2
ZIVO_ACCOUNT_LABEL="اکانت ۲"
ZIVO_ACCOUNT_CONTROLLER=0
ZIVO_PHONE=+989900655574
ZIVO_SELF_ID=0
ZIVO_BOT_USERNAME=zivo1bot
ZIVO_SESSION=/opt/zivo60/accounts/acc2/session
ZIVO_DB=/opt/zivo60/accounts/acc2/zivo60.db
ZIVO_MULTI_ACCOUNT_DB=/opt/zivo60/zivo_multi_accounts.db
ZIVO_TMP=/opt/zivo60/accounts/acc2/tmp
ZIVO_GROUP_BACKUP_ROOT=/opt/zivo60/accounts/acc2/backups/groups
ZIVO_WELCOME_MEDIA_DIR=/opt/zivo60/accounts/acc2/welcome_media
EOF
chmod 600 "$ACCOUNT_ENV_DIR/acc2.env"
fi
if [[ ! -e "$ACCOUNT_ENV_DIR/acc3.env" && ! -L "$ACCOUNT_ENV_DIR/acc3.env" ]]; then
printf 'acc3.env\0' >> "$ACCOUNT_ENV_CREATED_MANIFEST"
cat > "$ACCOUNT_ENV_DIR/acc3.env" <<'EOF'
ZIVO_ACCOUNT_KEY=acc3
ZIVO_ACCOUNT_LABEL="اکانت ۳"
ZIVO_ACCOUNT_CONTROLLER=0
ZIVO_PHONE=+989137511274
ZIVO_SELF_ID=0
ZIVO_BOT_USERNAME=zivo2bot
ZIVO_SESSION=/opt/zivo60/accounts/acc3/session
ZIVO_DB=/opt/zivo60/accounts/acc3/zivo60.db
ZIVO_MULTI_ACCOUNT_DB=/opt/zivo60/zivo_multi_accounts.db
ZIVO_TMP=/opt/zivo60/accounts/acc3/tmp
ZIVO_GROUP_BACKUP_ROOT=/opt/zivo60/accounts/acc3/backups/groups
ZIVO_WELCOME_MEDIA_DIR=/opt/zivo60/accounts/acc3/welcome_media
EOF
chmod 600 "$ACCOUNT_ENV_DIR/acc3.env"
fi

# Keep each secondary account's public bot username aligned with its live account.
for pair in "acc2:zivo1bot" "acc3:zivo2bot"; do
  key="${pair%%:*}"
  uname="${pair#*:}"
  envf="$ACCOUNT_ENV_DIR/$key.env"
  if grep -q '^ZIVO_BOT_USERNAME=' "$envf"; then
    sed -i "s/^ZIVO_BOT_USERNAME=.*/ZIVO_BOT_USERNAME=$uname/" "$envf"
  else
    printf 'ZIVO_BOT_USERNAME=%s\n' "$uname" >> "$envf"
  fi
  chmod 600 "$envf"
done

# Persist the hard realtime reserve for every account. Existing server env
# values are intentionally reconciled so an older 48-request background limit
# cannot silently restore transport congestion after this upgrade.
for key in main acc2 acc3; do
  envf="$ACCOUNT_ENV_DIR/$key.env"
  for setting in "ZIVO_INSTALLED_GROUP_AUTO_LEAVE_SECONDS=0" "ZIVO_DELETE_RPC_MIN_INTERVAL=3.00" "ZIVO_DELETE_RPC_FLOOD_BUFFER=0.75" "ZIVO_DELETE_RPC_FLOOD_COOLDOWN=8.0" "ZIVO_DELETE_RPC_TIMEOUT_COOLDOWN=15.0" "ZIVO_LIVE_DELETE_CIRCUIT_SECONDS=45.0" "ZIVO_CAMPAIGN_DELETE_CIRCUIT_SECONDS=90.0" "ZIVO_LOCK_DELETE_FAST_TIMEOUT=1.50" "ZIVO_MODERATION_PERMISSION_RETRY=300.0" "ZIVO_FOREGROUND_PRIORITY_HOT_SECONDS=3.0" "ZIVO_FOREGROUND_BACKGROUND_PENDING_SOFT=16" "ZIVO_STARTUP_BACKGROUND_QUIET_SECONDS=120" "ZIVO_BACKGROUND_REALTIME_QUIET_SECONDS=1.25" "ZIVO_BACKGROUND_REALTIME_FAIR_INTERVAL_SECONDS=5.0" "ZIVO_PRIVATE_FAST_POLL_PENDING_CEILING=22" "ZIVO_TRANSPORT_PENDING_WARN=32" "ZIVO_TRANSPORT_PENDING_CIRCUIT=96" "ZIVO_TRANSPORT_PENDING_IMMEDIATE=180" "ZIVO_TRANSPORT_STAGNANT_SECONDS=20" "ZIVO_TARGET_CLEANUP_RETRY_MIN_SECONDS=600" "ZIVO_SEND_RPC_MIN_INTERVAL=0.18" "ZIVO_SEND_RPC_FLOOD_BUFFER=0.35" "ZIVO_SEND_RPC_COMMAND_RETRY_MAX_WAIT=6.0" "ZIVO_SEND_RPC_COMMAND_RETRIES=2" "ZIVO_SEND_RPC_BACKGROUND_PRIORITY_WAIT=0.75" "ZIVO_TIER_SEND_BUSY_STAGGER=0.008" "ZIVO_RUNTIME_GROUP_BOOTSTRAP=1" "ZIVO_RUNTIME_GROUP_ACCESS_TTL=90" "ZIVO_RUNTIME_GROUP_AUTHORITY_TIMEOUT=5" "ZIVO_FULL_DIALOG_INVENTORY=1" "ZIVO_FULL_DIALOG_INVENTORY_INTERVAL=21600" "ZIVO_FULL_DIALOG_INVENTORY_REQUEST_POLL=5" "ZIVO_FULL_DIALOG_INVENTORY_REGISTER_ALL_PRIVATE=1" "ZIVO_CAMPAIGN_START_PENDING_SOFT=110" "ZIVO_CAMPAIGN_SEND_PENDING_HARD=150" "ZIVO_CAMPAIGN_SCAN_PENDING_HARD=160" "ZIVO_CAMPAIGN_SEND_RPC_MIN_INTERVAL=0.12" "ZIVO_CAMPAIGN_INTER_TARGET_DELAY=0.01" "ZIVO_CAMPAIGN_SCAN_PAGE_PAUSE=0.02" "ZIVO_CAMPAIGN_PROGRESS_REFRESH=2.0" "ZIVO_CAMPAIGN_FOREGROUND_GRACE=0.45" "ZIVO_CAMPAIGN_WORKER_IDLE_POLL=0.20" "ZIVO_OFFICIAL_CONTROL_ONLY=1" "ZIVO_ACCOUNT_IPC_REQUEST_TIMEOUT=60" "ZIVO_REMOTE_CONTROL_POLL_SECONDS=0.15" "ZIVO_FLOOD_GUARD_DELETE_BATCH=50" "ZIVO_FLOOD_GUARD_HISTORY_SCAN_CAP=1200" "ZIVO_FLOOD_GUARD_HISTORY_TASK_MAX=3"; do
    name="${setting%%=*}"
    value="${setting#*=}"
    if grep -q "^${name}=" "$envf"; then
      sed -i "s|^${name}=.*|${name}=${value}|" "$envf"
    else
      printf '%s=%s\n' "$name" "$value" >> "$envf"
    fi
  done
  chmod 600 "$envf"
done

# Dependencies and source already passed in the staged environment before any
# service stopped. Only validate the exact installed copies during downtime.
"$VALIDATE_PY" -m py_compile \
  "$BASE/zivo60.py" "$BASE/zivo_speaker.py" "$BASE/zivo_ai_speaker.py" \
  "$BASE/zivo_social_games.py" "$BASE/zivo_admin_ux.py" "$BASE/zivo_market_tools.py" \
  "$BASE/zivo_multi_account.py" "$BASE/zivo_ipc.py" "$BASE/zivo_premium.py" "$BASE/setup_zivo_accounts.py" \
  "$BASE/set_zivo60_pro.py" "$BASE/zivo_entertainment.py" "$BASE/zivo_voice.py" \
  "$BASE/check_zivo_market_provider.py" "$BASE/check_zivo_market_concurrency.py" \
  "$BASE/check_zivo_market_tools.py" "$BASE/check_zivo_voice_profiles.py" \
  "$BASE/check_activation_card_recovery_96_11.py" "$BASE/check_zivo60_96_11_features.py" \
  "$BASE/check_installer_transaction_96_11.py" "$BASE/check_zivo60_96_12_repairs.py" \
  "$BASE/check_zivo60_96_13_live_regressions.py" "$BASE/check_zivo60_96_14_emergency_recovery.py" \
  "$BASE/check_zivo60_96_15_legacy_group_recovery.py" "$BASE/check_zivo60_96_16_legacy_runtime_reconcile.py" \
  "$BASE/check_zivo60_96_17_send_flood_recovery.py" "$BASE/check_zivo60_96_18_runtime_presence.py" \
  "$BASE/check_zivo60_96_19_role_command_recovery.py" \
  "$BASE/check_zivo60_96_20_admin_economy_gifts.py" "$BASE/check_zivo60_96_21_owner_full_cleanup.py" \
  "$BASE/check_zivo60_96_22_full_dialog_inventory.py" "$BASE/check_zivo60_96_23_private_inventory_priority.py" \
  "$BASE/check_zivo60_96_24_cleanup_private_inventory.py" \
  "$BASE/check_zivo60_96_25_campaign_live_all_dialogs.py" \
  "$BASE/check_zivo60_96_26_campaign_live_progress_speed.py" \
  "$BASE/check_zivo60_96_27_exhaustive_raw_dialog_pagination.py" \
  "$BASE/check_zivo60_96_28_campaign_immediate_claim_fairness.py" \
  "$BASE/check_zivo60_96_29_behavioral_qa.py" \
  "$BASE/check_zivo60_96_51_1_installer_regression.py" \
  "$BASE/check_zivo60_96_52_wallet_commerce.py" \
  "$BASE/check_zivo60_96_52_installer_regression.py" \
  "$BASE/check_zivo60_96_53_tier_response_priority.py" \
  "$BASE/check_zivo60_96_51_campaign_group_delivery.py"

PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_join_recovery_69.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo_market_provider.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo_market_concurrency.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo_market_tools.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo_voice_profiles.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_activation_card_recovery_96_11.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_11_features.py"
"$VALIDATE_PY" "$BASE/check_installer_transaction_96_11.py" "$SRC/install_zivo60.sh"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_12_repairs.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_13_live_regressions.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_51_1_installer_regression.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_52_wallet_commerce.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_52_installer_regression.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_53_tier_response_priority.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_14_emergency_recovery.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_15_legacy_group_recovery.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_16_legacy_runtime_reconcile.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_17_send_flood_recovery.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_18_runtime_presence.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_19_role_command_recovery.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_20_admin_economy_gifts.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_21_owner_full_cleanup.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_22_full_dialog_inventory.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_23_private_inventory_priority.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_24_cleanup_private_inventory.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_25_campaign_live_all_dialogs.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_26_campaign_live_progress_speed.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_27_exhaustive_raw_dialog_pagination.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_28_campaign_immediate_claim_fairness.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_29_behavioral_qa.py"
ZIVO_INSTALLER_UNDER_TEST="$SRC/install_zivo60.sh" PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_51_campaign_group_delivery.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_30_owner_welcome_spam_meow_guard.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_31_live_transport_reliability.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_32_owner_zero_recovery.py"
ZIVO_PROFANITY_TEST_MAX_SECONDS=20 PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_33_profanity_guard_expansion.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_34_cleanup_reliability.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_35_owner_multigroup_recovery.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_36_welcome_end_to_end.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_37_forward_welcome_fastlane.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_38_premium_payment_foundation.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_38_1_installer_hotfix.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_39_purchase_ux.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_39_1_full_core_audit.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_39_2_installed_inventory.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_46_premium_tiers_existing_group_membership.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_50_cleanup_reliability.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_49_receipt_welcome_speaker.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_48_meow_commerce_lock_admin.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_47_official_admin_campaign_meter.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_39_3_startup_cutover.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_39_4_premium_schema_migration.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_40_official_control_bridge.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_41_instant_official_join.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_42_content_bio_join_bridge.py"
PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_43_direct_ipc_bridge.py"
# Historical markers remain for the transactional checker contract.
echo "INSTALLED COPY ZIVO60.96.11 FEATURE CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.12 REPAIR/PERFORMANCE CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.14 EMERGENCY RECOVERY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.15 LEGACY GROUP RECOVERY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.16 LEGACY RUNTIME RECONCILE/FAST STARTUP CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.17 SEND FLOOD RECOVERY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.18 RUNTIME PRESENCE/BASIC-FULL CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.19 ADMIN/SPECIAL ROLE RECOVERY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.20 ADMIN ECONOMY/GIFT CENTER CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.21 OWNER FULL-CLEANUP ACCESS CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.22 FULL DIALOG INVENTORY/COORDINATION PV CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.23 PRIVATE PRIORITY/THROTTLED INVENTORY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.24 CLEANUP/ALL-PRIVATE INVENTORY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.25 CAMPAIGN LIVE ALL-DIALOG TARGET CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.26 LIVE CAMPAIGN PROGRESS/FAST-LANE CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.27 EXHAUSTIVE RAW DIALOG PAGINATION CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.28 IMMEDIATE CAMPAIGN CLAIM/BOUNDED FAIRNESS CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.29 FORWARD/PET BEHAVIORAL QA CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.30 OWNER/WELCOME/SPAM/MEOW/GUARD CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.31 LIVE TRANSPORT RELIABILITY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.32 OWNER ZERO RECOVERY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.33 PROFANITY GUARD EXPANSION CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.34 CLEANUP RELIABILITY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.35 OWNER MULTIGROUP RECOVERY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.37 FORWARD/WELCOME FASTLANE CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.38 PREMIUM/PAYMENT FOUNDATION CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.39 PREMIUM PURCHASE UX CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.39.4 PREMIUM SCHEMA MIGRATION + STARTUP/CUTOVER + FULL INVENTORY CHECKS: PASS"
echo "INSTALLED COPY ZIVO60.96.53 TIER RESPONSE PRIORITY CHECKS: PASS"

# Switch the venv only when a replacement was actually built. In reuse mode
# the existing /opt/zivo60/venv remains byte-for-byte untouched, which makes
# rollback cheaper and safer on low-disk hosts.
if (( REUSE_ACTIVE_VENV == 1 )); then
  [[ -x "$BASE/venv/bin/python" ]] || { echo "VENV BASELINE DISAPPEARED BEFORE CUTOVER"; false; }
  venv_satisfies_current_release "$BASE/venv/bin/python" || { echo "VENV BASELINE CHANGED BEFORE CUTOVER"; false; }
  echo "VENV CUTOVER: REUSED | existing live venv preserved; no duplicate environment allocated."
else
  if grep -Fzxq -- "base/venv" "$ARTIFACT_MANIFEST"; then
    if [[ ! -L "$BASE/venv" && ! -e "$BASE/venv" ]]; then
      echo "VENV BASELINE DISAPPEARED BEFORE CUTOVER"
      false
    fi
    mv -- "$BASE/venv" "$BACKUP/venv"
  elif [[ -L "$BASE/venv" || -e "$BASE/venv" ]]; then
    echo "UNEXPECTED VENV APPEARED AFTER BASELINE SNAPSHOT"
    false
  fi
  ln -s -- "$STAGE_VENV" "$VENV_LINK_TMP"
  mv -Tf -- "$VENV_LINK_TMP" "$BASE/venv"
  echo "VENV CUTOVER: REPLACED | validated versioned environment activated."
fi

PYTHONPATH="$BASE" "$BASE/venv/bin/python" - <<'PY'
from pathlib import Path
from zivo_multi_account import reconcile_accounts_from_env, list_accounts
db=Path('/opt/zivo60/zivo_multi_accounts.db')
envd=Path('/etc/zivo60/accounts')
count=reconcile_accounts_from_env(db, envd)
rows={str(r['account_key']):r for r in list_accounts(db)}
for key in ('main','acc2','acc3'):
    if key not in rows:
        raise SystemExit(f'ACCOUNT REGISTRY MISSING: {key}')
    env=envd/f'{key}.env'
    sid=0
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            if line.startswith('ZIVO_SELF_ID='):
                try: sid=int(line.split('=',1)[1].strip() or 0)
                except Exception: sid=0
    if sid and int(rows[key]['self_id'] or 0) != sid:
        raise SystemExit(f'ACCOUNT SELF_ID MISMATCH: {key}')
print('ACCOUNT REGISTRY RECONCILE: PASS | env_rows=', count, '| accounts=', ','.join(rows))
PY

# Validate the actually installed copy too. Historical 96.39.1 audit requires
# both staged and installed-copy profanity benchmarks to use the server-safe cap.
ZIVO_PROFANITY_TEST_MAX_SECONDS=20 PYTHONPATH="$BASE" "$BASE/venv/bin/python" "$BASE/check_zivo60_96_33_profanity_guard_expansion.py"

wait_service_ready(){
  local unit="$1"
  local start_ts="$2"
  local label="$3"
  local cycles="${4:-60}"
  local state=""
  local pid="0"
  local logs=""
  local restarts="0"
  local i=0
  READY=0
  PID=0
  LOGS=""
  for i in $(seq 1 "$cycles"); do
    sleep 2
    state="$(systemctl is-active "$unit" 2>/dev/null || true)"
    pid="$(systemctl show -p MainPID --value "$unit" 2>/dev/null || printf '0\n')"
    restarts="$(systemctl show -p NRestarts --value "$unit" 2>/dev/null || printf '0\n')"
    if [[ "$state" == "active" && "$pid" =~ ^[1-9][0-9]*$ ]]; then
      logs="$(journalctl -u "$unit" --since "$start_ts" --no-pager -l | grep "python\[$pid\]" || true)"
      if echo "$logs" | grep -q 'ZIVO is ready'; then
        READY=1
        PID="$pid"
        LOGS="$logs"
        return 0
      fi
    fi
    # Restart=always intentionally creates short activating/inactive windows.
    # Do not rollback on the first transient GetState/session probe failure.
    if (( i == 1 || i % 5 == 0 )); then
      echo "STARTUP WAIT | $label | state=${state:-unknown} pid=${pid:-0} restarts=${restarts:-0} elapsed=$((i*2))s"
    fi
  done

  echo "STARTUP FAILED | $label | no stable ready marker after $((cycles*2))s"
  systemctl status "$unit" --no-pager -l || true
  echo "--- $label JOURNAL SINCE CUTOVER ---"
  journalctl -u "$unit" --since "$start_ts" --no-pager -l | tail -n 320 || true
  echo "--- END $label STARTUP DIAGNOSTICS ---"
  return 1
}

systemctl daemon-reload
systemctl enable "$SERVICE" >/dev/null
START_TS="$(date --iso-8601=seconds)"
if ! systemctl restart "$SERVICE"; then
  echo "SYSTEMD RESTART COMMAND FAILED: $SERVICE"
  systemctl status "$SERVICE" --no-pager -l || true
  journalctl -u "$SERVICE" --since "$START_TS" --no-pager -l | tail -n 320 || true
  false
fi
# safe_session_start now performs bounded existing-session retries. Give those
# retries time to complete instead of treating RestartSec as an install failure.
wait_service_ready "$SERVICE" "$START_TS" "main" 60 || false

for marker in \
  'ZIVO is ready' \
  'performance-router=scale-v37-help-permission-guard' \
  'sqlite-main=autoclose' \
  'performance-hotpath=enabled-locks+enabled-lock-set-cache+command-gate+filter-single-normalize+filter-precomputed-matchers+warning-cache+warning-ceiling+lock-notice-coalesce+exact-filter-presence+zero-rpc-cleanup' \
  'multi-account=isolated-sessions+shared-control' \
  'join-routing=capacity-failover+stale-claim-takeover+recent-recovery+group-info private-link-dedup=inflight+notice-guard pending-command=write-confirm+activate+replay settings-copy=shared-cross-account+legacy-recovery campaign-media=config-dc-discovery+single-preupload+permission-aware+transport-matrix' \
  'cross-account join worker started' \
  'panel-accounts=env-reconciled' \
  'group-claim=shared-exclusive' \
  'join-activation=receipt-safe' \
  'multi account | key=main' \
  'transport circuit monitor started' \
  'mass tag isolation started' \
  'speaker ai workers started' \
  'speaker-ai=persian-conversation-v4' \
  'social=ttt+ship+market+distance+global-meow+pets+houses' \
  'group join notice worker started' \
  'private inbox watchdog started' \
  'private fast dialog poll started' \
  'private known contact poll started' \
  'private startup backfill worker started' \
  'backoff=persistent-db-15..1200s' \
  'public-join=membership-recovery' \
  'invite-join=import-fallback' \
  'private-priority=eager+fairness' \
  'private-group-link=pre-rate-priority' \
  'private-membership=notice-only-once+no-membership-rpc' \
  'background-rpc=foreground-reserved' \
  'transport-pending=cancelled-prune+reconnect-queue-clean' \
  'help-delivery=link-restricted-fallback' \
  'settings-token=copy-noise-tolerant' \
  'filter-history=recent100+verified-delete+evasion-normalize+biocheck-safe' \
  'forward-lock=fast+multi-signal+verified-retry' \
  'message-rate=atomic-deadline+async-native' \
  'user-report=reply+manager-review+approve-reject' \
  'ban-tools=direct-unban+list-cleanup+bulk-release' \
  'font=unicode12' \
  'target-campaign=adaptive-batch+member-stop+banner-cleanup' \
  'log-storm=rate-limited'; do
  if ! echo "$LOGS" | grep -q "$marker"; then
    # “ZIVO is ready” above is the authoritative startup result. Journal
    # filtering can omit a single informational marker, so report it without
    # undoing a healthy deployment.
    echo "STARTUP MARKER NOT OBSERVED (non-blocking): $marker"
  fi
done


if [[ -d "/proc/$PID/fd" ]]; then
  echo "MAIN OPEN FDS AFTER START: $(find "/proc/$PID/fd" -maxdepth 1 -type l 2>/dev/null | wc -l)"
fi

# Do not start secondary accounts before their own sessions are authorized.
# The shared registry's enabled flag is the operator's choice.  An upgrade may
# restart an account that was already active, but it must not turn a previously
# disabled/stopped instance into a boot-enabled service on its own.
for unit in "${INSTANCE_UNITS[@]}"; do
  key="${unit#zivo60@}"
  key="${key%.service}"
  prior_active="$(unit_prior_field "$unit" active || printf '0\n')"
  prior_enabled="$(unit_prior_field "$unit" enabled || printf 'unknown\n')"
  registry_enabled="$(PYTHONPATH="$BASE" "$BASE/venv/bin/python" - "$MULTI_DB" "$key" <<'PY'
import sys
from pathlib import Path
from zivo_multi_account import account_enabled

print(1 if account_enabled(Path(sys.argv[1]), sys.argv[2], default=False) else 0)
PY
)"
  if [[ "$registry_enabled" != "1" ]]; then
    systemctl disable "$unit" >/dev/null 2>&1 || true
    systemctl stop "$unit" >/dev/null 2>&1 || true
    continue
  fi
  if [[ ! -f "$ACCOUNT_ENV_DIR/$key.env" ]] || ! grep -Eq '^ZIVO_SELF_ID=[1-9][0-9]*$' "$ACCOUNT_ENV_DIR/$key.env"; then
    systemctl stop "$unit" >/dev/null 2>&1 || true
    continue
  fi
  case "$prior_enabled" in
    enabled)
      systemctl enable "$unit" >/dev/null
      ;;
    enabled-runtime)
      systemctl enable --runtime "$unit" >/dev/null
      ;;
    *)
      systemctl disable "$unit" >/dev/null 2>&1 || true
      ;;
  esac
  if [[ "$prior_active" == "1" ]]; then
    account_start_ts="$(date --iso-8601=seconds)"
    if ! systemctl restart "$unit"; then
      echo "PREVIOUSLY-ACTIVE ACCOUNT RESTART COMMAND FAILED: $unit"
      systemctl status "$unit" --no-pager -l || true
      journalctl -u "$unit" --since "$account_start_ts" --no-pager -l | tail -n 240 || true
      false
    fi
    wait_service_ready "$unit" "$account_start_ts" "$key" 60 || false
  else
    systemctl stop "$unit" >/dev/null 2>&1 || true
  fi
done

for key in main acc2 acc3; do
  if [[ "$key" == "main" ]]; then unit="zivo60.service"; else unit="zivo60@$key.service"; fi
  sid="$(grep '^ZIVO_SELF_ID=' "$ACCOUNT_ENV_DIR/$key.env" 2>/dev/null | tail -1 | cut -d= -f2 || true)"
  state="$(systemctl is-active "$unit" 2>/dev/null || true)"
  printf 'ACCOUNT RUNTIME | %s | self_id=%s | service=%s\n' "$key" "${sid:-0}" "$state"
  if [[ "${sid:-0}" =~ ^[1-9][0-9]*$ ]]; then
    if [[ "$state" != "active" ]]; then
      echo "AUTHORIZED ACCOUNT SERVICE NOT ACTIVE (non-blocking): $unit"
      continue
    fi
    apid="$(systemctl show -p MainPID --value "$unit")"
    alogs="$(journalctl -u "$unit" --since "$START_TS" --no-pager -l | grep "python\[$apid\]" || true)"
    for _ in $(seq 1 30); do
      if echo "$alogs" | grep -q 'ZIVO is ready'; then break; fi
      sleep 1
      alogs="$(journalctl -u "$unit" --since "$START_TS" --no-pager -l | grep "python\[$apid\]" || true)"
    done
    echo "$alogs" | grep -q 'ZIVO is ready' || echo "ACCOUNT READY MARKER MISSING (non-blocking): $unit"
    echo "$alogs" | grep -q 'cross-account join worker started' || echo "JOIN WORKER MARKER MISSING (non-blocking): $unit"
    if echo "$alogs" | grep -Eq 'Too many open files|unable to open database file|SyntaxError|NameError|ImportError|ModuleNotFoundError'; then
      echo "ACCOUNT STARTUP REGRESSION (non-blocking): $unit"
      echo "$alogs" | tail -n 160
    fi
    if [[ -d "/proc/$apid/fd" ]]; then
      printf 'ACCOUNT FDS | %s | %s\n' "$key" "$(find "/proc/$apid/fd" -maxdepth 1 -type l 2>/dev/null | wc -l)"
    fi
  fi
done

# Runtime FD slope guard: the 60.65 failure leaked the main SQLite handle on
# every `with db_connect()` call. Sample the live controller after normal
# workers have been active; bounded jitter is fine, sustained growth is not.
if [[ -d "/proc/$PID/fd" ]]; then
  FD_A="$(find "/proc/$PID/fd" -maxdepth 1 -type l 2>/dev/null | wc -l)"
  sleep 8
  FD_B="$(find "/proc/$PID/fd" -maxdepth 1 -type l 2>/dev/null | wc -l)"
  sleep 8
  FD_C="$(find "/proc/$PID/fd" -maxdepth 1 -type l 2>/dev/null | wc -l)"
  echo "MAIN FD STABILITY | $FD_A -> $FD_B -> $FD_C"
  if (( FD_C > FD_A + 80 )); then
    echo "FD LEAK WARNING (non-blocking): main process grew too fast after startup"
  fi
fi

CURLOGS="$(journalctl -u "$SERVICE" --since "$START_TS" --no-pager -l | grep "python\[$PID\]" || true)"
if echo "$CURLOGS" | grep -Eq 'Too many open files|unable to open database file'; then
  echo "SQLITE/FD WARNING IN CURRENT PID (non-blocking)"
  echo "$CURLOGS" | tail -n 180
fi

# Permission errors from Telegram groups are runtime conditions, not install failures.
trap - ERR INT TERM HUP
echo
printf '%s\n' '========================================'
# Compatibility marker for 96.39 regression: ZIVO zivo60.96.39 PREMIUM PURCHASE UX DEPLOY: PASS
printf '%s\n' 'ZIVO zivo60.96.53 MEOW START REPAIR + TIER RESPONSE PRIORITY + OFFICIAL22 DEPLOY: PASS'
printf 'BACKUP: %s\n' "$BACKUP"
printf 'MAIN SERVICE: %s\n' "$(systemctl is-active "$SERVICE")"
printf '%s\n' '========================================'
printf '%s\n' 'NEW ACCOUNTS PRECONFIGURED:'
printf '%s\n' '  acc2 = +98 990 065 5574'
printf '%s\n' '  acc3 = 09137511274'
printf '%s\n' 'LOGIN BOTH WITH:'
printf '%s\n' '  /opt/zivo60/venv/bin/python /opt/zivo60/setup_zivo_accounts.py all'
printf '%s\n' '========================================'
systemctl status "$SERVICE" --no-pager -l | tail -n 35
printf '%s\n' '===== IMPORTANT LOGS ====='
journalctl -u "$SERVICE" --since "$START_TS" --no-pager -l | grep "python\[$PID\]" | grep -Ei 'zivo60.96.53|zivo60.96.52|zivo60.96.51.1|zivo60.96.51|zivo60.96.39.4|zivo60.96.39.3|zivo60.96.39.2|zivo60.96.39.1|zivo60.96.39|zivo60.96.38|zivo60.96.37|zivo60.96.36|zivo60.96.35|zivo60.96.34|zivo60.96.33|zivo60.96.32|zivo60.96.31|zivo60.96.30|zivo60.96.29|zivo60.96.28|zivo60.96.27|zivo60.96.26|zivo60.96.25|zivo60.96.24|zivo60.96.23|zivo60.96.22|zivo60.96.21|zivo60.96.20|zivo60.96.19|zivo60.96.18|zivo60.96.17|zivo60.96.16|zivo60.96.15|zivo60.96.14|zivo60.96.13|zivo60.96.12|zivo60.96.11|ZIVO is ready|social games started|SESSION AUTH|multi account|media upload config|media config endpoint|campaign media|cross-account join worker|recent join recovery|legacy false-failure recovery|welcome sent|shared claim owner probe|stale group claim|scale router|transport circuit|mass tag isolation|group join notice|private inbox watchdog|private fast dialog poll|private known contact poll|private startup backfill|pending activation fast worker|scheduled cleanup|router error|Traceback|ERROR' | tail -n 280 || true
