# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
"""Read-only Codex account limits, with no credential or billing controls."""
import contextlib
import math
import time
from wechat_entry import ReadOnlyAPI
from mobile_reads import ReadJobs

class UsageAPI(ReadOnlyAPI):
    METHODS={'account/rateLimits/read'}

def number(value):return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def normalize_limits(raw):
    rows=[];buckets=raw.get('rateLimitsByLimitId')
    if not isinstance(buckets,dict) or not buckets:
        legacy=raw.get('rateLimits');buckets={'codex':legacy} if isinstance(legacy,dict) else {}
    for key,bucket in buckets.items():
        if not isinstance(bucket,dict):continue
        windows=[]
        for slot in ('primary','secondary'):
            w=bucket.get(slot)
            if not isinstance(w,dict):continue
            used=w.get('usedPercent');duration=w.get('windowDurationMins');reset=w.get('resetsAt')
            windows.append({'id':slot,'remainingPercent':round(max(0,min(100,100-used)),1) if number(used) else None,
                'durationMinutes':duration if number(duration) and duration>0 else None,
                'resetsAt':reset if number(reset) and 0<reset<253402300799 else None})
        if windows:
            rows.append({'id':str(key)[:120],'name':str(bucket.get('limitName') or ('Codex' if key=='codex' else key))[:100],'windows':windows})
    rows.sort(key=lambda b:b['id']!='codex')
    return {'buckets':rows,'observedAt':time.time(),'available':bool(rows)}

class Quota:
    def __init__(self):self.jobs=ReadJobs(capacity=1,max_entries=1)
    def get(self):return self.jobs.poll(('account','usage'),self.read,ttl=60)
    def read(self):
        try:
            with contextlib.closing(UsageAPI()) as api:return normalize_limits(api.request('account/rateLimits/read',{}))
        except Exception:return {'error':'额度暂时无法读取，请稍后刷新。'}
