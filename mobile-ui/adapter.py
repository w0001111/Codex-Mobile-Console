# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Narrow desktop-task facade; browser cannot choose its actor or raw IPC method."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid

ENTRY_DIR=Path(__file__).resolve().parent.parent/'bridge'
sys.path.insert(0,str(ENTRY_DIR))
from paths import BRIDGE_STATE
from wechat_entry import Entry,identity,clean,target,check_saved
from desktop_ipc import DesktopIPC,IPCError,ensure_idle,ensure_can_send,latest_result,turns
from mobile_reads import StatusIPC,ConnectIPC,ReadJobs


def identity_key(value):
    return identity({**value,'version':1,'message_id':'mobile-identity','args':[]})[0]

def base_envelope(value):
    identity_key(value)
    return {key:value[key] for key in ('project','platform','session_key','user_id')}

class Adapter:
    def __init__(self,state=None,organization_path=None):
        from ui_state import UIState
        from delivery import DeliveryStore
        from artifacts import ArtifactStore
        from model_settings import ModelCatalog,SettingsStore
        from desktop_catalog import STATE
        from quota import Quota
        from message_activity import MessageActivity
        self.quota_reader=Quota()
        self.history_jobs=ReadJobs();self.file_jobs=ReadJobs(capacity=1,max_entries=32)
        self.cache={};self.lock=threading.Lock();self.pool=ThreadPoolExecutor(max_workers=4)
        self.index_lock=threading.Lock();self.index=None;self.index_at=0;self.index_complete=False;self.scan_at=0;self.scanning=False;self.hot_at=0;self.hot_scanning=False
        self.preferences=UIState(state or BRIDGE_STATE.parent);self.organization_path=organization_path or STATE
        self.receipts=DeliveryStore(self.preferences.directory);self.artifacts=ArtifactStore(self.preferences.directory)
        self.message_activity=MessageActivity(self.preferences.directory)
        self.models=ModelCatalog();self.model_changes=SettingsStore(self.preferences.directory)
    def current(self,env):
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:
            selected=entry.selected(actor)
            if not selected:return None
            row=entry.catalog.db.execute('SELECT title,cwd,thread_id FROM refs WHERE actor=? AND number=?',(actor,selected[0])).fetchone()
            if not row:return None
            item=self.item(entry,actor,selected[0],row[0],row[1],env.get('web_account',False))
            item.update(threadId=row[2],originalTitle=clean(row[0],300))
            self.preferences.decorate(actor,[item]);return item
    def item(self,entry,actor,n,title,cwd,web=False):
        label=entry.label(actor,n,title).split('｜',1)[1]
        return {'number':n,'ref':f'{"W" if web else "T"}{n:04d}','title':clean(label,140),'project':clean(Path(cwd).name,60),'status':'unknown','statusLabel':'待查询'}
    def catalog(self):
        with self.index_lock:
            if time.time()-self.index_at<30 and self.index is not None:return self.index,self.index_complete
            collected=[];cursor=None
            with contextlib.closing(Entry()) as entry:
                for _ in range(20):
                    r=entry.api.request('thread/list',{'limit':100,'cursor':cursor,'sortKey':'updated_at','sortDirection':'desc',
                        'modelProviders':[],'sourceKinds':['cli','vscode','exec','appServer','unknown'],'archived':False,'useStateDbOnly':True})
                    collected.extend(r.get('data',[]));cursor=r.get('nextCursor')
                    if not cursor:break
            self.index=list({t['id']:t for t in collected}.values());self.index_complete=not cursor;self.index_at=time.time()
            return self.index,self.index_complete
    def schedule_scan(self,threads):
        with self.lock:
            if self.scanning or time.time()-self.scan_at<30:return
            self.scanning=True;self.scan_at=time.time()
        def scan():
            try:
                for _ in self.pool.map(lambda t:self.observe(t['id'],False),threads):pass
            finally:
                with self.lock:self.scanning=False
        threading.Thread(target=scan,daemon=True).start()
    def schedule_live_refresh(self,thread_ids=None):
        with self.lock:
            if self.hot_scanning or time.time()-self.hot_at<14:return
            ids=[tid for tid,state in self.cache.items() if state.get('live') and (thread_ids is None or tid in thread_ids)]
            if not ids:return
            self.hot_scanning=True;self.hot_at=time.time()
        def scan():
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    for _ in pool.map(lambda tid:self.observe(tid,True),ids):pass
            finally:
                with self.lock:self.hot_scanning=False
        threading.Thread(target=scan,daemon=True).start()
    def listing(self,env,query='',cursor=None,group='all',status='all',limit=24,sort='priority'):
        from desktop_catalog import organization,project_for
        actor=identity_key(env);threads,complete=self.catalog()
        try:org=organization(self.organization_path);org_error=False
        except (OSError,ValueError,TypeError):
            org={'groups':[],'assignments':{},'projectless':set(),'pinnedThreads':set(),'hints':{}};org_error=True
        activity=self.message_activity.listing(t['id'] for t in threads) if sort=='message' else {}
        groups=[{k:g[k] for k in ('id','name','pinned')} for g in org['groups']]
        items=[]
        with contextlib.closing(Entry()) as entry:
            with entry.actor_lock(actor),entry.catalog.db:
                for t in threads:
                    tid=t['id'];row=entry.catalog.db.execute('SELECT number FROM refs WHERE actor=? AND thread_id=?',(actor,tid)).fetchone()
                    n=row[0] if row else entry.catalog.db.execute('SELECT COALESCE(MAX(number),0)+1 FROM refs WHERE actor=?',(actor,)).fetchone()[0]
                    title=' '.join((t.get('name') or t.get('preview') or '未命名会话').split());cwd=t.get('cwd') or ''
                    entry.catalog.db.execute('INSERT OR REPLACE INTO refs VALUES (?,?,?,?,?)',(actor,n,tid,title,cwd))
                    g={'id':'unavailable','name':'分组暂不可用','pinned':False} if org_error else project_for(t,org)
                    if g['id'] not in {x['id'] for x in groups}:groups.append({k:g[k] for k in ('id','name','pinned')})
                    item=self.item(entry,actor,n,title,cwd,env.get('web_account',False))
                    item.update(threadId=tid,originalTitle=clean(title,300),project=clean(g['name'],80),groupId=g['id'],desktopPinned=tid in org['pinnedThreads'],updatedAt=t.get('updatedAt',0))
                    item.update(activity.get(tid,{'messageAt':0,'messageKind':''}))
                    with self.lock:observed=dict(self.cache.get(tid,{}))
                    if not observed:observed={'status':'unknown','statusLabel':'待检查','feedback':'正在检查桌面状态','canSend':False,'canChangeModel':False,'sendBlockedReason':'请先连接会话并刷新状态','observedAt':0,'live':False,'resultRevision':''}
                    item.update({k:observed.get(k) for k in ('status','statusLabel','feedback','observedAt','canSend','live','resultRevision','modelSettings')})
                    if item['observedAt'] and time.time()-item['observedAt']>90:
                        item.update(status='unknown',statusLabel='状态待刷新',canSend=False,live=False)
                    items.append(item)
        self.preferences.decorate(actor,items)
        scope=[t for t in items if group=='all' or t['groupId']==group]
        counts={'active':sum(t['status']=='active' for t in scope),'needs_input':sum(t['status'] in ('needs_input','error') for t in scope),'new':sum(t['newResult'] for t in scope),
                'checked':sum(bool(t['observedAt']) for t in scope),'unknown':sum(t['status']=='unknown' for t in scope),'total':len(scope),'complete':complete}
        term=query.casefold()
        filtered=[t for t in items if (group=='all' or t['groupId']==group) and (not term or term in (t['title']+' '+t['originalTitle']+' '+t['project']).casefold())
            and (status=='all' or status=='new' and t['newResult'] or status=='needs_input' and t['status'] in ('needs_input','error') or t['status']==status)]
        if sort=='message':filtered.sort(key=lambda t:(-(t['messageAt'] or 0),t['threadId']))
        elif sort=='recent':filtered.sort(key=lambda t:(not t['pinned'],-(t['updatedAt'] or 0),t['number']))
        else:filtered.sort(key=lambda t:(t['status'] not in ('needs_input','error'),not t['newResult'],not t['pinned'],-t['updatedAt']))
        offset=int(cursor or 0)
        # New clients only need a quick status pass for the leading tasks.
        leading={t['threadId'] for t in filtered[offset:offset+min(limit,8)]}
        self.schedule_scan([t for t in threads if t['id'] in leading] if sort in ('recent','message') else threads)
        if sort in ('recent','message'):self.schedule_live_refresh(leading)
        else:self.schedule_live_refresh()
        return {'tasks':filtered[offset:offset+limit],'nextCursor':str(offset+limit) if offset+limit<len(filtered) else None,'current':self.current(env),
                'overview':counts,'groups':groups,'groupSyncError':org_error,'matchingCount':len(filtered),'observedAt':time.time()}
    def observe(self,tid,fresh=True):
        from presentation import final_revision
        from delivery import turn_receipts
        from model_settings import current_settings
        now=time.time()
        with self.lock:
            cached=self.cache.get(tid)
            if not fresh and cached and now-cached['observedAt']<12:return dict(cached)
        result={'status':'unknown','statusLabel':'桌面未连接','feedback':'点开任务查看已保存的回复','result':'','canSend':False,'canChangeModel':False,'sendBlockedReason':'请先连接会话并刷新状态','observedAt':now,'live':False,'resultRevision':'','recentTurns':[],'turnReceipts':[],'modelSettings':None}
        try:
            check_saved(tid)
            with StatusIPC(timeout=3 if fresh else 1) as ipc:
                owner=ipc.owner(tid)
                ipc.timeout=3
                state=ipc.snapshot(tid,owner)
            turn,text=latest_result(state);runtime=state.get('threadRuntimeStatus',{}).get('type','unknown');ts=(turn or {}).get('status')
            status='active' if runtime=='active' or ts=='inProgress' else 'idle' if runtime=='idle' else 'unknown'
            if status!='active' and (runtime=='systemError' or ts=='failed'):status='error'
            if state.get('requests') or state.get('threadGoalResumeConfirmation'):status='needs_input'
            label={'active':'运行中','idle':'已完成' if ts=='completed' else '可继续','unknown':'状态未知','needs_input':'待确认','error':'出错'}[status]
            messages=[x.get('text') for x in (turn or {}).get('items',[]) if x.get('type')=='agentMessage' and x.get('text')]
            can_send=True;blocked=''
            try:ensure_can_send(state)
            except IPCError as err:
                can_send=False
                blocked='请先在桌面完成确认' if str(err)=='thread-needs-user-input' else '运行中暂不能发送' if status=='active' else '尚未确认任务已结束，请刷新或在桌面查看'
            can_change_model=True
            try:ensure_idle(state)
            except IPCError:can_change_model=False
            if status=='error' and can_send:label='上轮失败，可继续'
            result.update(status=status,statusLabel=label,feedback=clean(messages[-1],1200) if messages else '本轮尚无文字反馈',
                result=clean(text,18000),canSend=can_send,canChangeModel=can_change_model,sendBlockedReason=blocked,live=True,resultRevision=final_revision(turns(state)),recentTurns=turns(state)[-3:],turnReceipts=turn_receipts(turns(state)),modelSettings=current_settings(state))
        except (IPCError,OSError,ValueError):pass
        with self.lock:
            if len(self.cache)>3000:self.cache.clear()
            self.cache[tid]=dict(result)
        return result
    def timeline(self,env,n,cursor=None,include_files=True):
        from presentation import normalize_turn,timestamp,turn_id
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:
            tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
            cwd=entry.catalog.db.execute('SELECT cwd FROM refs WHERE actor=? AND number=?',(actor,n)).fetchone()[0]
            if cursor:
                parsed=json.loads(cursor)
                if not isinstance(parsed,dict) or parsed.get('requestedThreadId')!=tid:raise ValueError('history cursor belongs to another thread')
            args={'threadId':tid,'limit':3,'itemsView':'full','sortDirection':'desc'}
            if cursor:args['cursor']=cursor
            saved=entry.api.request('thread/turns/list',args)
        raw=saved.get('data',[])
        if not cursor:
            with self.lock:live=self.cache.get(tid,{}).get('recentTurns',[])
            merged={turn_id(t):t for t in raw}
            # Only add live turns at or after the saved page boundary, preventing gaps when paging.
            boundary=min((timestamp(t) for t in raw),default=0)
            merged.update({turn_id(t):t for t in live if timestamp(t)>=boundary})
            raw=list(merged.values())
        result={'turns':[normalize_turn(t) for t in sorted(raw,key=timestamp)],'nextCursor':saved.get('nextCursor')}
        if include_files:
            result.update(skippedFiles=self.artifacts.discover(actor,tid,cwd,raw),files=self.artifacts.listing(actor,tid))
        return result
    def read_key(self,env,n,cursor):
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
        if cursor:
            parsed=json.loads(cursor)
            if not isinstance(parsed,dict) or parsed.get('requestedThreadId')!=tid:raise ValueError('history cursor belongs to another thread')
        return actor,tid,cursor
    def history(self,env,n,cursor=None):
        key=self.read_key(env,n,cursor)
        return self.history_jobs.poll(key,lambda:self.timeline(env,n,cursor,include_files=False),ttl=120 if cursor else 6)
    def file_page(self,env,n,cursor=None,refresh=None):
        key=self.read_key(env,n,cursor)
        if refresh:key=(*key,refresh)
        return self.file_jobs.poll(key,lambda:self.files(env,n,cursor),ttl=120)
    def detail(self,env,n,summary=False):
        from desktop_catalog import organization,project_for
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:
            tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
            row=entry.catalog.db.execute('SELECT title,cwd FROM refs WHERE actor=? AND number=?',(actor,n)).fetchone()
            item=self.item(entry,actor,n,*row,env.get('web_account',False));item.update({k:v for k,v in self.observe(tid).items() if k not in ('recentTurns','turnReceipts')})
            item.update(threadId=tid,originalTitle=clean(row[0],300))
            try:
                org=organization(self.organization_path);g=project_for({'id':tid,'cwd':row[1]},org)
                item.update(project=clean(g['name'],80),groupId=g['id'],desktopPinned=tid in org['pinnedThreads'])
            except (OSError,ValueError,TypeError):pass
            self.preferences.decorate(actor,[item]);item['current']=self.current(env)
        # Existing open pages still expect an embedded timeline. Keep that wire
        # contract; new clients explicitly request the independent summary view.
        if not summary:
            try:
                item['timeline']=self.timeline(env,n,include_files=False)
                item['timeline'].update(files=self.artifacts.listing(actor,tid),skippedFiles=0)
            except Exception:
                item['timeline']={'turns':[],'nextCursor':None,'error':'历史暂时无法读取，请重试；已有内容会保留。'}
        item['deliveries']=self.deliveries(env,n,refresh=False)['deliveries']
        return item
    def files(self,env,n,cursor=None):
        page=self.timeline(env,n,cursor)
        return {k:page[k] for k in ('files','skippedFiles','nextCursor')}
    def file(self,env,n,aid):
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
        return self.artifacts.read(actor,tid,aid)
    def deliveries(self,env,n,request_id=None,refresh=True):
        from delivery import resolve,turn_receipts,TERMINAL
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:
            tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
            records=self.receipts.records(actor,tid,request_id)
            observed=self.observe(tid,False) if refresh and records else self.cache.get(tid,{})
            raw=list(observed.get('turnReceipts',[]))
            if refresh and records and not observed.get('live'):
                try:raw+=turn_receipts(entry.api.request('thread/turns/list',{'threadId':tid,'limit':10,'itemsView':'full','sortDirection':'desc'}).get('data',[]))
                except Exception:pass
            result=[]
            for record in records:
                row=entry.db.execute('SELECT status,turn_id,thread_id FROM sends WHERE actor=? AND message_id=?',(actor,'mobile-'+record['requestId'])).fetchone()
                ack={'status':row[0],'turnId':row[1]} if row and row[2]==tid else None
                value=resolve(actor,record,ack,raw)
                if value['phase'] in TERMINAL:self.receipts.phase(actor,tid,record['requestId'],value['phase'])
                result.append(value)
        return {'deliveries':result}
    def quota(self):return self.quota_reader.get()
    def model_options(self):return {'models':self.models.listing()}
    def set_model(self,env,n,model,effort,expected,request_id):
        from model_settings import apply_settings
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:
            tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
            check_saved(tid)
            self.models.validate(model,effort)
            with entry.actor_lock(actor):
                response=apply_settings(tid,actor,request_id,model,effort,expected,self.model_changes)
        with self.lock:self.cache.pop(tid,None)
        return response
    def preference(self,env,n,kind,value):
        actor=identity_key(env)
        with contextlib.closing(Entry()) as entry:tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
        if kind=='alias' and (not isinstance(value,str) or len(value)>30):raise ValueError('invalid alias')
        if kind=='pin' and not isinstance(value,bool):raise ValueError('invalid pin')
        if kind=='seen' and (not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value)):raise ValueError('invalid result revision')
        self.preferences.update(actor,tid,kind,value.strip() if kind=='alias' else value)
        return {'ok':True}
    def action(self,env,n,action,text,request_id):
        if action not in ('select','send','name','leave'):raise ValueError('unsupported action')
        uuid.UUID(request_id)
        actor=identity_key(env)
        # Explicit target prevents a concurrent WeChat switch from rerouting this request.
        args=['leave'] if action=='leave' else [action,f'T{n:04d}']+([text] if action in ('send','name') else [])
        if action=='send' and (not isinstance(text,str) or not 1<=len(text.strip())<=4000):raise ValueError('message length')
        if action=='name' and (not isinstance(text,str) or not 1<=len(text.strip())<=30):raise ValueError('name length')
        envelope={**base_envelope(env),'version':1,'message_id':'mobile-'+request_id,'args':args}
        with contextlib.closing(Entry()) as entry:
            if action=='select':entry.ipc_factory=ConnectIPC
            if action=='send':
                tid,_,_,_=target(entry.catalog.db,actor,[f'T{n:04d}'])
                self.receipts.begin(actor,tid,request_id)
            try:response=entry.handle(envelope)
            except IPCError:response='本次操作未完成，请刷新任务后核对。不要立即重复发送。'
            record=entry.db.execute('SELECT status FROM sends WHERE actor=? AND message_id=?',(actor,envelope['message_id'])).fetchone()
            delivery=record[0] if record else 'refused'
            if action=='send':self.receipts.phase(actor,tid,request_id,delivery if delivery in ('accepted','refused') else 'uncertain')
        current=self.current(env)
        if env.get('web_account'):
            if action=='select':
                connected=bool(current and current['number']==n and self.observe(current['threadId'],True).get('live'))
                response='桌面会话已连接，可查看状态并继续操作。' if connected else '尚未确认桌面连接，请保持 Codex 桌面打开，再点连接重试。'
            elif action=='leave':response='已取消当前会话选择。'
            elif action=='send' and delivery=='accepted':response='消息已送入这个原会话，开始处理。'
            else:response=re.sub(r'\bT(\d{4,9})\b',r'W\1',response.replace('消息平台','网页').replace('微信','网页'))
        return {'response':response,'current':current,'delivery':delivery}
