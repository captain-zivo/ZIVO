from datetime import datetime, timezone, timedelta
import zivo_official16 as mod
assert mod.VERSION == 'zivo-official16'

class T:
    def __init__(self): self.sent=[]
    def send_text(self, chat_id, text, reply_markup=None):
        self.sent.append((str(chat_id), text, reply_markup)); return {'ok': True}
    def answer_callback(self,*a,**k): return {'ok': True}

def buttons(markup): return [b for row in (markup or {}).get('inline_keyboard',[]) for b in row]
def labels(markup): return [str(b.get('text') or '') for b in buttons(markup)]

store=mod.Store(); transport=T(); core=mod.BotCore(store,transport)
orders={}; gate={}; joins=[]; managed={}; existing={'enabled':False,'authorized':False}; plan_by_group={777:'free'}
admin_batches=[]
now=datetime.now(timezone.utc)
sub_windows={
    'free': {'plan':'free','status':'active','started_at':None,'expires_at':None},
    'silver': {'plan':'silver','status':'active','started_at':(now-timedelta(days=15)).isoformat(),'expires_at':(now+timedelta(days=15)).isoformat()},
    'gold': {'plan':'gold','status':'active','started_at':(now-timedelta(days=5)).isoformat(),'expires_at':(now+timedelta(days=25)).isoformat()},
    'diamond': {'plan':'diamond','status':'active','started_at':(now-timedelta(days=1)).isoformat(),'expires_at':(now+timedelta(days=29)).isoformat()},
}

def fake_ipc(account,payload,timeout=45.0):
    op=payload.get('op'); act=payload.get('action'); uid=int(payload.get('requester_user_id') or 0)
    if op=='status':
        return {'ok':True,'account_key':account,'account_label':account,'enabled':True,'connected':True,'self_id':10,'groups_count':999}
    if op=='official_group_access':
        if act=='add':
            gid=int(payload.get('group_id') or 0)
            managed[(uid,gid)]={'user_id':uid,'group_id':gid,'account_key':str(payload.get('account_key') or account),'title':str(payload.get('title') or ''),'member_count':int(payload.get('member_count') if payload.get('member_count') is not None else -1)}
            return {'ok':True,'group':dict(managed[(uid,gid)])}
        if act=='list': return {'ok':True,'groups':[dict(v) for (u,g),v in managed.items() if u==uid]}
    if op=='official_gate':
        st=gate.setdefault(uid,{'seen':False,'membership_passed':False})
        if act=='seen': st['seen']=True
        if act=='pass': st.update({'seen':True,'membership_passed':True})
        return {'ok':True,'state':dict(st)}
    if op=='membership_check': raise AssertionError('Official16 soft onboarding must not hard-check membership')
    if op=='official_admin_user': return {'ok':True,'state':{'broadcast_enabled':act=='broadcast_on'}}
    if op=='official_admin':
        if uid != 49145577: return {'ok':False,'error':'FORBIDDEN'}
        if act=='audience':
            return {'ok':True,'official':{'total':120,'enabled':115,'disabled':5},'account_network':{'private_total':940,'private_enabled':900,'private_disabled':40},'active_campaigns':0,
                    'accounts':[{'account_key':'main','private_count':400,'status':'online'},{'account_key':'acc2','private_count':300,'status':'online'},{'account_key':'acc3','private_count':240,'status':'online'}]}
        if act=='inventory_refresh': return {'ok':True,'requested_accounts':['main','acc2','acc3']}
        if act=='campaign_create':
            admin_batches.append(str(payload.get('text') or '')); return {'ok':True,'batch_id':'official16-1','job_ids':[1,2,3],'accounts':['main','acc2','acc3']}
        if act=='campaign_status': return {'ok':True,'jobs':[{'account_key':'main','status':'running','success_count':20,'failure_count':1,'total_targets':100}]}
        if act=='official_users': return {'ok':True,'user_ids':[60001,60002]}
    if op=='inspect_link':
        return {'ok':True,'title':'گروه تست','about':'بیوی تست','member_count':321,'group_id':777,'account_key':account,
                'already_member': bool(existing['enabled'] and account=='acc2'),'requester_can_control': bool(existing['enabled'] and account=='acc2' and existing['authorized'])}
    if op=='join':
        joins.append((account,dict(payload))); return {'ok':True,'result_code':'joined_full','group_id':777,'title':'گروه تست','member_count':321,'elapsed_ms':120,'joined_now':True,'requester_can_control':True}
    if op=='groups': return {'ok':True,'groups':[]}
    if op=='control': return {'ok':True,'result_code':'done','result_text':'CONTROL_OK','elapsed_ms':10}
    if op=='social': return {'ok':True,'result_text':'SOCIAL_OK'}
    if op=='premium' and act=='catalog':
        return {'ok':True,'plans':[{'plan':'silver','label':'نقره‌ای','prices':[{'duration_days':30,'money_toman':'55,000 تومان','money_rial':'550,000 ریال'}]},{'plan':'gold','label':'طلایی','prices':[{'duration_days':30,'money_toman':'99,000 تومان','money_rial':'990,000 ریال'}]},{'plan':'diamond','label':'الماس','prices':[{'duration_days':30,'money_toman':'120,000 تومان','money_rial':'1,200,000 ریال'}]}],'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='status':
        gid=int(payload.get('group_id') or 0); plan=plan_by_group.get(gid,'free'); sub=dict(sub_windows[plan])
        return {'ok':True,'subscription':sub,'plan_label':mod.PLAN_UX[plan]['label']}
    if op=='premium' and act=='create_order':
        o={'order_id':9,'order_code':'ZV-ABC-12345','amount_rial':550000,'original_amount_rial':550000,'discount_rial':0,'discount_code':'','group_id':777,'group_title':'گروه تست','plan':str(payload.get('plan') or 'silver'),'duration_days':30,'status':'created','zibal_track_id':0}; orders[9]=o; return {'ok':True,'order':dict(o),'wallet_balance':600000}
    if op=='premium' and act=='order': return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='zibal':
        orders[9]['status']='gateway_pending'; orders[9]['zibal_track_id']=123; return {'ok':True,'payment_url':'https://pay.example.test/start/123','order':dict(orders[9])}
    if op=='premium' and act=='check_payment':
        orders[9]['status']='activated'; plan_by_group[777]=str(orders[9]['plan']); return {'ok':True,'activated':True,'order':dict(orders[9]),'subscription':dict(sub_windows[orders[9]['plan']])}
    if op=='premium' and act=='my_subscriptions':
        row={'group_id':777,'group_title':'گروه تست','effective_plan':'silver',**sub_windows['silver']}; return {'ok':True,'subscriptions':[row]}
    if op=='premium' and act=='history': return {'ok':True,'orders':[]}
    raise AssertionError((account,payload))

core._ipc=fake_ipc
uid='60001'
# Soft onboarding twice, never pretends a hard membership verification occurred.
core.handle({'message':{'from':{'id':uid},'chat':{'id':uid},'id':'1','text':'/start','type':'TEXT'}})
assert 'به ZIVO خوش اومدی' in transport.sent[-1][1]
core.handle_callback({'callback_query':{'id':'g1','from':{'id':uid},'message':{'chat':{'id':uid},'message_id':'2'},'data':'gate:check'}})
second=transport.sent[-1]
assert 'عضویت در کانال‌های رسمی ZIVO' in second[1]
assert 'آخرین' not in second[1] and 'تأیید شد' not in second[1]
assert any(b.get('callback_data')=='menu:home' for b in buttons(second[2]))
core.handle_callback({'callback_query':{'id':'g2','from':{'id':uid},'message':{'chat':{'id':uid},'message_id':'3'},'data':'menu:home'}})
assert 'مدیریت هوشمند گروه‌های سروش+' in transport.sent[-1][1]

# Existing group + plan meter in same management panel.
existing.update(enabled=True,authorized=True); msg=mod.IncomingMessage(raw={},sender_id=uid,chat_id=uid,message_id='4',body='https://splus.ir/joingroup/abc',message_type='TEXT')
core._begin_group_link(msg,'invite','abc'); assert not joins and (int(uid),777) in managed
store.set_control_state(uid,active_group_id=777,mode='')
plan_by_group[777]='silver'; core._send_control_panel(uid,uid)
assert 'SILVER' in transport.sent[-1][1] and 'روز باقی‌مانده' in transport.sent[-1][1] and '🟩' in transport.sent[-1][1] and '٪' in transport.sent[-1][1]
# Expired meter uses red/empty battery.
expired={'plan':'silver','started_at':(now-timedelta(days=31)).isoformat(),'expires_at':(now-timedelta(days=1)).isoformat()}
assert '🪫' in core._subscription_meter(expired) and '🔴' in core._subscription_meter(expired)
core._premium_my_subscriptions(uid,uid); assert 'روز باقی‌مانده' in transport.sent[-1][1]

# Owner admin panel + audience + account-private campaign flow.
owner='49145577'; core._send_main_menu(owner,owner)
assert any(b.get('callback_data')=='admin:home' for b in buttons(transport.sent[-1][2]))
core.handle_callback({'callback_query':{'id':'a1','from':{'id':owner},'message':{'chat':{'id':owner},'message_id':'10'},'data':'admin:audience'}})
assert 'پیوی‌های اکانت‌های ZIVO' in transport.sent[-1][1] and '900' in transport.sent[-1][1]
core.handle_callback({'callback_query':{'id':'a2','from':{'id':owner},'message':{'chat':{'id':owner},'message_id':'11'},'data':'admin:adscope:accounts'}})
core.handle({'message':{'from':{'id':owner},'chat':{'id':owner},'id':'12','text':'اطلاعیه تست ZIVO','type':'TEXT'}})
assert 'پیش‌نمایش ارسال' in transport.sent[-1][1]
core.handle_callback({'callback_query':{'id':'a3','from':{'id':owner},'message':{'chat':{'id':owner},'message_id':'13'},'data':'admin:adsend'}})
assert admin_batches == ['اطلاعیه تست ZIVO'] and 'صف پیوی اکانت‌ها ساخته شد' in transport.sent[-1][1]
core.handle_callback({'callback_query':{'id':'a4','from':{'id':owner},'message':{'chat':{'id':owner},'message_id':'14'},'data':'admin:status'}})
assert 'وضعیت ارسال ZIVO' in transport.sent[-1][1]

# Gateway return remains intact.
plan_by_group[777]='free'; core._premium_create_order(uid,uid,777,'silver',30); core._premium_pay(uid,uid,9,'zibal')
assert any(b.get('url')=='https://pay.example.test/start/123' for b in buttons(transport.sent[-1][2]))
core._premium_check_payment(uid,uid,9); assert 'پرداخت موفق بود · پلن فعال شد' in transport.sent[-1][1]

print('ZIVO OFFICIAL16 ADMIN BROADCAST + SUBSCRIPTION METER UX: PASS')
print('  soft onboarding wording without fake hard-membership verification: PASS')
print('  subscription days/percent/green battery + expired red battery: PASS')
print('  owner admin audience/campaign flow: PASS')
print('  account-private campaign uses Core live-dialog campaign queue: PASS')
print('  direct gateway + activation return page preserved: PASS')
