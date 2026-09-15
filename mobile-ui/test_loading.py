# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from adapter import Adapter, Entry, identity_key
from mobile_reads import ReadJobs, StatusIPC
from desktop_ipc import IPCError
from test_security import ENV

class LoadingTests(unittest.TestCase):
 def test_slow_read_polls_without_duplicate_or_blocking_other_work(self):
  jobs=ReadJobs(capacity=1);release=threading.Event();started=threading.Event();calls=[]
  def read():
   calls.append(1);started.set();release.wait(2);return {'turns':['saved']}
  try:
   begin=time.monotonic();self.assertTrue(jobs.poll(('actor','thread'),read)['loading']);self.assertLess(time.monotonic()-begin,.3)
   self.assertTrue(started.wait(1))
   for _ in range(10):self.assertTrue(jobs.poll(('actor','thread'),read)['loading'])
   self.assertTrue(jobs.poll(('other','thread'),read)['queued']);self.assertEqual(len(calls),1)
  finally:release.set()
  for _ in range(100):
   result=jobs.poll(('actor','thread'),read)
   if not result.get('loading'):break
   time.sleep(.005)
  self.assertEqual(result,{'turns':['saved']});self.assertEqual(len(calls),1)
 def test_failures_are_bounded_cached_and_hide_private_errors(self):
  jobs=ReadJobs();calls=[]
  def fail():calls.append(1);raise RuntimeError('SECRET_PATH')
  jobs.poll(('a','t'),fail)
  for _ in range(100):
   r=jobs.poll(('a','t'),fail)
   if not r.get('loading'):break
   time.sleep(.005)
  self.assertIn('error',r);self.assertNotIn('SECRET_PATH',str(r));self.assertEqual(len(calls),1)
 def test_failed_page_expires_for_retry_and_cache_cannot_cross_accounts(self):
  jobs=ReadJobs()
  def failed():raise RuntimeError('failure')
  jobs.poll(('a','t'),failed,ttl=120)
  for _ in range(100):
   with jobs.lock:done=jobs.jobs[('a','t')]['done']
   if done:break
   time.sleep(.005)
  with jobs.lock:
   self.assertEqual(jobs.jobs[('a','t')]['ttl'],6)
   jobs.jobs[('a','t')]['at']-=7
  jobs.poll(('a','t'),lambda:{'turns':['owner a']})
  for _ in range(100):
   r=jobs.poll(('a','t'),lambda:{'turns':['owner a']})
   if not r.get('loading'):break
   time.sleep(.005)
  self.assertEqual(r['turns'],['owner a'])
  self.assertTrue(jobs.poll(('b','t'),lambda:{'turns':['owner b']})['loading'])
 def test_status_snapshot_does_not_request_complete_history(self):
  ipc=StatusIPC(timeout=1);tid=str(uuid.uuid4());sent=[]
  ipc._send=sent.append
  def receive():ipc.snapshots[(tid,'owner')]={'conversationState':{'id':tid,'hostId':'local'}}
  ipc._receive=receive
  with patch.object(ipc,'request',side_effect=AssertionError('complete history requested')):
   self.assertEqual(ipc.snapshot(tid,'owner')['id'],tid)
  self.assertEqual([m['method'] for m in sent],['thread-stream-following-changed'])
  ipc._receive=lambda:ipc.snapshots.update({(tid,'owner'):{'conversationState':{'id':'wrong','hostId':'local'}}})
  with self.assertRaises(IPCError):ipc.snapshot(tid,'owner')
 def test_partial_socket_reads_have_an_absolute_deadline(self):
  ipc=StatusIPC();ipc.read_deadline=time.monotonic()-.1
  with self.assertRaises(IPCError):ipc._read(100)
 def test_legacy_detail_retains_embedded_timeline(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);a=Adapter(root);tid=str(uuid.uuid4());actor=identity_key(ENV)
   def entry():return Entry(state_dir=root/'entry')
   with contextlib.closing(entry()) as e,e.catalog.db:e.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(actor,1,tid,'saved task','/tmp'))
   page={'turns':[{'id':'saved','items':[{'role':'result','text':'saved reply'}]}],'nextCursor':None}
   try:
    with patch('adapter.Entry',entry),patch.object(a,'observe',return_value={'live':False}),patch.object(a,'timeline',return_value=page) as timeline:
     self.assertEqual(a.detail(ENV,1)['timeline']['turns'][0]['items'][0]['text'],'saved reply')
     self.assertNotIn('timeline',a.detail(ENV,1,summary=True))
     self.assertEqual(timeline.call_count,1)
   finally:a.pool.shutdown()
 def test_old_and_new_http_read_contracts_are_explicit(self):
  import auth
  from server import create_app
  from test_security import ORIGIN,PASSWORD
  class Facade:
   def detail(self,e,n,summary=False):return {'summary':summary,**({} if summary else {'timeline':{'turns':['saved']}})}
   def timeline(self,*a):return {'turns':['saved']}
   def history(self,*a):return {'loading':True}
   def files(self,*a):return {'files':['saved']}
   def file_page(self,*a):return {'loading':True}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);auth.set_password(ENV,PASSWORD,root);app=create_app(Facade(),root,ORIGIN);client=app.test_client()
   code=auth.issue(ENV,root);r=client.post('/api/pair',json={'code':code,'password':PASSWORD},base_url=ORIGIN,headers={'Origin':ORIGIN});self.assertEqual(r.status_code,200)
   def get(path):return client.get(path,base_url=ORIGIN).json
   self.assertEqual(get('/api/tasks/1')['timeline']['turns'],['saved'])
   self.assertNotIn('timeline',get('/api/tasks/1?view=summary'))
   self.assertEqual(get('/api/tasks/1/history')['turns'],['saved'])
   self.assertEqual(get('/api/tasks/1/files')['files'],['saved'])
   self.assertTrue(get('/api/tasks/1/history?async=1')['loading'])
   self.assertTrue(get('/api/tasks/1/files?async=1')['loading'])
 def test_detail_history_and_files_are_independent_and_actor_scoped(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);a=Adapter(root);tid=str(uuid.uuid4());actor=identity_key(ENV)
   def entry():return Entry(state_dir=root/'entry')
   with contextlib.closing(entry()) as e,e.catalog.db:e.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(actor,1,tid,'old thread','/tmp'))
   try:
    with patch('adapter.Entry',entry),patch.object(a,'observe',return_value={'live':False}),patch.object(a,'timeline',side_effect=AssertionError('history blocks metadata')):
     self.assertEqual(a.detail(ENV,1,summary=True)['title'],'old thread')
     with self.assertRaises(ValueError):a.history(ENV,1,json.dumps({'requestedThreadId':str(uuid.uuid4())}))
     with self.assertRaises(Exception):a.history({**ENV,'user_id':'other'},1)
    def with_api():
     e=entry();e.api.request=lambda *args,**kw:{'data':[],'nextCursor':None};return e
    with patch('adapter.Entry',with_api),patch.object(a.artifacts,'discover',side_effect=AssertionError('files block messages')):
     self.assertEqual(a.timeline(ENV,1,include_files=False)['turns'],[])
   finally:a.pool.shutdown()

if __name__=='__main__':unittest.main()
