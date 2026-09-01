from pathlib import Path
import tempfile
import zivo_official17 as mod
assert mod.VERSION == 'zivo-official17'
assert str(mod.BASE_DIR) == '/opt/ZIVO_OFFICIAL_BOT17'

class T:
    def __init__(self): self.sent=[]; self.media=[]; self.downloaded=[]
    def send_text(self, chat_id, text, reply_markup=None): self.sent.append((str(chat_id),str(text),reply_markup)); return {'ok':True}
    def send_media(self, chat_id, item, caption=''): self.media.append((str(chat_id),dict(item),str(caption))); return {'ok':True}
    def download_media_item(self,item,destination):
        p=Path(destination); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'x'); self.downloaded.append((dict(item),str(p))); return p
    def answer_callback(self,*a,**k): return True

def cb(uid,data,mid='1'):
    return {'callback_query':{'id':'c'+mid,'from':{'id':uid},'message':{'message_id':mid,'chat':{'id':uid}},'data':data}}

def msg(uid,text='',**extra):
    m={'from':{'id':uid,'username':f'u{uid}','first_name':f'User{uid}'},'chat':{'id':uid},'message_id':'1','text':text,'type':'TEXT'}; m.update(extra); return {'message':m}

def labels(markup): return [str(b.get('text') or '') for row in (markup or {}).get('inline_keyboard',[]) for b in row]

transport=T(); core=mod.BotCore(mod.Store(),transport)
users={60001:{'user_id':60001,'username':'buyer','first_name':'خریدار'},60002:{'user_id':60002,'username':'target','first_name':'مقصد'},49145577:{'user_id':49145577,'username':'owner','first_name':'مالک'}}
bal={60001:1000,60002:10}; pending={}; orders={}; next_order=[10]; gifts={}; notifications=[]
locks=[{'name':'لینک','enabled':True,'max_warnings':3,'auto_ban':False},{'name':'فحش','enabled':False,'max_warnings':2,'auto_ban':True},{'name':'فوروارد','enabled':True,'max_warnings':3,'auto_ban':False}]
admin_calls=[]

def fake_ipc(account,p,timeout=45.0):
    op=p.get('op'); a=p.get('action'); uid=int(p.get('requester_user_id') or 0)
    if op=='official_gate':
        if a=='status': return {'ok':True,'state':{'seen':True,'membership_passed':True}}
        return {'ok':True,'state':{'seen':True,'membership_passed':True}}
    if op=='official_group_access' and a=='list': return {'ok':True,'groups':[{'group_id':777,'title':'گروه تست','account_key':'main','member_count':500}]}
    if op=='premium' and a=='status': return {'ok':True,'subscription':{'plan':'gold','status':'active'},'plan_label':'طلایی'}
    if op=='meow_commerce':
        if a=='resolve_target':
            ref=str(p.get('reference') or '').strip().lstrip('@')
            row=None
            for u in users.values():
                if ref==str(u['user_id']) or ref.lower()==u['username'].lower(): row=dict(u); break
            return {'ok':bool(row),'user':row,'error':'' if row else 'OFFICIAL_USER_NOT_STARTED'}
        if a=='balance': return {'ok':True,'balance':bal.get(uid,0)}
        if a=='transfer_prepare':
            target=int(p['target_user_id']); amount=int(p['meow_amount'])
            if target not in users: return {'ok':False,'error':'OFFICIAL_USER_NOT_STARTED'}
            if bal.get(uid,0)<amount: return {'ok':False,'error':'MEOW_INSUFFICIENT_BALANCE'}
            tax=max(1,(amount+49)//50); pending[uid]=(target,amount,tax,amount-tax)
            return {'ok':True,'transfer':{'recipient_id':target,'amount':amount,'tax':tax,'net_amount':amount-tax,'sender_balance':bal.get(uid,0)}}
        if a=='transfer_confirm':
            target,amount,tax,net=pending.pop(uid); bal[uid]-=amount; bal[target]=bal.get(target,0)+net
            return {'ok':True,'transfer':{'recipient_id':target,'amount':amount,'tax':tax,'net_amount':net,'sender_balance_after':bal[uid],'recipient_balance_after':bal[target]}}
        if a=='transfer_cancel': pending.pop(uid,None); return {'ok':True}
        if a=='gift_redeem':
            code=str(p.get('code') or '').upper(); g=gifts.get(code)
            if not g or g['used']: return {'ok':False,'error':'MEOW_GIFT_CODE_USED'}
            g['used']=True; bal[uid]=bal.get(uid,0)+g['amount']; return {'ok':True,'gift':{'code':code,'creator_user_id':g['creator'],'meow_amount':g['amount'],'balance_after':bal[uid]}}
        if a=='notifications': return {'ok':True,'notifications':list(notifications)}
        if a=='notification_finish': return {'ok':True}
    if op=='premium':
        if a in {'create_meow_order','create_meow_gift_order'}:
            oid=next_order[0]; next_order[0]+=1; amount=int(p['meow_amount']); kind='meow_gift_code' if a.endswith('gift_order') else 'meow_purchase'; target=int(p.get('target_user_id') or 0)
            o={'order_id':oid,'order_code':f'ZV-{oid}','order_kind':kind,'target_user_id':target,'meow_amount':amount,'original_amount_rial':amount*400,'amount_rial':amount*400,'discount_percent':0,'status':'created','gift_code':''}; orders[oid]=o
            return {'ok':True,'order':dict(o)}
        oid=int(p.get('order_ref') or 0); o=orders.get(oid,{})
        if a=='order': return {'ok':True,'order':dict(o)}
        if a=='discount_apply': o['discount_percent']=20; o['amount_rial']=int(o['original_amount_rial']*.8); return {'ok':True,'order':dict(o)}
        if a=='zibal': o['status']='gateway_pending'; return {'ok':True,'payment_url':f'https://pay.test/{oid}','order':dict(o)}
        if a=='card': return {'ok':True,'manual_receipt_required':True,'order':dict(o),'card_number':'6037991234567890','card_holder':'ZIVO','amount_rial':o['amount_rial']}
        if a=='check_payment':
            o['status']='activated'
            if o['order_kind']=='meow_purchase': bal[o['target_user_id']]=bal.get(o['target_user_id'],0)+o['meow_amount']
            else:
                o['gift_code']='ZIVO12345678'; gifts[o['gift_code']]={'creator':uid,'amount':o['meow_amount'],'used':False}
            return {'ok':True,'activated':True,'order':dict(o)}
        if a=='cancel': o['status']='cancelled'; return {'ok':True,'order':dict(o),'cancelled':True}
    if op=='official_group_locks':
        if a=='list': return {'ok':True,'plan':'gold','advanced_allowed':True,'locks':[dict(x) for x in locks]}
        name=p['lock_name']; x=next(z for z in locks if z['name']==name)
        if a=='toggle': x['enabled']=not x['enabled']
        elif a=='warning_delta': x['max_warnings']=max(1,x['max_warnings']+int(p.get('delta') or 0))
        elif a=='autoban_toggle': x['auto_ban']=not x['auto_ban']
        return {'ok':True,'lock':dict(x)}
    if op=='official_admin':
        if a=='official_users': return {'ok':True,'user_ids':[60001,60002]}
        if a=='campaign_create': admin_calls.append(dict(p)); return {'ok':True,'batch_id':f'b{len(admin_calls)}','job_ids':[len(admin_calls)],'accounts':p.get('account_keys') or []}
        if a=='campaign_status': return {'ok':True,'jobs':[]}
        if a=='audience': return {'ok':True,'official':{'enabled':2},'account_network':{'private_enabled':5},'accounts':[],'active_campaigns':0}
    if op=='status': return {'ok':True,'enabled':True,'connected':True,'account_key':account,'groups_count':1}
    if op=='groups': return {'ok':True,'groups':[]}
    if op=='social': return {'ok':True,'result_text':'SOCIAL_OK'}
    if op=='control': return {'ok':True,'result_text':'OK'}
    raise AssertionError((account,p))

core._ipc=fake_ipc
# register active group locally
core.store.add_managed_group(user_id='60001',group_id=777,account_key='main',title='گروه تست',member_count=500)
core.store.set_control_state('60001',active_group_id=777,mode='')

# transfer: amount -> target by username -> confirm, recipient receives Official message
core.handle_callback(cb('60001','meow:transfer'))
core.handle(msg('60001','100'))
core.handle(msg('60001','@target'))
assert any('تأیید انتقال' in x[1] for x in transport.sent)
core.handle_callback(cb('60001','meow:transfer:confirm','2'))
assert bal[60001]==900 and bal[60002]>10
assert any(x[0]=='60002' and 'Meow دریافت کردی' in x[1] for x in transport.sent)

# not-started recipient is blocked
core.handle_callback(cb('60001','meow:transfer','3')); core.handle(msg('60001','30')); core.handle(msg('60001','@nobody'))
assert any('هنوز بات رسمی ZIVO را Start نکرده' in x[1] for x in transport.sent)

# forwarded-message target resolution works without account-bot PM
core.handle_callback(cb('60001','meow:transfer','3f')); core.handle(msg('60001','40'))
fwd=msg('60001','',forward_from={'id':60002,'username':'target','first_name':'مقصد'})
core.handle(fwd)
assert any('تأیید انتقال' in x[1] and 'مقصد' in x[1] for x in transport.sent)
core.handle_callback(cb('60001','meow:cancel','3fc'))

# buy for someone else, price 40 toman, discount, direct URL, card copy, payment success
core.handle_callback(cb('60001','meow:buy','4')); core.handle_callback(cb('60001','meow:buy:other','5')); core.handle(msg('60001','@target')); core.handle(msg('60001','250'))
assert any('10,000 تومان' in x[1] and '100,000 ریال' in x[1] for x in transport.sent)
core.handle_callback(cb('60001','meow:amount:confirm','6')); core.handle_callback(cb('60001','meow:coupon:yes','7')); core.handle(msg('60001','SAVE20'))
assert any('تخفیف: 20٪' in x[1] for x in transport.sent)
core.handle_callback(cb('60001','meow:final:confirm','8'))
assert any(any(b.get('url','').startswith('https://pay.test/') for b in [q for row in (m or {}).get('inline_keyboard',[]) for q in row]) for _,_,m in transport.sent)
oid=max(orders)
core.handle_callback(cb('60001',f'meow:card:{oid}','9')); core.handle_callback(cb('60001','meow:copy:card','10')); assert transport.sent[-1][1]=='6037991234567890'
core.handle_callback(cb('60001','meow:copy:amount','10a')); assert transport.sent[-1][1]==str(orders[oid]['amount_rial'])
core.handle_callback(cb('60001',f'meow:check:{oid}','11')); assert any('Meow شارژ شد' in x[1] for x in transport.sent)

# gift code purchase -> eight digits after ZIVO -> redeem
core.handle_callback(cb('60001','meow:gift','12')); core.handle_callback(cb('60001','meow:gift:buy','13')); core.handle(msg('60001','100')); core.handle_callback(cb('60001','meow:amount:confirm','14')); core.handle_callback(cb('60001','meow:coupon:skip','15')); core.handle_callback(cb('60001','meow:final:confirm','16'))
goid=max(orders); core.handle_callback(cb('60001',f'meow:check:{goid}','17')); assert orders[goid]['gift_code']=='ZIVO12345678'
core.handle_callback(cb('60002','meow:gift:redeem','18')); core.handle(msg('60002','ZIVO12345678')); assert gifts['ZIVO12345678']['used']

# full lock control buttons, toggle/warning/autoban
core.handle_callback(cb('60001','locks:list','19')); assert any('مدیریت قفل‌های گروه' in x[1] for x in transport.sent)
core.handle_callback(cb('60001','locks:t:0:فحش','20')); assert next(x for x in locks if x['name']=='فحش')['enabled']
core.handle_callback(cb('60001','locks:w:1:0:لینک','21')); assert next(x for x in locks if x['name']=='لینک')['max_warnings']==4
core.handle_callback(cb('60001','locks:b:0:لینک','22')); assert next(x for x in locks if x['name']=='لینک')['auto_ban']

# admin: groups scope + all accounts + text and 2 photos + preview/send = 3 account campaigns
owner='49145577'
core.handle_callback(cb(owner,'admin:adscope:groups','23')); core.handle_callback(cb(owner,'admin:adacct:all','24'))
core.handle(msg(owner,'متن تبلیغ'))
core.handle(msg(owner,'',photo=[{'file_id':'ph1'}],caption='عکس اول'))
core.handle(msg(owner,'',photo=[{'file_id':'ph2'}],caption='عکس دوم'))
core.handle_callback(cb(owner,'admin:adpreview','25')); core.handle_callback(cb(owner,'admin:adsend17','26'))
assert len(admin_calls)==3
assert all(x['scope']=='groups' for x in admin_calls)
assert all(x['account_keys']==list(mod.IPC_ACCOUNT_KEYS) for x in admin_calls)
assert transport.downloaded

# admin: private-only to one chosen account
before=len(admin_calls)
core.handle_callback(cb(owner,'admin:adscope:private','26a')); core.handle_callback(cb(owner,'admin:adacct:acc2','26b'))
core.handle(msg(owner,'پیوی فقط acc2')); core.handle_callback(cb(owner,'admin:adpreview','26c')); core.handle_callback(cb(owner,'admin:adsend17','26d'))
new=admin_calls[before:]
assert len(new)==1 and new[0]['scope']=='private' and new[0]['account_keys']==['acc2']

# admin: private+groups to selected main proves combined target scope
before=len(admin_calls)
core.handle_callback(cb(owner,'admin:adscope:both','26e')); core.handle_callback(cb(owner,'admin:adacct:main','26f'))
core.handle(msg(owner,'پیوی و گروه main')); core.handle_callback(cb(owner,'admin:adpreview','26g')); core.handle_callback(cb(owner,'admin:adsend17','26h'))
new=admin_calls[before:]
assert len(new)==1 and new[0]['scope']=='both' and new[0]['account_keys']==['main']

# Official rich broadcast can send media too
core._admin_state[owner]={'stage':'ad_collect','scope':'official','account_keys':[],'items':[{'type':'text','text':'سلام'},{'type':'photo','file_id':'ph3','text':'کپشن'}]}
core._admin_send_parts(owner,owner)
import time; time.sleep(.5)
assert transport.media and any(x[0]=='60002' for x in transport.media)

print('ZIVO OFFICIAL17 MEOW + MEDIA CAMPAIGN + LOCK ADMIN TEST: PASS')
