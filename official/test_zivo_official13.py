import zivo_official13 as mod
assert mod.VERSION == 'zivo-official13'
store=mod.Store()
class T:
    def __init__(self): self.sent=[]
    def send_text(self, chat_id, text, reply_markup=None): self.sent.append((str(chat_id),text,reply_markup)); return {'ok':True}
    def answer_callback(self,*a,**k): return {'ok':True}
transport=T(); core=mod.BotCore(store,transport)
orders={}
def fake_ipc(account,payload,timeout=45.0):
    op=payload.get('op'); act=payload.get('action')
    if op=='status': return {'ok':True,'account_key':account,'account_label':account,'enabled':True,'connected':True,'self_id':1,'groups_count':5}
    if op=='inspect_link': return {'ok':True,'title':'گروه تست','about':'بیوی تست','member_count':321,'group_id':777,'account_key':account}
    if op=='join': return {'ok':True,'result_code':'joined_full','group_id':777,'title':'گروه تست','member_count':321,'elapsed_ms':120}
    if op=='groups': return {'ok':True,'groups':[{'group_id':777,'title':'گروه تست','account_key':'acc2','account_label':'acc2','member_count':321}]}
    if op=='premium' and act=='catalog': return {'ok':True,'plans':[{'plan':'silver','label':'نقره‌ای','prices':[{'duration_days':30,'money_toman':'55,000 تومان','money_rial':'550,000 ریال'}]},{'plan':'gold','label':'طلایی','prices':[{'duration_days':30,'money_toman':'99,000 تومان','money_rial':'990,000 ریال'}]},{'plan':'diamond','label':'الماس','prices':[{'duration_days':30,'money_toman':'120,000 تومان','money_rial':'1,200,000 ریال'}]}],'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='status': return {'ok':True,'subscription':{'plan':'free','status':'active'},'plan_label':'رایگان'}
    if op=='premium' and act=='create_order':
        o={'order_id':9,'order_code':'ZV-ABC-12345','amount_rial':550000,'original_amount_rial':550000,'discount_rial':0,'discount_code':'','group_id':777,'group_title':'گروه تست','plan':'silver','duration_days':30,'status':'created','zibal_track_id':0}; orders[9]=o; return {'ok':True,'order':dict(o),'wallet_balance':600000}
    if op=='premium' and act=='order': return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000,'payment':{'zibal_enabled':True,'card_enabled':False}}
    if op=='premium' and act=='discount_apply':
        orders[9].update({'amount_rial':495000,'original_amount_rial':550000,'discount_rial':55000,'discount_code':'WELCOME10'}); return {'ok':True,'order':dict(orders[9]),'wallet_balance':600000}
    if op=='premium' and act=='check_payment':
        orders[9]['status']='activated'; return {'ok':True,'activated':True,'order':dict(orders[9]),'subscription':{'plan':'silver','status':'active'}}
    if op=='premium' and act=='cancel': orders[9]['status']='cancelled'; return {'ok':True,'cancelled':True,'order':dict(orders[9])}
    if op=='premium' and act=='my_subscriptions': return {'ok':True,'subscriptions':[]}
    if op=='premium' and act=='history': return {'ok':True,'orders':[]}
    if op=='premium' and act=='social': return {'ok':True,'result_text':'SOCIAL_OK'}
    if op=='social': return {'ok':True,'result_text':'SOCIAL_OK'}
    raise AssertionError((account,payload))
core._ipc=fake_ipc
msg=mod.IncomingMessage(raw={},sender_id='49145577',chat_id='49145577',message_id='1',body='https://splus.ir/joingroup/abc123',message_type='TEXT')
core._begin_group_link(msg,'invite','abc123')
assert any('گروه شناسایی شد' in x[1] and '321' in x[1] for x in transport.sent)
pending=store._connect().execute('select * from pending_group_links order by request_id desc limit 1').fetchone(); rid=int(pending['request_id'])
cb=mod.IncomingCallback(raw={},callback_id='c1',sender_id='49145577',chat_id='49145577',message_id='2',data=f'bridge:confirm:{rid}')
core._confirm_group_join(cb,rid)
assert any('گروه با موفقیت وصل شد' in x[1] for x in transport.sent)
core._premium_group_menu('49145577','49145577',777)
assert any('انتخاب پلن' in x[1] for x in transport.sent)
core._premium_duration_menu('49145577','49145577',777,'silver')
assert any('انتخاب مدت اشتراک' in x[1] for x in transport.sent)
core._premium_create_order('49145577','49145577',777,'silver',30)
assert any('صفحه پرداخت ZIVO' in x[1] for x in transport.sent)
core._premium_request_coupon('49145577','49145577',9)
core._premium_apply_coupon('49145577','49145577',9,'WELCOME10')
assert any('کد تخفیف اعمال شد' in x[1] for x in transport.sent)
core._premium_check_payment('49145577','49145577',9)
assert any('اشتراک فعال شد' in x[1] for x in transport.sent)
core._premium_my_subscriptions('49145577','49145577')
assert any('این خطا نیست' in x[1] for x in transport.sent)
assert any('⚡' in str(btn) or '🔗' in str(btn) for _,_,mk in transport.sent if mk for row in mk.get('inline_keyboard',[]) for btn in row)
print('ZIVO OFFICIAL13 UX + PREVIEW + CHECKOUT TESTS: PASS')
