#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Actor-scoped messaging entry; existing catalog plus desktop-owned turn start."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import uuid

from paths import ROOT, BRIDGE_STATE, CODEX_HOME
from channel_access import valid_platform, admit
from control import Controller, ReadOnlyAPI, clean
from desktop_ipc import DesktopIPC, IPCError, ensure_idle, ensure_can_send, latest_result

HELP = '''消息平台任务菜单
界面：打开手机任务管理页，查看进度与切换任务
对话：查看任务目录；对话 关键词：搜索
切换 9：选中目录里的 9 号任务，之后直接输入文字
进度：查看当前任务正在做什么
结果：查看最近一轮的回答
命名 9 示例任务：设置消息平台目录简称
退出：回到原消息平台助手
菜单：随时查看当前位置与用法
运行中暂不接收新消息；等待确认时请在桌面处理。'''

ERRORS = {'no-client-found':'桌面尚未接管这个会话，请先发送“会话连接 T编号”。',
          'thread-not-idle':'原会话正在运行或状态未知，本条未发送。请等它完成后发送新消息。',
          'thread-needs-user-input':'原会话正在等待确认，请在桌面处理后再发送。',
          'snapshot-identity-mismatch':'返回的会话身份不一致，已阻止发送。'}


def identity(envelope):
    fields = ('project','platform','session_key','user_id','message_id')
    if envelope.get('version') != 1 or any(not isinstance(envelope.get(k),str) or not envelope[k] for k in fields):
        raise IPCError('缺少可信消息身份。')
    if not valid_platform(envelope['platform']):
        raise IPCError('平台标识无效。')
    args = envelope.get('args') or []
    if not isinstance(args,list) or len(args)>32 or any(not isinstance(s,str) or len(s)>4000 for s in args):
        raise IPCError('命令参数无效。')
    actor = hashlib.sha256(json.dumps([envelope[k] for k in fields[:-1]],ensure_ascii=False).encode()).hexdigest()
    digest = hashlib.sha256(json.dumps(args,ensure_ascii=False).encode()).hexdigest()
    return actor, args, digest


def target(db, actor, args):
    if args and re.fullmatch(r'T\d{4,9}',args[0].upper()):
        number,rest = int(args[0][1:]),args[1:]
    else:
        row=db.execute('SELECT number FROM choices WHERE actor=?',(actor,)).fetchone()
        if not row:
            raise IPCError('请先发送“会话选择 T编号”，或在命令中写明编号。')
        number,rest=row[0],args
    row=db.execute('SELECT thread_id,title,cwd FROM refs WHERE actor=? AND number=?',(actor,number)).fetchone()
    if not row:
        raise IPCError('这个编号不属于你的目录，请先发送“会话列表”。')
    uuid.UUID(row[0])
    return row[0],f'T{number:04d}｜{clean(row[1],70)}',rest,number


def check_saved(tid):
    databases = sorted(CODEX_HOME.glob('state_*.sqlite'),key=lambda p:int(p.stem.split('_')[-1]))
    with contextlib.closing(sqlite3.connect(databases[-1].as_uri()+'?mode=ro',uri=True)) as db:
        row=db.execute('SELECT archived FROM threads WHERE id=?',(tid,)).fetchone()
    if not row or row[0]:
        raise IPCError('会话不存在或已归档，未连接或发送。')


def reply_text(text):
    # Preserve full reply text while retaining the existing credential redaction.
    return re.sub(r'(?i)(bearer\s+|sk-)[A-Za-z0-9_.-]+', '[已隐藏凭据]', str(text))


def describe(label, tid, state, include_result=False):
    runtime=state.get('threadRuntimeStatus',{}).get('type','unknown')
    turn,text=latest_result(state)
    ts=(turn or {}).get('status')
    status={'idle':'空闲，可以发消息','active':'正在运行','systemError':'服务出错','notLoaded':'未加载'}.get(runtime,'状态未知')
    if runtime=='idle' and ts=='completed':status='最近一轮已完成，可以继续聊'
    if ts=='inProgress' and runtime in ('idle','active'):status='正在运行'
    if ts in ('interrupted','failed') and runtime=='idle':status={'interrupted':'最近一轮已中断','failed':'最近一轮失败'}[ts]
    if state.get('requests') or state.get('threadGoalResumeConfirmation'):status='等待你在桌面确认或补充输入'
    body=f'{label}\n状态：{status}'
    started=(turn or {}).get('turnStartedAtMs')
    if started and ts=='inProgress':
        seconds=max(0,int(time.time()-started/1000))
        body+=f'\n本轮已运行：{seconds//60}分{seconds%60}秒'
    if include_result:
        body+='\n\n'+(reply_text(text) if text else '本轮还没有助手文字回复；稍后发送“进度”或“结果”。')
    elif turn:
        messages=[x.get('text') for x in turn.get('items',[]) if x.get('type')=='agentMessage' and x.get('text')]
        if messages:body+='\n最近反馈：'+reply_text(messages[-1])
        elif ts=='inProgress':body+='\n正在处理，尚未产生文字反馈。'
    return body+'\n\n进度｜结果｜对话｜切换 编号｜退出'


class Entry:
    def __init__(self, state_dir=None, ipc_factory=DesktopIPC, check=check_saved):
        self.directory=Path(state_dir or BRIDGE_STATE)
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        self.api=ReadOnlyAPI()
        self.catalog=Controller(self.directory,self.api)
        self.ipc_factory,self.check=ipc_factory,check
        p=self.directory/'desktop-sends.sqlite3'
        fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600);os.close(fd);os.chmod(p,0o600)
        self.db=sqlite3.connect(p,timeout=5)
        self.db.execute('''CREATE TABLE IF NOT EXISTS sends (
            actor TEXT, message_id TEXT, digest TEXT, thread_id TEXT, status TEXT,
            response TEXT, turn_id TEXT, created REAL, PRIMARY KEY(actor,message_id))''')
        self.db.commit()
        self.db.executescript('''CREATE TABLE IF NOT EXISTS direct_routes (
            actor TEXT PRIMARY KEY, number INTEGER);
            CREATE TABLE IF NOT EXISTS nicknames (
            actor TEXT, number INTEGER, name TEXT, PRIMARY KEY(actor,number));
            CREATE TABLE IF NOT EXISTS menu_receipts (
            actor TEXT, message_id TEXT, digest TEXT, response TEXT, PRIMARY KEY(actor,message_id));
            CREATE TABLE IF NOT EXISTS route_receipts (
            actor TEXT, message_id TEXT, digest TEXT, response TEXT, PRIMARY KEY(actor,message_id));''')

    def close(self):
        self.catalog.close();self.api.close();self.db.close()

    @contextlib.contextmanager
    def actor_lock(self,actor):
        fd=os.open(self.directory/('actor-'+actor+'.lock'),os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally:os.close(fd)

    def label(self,actor,number,title):
        row=self.db.execute('SELECT name FROM nicknames WHERE actor=? AND number=?',(actor,number)).fetchone()
        name=row[0] if row else ' '.join(title.split())
        name=clean(name,1000)
        return f'T{number:04d}｜'+(name[:42]+'…' if len(name)>42 else name)

    def selected(self,actor):
        return self.db.execute('SELECT number FROM direct_routes WHERE actor=?',(actor,)).fetchone()

    def listing(self,actor,query='',cursor=None):
        result=self.api.request('thread/list',{'limit':8,'cursor':cursor,'sortKey':'updated_at',
            'sortDirection':'desc','modelProviders':[], 'sourceKinds':['cli','vscode','exec','appServer','unknown'],
            'archived':False,'searchTerm':query or None,'useStateDbOnly':True})
        selected=self.selected(actor)
        lines=['任务目录'+('（搜索：'+clean(query,40)+'）' if query else '')]
        with self.catalog.db:
            for thread in result.get('data',[]):
                row=self.catalog.db.execute('SELECT number FROM refs WHERE actor=? AND thread_id=?',(actor,thread['id'])).fetchone()
                number=row[0] if row else self.catalog.db.execute('SELECT COALESCE(MAX(number),0)+1 FROM refs WHERE actor=?',(actor,)).fetchone()[0]
                title=' '.join((thread.get('name') or thread.get('preview') or '未命名任务').split())
                cwd=thread.get('cwd') or ''
                self.catalog.db.execute('INSERT OR REPLACE INTO refs VALUES (?,?,?,?,?)',(actor,number,thread['id'],title,cwd))
                lines.append(('▶ ' if selected and selected[0]==number else '')+self.label(actor,number,title)+'\n  '+clean(Path(cwd).name or '未设置目录',40))
            self.catalog.db.execute('INSERT OR REPLACE INTO pages VALUES (?,?,?)',(actor,result.get('nextCursor'),query))
        if len(lines)==1:lines.append('没有找到匹配任务。')
        lines.append('切换 编号（如：切换 9）｜对话 关键词'+('｜下一页' if result.get('nextCursor') else ''))
        lines.append('目录包含本机未归档的主任务；进度 编号 可查实时状态。')
        return '\n'.join(lines)

    def saved_reply(self,tid,label):
        result=self.api.request('thread/turns/list',{
            'threadId':tid,'limit':3,'itemsView':'full','sortDirection':'desc'})
        texts=[]
        for turn in result.get('data',[]):
            texts=[item['text'] for item in turn.get('items',[])
                   if item.get('type')=='agentMessage' and item.get('text')]
            if texts:break
        body=reply_text('\n\n'.join(texts)) if texts else '最近三轮没有可展示的助手文字结果。'
        return label+'\n最近已保存的助手输出（不代表任务已完成）：\n\n'+body+'\n\n实时运行状态未知。'

    def route_message(self,env):
        actor,args,digest=identity(env)
        with self.actor_lock(actor):
            route_digest=hashlib.sha256((digest+str(bool(env.get('has_attachments')))).encode()).hexdigest()
            receipt=self.db.execute('SELECT digest,response FROM route_receipts WHERE actor=? AND message_id=?',(actor,env['message_id'])).fetchone()
            if receipt:
                return json.loads(receipt[1]) if receipt[0]==route_digest else {'handled':True,'response':'同一消息编号对应不同内容，已拒绝。'}
            if self.db.execute('SELECT 1 FROM menu_receipts WHERE actor=? AND message_id=?',(actor,env['message_id'])).fetchone():
                return {'handled':True,'response':'该消息编号已用于菜单命令，不会作为新文字转发。'}
            old=self.db.execute('SELECT digest,response FROM sends WHERE actor=? AND message_id=?',(actor,env['message_id'])).fetchone()
            if old:
                return {'handled':True,'response':(old[1] or '消息已登记，不会自动重发。请查看结果。') if old[0]==digest else '同一消息编号对应不同内容，已拒绝。'}
            pending={'handled':True,'response':'这条消息已登记，处理结果待核实；不会自动重发或转给其他任务。请先查看结果。'}
            with self.db:
                self.db.execute('INSERT INTO route_receipts VALUES (?,?,?,?)',(actor,env['message_id'],route_digest,json.dumps(pending,ensure_ascii=False)))
            try:result=self._route_message(env,actor,args,digest)
            except Exception:
                result={'handled':True,'response':'任务入口处理失败，本条未转发到其他任务。请查看结果后再决定是否发送新消息。'}
            # A previously unselected message must not become selected work on
            # replay, nor be dispatched to the ordinary agent twice.
            replay=result if result['handled'] else {'handled':True,'response':'这条消息首次接收时属于原消息平台助手；重复消息已忽略，不会转给当前任务。'}
            with self.db:
                self.db.execute('UPDATE route_receipts SET response=? WHERE actor=? AND message_id=?',(json.dumps(replay,ensure_ascii=False),actor,env['message_id']))
            return result

    def _route_message(self,env,actor,args,digest):
        selected=self.selected(actor)
        if not selected:return {'handled':False,'response':''}
        try:
            tid,unused,rest,number=target(self.catalog.db,actor,[f'T{selected[0]:04d}'])
            title=self.catalog.db.execute('SELECT title FROM refs WHERE actor=? AND number=?',(actor,number)).fetchone()[0]
            label=self.label(actor,number,title)
            if env.get('has_attachments'):
                return {'handled':True,'response':label+'\n当前直聊只支持文字，附件未发送。请在桌面发送附件，或先“退出”使用原消息平台助手。'}
            if len(args)!=1 or not args[0].strip():raise IPCError('请输入文字内容。')
            self.check(tid)
            response=self.send(env,actor,digest,tid,label,args[0])
        except (IPCError,OSError) as e:
            response=ERRORS.get(str(e),clean(str(e),200))+'\n本条未转发到其他任务。对话｜切换 编号｜退出'
        return {'handled':True,'response':response}

    def handle(self, env):
        actor,args,digest=identity(env)
        with self.actor_lock(actor):
            mutation=args and args[0] in ('select','选择','connect','连接','leave','退出','name','send','发送')
            if mutation:
                if self.db.execute('SELECT 1 FROM route_receipts WHERE actor=? AND message_id=?',(actor,env['message_id'])).fetchone():
                    return '该消息编号已用于普通文字，不会再次执行菜单操作。'
                old=self.db.execute('SELECT digest,response FROM menu_receipts WHERE actor=? AND message_id=?',(actor,env['message_id'])).fetchone()
                if old:
                    if old[0]!=digest:return '同一消息编号对应不同内容，已拒绝。'
                    if args[0] in ('send','发送'):return old[1]
                    selected=self.selected(actor)
                    location=f'T{selected[0]:04d}' if selected else '原消息平台助手'
                    return '重复命令，未再次执行。\n当前去向：'+location+'\n菜单：查看当前位置。'
                with self.db:
                    self.db.execute('INSERT INTO menu_receipts VALUES (?,?,?,?)',(actor,env['message_id'],digest,'该消息已登记，结果待核实；不会自动重发。请先查看原任务。'))
            try:result=self._handle(env)
            except Exception as e:
                if mutation:
                    response=ERRORS.get(str(e),clean(str(e),200)) if isinstance(e,IPCError) else '执行结果待核实；不会自动重发。请先查看原任务。'
                    with self.db:self.db.execute('UPDATE menu_receipts SET response=? WHERE actor=? AND message_id=?',(response,actor,env['message_id']))
                raise
            if mutation:
                with self.db:self.db.execute('UPDATE menu_receipts SET response=? WHERE actor=? AND message_id=?',(result,actor,env['message_id']))
            return result

    def _handle(self, env):
        actor,args,digest=identity(env)
        action=args[0] if args else 'help'
        action={'帮助':'help','连接':'connect','发送':'send','状态':'status','查看':'show','路由':'route',
                'select':'connect','选择':'connect','current':'status','当前':'status','退出':'leave'}.get(action,action)
        if action=='help':
            selected=self.selected(actor)
            current=self._handle({**env,'args':['status',f'T{selected[0]:04d}']}) if selected else '当前位置：原消息平台助手；先发“对话”，再发“切换 编号”。'
            return current+'\n\n'+HELP
        if action=='list':return self.listing(actor,' '.join(args[1:]))
        if action=='next':
            page=self.catalog.db.execute('SELECT cursor,query FROM pages WHERE actor=?',(actor,)).fetchone()
            return self.listing(actor,page[1],page[0]) if page and page[0] else '没有下一页。发送“对话”刷新目录，或“对话 关键词”搜索。'
        if action=='leave':
            with self.db:self.db.execute('DELETE FROM direct_routes WHERE actor=?',(actor,))
            with self.catalog.db:self.catalog.db.execute('DELETE FROM choices WHERE actor=?',(actor,))
            return '已退出任务直聊。后续文字发给原消息平台助手。\n对话：查看目录；切换 编号：重新进入任务。'
        if action not in ('connect','send','status','show','route','name'):return HELP
        if action in ('connect','status','show','route','name') and len(args)>1 and re.fullmatch(r'\d{1,9}',args[1]):
            args=[args[0],f'T{int(args[1]):04d}',*args[2:]]
        if action=='connect' and len(args)!=2:raise IPCError('用法：切换 9。先发“对话”查看编号。')
        if action=='send':
            old=self.db.execute('SELECT digest,status,response FROM sends WHERE actor=? AND message_id=?',
                                (actor,env['message_id'])).fetchone()
            if old:
                if old[0]!=digest:return '同一消息编号对应不同内容，已拒绝。'
                return old[2] or '该消息已登记，结果待核实；不会自动重发。请查看原会话。'
        target_args=args[1:]
        selected=self.selected(actor)
        if selected and (not target_args or not re.fullmatch(r'T\d{4,9}',target_args[0].upper())):
            target_args=[f'T{selected[0]:04d}',*target_args]
        tid,label,rest,number=target(self.catalog.db,actor,target_args)
        title=self.catalog.db.execute('SELECT title FROM refs WHERE actor=? AND number=?',(actor,number)).fetchone()[0]
        label=self.label(actor,number,title)
        if action=='name':
            name=' '.join(rest).strip()
            if not name or len(name)>30:raise IPCError('用法：命名 9 示例任务（简称不超过30字）。')
            with self.db:self.db.execute('INSERT OR REPLACE INTO nicknames VALUES (?,?,?)',(actor,number,name))
            return '已设置消息平台简称：'+self.label(actor,number,title)+'\n切换 '+str(number)+'：进入这个任务。'
        if action!='send' and rest:raise IPCError('请使用：进度 编号、结果 编号或切换 编号。')
        self.check(tid)
        if action=='send':
            prompt=' '.join(rest).strip()
            if not prompt or len(prompt)>8000:raise IPCError('请输入1至8000字符的发送内容。')
            return self.send(env,actor,digest,tid,label,prompt)
        try:
            with self.ipc_factory() as ipc:
                owner,state=ipc.connect_thread(tid,open_if_needed=action=='connect')
                if action=='connect':
                    with self.catalog.db:
                        self.catalog.db.execute('INSERT OR REPLACE INTO choices VALUES (?,?)',(actor,number))
                    with self.db:self.db.execute('INSERT OR REPLACE INTO direct_routes VALUES (?,?)',(actor,number))
                body=describe(label,tid,state,action=='show')
                if action=='route':body+='\n诊断：桌面原服务已连接\n原任务 ID：'+tid
                if action=='connect':body='已切换，后续文字直接发给这个任务：\n'+body
                elif self.selected(actor)==(number,):body='当前直聊目标：'+body
                return body
        except (IPCError,OSError) as e:
            # For disconnected desktop the old read-only catalog remains usable.
            if action=='show':
                return '桌面实时接口暂不可用，以下仅是已保存的历史：\n'+self.saved_reply(tid,label)
            if action=='connect':
                selected=self.selected(actor)
                location=f'T{selected[0]:04d}' if selected else '原消息平台助手'
                return label+'\n连接失败，未切换。当前仍是：'+location+'\n请保持桌面应用打开，再试“切换 '+str(number)+'”。'
            return label+'\n'+ERRORS.get(str(e),'桌面连接暂不可用，未发送。请保持桌面应用打开。')

    def send(self,env,actor,digest,tid,label,prompt):
        path=self.directory/('desktop-'+tid+'.lock')
        fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
        try:
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:return '该会话正在处理另一条发送请求，本条未发送。'
            with self.ipc_factory() as ipc:
                owner,state=ipc.connect_thread(tid,open_if_needed=True)
                ensure_can_send(state)
                # Commit BEFORE IPC mutation: crash/timeout cannot replay this message.
                with self.db:
                    cur=self.db.execute('INSERT OR IGNORE INTO sends VALUES (?,?,?,?,?,?,?,?)',
                        (actor,env['message_id'],digest,tid,'dispatching','',None,time.time()))
                if not cur.rowcount:return '该消息已登记，不会重复发送，请查看原会话。'
                client_id=str(uuid.uuid5(uuid.NAMESPACE_URL,actor+'\0'+env['message_id']))
                try:
                    result=ipc.start(tid,owner,prompt,client_id)
                    turn_id=result['result']['result']['turn']['id']
                    response=f'{label}\n已送入原任务，开始处理。\n进度：查看正在做什么；结果：查看回复。'
                    status='accepted'
                except Exception:
                    status,turn_id='uncertain',None
                    response=label+'\n发送结果待核实，不自动重发。请先查看原会话，避免重复执行。'
                with self.db:
                    self.db.execute('UPDATE sends SET status=?,response=?,turn_id=? WHERE actor=? AND message_id=?',
                                    (status,response,turn_id,actor,env['message_id']))
                return response
        except (IPCError,OSError) as e:
            return label+'\n'+ERRORS.get(str(e),'桌面连接暂不可用，本条未发送。')
        finally:
            os.close(fd)

    @staticmethod
    def label_number(label):return label.split('｜')[0]


def main():
    os.umask(0o077)
    routing='--route-message' in sys.argv[1:]
    try:
        raw=sys.stdin.read(32769)
        if len(raw)>32768:raise IPCError('输入过长。')
        env=json.loads(raw)
        if not isinstance(env,dict):raise IPCError('输入格式错误。')
        identity(env)
        denied = admit(env)
        if denied is not None:
            print(json.dumps({'handled': True, 'response': denied}, ensure_ascii=False) if routing else denied)
            return
        if routing and env.get('args') in (['界面'],['打开界面'],['任务界面']):
            identity(env)
            import subprocess
            result=subprocess.run([sys.executable, str(ROOT/'mobile-ui/mobile_entry.py')],input=json.dumps(env),text=True,capture_output=True,timeout=8)
            response=result.stdout.strip() if result.returncode==0 else '手机界面暂不可用，请稍后再试。'
            print(json.dumps({'handled':True,'response':response},ensure_ascii=False))
            return
        with contextlib.closing(Entry()) as entry:
            result=entry.route_message(env) if routing else entry.handle(env)
    except IPCError as e:
        result=ERRORS.get(str(e),clean(str(e),300))
    except Exception:
        result='会话总控暂不可用。若刚发送过消息，请先查看原会话，不要立即重复发送。菜单｜退出'
    if routing:
        if not isinstance(result,dict):result={'handled':True,'response':result}
        print(json.dumps(result,ensure_ascii=False))
    else:print(result)


if __name__=='__main__':main()
