# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Web-only aliases, pin overrides and seen-result markers, scoped by actor and thread."""
import contextlib
import os
from pathlib import Path
import sqlite3

class UIState:
    def __init__(self,directory):self.directory=Path(directory)
    def connect(self):
        self.directory.mkdir(mode=0o700,parents=True,exist_ok=True)
        p=self.directory/'ui.sqlite3';fd=os.open(p,os.O_CREAT|os.O_RDWR,0o600);os.close(fd)
        db=sqlite3.connect(p,timeout=5)
        db.execute('CREATE TABLE IF NOT EXISTS preferences (actor TEXT, thread TEXT, alias TEXT DEFAULT "", pinned INTEGER, seen TEXT, PRIMARY KEY(actor,thread))')
        return db
    def decorate(self,actor,items):
        with contextlib.closing(self.connect()) as db,db:
            for item in items:
                tid=item['threadId'];rev=item.get('resultRevision','')
                db.execute('INSERT OR IGNORE INTO preferences(actor,thread,seen) VALUES (?,?,?)',(actor,tid,rev if item.get('live') else None))
                alias,pin,seen=db.execute('SELECT alias,pinned,seen FROM preferences WHERE actor=? AND thread=?',(actor,tid)).fetchone()
                if seen is None and item.get('live'):
                    seen=rev;db.execute('UPDATE preferences SET seen=? WHERE actor=? AND thread=?',(rev,actor,tid))
                item.update(alias=alias,title=alias or item['originalTitle'],pinned=bool(pin) if pin is not None else item.get('desktopPinned',False),newResult=bool(rev and seen is not None and rev!=seen))
    def update(self,actor,tid,kind,value):
        columns={'alias':'alias','pin':'pinned','seen':'seen'}
        if kind not in columns:raise ValueError('unsupported preference')
        with contextlib.closing(self.connect()) as db,db:
            db.execute('INSERT OR IGNORE INTO preferences(actor,thread) VALUES (?,?)',(actor,tid))
            db.execute('UPDATE preferences SET '+columns[kind]+'=? WHERE actor=? AND thread=?',(value,actor,tid))
