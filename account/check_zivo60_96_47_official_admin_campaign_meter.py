from pathlib import Path
import tempfile, importlib.util
ROOT=Path(__file__).resolve().parent
core=(ROOT/'zivo60.py').read_text(encoding='utf-8')
prem=(ROOT/'zivo_premium.py').read_text(encoding='utf-8')
assert any(f'VERSION = "{v}"' in core for v in ('zivo60.96.47','zivo60.96.48','zivo60.96.49','zivo60.96.50'))
for token in ['op == "official_admin"','campaign_create','campaign_status','request_full_inventory_sync_all','multi_create_campaign_jobs','telegram_network_inventory_counts','op == "official_admin_user"']:
    assert token in core, token
for token in ['broadcast_enabled','official_broadcast_user_ids','official_broadcast_counts','official_set_broadcast_enabled',"'started_at': started.isoformat()"]:
    assert token in prem, token
spec=importlib.util.spec_from_file_location('zivo_premium_9647',ROOT/'zivo_premium.py')
p=importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
with tempfile.TemporaryDirectory() as td:
    p._DB_PATH=Path(td)/'premium.db'; p._SCHEMA_READY.clear(); p._PLAN_CACHE.clear(); p.init_db()
    p.official_user_mark_seen(1001); p.official_user_mark_seen(1002)
    assert p.official_broadcast_counts()['enabled']==2
    p.official_set_broadcast_enabled(1002,False)
    assert p.official_broadcast_counts()=={'total':2,'enabled':1,'disabled':1}
    assert p.official_broadcast_user_ids()==[1001]
    sub=p.activate_subscription(77,p.PLAN_SILVER,30,buyer_user_id=1001)
    state=p.get_subscription(77,use_cache=False)
    assert state.get('started_at') and state.get('expires_at')
print('CHECK ZIVO60.96.47 OFFICIAL ADMIN CAMPAIGN + SUBSCRIPTION METER: PASS')
print('  persistent Official broadcast opt-out: PASS')
print('  live-dialog campaign IPC + audience inventory contract: PASS')
print('  subscription started/expires timestamps exposed for real progress meter: PASS')
