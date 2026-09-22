# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from message_activity import MessageActivity,event_time
from adapter import Adapter,Entry
from test_security import ENV

class MessageActivityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.registry=self.root/'state.sqlite';self.rollout=self.root/'a.jsonl'
  with sqlite3.connect(self.registry) as db:
   db.execute('CREATE TABLE threads (id TEXT,rollout_path TEXT,archived INTEGER)');db.execute('INSERT INTO threads VALUES (?,?,0)',('a',str(self.rollout)))
  self.rollout.write_text(json.dumps({'type':'session_meta','payload':{'id':'a'}})+'\n')
  self.reader=MessageActivity(self.root,self.registry)
 def tearDown(self):self.tmp.cleanup()
 def add(self,at,role='user',phase=None,type='response_item'):
  event={'timestamp':f'2026-09-22T00:{at}:00Z','type':type,'payload':{'type':'message','role':role,'phase':phase,'content':[]}}
  with self.rollout.open('a') as f:f.write(json.dumps(event)+'\n')
 def current(self):return self.reader.listing(['a'])['a']
 def test_custom_codex_home_uses_latest_registry(self):
  from unittest.mock import patch
  home=self.root/'custom-codex';home.mkdir()
  for name in ['state_2.sqlite','state_12.sqlite','state_invalid.sqlite']:(home/name).touch()
  with patch.dict(os.environ,{'CODEX_HOME':str(home)}):
   self.assertEqual(MessageActivity(self.root)._registry(),(home/'state_12.sqlite').resolve())
 def test_only_sends_and_final_replies_change_time(self):
  self.add('01');first=self.current();self.assertEqual(first['messageKind'],'sent')
  self.add('02','assistant','commentary');self.add('03','developer');os.utime(self.rollout,None)
  self.assertEqual(self.current(),first)
  self.add('04','assistant','final_answer');second=self.current();self.assertEqual(second['messageKind'],'reply');self.assertGreater(second['messageAt'],first['messageAt'])
  self.add('05');self.assertGreater(self.current()['messageAt'],second['messageAt'])
  self.assertEqual(MessageActivity(self.root,self.registry).listing(['a'])['a'],self.current())
 def test_partial_record_is_revisited_and_truncation_rescanned(self):
  self.add('01');first=self.current()
  record=json.dumps({'timestamp':'2026-09-22T00:06:00Z','type':'event_msg','payload':{'type':'user_message','message':'test'}})
  with self.rollout.open('a') as f:f.write(record[:30])
  self.assertEqual(self.current(),first)
  with self.rollout.open('a') as f:f.write(record[30:]+'\n')
  self.assertGreater(self.current()['messageAt'],first['messageAt'])
  self.rollout.write_text(json.dumps({'type':'session_meta','payload':{'id':'a'}})+'\n');self.add('02')
  self.assertLess(self.current()['messageAt'],event_time(record.encode())[0])
 def test_identity_scope_unknown_and_oversized_tool_log(self):
  self.assertEqual(self.reader.listing(['other']),{})
  self.assertEqual(self.current()['messageAt'],0)
  self.add('01');first=self.current()
  with self.rollout.open('ab') as f:f.write(b'{"type":"tool","text":"'+b'x'*(9*1024*1024)+b'"}\n')
  # Cold scan must skip a giant tool line and still find the earlier user event.
  (self.root/'message-activity.sqlite3').unlink();self.assertEqual(self.current(),first)
  with sqlite3.connect(self.registry) as db:db.execute('UPDATE threads SET id=?',('wrong',))
  self.assertEqual(self.reader.listing(['wrong']),{})
 def test_completed_event_needs_a_reply_and_unknown_never_uses_clock(self):
  for payload,want in [({'type':'task_complete'},None),({'type':'task_complete','last_agent_message':'ok'},'reply')]:
   found=event_time(json.dumps({'timestamp':'2026-09-22T00:01:00Z','type':'event_msg','payload':payload}).encode());self.assertEqual(found[1] if found else None,want)

class MessageOrderTests(unittest.TestCase):
 def test_global_message_order_ignores_status_updated_time_and_pin(self):
  import uuid
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);org=root/'org.json';org.write_text(json.dumps({'local-projects':{'p':{'name':'项目','rootPaths':['/work/demo-project']}}}))
   a=Adapter(root,org);threads=[{'id':str(uuid.uuid4()),'name':str(i),'cwd':'/work/demo-project','updatedAt':100000-i} for i in range(40)]
   from adapter import identity_key
   a.preferences.update(identity_key(ENV),threads[0]['id'],'pin',True)
   activity={t['id']:{'messageAt':i+1,'messageKind':'sent' if i%2 else 'reply'} for i,t in enumerate(threads)}
   real=Entry
   try:
    with patch('adapter.Entry',lambda:real(state_dir=root/'entry')),patch.object(a,'catalog',return_value=(threads,True)),patch.object(a.message_activity,'listing',return_value=activity),patch.object(a,'schedule_scan'),patch.object(a,'schedule_live_refresh'):
     before=a.listing(ENV,sort='message',limit=8)
     self.assertEqual([t['threadId'] for t in before['tasks']],[t['id'] for t in reversed(threads[-8:])])
     for t in threads[:8]:t['updatedAt']+=1000000
     after=a.listing(ENV,sort='message',limit=8);self.assertEqual([t['threadId'] for t in before['tasks']],[t['threadId'] for t in after['tasks']])
     activity[threads[8]['id']]={'messageAt':1000,'messageKind':'reply'}
     self.assertEqual(a.listing(ENV,sort='message',limit=8)['tasks'][0]['threadId'],threads[8]['id'])
   finally:a.pool.shutdown()
if __name__=='__main__':unittest.main()
