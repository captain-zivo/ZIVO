#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CORE = (ROOT / "zivo60.py").read_text(encoding="utf-8")
LEGACY = (ROOT / "check_zivo60_96_13_live_regressions.py").read_text(encoding="utf-8")
INSTALLER = (ROOT / "install_zivo60.sh").read_text(encoding="utf-8")

tree = ast.parse(CORE)
version = next(
    node.value.value
    for node in tree.body
    if isinstance(node, ast.Assign)
    and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in node.targets)
    and isinstance(node.value, ast.Constant)
)
# This historical regression remains in every newer installer.  It verifies the
# 96.51.1 rollback failure contract, not the current release number.
assert version.startswith("zivo60.96.")

classifier = next(
    node
    for node in tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "_is_group_inaccessible_error"
)
module = ast.Module(body=[classifier], type_ignores=[])
ast.fix_missing_locations(module)
namespace: dict[str, object] = {}
exec(compile(module, str(ROOT / "zivo60.py"), "exec"), namespace)
is_inaccessible = namespace["_is_group_inaccessible_error"]
assert callable(is_inaccessible)
assert not is_inaccessible(RuntimeError("ChatSendPlainForbidden: You cannot send plain results"))
assert is_inaccessible(RuntimeError("CHAT_WRITE_FORBIDDEN"))
assert is_inaccessible(RuntimeError("CHANNELPRIVATE"))

assert "assert not ns['_is_group_inaccessible_error'](PlainForbidden" in LEGACY
assert "RuntimeError('CHAT_WRITE_FORBIDDEN')" in LEGACY

predeploy_end = INSTALLER.index('echo "PREDEPLOY ZIVO60.')
predeploy = INSTALLER[:predeploy_end]
cutover_start = INSTALLER.index("discover_instance_units", predeploy_end)
assert '"$SRC/check_zivo60_96_13_live_regressions.py"' in predeploy
assert '"$SRC/check_zivo60_96_51_1_installer_regression.py"' in predeploy
assert predeploy.count('"$SRC/check_zivo60_96_13_live_regressions.py"') >= 2
assert predeploy.count('"$SRC/check_zivo60_96_51_1_installer_regression.py"') >= 2
assert predeploy.rfind('"$SRC/check_zivo60_96_13_live_regressions.py"') < cutover_start
assert predeploy.rfind('"$SRC/check_zivo60_96_51_1_installer_regression.py"') < cutover_start
assert "check_zivo60_96_51_1_installer_regression.py" in INSTALLER

print("CHECK ZIVO60.96.51.1 INSTALLER REGRESSION HOTFIX: PASS")
print("  legacy plain-forbidden contract aligned with rich fallback: PASS")
print("  real inaccessible group errors remain classified: PASS")
print("  legacy conflict gate runs before cutover: PASS")
