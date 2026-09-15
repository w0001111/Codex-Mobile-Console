# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Message receipts keyed by exact actor, thread and request; no automatic retry."""
import contextlib
import time
import uuid
from ui_state import UIState

LABELS={'sending':'正在发送','accepted':'已接收','executing':'正在执行','completed':'回复完成','uncertain':'结果待核对','refused':'未发送','failed':'执行失败','interrupted':'已中断','waiting':'等待你处理','ended':'本轮已结束'}
TERMINAL={'completed','failed','interrupted','refused','ended'}

def turn_receipts(raw):
    result=[]
    for t in raw:
        items=t.get('items',[])
        result.append({'id':t.get('turnId') or t.get('id'),'status':t.get('status'),
            'clientIds':[i.get('clientId') for i in items if i.get('type')=='userMessage' and i.get('clientId')],
            'hasReply':any(i.get('type')=='agentMessage' and i.get('phase') in ('final_answer',None) and i.get('text') for i in items)})
    return result

def resolve(actor,record,ack,turns,now=None):
    now=time.time() if now is None else now
    phase=record['phase'];confirmed=False
    if phase in TERMINAL:return {**record,'label':LABELS[phase]}
    client_id=str(uuid.uuid5(uuid.NAMESPACE_URL,actor+'\0mobile-'+record['requestId']))
    turn_id=ack.get('turnId') if ack else None
    match=next((t for t in turns if (turn_id and t['id']==turn_id) or client_id in t.get('clientIds',[])),None)
    if match:
        status=match['status'];confirmed=True
        phase={'inProgress':'executing','completed':'completed' if match.get('hasReply') else 'ended','failed':'failed','interrupted':'interrupted'}.get(status,'accepted')
    elif ack and ack.get('status')=='accepted':phase='accepted'
    elif ack and ack.get('status') in ('uncertain','dispatching'):phase='uncertain'
    elif phase=='sending' and now-record['createdAt']>45:phase='uncertain'
    hint=''
    if phase=='accepted' and not confirmed:hint='电脑已确认接收；当前执行状态暂未核实。'
    if phase=='uncertain':hint='正在按这条消息的编号核对，请勿重复发送。'
    return {**record,'phase':phase,'label':LABELS[phase],'hint':hint,'checkedAt':now}

class DeliveryStore(UIState):
    def connect(self):
        db=super().connect()
        db.execute('CREATE TABLE IF NOT EXISTS web_receipts (actor TEXT, thread TEXT, request_id TEXT, phase TEXT, created REAL, PRIMARY KEY(actor,request_id))')
        return db
    def begin(self,actor,tid,rid):
        with contextlib.closing(self.connect()) as db,db:
            db.execute('INSERT OR IGNORE INTO web_receipts VALUES (?,?,?,?,?)',(actor,tid,rid,'sending',time.time()))
            if db.execute('SELECT thread FROM web_receipts WHERE actor=? AND request_id=?',(actor,rid)).fetchone()[0]!=tid:raise ValueError('request belongs to another thread')
    def phase(self,actor,tid,rid,phase):
        if phase not in LABELS:raise ValueError('unknown receipt phase')
        with contextlib.closing(self.connect()) as db,db:db.execute('UPDATE web_receipts SET phase=? WHERE actor=? AND thread=? AND request_id=?',(phase,actor,tid,rid))
    def records(self,actor,tid,rid=None):
        with contextlib.closing(self.connect()) as db:
            sql='SELECT request_id,phase,created FROM web_receipts WHERE actor=? AND thread=?';args=[actor,tid]
            if rid:sql+=' AND request_id=?';args.append(rid)
            sql+=' ORDER BY created DESC LIMIT 8'
            return [{'requestId':r,'phase':p,'createdAt':t} for r,p,t in db.execute(sql,args)]
