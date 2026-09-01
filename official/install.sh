#!/usr/bin/env bash
set -Eeuo pipefail
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
DST=/opt/ZIVO_OFFICIAL_BOT22
SERVICE=zivo-official22.service
[[ $EUID -eq 0 ]] || { echo "ERROR: run as root" >&2; exit 1; }

for n in $(seq 1 22); do
  svc="zivo-official${n}.service"
  systemctl stop "$svc" 2>/dev/null || true
  systemctl disable "$svc" 2>/dev/null || true
done
systemctl stop zivo-official.service 2>/dev/null || true
systemctl disable zivo-official.service 2>/dev/null || true
pkill -TERM -f '/opt/ZIVO_OFFICIAL_BOT[0-9]+/.*zivo_official[0-9]+\.py' 2>/dev/null || true
sleep 1
pkill -KILL -f '/opt/ZIVO_OFFICIAL_BOT[0-9]+/.*zivo_official[0-9]+\.py' 2>/dev/null || true

mkdir -p "$DST" /run/zivo-ipc
chmod 0700 /run/zivo-ipc
for f in zivo_official22.py test_zivo_official22.py zivo_official21.py test_zivo_official21.py zivo_official20.py test_zivo_official20.py zivo_official19.py test_zivo_official19.py zivo_official18.py test_zivo_official18.py zivo_official17.py zivo_official16.py zivo_official15.py zivo_official14.py zivo_official13.py zivo_official12.py zivo_official11_legacy.py zivo_official10_legacy.py zivo_entertainment.py zivo_market_tools.py zivo_social_games.py zivo_multi_account.py zivo_ipc.py test_zivo_official17.py test_zivo_official16.py requirements.txt README_FA.txt RUN_COMMANDS_FA.txt BRIDGE_ARCHITECTURE_FA.txt BUILD_INFO.txt RELEASE_NOTES_OFFICIAL22_FA.txt RELEASE_NOTES_OFFICIAL21_FA.txt RELEASE_NOTES_OFFICIAL20_FA.txt; do
  cp "$SRC_DIR/$f" "$DST/$f"
done

requests_venv_ok(){
  local candidate="$1"
  [[ -x "$candidate/bin/python" ]] || return 1
  "$candidate/bin/python" - <<'PYREQ' >/dev/null 2>&1
from importlib.metadata import PackageNotFoundError, version
try:
    v=version('requests')
except PackageNotFoundError:
    raise SystemExit(1)
parts=[]
for item in v.split('.'):
    digits=''.join(ch for ch in item if ch.isdigit())
    if not digits: break
    parts.append(int(digits))
cur=tuple(parts or [0])
if not ((2,32) <= cur < (3,0)):
    raise SystemExit(1)
import requests
PYREQ
}

OFFICIAL_VENV_REUSED=0
if requests_venv_ok "$DST/venv"; then
  OFFICIAL_VENV_REUSED=1
  echo "OFFICIAL22 VENV: REUSED | existing=$DST/venv"
else
  rm -rf -- "$DST/venv"
  for candidate in /opt/ZIVO_OFFICIAL_BOT21/venv /opt/ZIVO_OFFICIAL_BOT20/venv /opt/ZIVO_OFFICIAL_BOT19/venv /opt/ZIVO_OFFICIAL_BOT18/venv /opt/ZIVO_OFFICIAL_BOT17/venv /opt/ZIVO_OFFICIAL_BOT16/venv /opt/ZIVO_OFFICIAL_BOT15/venv /opt/ZIVO_OFFICIAL_BOT14/venv /opt/ZIVO_OFFICIAL_BOT13/venv /opt/ZIVO_OFFICIAL_BOT12/venv /opt/zivo60/venv; do
    if requests_venv_ok "$candidate"; then
      target="$(readlink -f -- "$candidate")"
      ln -s -- "$target" "$DST/venv"
      OFFICIAL_VENV_REUSED=1
      echo "OFFICIAL22 VENV: REUSED | source=$candidate target=$target"
      break
    fi
  done
fi
if (( OFFICIAL_VENV_REUSED == 0 )); then
  FREE_MB="$(df -Pm / | awk 'NR==2 {print $4}')"
  if [[ ! "${FREE_MB:-}" =~ ^[0-9]+$ ]] || (( FREE_MB < 96 )); then
    echo "ERROR: Official22 needs a small requests venv but only ${FREE_MB:-0}MB is free." >&2
    exit 1
  fi
  python3 -m venv "$DST/venv"
  "$DST/venv/bin/pip" install -q --disable-pip-version-check -r "$DST/requirements.txt"
  requests_venv_ok "$DST/venv" || { echo "ERROR: Official22 venv dependency validation failed" >&2; exit 1; }
  echo "OFFICIAL22 VENV: CREATED | dependency set validated"
fi

"$DST/venv/bin/python" -m py_compile "$DST/zivo_official22.py" "$DST/zivo_ipc.py" "$DST/test_zivo_official22.py"
PYTHONPATH="$DST" "$DST/venv/bin/python" "$DST/test_zivo_official22.py"
for key in main acc2 acc3; do [[ -S "/run/zivo-ipc/${key}.sock" ]] || { echo "ERROR: account IPC socket missing: /run/zivo-ipc/${key}.sock" >&2; exit 1; }; done

install -m 0644 "$SRC_DIR/zivo-official22.service" "/etc/systemd/system/$SERVICE"
systemctl daemon-reload
systemctl enable "$SERVICE"
systemctl restart "$SERVICE"
sleep 2
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 120 --no-pager; exit 1; }
PID="$(systemctl show -p MainPID --value "$SERVICE")"
CMD="$(tr '\0' ' ' < "/proc/$PID/cmdline")"
case "$CMD" in *'/opt/ZIVO_OFFICIAL_BOT22/zivo_official22.py'*) ;; *) echo "ERROR: wrong Official22 runtime: $CMD" >&2; exit 1;; esac
if pgrep -af '/opt/ZIVO_OFFICIAL_BOT([1-9]|10|11|12|13|14|15|16|17|18|19|20|21)/.*zivo_official([1-9]|10|11|12|13|14|15|16|17|18|19|20|21)\.py' >/tmp/zivo_old_official.$$ 2>/dev/null; then
  echo "ERROR: old Official runtime still alive" >&2; cat /tmp/zivo_old_official.$$ >&2; rm -f /tmp/zivo_old_official.$$; exit 1
fi
rm -f /tmp/zivo_old_official.$$ 2>/dev/null || true

echo "OFFICIAL22 MEOW START REPAIR + WALLET COMMERCE CUTOVER VERIFIED"
systemctl status "$SERVICE" --no-pager -l
