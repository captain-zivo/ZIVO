#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from pathlib import Path
from zivo_multi_account import (
    list_accounts, eligible_join_accounts, account_join_capacity_blocked,
    recent_unfinished_join_requests,
)
DB=Path(os.getenv('ZIVO_MULTI_ACCOUNT_DB', '/opt/zivo60/zivo_multi_accounts.db'))
rows=list_accounts(DB)
print('ACCOUNTS:', len(rows))
for r in rows:
    key=str(r['account_key'])
    print(f"{key}: self_id={int(r['self_id'] or 0)} enabled={int(r['enabled'] or 0)} status={r['status']} groups={int(r['groups_count'] or 0)} capacity_blocked={account_join_capacity_blocked(DB,key)}")
    failed=recent_unfinished_join_requests(DB,key,age_seconds=7200,limit=30)
    print(f"  recent_unfinished_links={len(failed)}")
print('FAILOVER FROM main:', ','.join(str(r['account_key']) for r in eligible_join_accounts(DB,'main')) or '<none>')
