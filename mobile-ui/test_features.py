# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
from adapter import Adapter,Entry,identity_key
from desktop_catalog import organization,project_for
from presentation import normalize_turn,final_revision
from ui_state import UIState
from test_security import SecurityTests,ENV

class FeatureTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
 def tearDown(self):self.temp.cleanup()
 def test_desktop_project_names_assignments_and_order(self):
  p=self.root/'desktop.json';p.write_text(json.dumps({'local-projects':{'a':{'name':'我的简称','rootPaths':['/work/a']},'b':{'name':'示例项目乙','rootPaths':['/work/b']}},'project-order':['a','b'],'pinned-project-ids':['b'],'thread-project-assignments':{'t':{'projectId':'b'}}}))
  org=organization(p)
  self.assertEqual([g['name'] for g in org['groups']],['示例项目乙','我的简称'])
  self.assertEqual(project_for({'id':'t','cwd':'/work/a'},org)['name'],'示例项目乙')
  self.assertEqual(project_for({'id':'x','cwd':'/work/ab'},org)['id'],'projectless')
  self.assertEqual(project_for({'id':'x','cwd':'/work/a/sub'},org)['id'],'a')
  org['projectless'].add('x');self.assertEqual(project_for({'id':'x','cwd':'/work/a'},org)['id'],'projectless')
 def test_project_changes_are_read_fresh(self):
  p=self.root/'desktop.json';p.write_text('{"local-projects":{"a":{"name":"原名"}}}')
  self.assertEqual(organization(p)['groups'][0]['name'],'原名')
  p.write_text('{"local-projects":{"a":{"name":"新名"}}}')
  self.assertEqual(organization(p)['groups'][0]['name'],'新名')
  p.write_text('{}')
  with self.assertRaises(ValueError):organization(p)
 def test_web_preferences_isolated_and_unread_revision_not_timestamp(self):
  state=UIState(self.root)
  def item(rev,live=True):return {'threadId':'t','originalTitle':'原名','resultRevision':rev,'live':live,'desktopPinned':True}
  first=item('old');state.decorate('a',[first]);self.assertFalse(first['newResult']);self.assertTrue(first['pinned'])
  state.update('a','t','alias','简称');state.update('a','t','pin',False)
  nxt=item('new');state.decorate('a',[nxt]);self.assertTrue(nxt['newResult']);self.assertEqual(nxt['title'],'简称');self.assertFalse(nxt['pinned'])
  other=item('new');state.decorate('b',[other]);self.assertFalse(other['newResult']);self.assertEqual(other['title'],'原名')
  state.update('a','t','seen','new');r=item('even-newer');state.decorate('a',[r]);self.assertTrue(r['newResult'])
  r=item('new');state.decorate('a',[r]);self.assertFalse(r['newResult'])
 def test_unknown_baseline_does_not_mark_old_results_new(self):
  s=UIState(self.root);a={'threadId':'t','originalTitle':'a','live':False};s.decorate('a',[a]);a.update(live=True,resultRevision='old');s.decorate('a',[a]);self.assertFalse(a['newResult'])
  a['resultRevision']='new';s.decorate('a',[a]);self.assertTrue(a['newResult'])
 def test_timeline_preserves_order_full_text_and_excludes_hidden_data(self):
  long='中文'*12000
  t={'id':'t','startedAt':42,'status':'completed','items':[{'type':'userMessage','id':'u','content':[{'type':'text','text':'问题'}]}, {'type':'reasoning','text':'PRIVATE_REASONING'}, {'type':'agentMessage','id':'f','text':'处理中','phase':'commentary'}, {'type':'commandExecution','status':'completed','command':'SECRET_COMMAND','aggregatedOutput':'SECRET_OUTPUT'}, {'type':'agentMessage','id':'r','phase':'final_answer','text':long}]}
  result=normalize_turn(t);self.assertEqual([i['role'] for i in result['items']],['user','feedback','operation','result']);self.assertEqual(result['items'][-1]['text'],long)
  self.assertNotIn('PRIVATE_REASONING',str(result));self.assertNotIn('SECRET_COMMAND',str(result));self.assertNotIn('SECRET_OUTPUT',str(result));self.assertEqual(result['at'],42000)
  rev=final_revision([t]);self.assertEqual(len(rev),64);t['items'][-1]['text']='new';self.assertNotEqual(rev,final_revision([t]));t['status']='inProgress';self.assertEqual(final_revision([t]),'')
 def test_full_catalog_search_alias_priority_and_unknown_counts(self):
  org=self.root/'org.json';org.write_text(json.dumps({'local-projects':{'p':{'name':'示例项目乙','rootPaths':['/work/demo-project']}},'pinned-project-ids':['p']}))
  a=Adapter(self.root,org);threads=[{'id':str(uuid.uuid4()),'name':'会话'+str(n),'cwd':'/work/demo-project','updatedAt':n} for n in range(30)]
  actor=identity_key(ENV);a.preferences.update(actor,threads[0]['id'],'alias','手机简称')
  for i,t in enumerate(threads):a.cache[t['id']]={'status':'needs_input' if i==2 else 'active' if i==3 else 'unknown','statusLabel':'状态','observedAt':__import__('time').time(),'live':i in (2,3),'resultRevision':''}
  realEntry=Entry
  def entry():return realEntry(state_dir=self.root/'entry')
  with patch('adapter.Entry',entry),patch.object(a,'catalog',return_value=(threads,True)),patch.object(a,'schedule_scan'),patch.object(a,'schedule_live_refresh'):
   r=a.listing(ENV);self.assertEqual(r['overview']['total'],30);self.assertEqual(r['overview']['unknown'],28);self.assertEqual(r['tasks'][0]['threadId'],threads[2]['id']);self.assertEqual(len(r['tasks']),24)
   r=a.listing(ENV,query='手机简称');self.assertEqual(r['matchingCount'],1);self.assertEqual(r['tasks'][0]['title'],'手机简称')
   r=a.listing(ENV,group='p',status='active');self.assertEqual(len(r['tasks']),1)
   r=a.listing(ENV,group='missing');self.assertEqual(r['overview']['total'],0);self.assertEqual(r['overview']['active'],0)
  a.pool.shutdown()
 def test_recent_sort_is_global_before_pagination_with_pins_first(self):
  org=self.root/'recent-org.json';org.write_text(json.dumps({'local-projects':{'p':{'name':'项目','rootPaths':['/work/demo-project']}}}))
  a=Adapter(self.root,org);threads=[{'id':str(uuid.uuid4()),'name':'任务'+str(n),'cwd':'/work/demo-project','updatedAt':n} for n in range(40)]
  actor=identity_key(ENV);a.preferences.update(actor,threads[0]['id'],'pin',True)
  for i,t in enumerate(threads):a.cache[t['id']]={'status':'error' if i==1 else 'idle','statusLabel':'状态','observedAt':__import__('time').time(),'live':True,'resultRevision':''}
  realEntry=Entry
  try:
   with patch('adapter.Entry',lambda:realEntry(state_dir=self.root/'entry')),patch.object(a,'catalog',return_value=(threads,True)),patch.object(a,'schedule_scan') as scan,patch.object(a,'schedule_live_refresh'):
    recent=a.listing(ENV,sort='recent',limit=8)
    expected=[threads[0]['id']]+[t['id'] for t in reversed(threads[33:])]
    self.assertEqual([t['threadId'] for t in recent['tasks']],expected)
    self.assertEqual({t['id'] for t in scan.call_args.args[0]},set(expected))
    page=a.listing(ENV,sort='recent',limit=8,cursor=recent['nextCursor'])
    self.assertEqual([t['threadId'] for t in page['tasks']],[t['id'] for t in reversed(threads[25:33])])
    self.assertEqual(a.listing(ENV)['tasks'][0]['threadId'],threads[1]['id'])
  finally:a.pool.shutdown()
 def test_history_cursor_cannot_cross_thread(self):
  a=Adapter(self.root);tid=str(uuid.uuid4());actor=identity_key(ENV)
  with contextlib.closing(Entry(state_dir=self.root/'entry')) as e:
   with e.catalog.db:e.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(actor,1,tid,'test','/tmp'))
  realEntry=Entry
  with patch('adapter.Entry',lambda:realEntry(state_dir=self.root/'entry')):
   with self.assertRaises(ValueError):a.timeline(ENV,1,json.dumps({'requestedThreadId':str(uuid.uuid4())}))
  a.pool.shutdown()

class FeatureSecurityTests(SecurityTests):
 def test_background_reads_do_not_extend_idle_but_user_activity_does(self):
  csrf=self.login()
  import auth,time
  with contextlib.closing(auth.connect(self.state)) as db,db:db.execute('UPDATE session_activity SET seen=?',(time.time()-1790,))
  with contextlib.closing(auth.connect(self.state)) as db:before=db.execute('SELECT seen FROM session_activity').fetchone()[0]
  self.assertEqual(self.client.get('/api/session',base_url='https://mobile.example.test').status_code,200)
  with contextlib.closing(auth.connect(self.state)) as db:self.assertEqual(db.execute('SELECT seen FROM session_activity').fetchone()[0],before)
  self.assertEqual(self.post('/api/activity',{}).status_code,403)
  self.assertEqual(self.post('/api/activity',{},headers={'X-CSRF-Token':csrf}).status_code,200)
  with contextlib.closing(auth.connect(self.state)) as db:self.assertGreater(db.execute('SELECT seen FROM session_activity').fetchone()[0],before)
 def test_new_endpoints_require_login_and_csrf(self):
  from test_security import ORIGIN
  self.assertEqual(self.client.get('/api/tasks/1/history',base_url=ORIGIN).status_code,401)
  self.assertEqual(self.post('/api/tasks/1/preference',{'kind':'pin','value':True}).status_code,401)
  self.login();self.assertEqual(self.post('/api/tasks/1/preference',{'kind':'pin','value':True}).status_code,403)

if __name__=='__main__':unittest.main()
