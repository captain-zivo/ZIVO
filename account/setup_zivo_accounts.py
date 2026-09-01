#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Interactive login/configuration helper for ZIVO secondary Soroush accounts."""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import subprocess
from pathlib import Path

from splusthon import SoroushClient
from zivo_multi_account import init_control_db, register_account, set_account_enabled

BASE = Path('/opt/zivo60')
ENV_DIR = Path('/etc/zivo60/accounts')
PROFILES = {
    'acc2': {'label': 'اکانت ۲', 'phone': '+989900655574', 'username': 'zivo1bot'},
    'acc3': {'label': 'اکانت ۳', 'phone': '+989137511274', 'username': 'zivo2bot'},
}


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def render_env(key: str, phone: str, label: str, self_id: int, username: str = "") -> str:
    account_dir = BASE / 'accounts' / key
    return '\n'.join([
        f'ZIVO_ACCOUNT_KEY={key}',
        f'ZIVO_ACCOUNT_LABEL="{label}"',
        f'ZIVO_ACCOUNT_CONTROLLER=0',
        f'ZIVO_PHONE={phone}',
        f'ZIVO_SELF_ID={int(self_id)}',
        f'ZIVO_BOT_USERNAME={username or "zivobot"}',
        f'ZIVO_SESSION={account_dir / "session"}',
        f'ZIVO_DB={account_dir / "zivo60.db"}',
        f'ZIVO_MULTI_ACCOUNT_DB={BASE / "zivo_multi_accounts.db"}',
        f'ZIVO_TMP={account_dir / "tmp"}',
        f'ZIVO_GROUP_BACKUP_ROOT={account_dir / "backups" / "groups"}',
        f'ZIVO_WELCOME_MEDIA_DIR={account_dir / "welcome_media"}',
        '',
    ])


async def login_account(key: str, phone: str, label: str, username: str = '') -> int:
    account_dir = BASE / 'accounts' / key
    account_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(account_dir, 0o700)
    session_path = str(account_dir / 'session')
    print(f'\n=== ZIVO {label} | {phone} ===')
    print('کد ورود سروش را وقتی درخواست شد وارد کن. هر اکانت سشن جدا دارد.')
    client = SoroushClient(session_path, connection_retries=2, request_retries=2, timeout=20)
    try:
        await client.start(phone=phone)
        self_id = int(getattr(client, '_self_id', 0) or 0)
        if not self_id:
            try:
                me = await client.get_me()
                self_id = int(getattr(me, 'id', 0) or 0)
            except Exception:
                pass
        if not self_id:
            raise RuntimeError('LOGIN_OK_BUT_SELF_ID_UNRESOLVED')
        env_path = ENV_DIR / f'{key}.env'
        atomic_write(env_path, render_env(key, phone, label, self_id, username))
        control_db = BASE / 'zivo_multi_accounts.db'
        init_control_db(control_db)
        register_account(
            control_db,
            account_key=key, label=label, phone=phone, self_id=self_id,
            enabled=True, is_controller=False, session_path=session_path,
            db_path=str(account_dir / 'zivo60.db'), status='configured',
        )
        set_account_enabled(control_db, key, True)
        print(f'LOGIN PASS | account={key} self_id={self_id}')
        return self_id
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('account', nargs='?', choices=['acc2', 'acc3', 'all'], default='all')
    parser.add_argument('--no-start', action='store_true', help='login/config only; do not start systemd unit')
    args = parser.parse_args()
    keys = list(PROFILES) if args.account == 'all' else [args.account]
    for key in keys:
        profile = PROFILES[key]
        self_id = asyncio.run(login_account(key, profile['phone'], profile['label'], profile.get('username', '')))
        if not args.no_start:
            unit = f'zivo60@{key}.service'
            subprocess.run(['systemctl', 'daemon-reload'], check=False)
            subprocess.run(['systemctl', 'enable', unit], check=False)
            subprocess.run(['systemctl', 'restart', unit], check=True)
            print(f'SERVICE STARTED | {unit} | self_id={self_id}')
    print('\nتمام شد. از پنل تلگرام > 🤖 اکانت‌ها وضعیت هر اکانت را می‌بینی.')


if __name__ == '__main__':
    main()
