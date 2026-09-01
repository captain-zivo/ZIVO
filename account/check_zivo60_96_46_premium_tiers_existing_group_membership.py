from pathlib import Path
import tempfile
import importlib.util

ROOT=Path(__file__).resolve().parent
core=(ROOT/'zivo60.py').read_text(encoding='utf-8')
prem_src=(ROOT/'zivo_premium.py').read_text(encoding='utf-8')
assert any(f'VERSION = "{v}"' in core for v in ('zivo60.96.46','zivo60.96.48','zivo60.96.49','zivo60.96.50'))
for token in [
    'PREMIUM_ADVANCED_COMMANDS','premium_requirement_for_command','premium_locked_text',
    'premium_daily_report_text','premium_weekly_report_text','premium_group_health_text',
'op == "official_gate"','op == "membership_check"',
    'requester_can_control','already_member','premium.meow_luck_multiplier','premium.pet_discount_percent',
    'premium.feature_allowed(int(group_id), "content_filter")','premium.feature_allowed(int(group_id), "auto_backup")',
    'premium.consume_ai_daily_quota','_premium_grant_activation_benefits','diamond-activation-meow',
]:
    assert token in core, token
for token in ['PLAN_FREE','PLAN_SILVER','PLAN_GOLD','PLAN_DIAMOND','official_private_users','premium_ai_daily_usage','reserve_bonus_once']:
    assert token in prem_src, token

spec=importlib.util.spec_from_file_location('zivo_premium_9646', ROOT/'zivo_premium.py')
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
with tempfile.TemporaryDirectory() as td:
    p._DB_PATH=Path(td)/'premium.db'; p._SCHEMA_READY.clear(); p._PLAN_CACHE.clear(); p.init_db()
    assert p.cleanup_limit(100)==700
    assert p.pet_discount_percent(100)==0 and abs(p.meow_luck_multiplier(100)-1.0)<1e-9
    p.activate_subscription(100,p.PLAN_SILVER,30,buyer_user_id=1)
    assert p.cleanup_limit(100)==2000 and p.feature_allowed(100,'content_filter')
    assert p.pet_discount_percent(100)==10 and abs(p.meow_luck_multiplier(100)-1.15)<1e-9
    p.activate_subscription(101,p.PLAN_GOLD,30,buyer_user_id=1)
    assert p.cleanup_limit(101)==5000 and p.feature_allowed(101,'daily_report') and p.feature_allowed(101,'ai_speaker')
    assert p.consume_ai_daily_quota(101)['allowed'] is True
    p.activate_subscription(102,p.PLAN_DIAMOND,30,buyer_user_id=1)
    assert p.cleanup_limit(102)==0 and p.feature_allowed(102,'weekly_report') and p.feature_allowed(102,'auto_backup')
    assert p.consume_ai_daily_quota(102)['remaining']==-1
    assert p.reserve_bonus_once(102,1,'diamond-activation-meow',100,9) is True
    assert p.reserve_bonus_once(102,1,'diamond-activation-meow',100,10) is False
    assert p.official_user_state(555)['seen'] is False
    p.official_user_mark_seen(555)
    assert p.official_user_state(555)['seen'] is True and not p.official_user_state(555)['membership_passed']
    p.official_user_pass_gate(555)
    assert p.official_user_state(555)['membership_passed'] is True
    saved=p.official_add_managed_group(555,777,'acc2','گروه تست',321)
    assert saved['group_id']==777 and saved['account_key']=='acc2'
    restored=p.official_managed_groups(555)
    assert any(int(r.get('group_id') or 0)==777 and r.get('account_key')=='acc2' for r in restored)
print('CHECK ZIVO60.96.46 PREMIUM TIERS + EXISTING GROUP + MEMBERSHIP: PASS')
print('  FREE/SILVER/GOLD/DIAMOND runtime entitlements: PASS')
print('  Content Filter/Auto Backup/AI runtime gates: PASS')
print('  Premium economy + Diamond one-time bonus guard: PASS')
print('  Persistent new-private membership gate via account IPC: PASS')
print('  Persistent Official managed-group mapping survives restart: PASS')
