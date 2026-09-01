#!/usr/bin/env python3
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB = Path("/opt/zivo60/zivo60.db")


def usage():
    print("usage:")
    print("  set_zivo60_pro.py <group_id> on [days]")
    print("  set_zivo60_pro.py <group_id> off")
    raise SystemExit(64)


if len(sys.argv) < 3:
    usage()

try:
    group_id = int(sys.argv[1])
except ValueError:
    usage()

mode = sys.argv[2].strip().lower()
if mode not in {"on", "off"}:
    usage()

expires_at = None
active = mode == "on"

if active and len(sys.argv) >= 4:
    try:
        days = int(sys.argv[3])
    except ValueError:
        usage()

    if days <= 0:
        usage()

    expires_at = (
        datetime.now(timezone.utc)
        + timedelta(days=days)
    ).isoformat()

con = sqlite3.connect(DB)
try:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS pro_entitlements (
            group_id INTEGER PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT,
            source TEXT NOT NULL DEFAULT 'operator',
            updated_at TEXT NOT NULL
        )
        """
    )
    con.execute(
        """
        INSERT INTO pro_entitlements (
            group_id,
            active,
            expires_at,
            source,
            updated_at
        ) VALUES (?, ?, ?, 'operator', ?)
        ON CONFLICT(group_id) DO UPDATE SET
            active = excluded.active,
            expires_at = excluded.expires_at,
            source = excluded.source,
            updated_at = excluded.updated_at
        """,
        (
            group_id,
            1 if active else 0,
            expires_at,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    con.commit()
finally:
    con.close()

print(
    f"group={group_id} pro={'ON' if active else 'OFF'} "
    f"expires_at={expires_at or 'none'}"
)
