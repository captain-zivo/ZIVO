import zivo_official15 as mod
assert mod.VERSION == 'zivo-official15'

class T:
    def __init__(self): self.sent=[]
    def send_text(self, chat_id, text, reply_markup=None):
        self.sent.append((str(chat_id), text, reply_markup)); return {'ok': True}
    def answer_callback(self,*a,**k): return {'ok': True}

def buttons(markup):
    return [b for row in (markup or {}).get('inline_keyboard',[]) for b in row]

def labels(markup):
    return [str(b.get('text') or '') for b in buttons(markup)]

store=mod.Store(); transport=T(); core=mod.BotCore(store,transport)
orders={}; gate={}; joins=[]; managed={}; existing={'enabled':False,'authorized':False}; plan_by_group={777:'free'}

def fake_ipc(account,payload,timeout=45.0):
    op=payload.get('op'); act=payload.get('action'); uid=int(payload.get('requester_user_id') or 0)
    if op=='status':
        return {'ok':True,'account_key':account,'account_label':account,'enabled':True,'connected':True,'self_id':10,'groups_count':999}
    if op=='official_group_access':
        if act=='add':
            gid=int(payload.get('group_id') or 0)
            managed[(uid,gid)]={'user_id':uid,'group_id':gid,'account_key':str(payload.get('account_key') or account),'title':str(payload.get('title') or ''),'member_count':int(payload.get('member_count') if payload.get('member_count') is not None else -1)}
            return {'ok':True,'group':dict(managed[(uid,gid)])}
        if act=='list':
            return {'ok':True,'groups':[dict(v) for (u,g),v in managed.items() if u==uid]}
        raise AssertionError(('official_group_access',payload))
    if op=='official_gate':
        st=gate.setdefault(uid,{'seen':False,'membership_passed':False})
        if act=='seen': st['seen']=True
        if act=='pass': st.update({'seen':True,'membership_passed':True})
        return {'ok':True,'state':dict(st)}
    if op=='membership_check':
        raise AssertionError('Official15 soft onboarding must not hard-check membership')
    if op=='inspect_link':
        return {'ok':True,'title':'گروه تست','about':'بیوی تست','member_count':321,'group_id':777,'account_key':account,
                'already_member': bool(existing['enabled'] and account=='acc2'),
                'requester_can_control': bool(existing['enabled'] and account=='acc2' and existing['authorized'])}
    if op=='join':
        joins.append((account,dict(payload)))
        return {'ok':True,'result_code':'joined_full','group_id':777,'title':'گروه تست','member_count':321,'elapsed_ms':120,'joined_now':True,'requester_can_control':True}
    if op=='groups': return {'ok':True,'groups':[]}
    if op=='control': return {'ok':True,'result_code':'done','result_text':'CONTROL_OK','elapsed_ms':10}
    if op=='social': return {'ok':True,'result_text':'SOCIAL_OK'}
    if op=='premium' and act=='catalog':
        return {'ok':True,'plans':[{'plan':'silver','label':'نقره‌ای','prices':[{'duration_days':30,'money_toman':'55,000 تومان','money_rial':'550,000 ریال'}]},{'plan':'gold','label':'طلایی','prices':[{'duration_days':30,'money_toman':'99,000 تومان','money_rial':'990,000 ریال'}]},{'plan':'diamond','label':'الماس','prices':[{'duration_days':30,'money_toman':'120,000 تومان','money_rial':'1,200,000 ریال'}]}],'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='status':
        gid=int(payload.get('group_id') or 0); plan=plan_by_group.get(gid,'free')
        return {'ok':True,'subscription':{'plan':plan,'status':'active'},'plan_label':mod.PLAN_UX[plan]['label']}
    if op=='premium' and act=='create_order':
        o={'order_id':9,'order_code':'ZV-ABC-12345','amount_rial':550000,'original_amount_rial':550000,'discount_rial':0,'discount_code':'','group_id':777,'group_title':'گروه تست','plan':str(payload.get('plan') or 'silver'),'duration_days':30,'status':'created','zibal_track_id':0}; orders[9]=o; return {'ok':True,'order':dict(o),'wallet_balance':600000}
    if op=='premium' and act=='order': return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='zibal':
        orders[9]['status']='gateway_pending'; orders[9]['zibal_track_id']=123
        return {'ok':True,'payment_url':'https://pay.example.test/start/123','order':dict(orders[9])}
    if op=='premium' and act=='discount_apply':
        orders[9].update({'amount_rial':495000,'discount_rial':55000,'discount_code':'WELCOME10'}); return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000}
    if op=='premium' and act=='check_payment':
        orders[9]['status']='activated'; plan_by_group[777]=str(orders[9]['plan']); return {'ok':True,'activated':True,'order':dict(orders[9]),'subscription':{'plan':orders[9]['plan'],'status':'active'}}
    if op=='premium' and act=='my_subscriptions': return {'ok':True,'subscriptions':[]}
    if op=='premium' and act=='history': return {'ok':True,'orders':[]}
    raise AssertionError((account,payload))

core._ipc=fake_ipc
uid='60001'

# Soft onboarding: first PM invitation, second interaction unlocks; no membership RPC.
core.handle({'message':{'from':{'id':uid},'chat':{'id':uid},'id':'1','text':'/start','type':'TEXT'}})
first=transport.sent[-1]
assert 'خوش اومدی به ZIVO' in first[1]
assert sum(1 for b in buttons(first[2]) if b.get('url')) == 2
assert any(b.get('callback_data')=='gate:check' for b in buttons(first[2]))
core.handle_callback({'callback_query':{'id':'g1','from':{'id':uid},'message':{'chat':{'id':uid},'message_id':'2'},'data':'gate:check'}})
second=transport.sent[-1]
assert 'آخرین یادآوری عضویت ZIVO' in second[1]
assert 'دسترسی به پنل ZIVO از الان بازه' in second[1]
assert gate[int(uid)]['membership_passed'] is True
# Third start goes directly to main menu.
core.handle({'message':{'from':{'id':uid},'chat':{'id':uid},'id':'3','text':'/start','type':'TEXT'}})
assert 'مدیریت هوشمند گروه‌های سروش+' in transport.sent[-1][1]
assert 'مرکز کنترل' not in transport.sent[-1][1]

# Existing-account group: no duplicate join and persistent control mapping.
existing.update(enabled=True,authorized=True); joins.clear()
msg=mod.IncomingMessage(raw={},sender_id=uid,chat_id=uid,message_id='4',body='https://splus.ir/joingroup/abc',message_type='TEXT')
core._begin_group_link(msg,'invite','abc')
assert not joins and 'از قبل به ZIVO متصل بود' in transport.sent[-1][1]
assert (int(uid),777) in managed
store.set_control_state(uid,active_group_id=777,mode='')

# Dynamic management panel really changes with group plan.
plan_by_group[777]='free'; core._send_control_panel(uid,uid); free_labels=labels(transport.sent[-1][2]); free_text=transport.sent[-1][1]
assert 'FREE' in free_text and any('حذف 700' in x for x in free_labels)
assert not any('فیلتر محتوا' in x for x in free_labels) and not any('AI روشن' in x for x in free_labels)
plan_by_group[777]='silver'; core._send_control_panel(uid,uid); silver_labels=labels(transport.sent[-1][2]); silver_text=transport.sent[-1][1]
assert 'SILVER' in silver_text and any('حذف 2,000' in x for x in silver_labels) and any('فیلتر محتوا' in x for x in silver_labels)
assert not any('AI روشن' in x for x in silver_labels)
plan_by_group[777]='gold'; core._send_control_panel(uid,uid); gold_labels=labels(transport.sent[-1][2]); gold_text=transport.sent[-1][1]
assert 'GOLD' in gold_text and any('حذف 5,000' in x for x in gold_labels) and any('گزارش امروز' in x for x in gold_labels) and any('AI روشن' in x for x in gold_labels)
assert not any('Auto Mod روشن' in x for x in gold_labels)
plan_by_group[777]='diamond'; core._send_control_panel(uid,uid); dia_labels=labels(transport.sent[-1][2]); dia_text=transport.sent[-1][1]
assert 'DIAMOND' in dia_text and any('Auto Mod روشن' in x for x in dia_labels) and any('سلامت گروه' in x for x in dia_labels) and any('Watch List' in x for x in dia_labels)
# Plan feature screen is contextual to the selected group.
core._send_plan_features(uid,uid); assert 'امکانات فعال همین گروه' in transport.sent[-1][1] and 'DIAMOND' in transport.sent[-1][1]

# Cleanup buttons dispatch exact group command.
core.handle_callback({'callback_query':{'id':'c1','from':{'id':uid},'message':{'chat':{'id':uid},'message_id':'5'},'data':'ctl:cleanup:5000'}})
assert 'CONTROL_OK' in transport.sent[-1][1]

# Checkout keeps direct payment URL and post-payment page lists unlocked features.
plan_by_group[777]='free'
core._premium_create_order(uid,uid,777,'silver',30)
core._premium_pay(uid,uid,9,'zibal')
last=transport.sent[-1]
assert 'صفحه پرداخت آماده شد' in last[1]
assert any(b.get('url')=='https://pay.example.test/start/123' for b in buttons(last[2]))
core._premium_check_payment(uid,uid,9)
last=transport.sent[-1]
assert 'پرداخت موفق بود · پلن فعال شد' in last[1]
assert 'قابلیت‌هایی که همین الان به مدیریت این گروه اضافه شدند' in last[1]
assert 'سقف پاکسازی از 700 به 2,000' in last[1]
assert any('مدیریت گروه · SILVER' in str(b.get('text')) for b in buttons(last[2]))
# After activation same management panel becomes SILVER.
core._send_control_panel(uid,uid)
assert 'SILVER' in transport.sent[-1][1] and any('فیلتر محتوا' in x for x in labels(transport.sent[-1][2]))

# Main UI no longer exposes separate premium-control center.
assert not any(b.get('callback_data')=='menu:premiumtools' for b in buttons(mod.MAIN_MENU))
assert any(b.get('callback_data')=='ctl:current' and 'مدیریت گروه' in str(b.get('text')) for b in buttons(mod.MAIN_MENU))

print('ZIVO OFFICIAL15 DYNAMIC GROUP PANEL + PAYMENT RETURN + SOFT GATE: PASS')
print('  two-touch soft onboarding with no hard membership RPC: PASS')
print('  existing-group reuse/no duplicate join: PASS')
print('  FREE/SILVER/GOLD/DIAMOND dynamic management buttons: PASS')
print('  plan-aware cleanup controls: PASS')
print('  direct gateway URL + dedicated activated/unlocked-features page: PASS')
print('  separate premium control center removed from main UI: PASS')
