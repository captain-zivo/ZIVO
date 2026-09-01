#!/usr/bin/env python3
from zivo_ipc import DEFAULT_ACCOUNTS, request, socket_path

def main():
    failures=[]
    for key in DEFAULT_ACCOUNTS:
        path=socket_path(key)
        if not path.exists():
            failures.append(f"{key}:socket-missing")
            continue
        try:
            data=request(key,{"op":"status"},timeout=3.0)
        except Exception as exc:
            failures.append(f"{key}:{type(exc).__name__}:{exc}")
            continue
        if not data.get("ok") or str(data.get("account_key") or "") != key:
            failures.append(f"{key}:bad-response:{data}")
            continue
        print(f"IPC PASS | {key} | version={data.get('version')} | connected={data.get('connected')} | groups={data.get('groups_count')}")
    if failures:
        raise SystemExit("IPC SMOKE FAIL | "+" | ".join(failures))
    print("ZIVO DIRECT IPC SMOKE: PASS")

if __name__ == "__main__":
    main()
