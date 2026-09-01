from pathlib import Path
import tempfile
import zivo_official19 as mod
assert mod.VERSION=='zivo-official19'
assert str(mod.BASE_DIR)=='/opt/ZIVO_OFFICIAL_BOT19'

class T:
    def __init__(self): self.sent=[]; self.media=[]; self.downloaded=[]
    def send_text(self,chat_id,text,reply_markup=None): self.sent.append((str(chat_id),str(text),reply_markup)); return {'ok':True}
    def send_media(self,chat_id,item,caption=''): self.media.append((str(chat_id),dict(item),str(caption))); return {'ok':True}
    def download_media_item(self,item,destination):
        p=Path(destination); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'jpg'); self.downloaded.append(str(p)); return p
    def answer_callback(self,*a,**k): return True

def cb(uid,data): return {'callback_query':{'id':'c1','from':{'id':uid},'message':{'message_id':'1','chat':{'id':uid}},'data':data}}
def msg(uid,text='',photo=False,caption=''):
    m={'from':{'id':uid,'username':f'u{uid}','first_name':f'User{uid}'},'chat':{'id':uid},'message_id':'11','type':'TEXT','text':text}
    if photo:
        m.pop('text',None); m['photo']=[{'file_id':'PHOTO123'}]; m['caption']=caption
    return {'message':m}

t=T(); core=mod.BotCore(mod.Store(),t)
orders={10:{'order_id':10,'order_code':'ZV-ABC-12345','order_kind':'meow_purchase','buyer_user_id':60001,'target_user_id':60002,'meow_amount':150,'amount_rial':60000,'status':'created','receipt_path':'','group_id':0},
        11:{'order_id':11,'order_code':'ZV-GRP-12345','order_kind':'subscription','buyer_user_id':60001,'group_id':777,'group_title':'گروه تست','plan':'gold','duration_days':30,'amount_rial':100000,'status':'receipt_submitted','receipt_path':'PHOTO999'}}
review={}
custom=[]

def detail(o):
    x=dict(o); x['review']=dict(review.get(o['order_id'],{})); x['buyer']={'user_id':60001,'username':'buyer','first_name':'Buyer'}; x['target']={'user_id':60002,'username':'target','first_name':'Target'}; return x

def fake(account,p,timeout=45.0):
    op=p.get('op'); a=p.get('action')
    if op=='status': return {'ok':True,'account_key':account,'account_label':account,'enabled':True,'connected':True,'self_id':1,'groups_count':1}
    if op=='official_group_access' and a=='list': return {'ok':True,'groups':[{'group_id':777,'title':'گروه تست','account_key':'main','member_count':500}]}
    if op=='premium':
        if a=='status': return {'ok':True,'subscription':{'plan':'gold','status':'active'},'plan_label':'طلایی'}
        if a=='card':
            oid=int(p['order_ref']); o=orders[oid]; o['status']='awaiting_receipt'; return {'ok':True,'manual_receipt_required':True,'order':dict(o),'card_number':'6037991234567890','card_holder':'ZIVO','amount_rial':o['amount_rial']}
    if op=='official_payment_admin':
        if a=='receipt_submit':
            oid=int(p['order_id']); o=orders[oid]; o['status']='receipt_submitted'; o['receipt_path']=p['file_id']; review[oid]={'receipt_file_id':p['file_id'],'admin_status':'pending'}; return {'ok':True,'order':detail(o)}
        if a=='detail':
            ref=str(p.get('order_ref')); o=orders.get(int(ref)) if ref.isdigit() else next((x for x in orders.values() if x['order_code']==ref),None); return {'ok':bool(o),'order':detail(o) if o else None}
        if a=='list': return {'ok':True,'orders':[dict(x) for x in orders.values()]}
        if a=='approve':
            oid=int(p['order_id']); orders[oid]['status']='activated'; review.setdefault(oid,{})['admin_status']='approved'; return {'ok':True,'order':detail(orders[oid])}
        if a in {'reject','reverse'}:
            oid=int(p['order_id']); orders[oid]['status']='reversed' if a=='reverse' or orders[oid]['status']=='activated' else 'rejected'; review.setdefault(oid,{})['admin_status']=orders[oid]['status']; return {'ok':True,'order':detail(orders[oid])}
    if op=='official_group_customization':
        custom.append(dict(p));
        if a=='speaker_list': return {'ok':True,'items':[{'trigger':'سلام','response':'درود'}]}
        if a=='speaker_delete': return {'ok':True,'removed':True}
        if a=='speaker_learn':
            if 'فحش' in str(p.get('response')): return {'ok':False,'error':'SPEAKER_PROFANITY_BLOCKED'}
            return {'ok':True,'count':2}
        return {'ok':True,'settings':{}}
    return {'ok':True,'groups':[]}
core._ipc=fake
# speed cache / parallel probe shape
rows=core._account_rows(); assert len(rows)==3
# card page has paid button
core._premium_payment('60001','60001',10,'card'); labels=[b['text'] for row in t.sent[-1][2]['inline_keyboard'] for b in row]; assert any('پرداخت کردم' in x for x in labels)
# photo-only receipt: text is rejected, photo accepted and owner notified
core.handle_callback(cb('60001','receipt:start:10'))
r=core.handle(msg('60001','not a photo')); assert 'فقط عکس' in r
r=core.handle(msg('60001',photo=True)); assert 'رسید دریافت شد' in r and orders[10]['status']=='receipt_submitted'; assert any(x[1].get('file_id')=='PHOTO123' for x in t.media)
# admin order list/detail/search and approve/reverse
core.handle_callback(cb(str(next(iter(mod.GLOBAL_OWNER_IDS))),'payadmin:list')); assert 'مدیریت سفارش' in t.sent[-1][1]
owner=str(next(iter(mod.GLOBAL_OWNER_IDS)))
core.handle_callback(cb(owner,'payadmin:approve:10')); assert orders[10]['status']=='activated'
core.handle_callback(cb(owner,'payadmin:reverse:10')); assert orders[10]['status']=='reversed'
# Gold welcome text and media + speaker safe/profanity blocked
core.store.add_managed_group(user_id='60001',group_id=777,account_key='main',title='گروه تست',member_count=500)
core.store.set_control_state('60001',active_group_id=777)
core.handle_callback(cb('60001','custom:welcome:text')); core.handle(msg('60001','خوش آمدی {نام} | {بیو}')); assert any(x.get('action')=='welcome_text' for x in custom)
core.handle_callback(cb('60001','custom:welcome:photo')); core.handle(msg('60001',photo=True)); assert any(x.get('action')=='welcome_media_path' for x in custom)
core.handle_callback(cb('60001','custom:speaker:learn')); r=core.handle(msg('60001','سلام => درود')); assert 'ذخیره شد' in r
core.handle_callback(cb('60001','custom:speaker:learn')); r=core.handle(msg('60001','x => فحش')); assert 'ذخیره نشد' in r or 'فحش' in r
# Official19 cleanup must return immediately via queue and status polling.
control_jobs={}
next_job=[500]
old_fake=core._ipc
def fake19(account,p,timeout=45.0):
    if p.get('op')=='control_enqueue':
        jid=next_job[0]; next_job[0]+=1
        control_jobs[jid]={'status':'queued','result_text':'در صف'}
        return {'ok':True,'status':'queued','job_id':jid,'result_code':'QUEUED'}
    if p.get('op')=='control_status':
        jid=int(p.get('job_id') or 0); row=control_jobs.get(jid)
        return {'ok':bool(row),'job_id':jid,**(row or {'status':'missing'})}
    return old_fake(account,p,timeout)
core._ipc=fake19
core.store.add_managed_group(user_id='60001',group_id=777,account_key='main',title='گروه تست',member_count=500)
core.store.set_control_state('60001',active_group_id=777)
text=core._queue_remote_command(user_id='60001',chat_id='60001',command_text='پاکسازی 5000')
assert 'شروع شد' in text and 'CL-500' in text
assert core._last_control_job['60001']['job_id']==500
control_jobs[500]={'status':'done','result_text':'فرمان اجرا شد: پاکسازی 5000'}
status=core._control_job_status('60001','60001')
assert 'موفقیت' in status and 'CL-500' in status
print('ZIVO OFFICIAL19 RECEIPT/WELCOME/SPEAKER + ASYNC CLEANUP TEST: PASS')
