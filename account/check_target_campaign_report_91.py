#!/usr/bin/env python3
from __future__ import annotations
import ast, importlib.util, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
SRC=(ROOT/'zivo60.py').read_text(encoding='utf-8')
MSRC=(ROOT/'zivo_multi_account.py').read_text(encoding='utf-8')
TREE=ast.parse(SRC)
assert 'VERSION = "zivo60.93"' in SRC
assert 'target-campaign=adaptive-batch+member-stop+banner-cleanup' in SRC
assert 'user-report=reply+manager-review+approve-reject' in SRC
assert 'campaign_mode TEXT NOT NULL DEFAULT \'standard\'' in MSRC
assert 'CREATE TABLE IF NOT EXISTS campaign_deliveries' in MSRC
assert 'paused_measurement' in SRC and 'target_reached_cleanup_partial' in SRC
assert 'multi_record_campaign_delivery' in SRC and 'cleanup_target_campaign_banners' in SRC
assert '📢 تبلیغات برای کیه؟' in SRC and '🎯 برای شخص دیگر' in SRC
assert 'تایید گزارش 123' in SRC and 'رد گزارش 123' in SRC

def fn(name: str):
    node=next(n for n in TREE.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    return ast.get_source_segment(SRC,node) or ''

batch_src=fn('target_campaign_batch_size')
ns={}
exec(compile(ast.parse(batch_src),'<batch>','exec'),ns)
b=ns['target_campaign_batch_size']
assert b(900)==100
assert b(500)==50
assert b(201)==50
assert b(200)==20
assert b(51)==20
assert b(50)==10
assert b(21)==10
assert b(20)==5
assert b(6)==5
assert b(5)==1

run=fn('run_target_growth_campaign_job')
for token in ('measure_target_group_members','target_campaign_batch_size','multi_record_campaign_delivery','cleanup_target_campaign_banners','paused_measurement','target_reached'):
    assert token in run, token
assert run.index('measure_target_group_members') < run.index('telegram_group_targets')

report=fn('command_user_report')
assert 'review_user_report' in report
assert '_send_persistent_user_report_card' in report
assert 'delete_messages' not in report
assert 'apply_manual_banned_rights' not in report

spec=importlib.util.spec_from_file_location('multi86',ROOT/'zivo_multi_account.py')
mod=importlib.util.module_from_spec(spec); assert spec and spec.loader; spec.loader.exec_module(mod)
with tempfile.TemporaryDirectory() as td:
    db=Path(td)/'control.db'
    mod.init_control_db(db)
    mod.register_account(db,account_key='main',label='main',phone='',self_id=1,enabled=True,is_controller=True,session_path='s',db_path='d')
    ids=mod.create_campaign_jobs(
        db,batch_id='t',account_keys=['main'],scope='groups',content={'type':'text','text':'banner'},
        repeat_count=1,interval_seconds=0,campaign_mode='target_growth',target_group_link='https://splus.ir/test',
        target_group_id=99,target_member_count=500,baseline_member_count=400,
    )
    row=mod.get_job(db,ids[0])
    assert row['campaign_mode']=='target_growth' and int(row['target_member_count'])==500
    did=mod.record_campaign_delivery(db,job_id=ids[0],account_key='main',target_group_id=10,sent_message_id=77)
    assert len(mod.campaign_deliveries(db,ids[0],'sent'))==1
    mod.update_campaign_delivery(db,did,status='deleted')
    assert mod.campaign_deliveries(db,ids[0])[0]['status']=='deleted'
print('CHECK ZIVO60.91 TARGET CAMPAIGN + REPORT REVIEW: PASS')
