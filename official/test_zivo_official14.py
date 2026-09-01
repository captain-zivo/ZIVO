import zivo_official14 as mod
assert mod.VERSION == 'zivo-official14'

class T:
    def __init__(self): self.sent=[]
    def send_text(self, chat_id, text, reply_markup=None): self.sent.append((str(chat_id),text,reply_markup)); return {'ok':True}
    def answer_callback(self,*a,**k): return {'ok':True}

def buttons(markup):
    return [b for row in (markup or {}).get('inline_keyboard',[]) for b in row]

store=mod.Store(); transport=T(); core=mod.BotCore(store,transport)
orders={}; gate={}; joins=[]; managed={}; existing_mode={'enabled':False,'authorized':False}
def fake_ipc(account,payload,timeout=45.0):
    op=payload.get('op'); act=payload.get('action'); uid=int(payload.get('requester_user_id') or 0)
    if op=='status': return {'ok':True,'account_key':account,'account_label':account,'enabled':True,'connected':True,'self_id':10+{'main':0,'acc2':1,'acc3':2}.get(account,0),'groups_count':99}
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
        allowed=bool(gate.setdefault(uid,{}).get('network_member'))
        return {'ok':True,'allowed':allowed,'missing':[] if allowed else ['@ZIVOHELP','@ZIVOCMD'],'unknown':[],'channels':['@ZIVOHELP','@ZIVOCMD']}
    if op=='inspect_link':
        return {'ok':True,'title':'گروه تست','about':'بیوی تست','member_count':321,'group_id':777,'account_key':account,
                'already_member': bool(existing_mode['enabled'] and account=='acc2'),
                'requester_can_control': bool(existing_mode['enabled'] and account=='acc2' and existing_mode['authorized'])}
    if op=='join':
        joins.append((account,dict(payload)))
        return {'ok':True,'result_code':'joined_full','group_id':777,'title':'گروه تست','member_count':321,'elapsed_ms':120,'joined_now':True,'requester_can_control':True}
    if op=='groups': return {'ok':True,'groups':[]}
    if op=='control': return {'ok':True,'result_code':'done','result_text':'CONTROL_OK','elapsed_ms':10}
    if op=='social': return {'ok':True,'result_text':'SOCIAL_OK'}
    if op=='premium' and act=='catalog': return {'ok':True,'plans':[{'plan':'silver','label':'نقره‌ای','prices':[{'duration_days':30,'money_toman':'55,000 تومان','money_rial':'550,000 ریال'}]},{'plan':'gold','label':'طلایی','prices':[{'duration_days':30,'money_toman':'99,000 تومان','money_rial':'990,000 ریال'}]},{'plan':'diamond','label':'الماس','prices':[{'duration_days':30,'money_toman':'120,000 تومان','money_rial':'1,200,000 ریال'}]}],'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='status': return {'ok':True,'subscription':{'plan':'gold','status':'active'},'plan_label':'طلایی'}
    if op=='premium' and act=='create_order':
        o={'order_id':9,'order_code':'ZV-ABC-12345','amount_rial':550000,'original_amount_rial':550000,'discount_rial':0,'discount_code':'','group_id':777,'group_title':'گروه تست','plan':'silver','duration_days':30,'status':'created','zibal_track_id':0}; orders[9]=o; return {'ok':True,'order':dict(o),'wallet_balance':600000}
    if op=='premium' and act=='order': return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='zibal':
        orders[9]['status']='gateway_pending'; orders[9]['zibal_track_id']=123
        return {'ok':True,'payment_url':'https://pay.example.test/start/123','order':dict(orders[9])}
    if op=='premium' and act=='discount_apply':
        orders[9].update({'amount_rial':495000,'original_amount_rial':550000,'discount_rial':55000,'discount_code':'WELCOME10'}); return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000}
    if op=='premium' and act=='check_payment':
        orders[9]['status']='activated'; return {'ok':True,'activated':True,'order':dict(orders[9]),'subscription':{'plan':'silver','status':'active'}}
    if op=='premium' and act=='my_subscriptions': return {'ok':True,'subscriptions':[]}
    if op=='premium' and act=='history': return {'ok':True,'orders':[]}
    raise AssertionError((account,payload))
core._ipc=fake_ipc

# New private user: first PM is gated, buttons are URLs + check.
uid='60001'; msg=mod.IncomingMessage(raw={},sender_id=uid,chat_id=uid,message_id='1',body='/start',message_type='TEXT')
core.handle({'message':{'from':{'id':uid},'chat':{'id':uid},'id':'1','text':'/start','type':'TEXT'}})
last=transport.sent[-1]; assert 'خوش اومدی' in last[1]
bs=buttons(last[2]); assert sum(1 for b in bs if b.get('url'))==2 and any(b.get('callback_data')=='gate:check' for b in bs)
# Failed membership check remains gated.
cb=mod.IncomingCallback(raw={},callback_id='g1',sender_id=uid,chat_id=uid,message_id='2',data='gate:check')
core.handle_callback({'callback_query':{'id':'g1','from':{'id':uid},'message':{'chat':{'id':uid},'message_id':'2'},'data':'gate:check'}})
assert 'هنوز عضویتت در کانال‌های رسمی تأیید نشده' in transport.sent[-1][1]
# Pass once; persistent gate updated.
gate[int(uid)]['network_member']=True
core.handle_callback({'callback_query':{'id':'g2','from':{'id':uid},'message':{'chat':{'id':uid},'message_id':'3'},'data':'gate:check'}})
assert gate[int(uid)]['membership_passed'] is True and 'پنل کامل ZIVO' in transport.sent[-1][1]
# Fresh Official memory after restart consults persistent state and does not gate again.
store2=mod.Store(); t2=T(); core2=mod.BotCore(store2,t2); core2._ipc=fake_ipc
core2.handle({'message':{'from':{'id':uid},'chat':{'id':uid},'id':'4','text':'/start','type':'TEXT'}})
assert 'مرکز فرماندهی گروه' in t2.sent[-1][1] and 'FREE' in t2.sent[-1][1]

# Existing ZIVO account in group + authorized requester: reuse, no second join.
existing_mode.update(enabled=True,authorized=True); joins.clear()
msg2=mod.IncomingMessage(raw={},sender_id=uid,chat_id=uid,message_id='5',body='https://splus.ir/joingroup/abc',message_type='TEXT')
core._begin_group_link(msg2,'invite','abc')
assert not joins and 'از قبل به ZIVO متصل بود' in transport.sent[-1][1]
assert core._premium_group_row(uid,777) is not None
assert (int(uid),777) in managed, 'existing group must persist in shared Core mapping'
# Official restart must recover the group from Core even though local Store is empty.
store3=mod.Store(); t3=T(); core3=mod.BotCore(store3,t3); core3._ipc=fake_ipc
recovered=core3._managed_rows_for_user(uid)
assert any(int(r.get('group_id') or 0)==777 and r.get('account_key')=='acc2' for r in recovered)
# Existing but unauthorized: no second account join and claim button shown.
uid2='60002'; gate[int(uid2)]={'seen':True,'membership_passed':True,'network_member':True}; existing_mode.update(enabled=True,authorized=False); joins.clear()
msg3=mod.IncomingMessage(raw={},sender_id=uid2,chat_id=uid2,message_id='6',body='https://splus.ir/joingroup/abc',message_type='TEXT')
core._begin_group_link(msg3,'invite','abc')
assert not joins and 'اکانت دیگری Join نمی‌شود' in transport.sent[-1][1]
assert any(b.get('callback_data','').startswith('bridge:claim:') for b in buttons(transport.sent[-1][2]))

# New group normal flow still joins after explicit confirm.
existing_mode.update(enabled=False,authorized=False); joins.clear()
msg4=mod.IncomingMessage(raw={},sender_id=uid,chat_id=uid,message_id='7',body='https://splus.ir/joingroup/new',message_type='TEXT')
core._begin_group_link(msg4,'invite','new')
pending=store._connect().execute('select * from pending_group_links where user_id=? order by request_id desc limit 1',(uid,)).fetchone(); rid=int(pending['request_id'])
cb2=mod.IncomingCallback(raw={},callback_id='c2',sender_id=uid,chat_id=uid,message_id='8',data=f'bridge:confirm:{rid}')
core._confirm_group_join(cb2,rid)
assert len(joins)==1 and 'اتصال ZIVO با موفقیت انجام شد' in transport.sent[-1][1]

# Checkout: direct URL payment button + dedicated activated page.
core._premium_create_order(uid,uid,777,'silver',30)
core._premium_pay(uid,uid,9,'zibal')
last=transport.sent[-1]; assert 'درگاه پرداخت آماده شد' in last[1]
assert any(b.get('url')=='https://pay.example.test/start/123' for b in buttons(last[2]))
core._premium_check_payment(uid,uid,9)
last=transport.sent[-1]; assert '🎉 پرداخت با موفقیت تأیید شد' in last[1] and 'قابلیت‌های این پلن همین الان' in last[1]
assert any(b.get('callback_data')=='ctl:current' for b in buttons(last[2]))
# Plan comparison is list-form and actual tier controls are exposed.
assert all(x in mod.CAPABILITY_STATUS_TEXT for x in ['FREE','SILVER','GOLD','DIAMOND','Meow Luck','Content Filter'])
assert any(b.get('callback_data')=='ctl:q:ai_on' for b in buttons(mod.PREMIUM_TOOLS_MENU))
print('ZIVO OFFICIAL14 PREMIUM TIERS + MEMBERSHIP + PAY UX TESTS: PASS')
print('  new-private persistent membership gate + URL buttons: PASS')
print('  existing-group reuse / no duplicate account join + restart persistence: PASS')
print('  explicit preview/confirm new-group join: PASS')
print('  direct gateway URL + dedicated activated page: PASS')
print('  FREE/SILVER/GOLD/DIAMOND list UI + controls: PASS')
