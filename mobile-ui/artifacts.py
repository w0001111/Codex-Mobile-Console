# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Explicit per-thread output references -> immutable, authenticated snapshots.
No arbitrary path route, directory browsing, symlinks or input/source citations.
"""
import contextlib
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
from urllib.parse import unquote
from ui_state import UIState

MAX_FILE=32*1024*1024
MAX_CACHE=512*1024*1024
EXTENSIONS={'.pdf','.docx','.xlsx','.pptx','.csv','.txt','.md','.tex','.png','.jpg','.jpeg','.webp','.gif'}
SENSITIVE=re.compile(r'password|passwd|secret|credential|token|id_rsa|id_ed25519|authorized_keys|known_hosts',re.I)

def output_references(turn,cwd):
    if turn.get("status")!="completed":return []
    written=set()
    for item in turn.get('items',[]):
        if item.get('type')=='fileChange' and item.get('status')=='completed':
            for change in item.get('changes',[]):
                kind=change.get('kind',{});kind=kind.get('type') if isinstance(kind,dict) else kind
                path=change.get('path')
                if kind in ('add','update') and isinstance(path,str):written.add(str(Path(path) if Path(path).is_absolute() else Path(cwd)/path))
    refs=[]
    for item in turn.get('items',[]):
        if item.get('type')!='agentMessage' or item.get('phase') not in ('final_answer',None):continue
        text=item.get('text','');paths=[]
        for match in re.finditer(r':codex-file-citation\{([^}]*)\}',text):
            fields={}
            for key,value in re.findall(r'(\w+)="((?:\\.|[^"\\])*)"',match[1]):
                try:fields[key]=json.loads('"'+value+'"')
                except ValueError:pass
            if fields.get('purpose')=='output' and isinstance(fields.get('path'),str):paths.append(fields['path'])
        for match in re.finditer(r'\[[^\]]*\]\((?:<([^>]+)>|([^\)]+))\)',text):
            path=unquote(match[1] or match[2]);path=re.sub(r':\d+$','',path)
            # An explicit inline image is a request to display that local output.
            # Ordinary file links still need a completed file-change proof.
            embedded=match.start()>0 and text[match.start()-1]=='!'
            if path in written or (embedded and Path(path).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif')):paths.append(path)
        for path in dict.fromkeys(paths):refs.append({'path':path,'turnId':turn.get('turnId') or turn.get('id') or '', 'messageId':item.get('id') or hashlib.sha256(text.encode()).hexdigest()})
    return refs

def allowed_path(raw,cwd):
    if not isinstance(raw,str) or any(ord(c)<32 for c in raw):raise ValueError('文件路径无效')
    p=Path(raw);root=Path(cwd)
    if not p.is_absolute() or not root.is_absolute() or '..' in p.parts or '..' in root.parts:raise ValueError('只开放会话工作目录中的成果')
    try:p.relative_to(root)
    except ValueError:raise ValueError('文件位于会话工作目录之外')
    if p.suffix.lower() not in EXTENSIONS:raise ValueError('此文件类型暂不开放')
    if any(part.startswith('.') or part.lower() in ('private','node_modules','secrets','credentials') for part in p.parts[1:]) or SENSITIVE.search(p.name):raise ValueError('敏感文件不开放')
    return p

def secure_open(path):
    """Walk every component with O_NOFOLLOW; do not follow a swapped parent directory."""
    parts=Path(path).parts
    if not Path(path).is_absolute() or '..' in parts:raise ValueError('invalid path')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in parts[1:-1]:
            nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=nxt
        out=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
    finally:os.close(fd)
    st=os.fstat(out)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:os.close(out);raise ValueError('只开放普通成果文件，不跟随链接')
    return out

def image_type(name,data):
    ext=Path(name).suffix.lower()
    if ext=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if ext in ('.jpg','.jpeg') and data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if ext=='.webp' and data[:4]==b'RIFF' and data[8:12]==b'WEBP':return 'image/webp'
    if ext=='.gif' and data[:6] in (b'GIF87a',b'GIF89a'):return 'image/gif'
    return None

class ArtifactStore(UIState):
    def connect(self):
        db=super().connect()
        db.execute('''CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY, actor TEXT, thread TEXT, proof TEXT,
          name TEXT, size INTEGER, digest TEXT, created REAL, UNIQUE(actor,thread,proof))''')
        db.execute('CREATE TABLE IF NOT EXISTS artifact_sources (id TEXT PRIMARY KEY, path TEXT)')
        return db
    def capture(self,actor,tid,cwd,reference):
        p=allowed_path(reference['path'],cwd)
        proof=hashlib.sha256(json.dumps([reference['turnId'],reference['messageId'],str(p)]).encode()).hexdigest()
        with contextlib.closing(self.connect()) as db:
            old=db.execute('SELECT id FROM artifacts WHERE actor=? AND thread=? AND proof=?',(actor,tid,proof)).fetchone()
            if old:
                with db:db.execute('INSERT OR IGNORE INTO artifact_sources VALUES (?,?)',(old[0],str(p)))
                return old[0]
            used=db.execute('SELECT COALESCE(SUM(size),0) FROM artifacts').fetchone()[0]
        fd=secure_open(p)
        try:
            before=os.fstat(fd)
            if before.st_size>MAX_FILE:raise ValueError('文件超过 32 MB，请在桌面查看')
            if used+before.st_size>MAX_CACHE:raise ValueError('成果缓存已满，请在桌面查看')
            with os.fdopen(fd,'rb',closefd=False) as f:data=f.read(MAX_FILE+1)
            after=os.fstat(fd)
            if len(data)>MAX_FILE or (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise ValueError('文件仍在更新，请稍后重试')
        finally:os.close(fd)
        aid=secrets.token_hex(16);cache=self.directory/'artifact-cache';cache.mkdir(mode=0o700,parents=True,exist_ok=True)
        target=cache/aid
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as f:f.write(data)
        try:
            with contextlib.closing(self.connect()) as db,db:
                # Recheck quota under the writer transaction; concurrent snapshots cannot exceed it.
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT COALESCE(SUM(size),0) FROM artifacts').fetchone()[0]+len(data)>MAX_CACHE:raise ValueError('成果缓存已满，请在桌面查看')
                db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?,?,?,?)',(aid,actor,tid,proof,p.name,len(data),hashlib.sha256(data).hexdigest(),time.time()))
                actual=db.execute('SELECT id FROM artifacts WHERE actor=? AND thread=? AND proof=?',(actor,tid,proof)).fetchone()[0]
                db.execute('INSERT OR IGNORE INTO artifact_sources VALUES (?,?)',(actual,str(p)))
            if actual!=aid:target.unlink()
            return actual
        except Exception:
            target.unlink(missing_ok=True);raise
    def discover(self,actor,tid,cwd,turns):
        skipped=0
        for turn in turns:
            for ref in output_references(turn,cwd)[:100]:
                try:self.capture(actor,tid,cwd,ref)
                except (OSError,ValueError):skipped+=1
        return skipped
    def listing(self,actor,tid):
        with contextlib.closing(self.connect()) as db:
            return [{'id':a,'name':n,'size':s,'capturedAt':t,'sourcePath':p,'image':Path(n).suffix.lower() in ('.png','.jpg','.jpeg','.webp','.gif')} for a,n,s,t,p in db.execute('SELECT a.id,a.name,a.size,a.created,s.path FROM artifacts a LEFT JOIN artifact_sources s ON a.id=s.id WHERE a.actor=? AND a.thread=? ORDER BY a.created DESC',(actor,tid))]
    def read(self,actor,tid,aid):
        with contextlib.closing(self.connect()) as db:row=db.execute('SELECT name,size,digest FROM artifacts WHERE id=? AND actor=? AND thread=?',(aid,actor,tid)).fetchone()
        if not row:raise FileNotFoundError()
        fd=secure_open(self.directory/'artifact-cache'/aid)
        with os.fdopen(fd,'rb') as f:data=f.read(MAX_FILE+1)
        if len(data)!=row[1] or not hmac.compare_digest(hashlib.sha256(data).hexdigest(),row[2]):raise ValueError('成果副本校验失败')
        return row[0],data,image_type(row[0],data)
