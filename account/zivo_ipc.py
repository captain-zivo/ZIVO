from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any, Dict

IPC_DIR = Path(os.getenv("ZIVO_IPC_DIR", "/run/zivo-ipc"))
DEFAULT_ACCOUNTS = tuple(
    part.strip().lower()
    for part in os.getenv("ZIVO_IPC_ACCOUNTS", "main,acc2,acc3").split(",")
    if part.strip()
)
MAX_FRAME_BYTES = max(4096, min(1048576, int(os.getenv("ZIVO_IPC_MAX_FRAME_BYTES", "262144"))))


def socket_path(account_key: str) -> Path:
    key = str(account_key or "").strip().lower()
    if not key or not all(ch.isalnum() or ch in "_-" for ch in key):
        raise ValueError("IPC_ACCOUNT_KEY_INVALID")
    return IPC_DIR / f"{key}.sock"


def request(account_key: str, payload: Dict[str, Any], timeout: float = 45.0) -> Dict[str, Any]:
    path = socket_path(account_key)
    raw = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise ValueError("IPC_REQUEST_TOO_LARGE")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(max(0.2, float(timeout)))
        sock.connect(str(path))
        sock.sendall(raw)
        buf = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if len(buf) > MAX_FRAME_BYTES:
                raise RuntimeError("IPC_RESPONSE_TOO_LARGE")
            if b"\n" in chunk:
                break
    if not buf:
        raise RuntimeError("IPC_EMPTY_RESPONSE")
    line = bytes(buf).split(b"\n", 1)[0]
    data = json.loads(line.decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("IPC_RESPONSE_INVALID")
    return data
