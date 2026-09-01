#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORE = (ROOT / "zivo60.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "install_zivo60.sh").read_text(encoding="utf-8")

tree = ast.parse(CORE)
version = next(
    node.value.value
    for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)
    and isinstance(node.value, ast.Constant)
)
# This historical gate stays active in 96.53; it validates the 96.52 wallet
# cutover contract rather than pinning every later release to the old version.
assert version in {"zivo60.96.52", "zivo60.96.53"}
assert any(token in INSTALLER for token in ('pre_zivo60_96_52_', 'pre_zivo60_96_53_'))
assert any(token in INSTALLER for token in ('zivo60_96_52_', 'zivo60_96_53_'))

for filename in (
    "check_zivo60_96_13_live_regressions.py",
    "check_zivo60_96_51_1_installer_regression.py",
    "check_zivo60_96_52_wallet_commerce.py",
    "check_zivo60_96_52_installer_regression.py",
):
    assert filename in INSTALLER, filename

predeploy_end = INSTALLER.index('echo "PREDEPLOY ZIVO60.')
predeploy = INSTALLER[:predeploy_end]
cutover_start = INSTALLER.index("discover_instance_units", predeploy_end)
for filename in (
    "check_zivo60_96_13_live_regressions.py",
    "check_zivo60_96_51_1_installer_regression.py",
    "check_zivo60_96_52_wallet_commerce.py",
    "check_zivo60_96_52_installer_regression.py",
):
    needle = f'"$SRC/{filename}"'
    assert predeploy.count(needle) >= 2, filename
    assert predeploy.rfind(needle) < cutover_start, filename

assert 'PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_52_wallet_commerce.py"' in INSTALLER
assert 'PYTHONPATH="$BASE" "$VALIDATE_PY" "$BASE/check_zivo60_96_52_installer_regression.py"' in INSTALLER
assert any(marker in INSTALLER for marker in (
    "ZIVO zivo60.96.52 WALLET COMMERCE",
    "ZIVO zivo60.96.53 MEOW START REPAIR",
))

print("CHECK ZIVO60.96.52 INSTALLER REGRESSION: PASS")
print("  legacy failure gate + wallet commerce QA run before cutover: PASS")
print("  installed-copy wallet QA retained after copy: PASS")
