# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Narrow per-thread model settings; no global config or permission mutations."""
import contextlib
import hashlib
import json
import re
import threading
import time
from desktop_ipc import DesktopIPC,IPCError,ensure_idle
from wechat_entry import ReadOnlyAPI
from ui_state import UIState

EFFORT_LABELS={'none':'无','minimal':'最低','low':'低','medium':'中','high':'高','xhigh':'很高','max':'最高','ultra':'超高','persistent':'持续'}

def safe_model(value):return value if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}',value) else None

def current_settings(state):
    settings=state.get('latestThreadSettings') or {}
    model=safe_model(settings.get('model') or state.get('latestModel'))
    effort=settings.get('effort',state.get('latestReasoningEffort'))
    if effort not in EFFORT_LABELS:effort=None
    value={'model':model,'effort':effort,'effortLabel':EFFORT_LABELS.get(effort,'默认 / 未指定'),'known':bool(model)}
    value['revision']=hashlib.sha256(json.dumps([state.get('id'),model,effort,state.get('modelProvider'),(state.get('latestCollaborationMode') or {}).get('mode')],sort_keys=True).encode()).hexdigest()
    return value

def turn_settings(turn):
    # Desktop reconstructs older turns using the CURRENT model. Never label that as historical fact.
    if turn.get('permissionParamsSource')=='inferred':return None
    params=turn.get('params') or {};mode=(params.get('collaborationMode') or {}).get('settings') or {}
    model=safe_model(mode.get('model') or params.get('model'))
    if not model:return None
    effort=mode.get('reasoning_effort',params.get('effort'))
    return {'model':model,'effort':effort if effort in EFFORT_LABELS else None,'effortLabel':EFFORT_LABELS.get(effort,'未记录')}

class ModelAPI(ReadOnlyAPI):METHODS={'model/list'}

class ModelCatalog:
    def __init__(self):self.lock=threading.Lock();self.at=0;self.rows=None
    def listing(self,fresh=False):
        with self.lock:
            if not fresh and self.rows is not None and time.time()-self.at<60:return self.rows
            result=[];cursor=None
            with contextlib.closing(ModelAPI()) as api:
                for _ in range(5):
                    response=api.request('model/list',{'cursor':cursor,'includeHidden':False,'limit':100})
                    for row in response.get('data',[]):
                        model=safe_model(row.get('model'))
                        if not model or row.get('hidden'):continue
                        efforts=[e.get('reasoningEffort') for e in row.get('supportedReasoningEfforts',[]) if e.get('reasoningEffort') in EFFORT_LABELS]
                        if not efforts:continue
                        default=row.get('defaultReasoningEffort')
                        result.append({'id':model,'label':str(row.get('displayName') or model)[:120],'efforts':[{'id':e,'label':EFFORT_LABELS[e]+' · '+e} for e in dict.fromkeys(efforts)],'defaultEffort':default if default in efforts else efforts[0]})
                    cursor=response.get('nextCursor')
                    if not cursor:break
                if cursor:raise ValueError('model catalog incomplete')
            if not result:raise ValueError('model catalog unavailable')
            self.rows=list({r['id']:r for r in result}.values());self.at=time.time();return self.rows
    def validate(self,model,effort):
        rows=self.listing(fresh=True)
        if not any(r['id']==model and any(e['id']==effort for e in r['efforts']) for r in rows):raise SettingsError('该模型或推理强度当前不可用，请刷新选项。',400)

class SettingsError(ValueError):
    def __init__(self,message,status=409):super().__init__(message);self.status=status

class SettingsIPC(DesktopIPC):
    VERSIONS={k:v for k,v in DesktopIPC.VERSIONS.items() if k!='thread-follower-start-turn'}|{'thread-follower-update-thread-settings':1}
    def update_model(self,tid,owner,model,effort):
        if not isinstance(model,str) or safe_model(model)!=model or effort not in EFFORT_LABELS:raise ValueError('invalid model settings')
        return self.request('thread-follower-update-thread-settings',{'conversationId':tid,'threadSettings':{'model':model,'effort':effort}},owner)

class SettingsStore(UIState):
    def connect(self):
        db=super().connect()
        db.execute('CREATE TABLE IF NOT EXISTS model_changes (actor TEXT, request TEXT, thread TEXT, digest TEXT, response TEXT, created REAL, PRIMARY KEY(actor,request))')
        return db
    def previous(self,actor,tid,rid,digest):
        with contextlib.closing(self.connect()) as db:row=db.execute('SELECT thread,digest,response FROM model_changes WHERE actor=? AND request=?',(actor,rid)).fetchone()
        if not row:return None
        if row[0]!=tid or row[1]!=digest:raise SettingsError('此请求编号已经用于其他设置，请刷新后操作。')
        return json.loads(row[2])
    def save(self,actor,tid,rid,digest,response):
        with contextlib.closing(self.connect()) as db,db:db.execute('INSERT OR REPLACE INTO model_changes VALUES (?,?,?,?,?,?)',(actor,rid,tid,digest,json.dumps(response),time.time()))

def protected_state(state):
    # Read-back comparison only. These values are never returned to the browser.
    settings=state.get('latestThreadSettings') or {}
    excluded={'model','effort','collaborationMode'}
    mode=settings.get('collaborationMode') or state.get('latestCollaborationMode') or {}
    return {'settings':{k:v for k,v in settings.items() if k not in excluded},'mode':mode.get('mode'),'instructions':(mode.get('settings') or {}).get('developer_instructions'),'permissions':state.get('currentPermissions'),'cwd':state.get('cwd')}

def apply_settings(tid,actor,rid,model,effort,expected,store,ipc_factory=SettingsIPC):
    digest=hashlib.sha256(json.dumps([model,effort,expected]).encode()).hexdigest()
    previous=store.previous(actor,tid,rid,digest)
    if previous is not None:return {**previous,'replayed':True}
    with ipc_factory(timeout=5) as ipc:
        owner,state=ipc.connect_thread(tid,open_if_needed=False)
        try:ensure_idle(state)
        except IPCError:raise SettingsError('会话正在运行、等待确认或状态未知，请等空闲后再切换。')
        before=current_settings(state)
        if not before['known']:raise SettingsError('当前会话设置尚未读取完整，请在桌面打开会话后刷新。')
        if before['revision']!=expected:raise SettingsError('会话设置已变化，请刷新后重新选择。')
        pending={'status':'uncertain','message':'设置请求已登记，请刷新核对当前模型；不会自动重复提交。'}
        store.save(actor,tid,rid,digest,pending)
        try:
            ipc.update_model(tid,owner,model,effort)
            after=ipc.snapshot(tid,owner);current=current_settings(after)
            if current['model']==model and current['effort']==effort and protected_state(state)==protected_state(after):
                response={'status':'confirmed','message':'已保存此会话设置，从下一轮消息生效。','settings':current}
            else:response={'status':'uncertain','message':'尚未确认设置完全同步，请刷新核对当前模型。'}
        except (IPCError,OSError,ValueError):response=pending
        store.save(actor,tid,rid,digest,response)
        return response
