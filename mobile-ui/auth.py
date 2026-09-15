# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""One-use WeChat authorization; independent web principal and revocable sessions."""
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

ROOT=Path(__file__).resolve().parent
STATE=Path(os.environ.get('MOBILE_STATE_DIR', str(ROOT.parent/'private'))).expanduser().resolve()
SESSION_LIFETIME=12*3600
IDLE_TIMEOUT=30*60

def connect(directory=STATE):
    directory=Path(directory);directory.mkdir(mode=0o700,parents=True,exist_ok=True);os.chmod(directory,0o700)
    path=directory/'auth.sqlite3'
    fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600);os.close(fd);os.chmod(path,0o600)
    db=sqlite3.connect(path,timeout=5)
    db.executescript('''CREATE TABLE IF NOT EXISTS pairs (digest TEXT PRIMARY KEY, identity TEXT, expires REAL);
      CREATE TABLE IF NOT EXISTS sessions (digest TEXT PRIMARY KEY, identity TEXT, csrf TEXT, expires REAL);
      CREATE TABLE IF NOT EXISTS attempts (bucket TEXT PRIMARY KEY, count INTEGER, expires REAL);
      CREATE TABLE IF NOT EXISTS session_activity (digest TEXT PRIMARY KEY, created REAL, seen REAL);
      CREATE TABLE IF NOT EXISTS web_passwords (actor TEXT PRIMARY KEY, salt BLOB, verifier BLOB);
      CREATE TABLE IF NOT EXISTS password_sessions (digest TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS session_metadata (digest TEXT PRIMARY KEY, public_id TEXT UNIQUE, label TEXT);
      CREATE TABLE IF NOT EXISTS auth_migrations (name TEXT PRIMARY KEY);
      CREATE TABLE IF NOT EXISTS login_history (id INTEGER PRIMARY KEY, at REAL, actor TEXT, kind TEXT, label TEXT, session_id TEXT);
      CREATE INDEX IF NOT EXISTS login_history_actor_id ON login_history(actor,id);
      CREATE TABLE IF NOT EXISTS security_events (id INTEGER PRIMARY KEY, at REAL, kind TEXT, actor TEXT);''')
    # An earlier unpublished candidate had a smaller audit schema.
    db.execute('BEGIN IMMEDIATE')
    if 'actor' not in {r[1] for r in db.execute('PRAGMA table_info(security_events)')}:
        db.execute('ALTER TABLE security_events ADD COLUMN actor TEXT')
    if not db.execute("SELECT 1 FROM auth_migrations WHERE name='login_history_v1'").fetchone():
        db.execute('''INSERT INTO login_history(at,actor,kind,label,session_id)
          SELECT at,actor,kind,NULL,NULL FROM security_events WHERE actor IS NOT NULL
          AND kind IN ('login_ok','login_rejected','password_setup_required','password_set','logout','owner_sessions_revoked','single_login_revoked') ORDER BY id''')
        db.execute("INSERT INTO auth_migrations VALUES ('login_history_v1')")
    db.commit()
    return db

def digest(value):return hashlib.sha256(value.encode()).hexdigest()

def web_identity(source):
    from adapter import identity_key,base_envelope
    source=base_envelope(source);key=identity_key(source)
    # Reuse the desktop dispatcher's envelope format, with a separate principal.
    # No WeChat process participates in desktop reads, selection or sends.
    return {'project':'codex-web-console','platform':source['platform'],'session_key':'web:'+key,
            'user_id':key,'web_account':True,'source_identity':source}

def issue(identity,directory=STATE):
    from adapter import base_envelope
    identity=base_envelope(identity)
    code=secrets.token_hex(10).upper()
    with contextlib.closing(connect(directory)) as db,db:
        db.execute('DELETE FROM pairs WHERE expires < ?',(time.time(),))
        db.execute('DELETE FROM pairs WHERE identity=?',(json.dumps(identity,sort_keys=True),))
        db.execute('INSERT INTO pairs VALUES (?,?,?)',(digest(code),json.dumps(identity,sort_keys=True),time.time()+600))
    return code

def audit_in(db,kind,identity=None,*,user_agent=None,session_id=None,label=None):
    from adapter import identity_key
    actor=identity_key(identity) if identity else None
    db.execute('INSERT INTO security_events(at,kind,actor) VALUES (?,?,?)',(time.time(),kind,actor))
    db.execute('DELETE FROM security_events WHERE id <= (SELECT COALESCE(MAX(id),0)-1000 FROM security_events)')
    if actor and kind in HISTORY_LABELS:
        browser=browser_label(user_agent) if user_agent is not None else label
        db.execute('INSERT INTO login_history(at,actor,kind,label,session_id) VALUES (?,?,?,?,?)',(time.time(),actor,kind,browser,session_id))
        db.execute('DELETE FROM login_history WHERE actor=? AND id NOT IN (SELECT id FROM login_history WHERE actor=? ORDER BY id DESC LIMIT 1000)',(actor,actor))

def password_hash(password,salt):
    return hashlib.scrypt(password.encode('utf-8'),salt=salt,n=2**17,r=8,p=1,maxmem=256*1024*1024,dklen=32)

def set_password(source,password,directory=STATE):
    """Local operator only. No HTTP or WeChat reset path."""
    from adapter import identity_key,base_envelope
    if not isinstance(password,str) or not 9<=len(password)<=128 or not password.strip():
        raise ValueError('密码需要 9–128 个字符，请使用独立的长密码。')
    source=base_envelope(source);salt=secrets.token_bytes(16);verifier=password_hash(password,salt)
    with contextlib.closing(connect(directory)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR REPLACE INTO web_passwords VALUES (?,?,?)',(identity_key(source),salt,verifier))
        db.execute('DELETE FROM sessions WHERE identity=?',(json.dumps(web_identity(source),sort_keys=True),))
        db.execute('DELETE FROM pairs WHERE identity=?',(json.dumps(source,sort_keys=True),))
        db.execute('DELETE FROM session_activity WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM password_sessions WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM session_metadata WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM password_sessions WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM attempts WHERE bucket=?',('password:'+identity_key(source),))
        audit_in(db,'password_set',web_identity(source))

def browser_label(user_agent):
    ua=str(user_agent)[:600].lower()
    device='iPhone' if 'iphone' in ua else 'iPad' if 'ipad' in ua else 'Android' if 'android' in ua else 'Mac' if 'macintosh' in ua else 'Windows' if 'windows' in ua else '设备'
    browser='微信浏览器' if 'micromessenger' in ua else 'Edge' if 'edg/' in ua else 'Chrome' if 'chrome' in ua or 'crios' in ua else 'Firefox' if 'firefox' in ua else 'Safari' if 'safari' in ua else '浏览器'
    return device+' · '+browser

def exchange(code,directory=STATE,*,password='',user_agent=''):
    from adapter import identity_key
    now=time.time()
    with contextlib.closing(connect(directory)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT count,expires FROM attempts WHERE bucket='pair'").fetchone()
        if row and row[1]>now and row[0]>=30:return None,'rate'
        count=(row[0] if row and row[1]>now else 0)+1;end=row[1] if row and row[1]>now else now+60
        db.execute("INSERT OR REPLACE INTO attempts VALUES ('pair',?,?)",(count,end))
        row=db.execute('SELECT identity,expires FROM pairs WHERE digest=?',(digest(code),)).fetchone()
        if not row or row[1]<now:
            audit_in(db,'pair_rejected');return None,'invalid'
        source=json.loads(row[0]);actor=identity_key(source)
        bucket='password:'+actor
        stored=db.execute('SELECT salt,verifier FROM web_passwords WHERE actor=?',(actor,)).fetchone()
        # Only reveal setup status after possession of a valid one-use code.
        # Missing enrollment is not a password guess and must never cause lockout.
        if not stored:
            db.execute('DELETE FROM attempts WHERE bucket=?',(bucket,))
            audit_in(db,'password_setup_required',web_identity(source),user_agent=user_agent)
            return None,'password_unset'
        failures=db.execute('SELECT count,expires FROM attempts WHERE bucket=?',(bucket,)).fetchone()
        if failures and failures[1]>now and failures[0]>=5:
            audit_in(db,'login_throttled',web_identity(source),user_agent=user_agent)
            return None,'password_rate'
        valid=isinstance(password,str) and 9<=len(password)<=128
        if not valid or not hmac.compare_digest(password_hash(password,stored[0]),stored[1]):
            count=(failures[0] if failures and failures[1]>now else 0)+1
            end=failures[1] if failures and failures[1]>now else now+900
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',(bucket,count,end))
            audit_in(db,'login_rejected',web_identity(source),user_agent=user_agent);return None,'invalid'
        identity=web_identity(source)
        db.execute('DELETE FROM attempts WHERE bucket=?',(bucket,))
        db.execute('DELETE FROM pairs WHERE digest=?',(digest(code),))
        token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        db.execute('DELETE FROM sessions WHERE expires<?',(now,))
        db.execute('DELETE FROM session_activity WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM password_sessions WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM session_metadata WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(digest(token),json.dumps(identity,sort_keys=True),csrf,now+SESSION_LIFETIME))
        db.execute('INSERT INTO session_activity VALUES (?,?,?)',(digest(token),now,now))
        db.execute('INSERT INTO password_sessions VALUES (?)',(digest(token),))
        public_id=secrets.token_hex(16)
        db.execute('INSERT INTO session_metadata VALUES (?,?,?)',(digest(token),public_id,browser_label(user_agent)))
        db.execute('DELETE FROM session_metadata WHERE digest NOT IN (SELECT digest FROM sessions)')
        audit_in(db,'login_ok',identity,user_agent=user_agent,session_id=public_id)
        return (token,csrf),'ok'

def session(token,directory=STATE,*,touch=False):
    if not token or len(token)>100:return None
    with contextlib.closing(connect(directory)) as db,db:
        row=db.execute('SELECT identity,csrf,expires FROM sessions WHERE digest=?',(digest(token),)).fetchone()
        activity=db.execute('SELECT seen FROM session_activity WHERE digest=?',(digest(token),)).fetchone()
        if not db.execute('SELECT 1 FROM password_sessions WHERE digest=?',(digest(token),)).fetchone():return None
        if not row or row[2]<=time.time() or not activity or time.time()-activity[0]>IDLE_TIMEOUT:return None
        identity=json.loads(row[0])
        if not identity.get('web_account'):return None
        if touch:db.execute('UPDATE session_activity SET seen=? WHERE digest=?',(time.time(),digest(token)))
        return identity,row[1]

def logout(token,directory=STATE):
    with contextlib.closing(connect(directory)) as db,db:
        row=db.execute('SELECT identity FROM sessions WHERE digest=?',(digest(token),)).fetchone()
        meta=db.execute('SELECT public_id,label FROM session_metadata WHERE digest=?',(digest(token),)).fetchone()
        db.execute('DELETE FROM sessions WHERE digest=?',(digest(token),))
        db.execute('DELETE FROM session_activity WHERE digest=?',(digest(token),))
        db.execute('DELETE FROM password_sessions WHERE digest=?',(digest(token),))
        db.execute('DELETE FROM session_metadata WHERE digest=?',(digest(token),))
        if row:audit_in(db,'logout',json.loads(row[0]),session_id=meta[0] if meta else None,label=meta[1] if meta else None)

def revoke_owner(identity,directory=STATE):
    with contextlib.closing(connect(directory)) as db,db:
        db.execute('DELETE FROM sessions WHERE identity=?',(json.dumps(identity,sort_keys=True),))
        db.execute('DELETE FROM session_activity WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM password_sessions WHERE digest NOT IN (SELECT digest FROM sessions)')
        db.execute('DELETE FROM session_metadata WHERE digest NOT IN (SELECT digest FROM sessions)')
        source=identity.get('source_identity')
        if source:db.execute('DELETE FROM pairs WHERE identity=?',(json.dumps(source,sort_keys=True),))
        audit_in(db,'owner_sessions_revoked',identity)

def revoke_all(directory=STATE):
    with contextlib.closing(connect(directory)) as db,db:
        db.execute('DELETE FROM sessions');db.execute('DELETE FROM session_activity');db.execute('DELETE FROM pairs')
        db.execute('DELETE FROM password_sessions');db.execute('DELETE FROM session_metadata')
        audit_in(db,'all_sessions_revoked')

def logins(identity,current_token,directory=STATE):
    now=time.time();key=json.dumps(identity,sort_keys=True)
    with contextlib.closing(connect(directory)) as db,db:
        rows=db.execute('''SELECT s.digest,a.created,a.seen,s.expires FROM sessions s
          JOIN session_activity a ON a.digest=s.digest JOIN password_sessions p ON p.digest=s.digest
          WHERE s.identity=? AND s.expires>? AND a.seen>? ORDER BY a.created DESC''',(key,now,now-IDLE_TIMEOUT)).fetchall()
        result=[]
        for token_digest,created,seen,expires in rows:
            db.execute('INSERT OR IGNORE INTO session_metadata VALUES (?,?,?)',(token_digest,secrets.token_hex(16),'升级前的浏览器登录'))
            public_id,label=db.execute('SELECT public_id,label FROM session_metadata WHERE digest=?',(token_digest,)).fetchone()
            result.append({'id':public_id,'label':label,'createdAt':created,'lastActiveAt':seen,'expiresAt':expires,'current':hmac.compare_digest(token_digest,digest(current_token))})
        return sorted(result,key=lambda x:not x['current'])

def revoke_login(identity,public_id,current_token,directory=STATE):
    with contextlib.closing(connect(directory)) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT s.digest,m.label FROM sessions s JOIN session_metadata m ON m.digest=s.digest WHERE m.public_id=? AND s.identity=?',(public_id,json.dumps(identity,sort_keys=True))).fetchone()
        if not row:return None
        token_digest=row[0]
        for table in ('sessions','session_activity','password_sessions','session_metadata'):db.execute('DELETE FROM '+table+' WHERE digest=?',(token_digest,))
        audit_in(db,'single_login_revoked',identity,session_id=public_id,label=row[1])
        return {'ok':True,'current':hmac.compare_digest(token_digest,digest(current_token))}


HISTORY_LABELS={'login_ok':'登录成功','login_rejected':'登录失败：密码不匹配','login_throttled':'登录被限速拦截','password_setup_required':'登录未完成：尚未设置密码','password_set':'在 Mac 设置或更改密码','logout':'主动退出登录','owner_sessions_revoked':'退出全部网页登录','single_login_revoked':'单独退出某次登录'}

def login_history(identity,current_token,directory=STATE,before=None):
    from adapter import identity_key
    actor=identity_key(identity);now=time.time()
    with contextlib.closing(connect(directory)) as db:
        current=db.execute('SELECT public_id FROM session_metadata WHERE digest=?',(digest(current_token),)).fetchone()
        sql='SELECT id,at,kind,label,session_id FROM login_history WHERE actor=?';args=[actor]
        if before is not None:sql+=' AND id<?';args.append(int(before))
        rows=db.execute(sql+' ORDER BY id DESC LIMIT 31',args).fetchall()
        events=[]
        for eid,at,kind,label,sid in rows[:30]:
            active=False
            if sid:
                found=db.execute('''SELECT 1 FROM session_metadata m JOIN sessions s ON s.digest=m.digest
                  JOIN session_activity a ON a.digest=s.digest JOIN password_sessions p ON p.digest=s.digest
                  WHERE m.public_id=? AND s.identity=? AND s.expires>? AND a.seen>?''',(sid,json.dumps(identity,sort_keys=True),now,now-IDLE_TIMEOUT)).fetchone()
                active=bool(found)
            events.append({'id':eid,'at':at,'kind':kind,'title':HISTORY_LABELS.get(kind,'登录事件'),'browser':label or '未记录（旧记录或本机操作）','sessionActive':active,'sessionStatus':'active' if active else 'ended' if sid else 'unrecorded','current':bool(kind=='login_ok' and sid and current and current[0]==sid)})
        recent=dict(db.execute('SELECT kind,COUNT(*) FROM login_history WHERE actor=? AND at>=? GROUP BY kind',(actor,now-86400)))
        total=db.execute('SELECT COUNT(*) FROM login_history WHERE actor=?',(actor,)).fetchone()[0]
        return {'events':events,'nextCursor':str(rows[29][0]) if len(rows)>30 else None,'retainedCount':total,'summary':{'successful':recent.get('login_ok',0),'failed':recent.get('login_rejected',0),'blocked':recent.get('login_throttled',0)}}
