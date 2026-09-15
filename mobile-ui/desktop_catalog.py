# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Read only the desktop's saved local project organization. Never write its state."""
import json
import os
from pathlib import Path

STATE=Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'.codex-global-state.json'

def organization(path=STATE):
    data=json.loads(Path(path).read_text())
    projects=data.get('local-projects')
    if not isinstance(projects,dict):raise ValueError('unknown desktop project schema')
    pins=data.get('pinned-project-ids',[])
    order=data.get('project-order',[])
    ids=list(dict.fromkeys(pins+[p for p in projects if p not in order]+order+list(projects)))
    groups=[]
    for pid in ids:
        p=projects.get(pid)
        if not isinstance(p,dict):continue
        groups.append({'id':pid,'name':str(p.get('name') or '未命名项目'),'roots':p.get('rootPaths',[]),'pinned':pid in pins})
    return {'groups':groups,'assignments':data.get('thread-project-assignments',{}),
            'projectless':set(data.get('projectless-thread-ids',[])),
            'pinnedThreads':set(data.get('pinned-thread-ids',[])),
            'hints':data.get('thread-workspace-root-hints',{})}

def project_for(thread,org):
    groups=org['groups'];by_id={g['id']:g for g in groups};tid=thread['id']
    assigned=org['assignments'].get(tid)
    pid=(assigned or {}).get('projectId') if isinstance(assigned,dict) else None
    pid=pid or thread.get('projectId')
    if pid in by_id:return by_id[pid]
    if pid:return {'id':'unmatched','name':'桌面项目暂未同步','pinned':False}
    if tid in org['projectless']:return {'id':'projectless','name':'独立会话','pinned':False}
    cwd=org['hints'].get(tid) or thread.get('cwd') or ''
    candidates=[]
    for g in groups:
        for root in g['roots']:
            if isinstance(root,str) and (cwd==root or cwd.startswith(root.rstrip('/')+'/')):candidates.append((len(root),g))
    return max(candidates,key=lambda x:x[0])[1] if candidates else {'id':'projectless','name':'独立会话','pinned':False}
