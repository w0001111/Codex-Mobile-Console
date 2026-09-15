# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""A separate, authenticated mobile surface; never proxies the management API."""
import hmac
from io import BytesIO
import json
import os
from pathlib import Path
import re
import threading
from urllib.parse import urlsplit
from flask import Flask,request,jsonify,send_from_directory,send_file,g
from werkzeug.exceptions import HTTPException
import auth
from adapter import Adapter
from model_settings import SettingsError,safe_model,EFFORT_LABELS

ROOT=Path(__file__).resolve().parent
COOKIE='mobile_task_session'

def create_app(adapter=None,state=auth.STATE,public_url=None,local_url=None,static_root=None):
    app=Flask(__name__,static_folder=None)
    app.config.update(MAX_CONTENT_LENGTH=16384)
    service=adapter or Adapter(state=state)
    slots=threading.BoundedSemaphore(4)
    assets_root=Path(static_root) if static_root else ROOT/'frontend/dist'
    def origins():
        urls={'http://127.0.0.1:9840','http://localhost:9840'}
        if local_url and urlsplit(local_url).hostname in ('localhost','127.0.0.1'):urls.add(local_url)
        try:
            url=public_url or json.loads((Path(state)/'public.json').read_text())['url']
            p=urlsplit(url)
            if p.scheme=='https' and p.netloc and not p.username:urls.add('https://'+p.netloc)
        except (OSError,ValueError,KeyError):pass
        return urls
    def fail(message,code):return jsonify(error=message),code
    @app.before_request
    def gate():
        allowed=origins()
        if request.host not in {urlsplit(url).netloc for url in allowed}:return fail('访问地址无效',403)
        if request.method not in ('GET','POST','HEAD'):return fail('不支持此操作',405)
        if request.method=='POST':
            if request.headers.get('Origin') not in allowed:return fail('来源校验失败，请从管理页面操作',403)
            # Both origin and host must match; do not allow cross-origin local/public requests.
            if urlsplit(request.headers['Origin']).netloc!=request.host:return fail('来源校验失败',403)
            if request.mimetype!='application/json':return fail('请求格式无效',415)
        if not request.path.startswith('/api/'):return None
        if request.path=='/api/pair':return None
        found=auth.session(request.cookies.get(COOKIE,''),state)
        if not found:return fail('请使用消息平台登录码和独立密码登录',401)
        g.identity,g.csrf=found
        if request.method=='POST' and not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),g.csrf):return fail('验证已失效，请刷新页面',403)
    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
          'X-Frame-Options':'DENY','Permissions-Policy':'camera=(), microphone=(), geolocation=()',
          'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
        return response
    @app.errorhandler(Exception)
    def error(err):
        if isinstance(err,SettingsError):return fail(str(err),err.status)
        if isinstance(err,HTTPException):return fail('请求无效或资源不存在',err.code)
        # Do not return provider errors, prompts, filesystem paths or credentials.
        return fail('电脑暂时无法完成请求，请稍后刷新；发送失败时请先核对任务',503)
    def body():
        value=request.get_json()
        if not isinstance(value,dict):raise ValueError('invalid body')
        return value
    def signed_in(result):
        token,csrf=result
        response=jsonify(csrf=csrf)
        response.set_cookie(COOKIE,token,max_age=auth.SESSION_LIFETIME,secure=True,httponly=True,samesite='Strict',path='/')
        return response
    @app.post('/api/pair')
    def pair():
        data=body();code=data.get('code','');password=data.get('password','')
        if not isinstance(code,str) or len(code)>100:return fail('配对码无效',400)
        if not isinstance(password,str) or len(password)>128:return fail('登录信息无效',400)
        code=re.sub(r'[\s-]','',code).upper()
        result,status=auth.exchange(code,state,password=password,user_agent=request.headers.get("User-Agent",""))
        if not result:
            if status=='password_unset':return fail('尚未设置网页登录密码。请先在 Mac 双击「设置网页登录密码.command」完成设置，再到已绑定的消息平台重新发送「界面」。这里使用单独设置的网页密码。',401)
            messages={'rate':'尝试过于频繁，请一分钟后再试','password_rate':'尝试过于频繁，请 15 分钟后再试'}
            return fail(messages.get(status,'登录码或密码不正确，或尚未在 Mac 设置独立密码。登录码过期请重新获取。'),429 if status in messages else 401)
        return signed_in(result)
    @app.get('/api/session')
    def session():return jsonify(csrf=g.csrf,current=service.current(g.identity),mode='web' if g.identity.get('web_account') else 'wechat')
    @app.post('/api/activity')
    def activity():
        # Only called by actual UI input events, never by automatic list/history polling.
        auth.session(request.cookies.get(COOKIE,''),state,touch=True)
        return jsonify(ok=True)
    @app.post('/api/logout')
    def logout():
        auth.logout(request.cookies.get(COOKIE,''),state)
        response=jsonify(ok=True);response.delete_cookie(COOKIE,secure=True,httponly=True,samesite='Strict');return response
    def bounded(fn):
        if not slots.acquire(blocking=False):return fail('正在查询，请稍后刷新',429)
        try:return jsonify(fn())
        finally:slots.release()
    @app.post('/api/logout-all')
    def logout_all():
        auth.revoke_owner(g.identity,state)
        response=jsonify(ok=True);response.delete_cookie(COOKIE,secure=True,httponly=True,samesite='Strict');return response
    @app.get('/api/tasks')
    def tasks():
        query=request.args.get('q','');cursor=request.args.get('cursor')
        group=request.args.get('group','all');status=request.args.get('status','all')
        limit=request.args.get('limit','24')
        if not limit.isdigit() or not 1<=int(limit)<=2000:return fail('分页无效',400)
        limit=int(limit)
        if len(query)>100 or len(group)>150 or (cursor and (not cursor.isdigit() or len(cursor)>5)) or status not in ('all','active','needs_input','new'):return fail('查询无效',400)
        if group=='all' and status=='all' and limit==24:return bounded(lambda:service.listing(g.identity,query,cursor))
        return bounded(lambda:service.listing(g.identity,query,cursor,group=group,status=status,limit=limit))
    @app.get('/api/tasks/<int:number>')
    def detail(number):
        if not 0<number<10**9:return fail('任务编号无效',400)
        if request.args.get('view')=='summary':return bounded(lambda:service.detail(g.identity,number,summary=True))
        return bounded(lambda:service.detail(g.identity,number))
    @app.get('/api/tasks/<int:number>/history')
    def history(number):
        cursor=request.args.get('cursor')
        if not 0<number<10**9 or (cursor and len(cursor)>4000):return fail('历史查询无效',400)
        if request.args.get('async')=='1':return bounded(lambda:service.history(g.identity,number,cursor))
        return bounded(lambda:service.timeline(g.identity,number,cursor))
    @app.get('/api/quota')
    def quota():return jsonify(service.quota())
    @app.get('/api/models')
    def models():return bounded(service.model_options)
    @app.post('/api/tasks/<int:number>/model-settings')
    def model_settings(number):
        data=body();model=data.get('model');effort=data.get('effort');expected=data.get('expectedRevision');rid=data.get('requestId')
        if set(data)!={'model','effort','expectedRevision','requestId'} or not 0<number<10**9:return fail('设置请求无效',400)
        if not isinstance(model,str) or safe_model(model)!=model or not isinstance(effort,str) or effort not in EFFORT_LABELS:return fail('模型或推理强度无效',400)
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):return fail('请刷新会话设置',400)
        if not isinstance(rid,str) or not re.fullmatch('[0-9a-fA-F-]{36}',rid):return fail('设置请求编号无效',400)
        return bounded(lambda:service.set_model(g.identity,number,model,effort,expected,rid))
    @app.get('/api/login-history')
    def login_history():
        cursor=request.args.get('cursor')
        if cursor is not None and (not cursor.isdigit() or not 1<=len(cursor)<=18 or int(cursor)<1):return fail('登录记录分页无效',400)
        return jsonify(auth.login_history(g.identity,request.cookies.get(COOKIE,''),state,cursor))
    @app.get('/api/logins')
    def logins():return jsonify(logins=auth.logins(g.identity,request.cookies.get(COOKIE,''),state))
    @app.post('/api/logins/<public_id>/revoke')
    def revoke_login(public_id):
        if not re.fullmatch('[0-9a-f]{32}',public_id):return fail('登录记录不存在',404)
        result=auth.revoke_login(g.identity,public_id,request.cookies.get(COOKIE,''),state)
        if result is None:return fail('登录记录不存在',404)
        response=jsonify(result)
        if result['current']:response.delete_cookie(COOKIE,secure=True,httponly=True,samesite='Strict')
        return response
    @app.get('/api/tasks/<int:number>/deliveries')
    def deliveries(number):
        rid=request.args.get('requestId')
        if not 0<number<10**9 or (rid and not re.fullmatch('[0-9a-fA-F-]{36}',rid)):return fail('消息编号无效',400)
        return bounded(lambda:service.deliveries(g.identity,number,rid))
    @app.get('/api/tasks/<int:number>/files')
    def files(number):
        cursor=request.args.get('cursor')
        if not 0<number<10**9 or (cursor and len(cursor)>4000):return fail('成果查询无效',400)
        if request.args.get('async')=='1':return bounded(lambda:service.file_page(g.identity,number,cursor))
        return bounded(lambda:service.files(g.identity,number,cursor))
    @app.get('/api/tasks/<int:number>/files/<aid>')
    @app.get('/api/tasks/<int:number>/files/<aid>/preview')
    def file(number,aid):
        if not 0<number<10**9 or not re.fullmatch('[0-9a-f]{32}',aid):return fail('成果不存在',404)
        if not slots.acquire(blocking=False):return fail('正在读取，请稍后重试',429)
        try:
            try:name,data,mime=service.file(g.identity,number,aid)
            except FileNotFoundError:return fail('成果不存在',404)
            preview=request.path.endswith('/preview')
            if preview and not mime:return fail('此成果不支持图片预览',415)
            return send_file(BytesIO(data),as_attachment=not preview,download_name=name,mimetype=mime if preview else 'application/octet-stream',conditional=False,max_age=0)
        finally:slots.release()
    @app.post('/api/tasks/<int:number>/preference')
    def preference(number):
        data=body();kind=data.get('kind');value=data.get('value')
        if not 0<number<10**9 or kind not in ('alias','pin','seen'):return fail('设置无效',400)
        if kind=='alias' and (not isinstance(value,str) or len(value)>30):return fail('简称最多 30 个字符',400)
        if kind=='pin' and not isinstance(value,bool):return fail('置顶设置无效',400)
        if kind=='seen' and (not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value)):return fail('结果标记无效',400)
        return bounded(lambda:service.preference(g.identity,number,kind,value))
    @app.post('/api/action')
    def action():
        data=body();n=data.get('number');action=data.get('action');rid=data.get('requestId')
        if action not in ('select','send','name','leave') or not isinstance(n,int) or isinstance(n,bool) or not 0<n<10**9:return fail('操作无效',400)
        if not isinstance(rid,str) or not re.fullmatch(r'[0-9a-fA-F-]{36}',rid):return fail('请求编号无效',400)
        text=data.get('text','')
        if not isinstance(text,str) or len(text)>4000:return fail('内容过长',400)
        return bounded(lambda:service.action(g.identity,n,action,text,rid))
    @app.get('/')
    def index():return send_from_directory(assets_root,'index.html')
    @app.get('/assets/<path:name>')
    def assets(name):return send_from_directory(assets_root/'assets',name)
    return app

if __name__=='__main__':
    os.umask(0o077)
    from waitress import serve
    serve(create_app(),host='127.0.0.1',port=9840,threads=8,connection_limit=48,channel_timeout=20,max_request_body_size=16384,
          clear_untrusted_proxy_headers=True,expose_tracebacks=False)
