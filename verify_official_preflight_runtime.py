from pathlib import Path
root=Path(__file__).resolve().parent
allsh=(root/'install_all.sh').read_text()
off=(root/'official/install.sh').read_text()
assert 'python3 "$ROOT/official/test_zivo_official22.py"' not in allsh
assert 'OFFICIAL22 PREFLIGHT: DEFERRED' in allsh
assert off.index('requests_venv_ok') < off.index('PYTHONPATH="$DST" "$DST/venv/bin/python" "$DST/test_zivo_official22.py"')
assert 'DST=/opt/ZIVO_OFFICIAL_BOT22' in off and 'SERVICE=zivo-official22.service' in off
assert '/opt/ZIVO_OFFICIAL_BOT22/zivo_official22.py' in off
print('ZIVO 96.53 OFFICIAL22 PREFLIGHT/RUNTIME ORDER: PASS')
