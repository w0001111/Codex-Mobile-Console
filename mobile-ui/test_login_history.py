# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib,json,sqlite3,tempfile,time,unittest
from pathlib import Path
from adapter import identity_key
import auth
from test_security import ENV,PASSWORD,ORIGIN,FakeAdapter
from server import create_app

class LoginHistoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.web=auth.web_identity(ENV)
  auth.set_password(ENV,PASSWORD,self.root)
 def tearDown(self):self.temp.cleanup()
 def login(self,ua='iPhone Safari'):
  code=auth.issue(ENV,self.root);result,status=auth.exchange(code,self.root,password=PASSWORD,user_agent=ua);self.assertEqual(status,'ok');return result[0]
 def events(self,token='',**kw):return auth.login_history(self.web,token,self.root,**kw)
 def test_success_failure_browser_and_logout_persist_without_secrets(self):
  code=auth.issue(ENV,self.root)
  self.assertEqual(auth.exchange(code,self.root,password='incorrect',user_agent='Windows Chrome')[1],'invalid')
  token=self.login();before=self.events(token)
  self.assertEqual(before['summary']['successful'],1);self.assertEqual(before['summary']['failed'],1)
  success=next(e for e in before['events'] if e['kind']=='login_ok');self.assertTrue(success['current']);self.assertEqual(success['browser'],'iPhone · Safari');self.assertEqual(success['sessionStatus'],'active')
  failed=next(e for e in before['events'] if e['kind']=='login_rejected');self.assertEqual(failed['browser'],'Windows · Chrome')
  auth.logout(token,self.root);after=self.events()
  self.assertEqual(after['events'][0]['kind'],'logout');self.assertEqual(after['events'][0]['browser'],'iPhone · Safari')
  self.assertEqual(next(e for e in after['events'] if e['kind']=='login_ok')['sessionStatus'],'ended')
  with contextlib.closing(auth.connect(self.root)) as db:stored=str(db.execute('SELECT * FROM login_history').fetchall())
  for secret in (PASSWORD,'incorrect',code,token,ENV['session_key']):self.assertNotIn(secret,stored)
 def test_throttling_recorded_for_known_account_only(self):
  code=auth.issue(ENV,self.root)
  for _ in range(5):auth.exchange(code,self.root,password='incorrect',user_agent='iPhone Safari')
  self.assertEqual(auth.exchange(code,self.root,password=PASSWORD,user_agent='iPhone Safari')[1],'password_rate')
  result=self.events();self.assertEqual(result['summary']['failed'],5);self.assertEqual(result['summary']['blocked'],1)
  count=result['retainedCount'];auth.exchange('unknown-code',self.root,password='incorrect',user_agent='Chrome');self.assertEqual(self.events()['retainedCount'],count)
 def test_cross_account_records_not_exposed(self):
  token=self.login();other={**ENV,'user_id':'other'};webother=auth.web_identity(other)
  auth.set_password(other,PASSWORD,self.root);code=auth.issue(other,self.root);other_token=auth.exchange(code,self.root,password=PASSWORD,user_agent='Windows Firefox')[0][0]
  mine=self.events(token);theirs=auth.login_history(webother,other_token,self.root)
  self.assertEqual(mine['summary']['successful'],1);self.assertEqual(theirs['summary']['successful'],1)
  self.assertNotIn('Windows',str(mine));self.assertNotIn('iPhone',str(theirs))
 def test_per_account_retention_and_stable_pagination(self):
  actor=identity_key(self.web);otherweb=auth.web_identity({**ENV,'user_id':'other'})
  with contextlib.closing(auth.connect(self.root)) as db,db:
   db.executemany('INSERT INTO login_history(at,actor,kind,label) VALUES (?,?,?,?)',[(time.time(),actor,'login_ok','fixture') for _ in range(1003)])
   auth.audit_in(db,'login_ok',otherweb,user_agent='Firefox');auth.audit_in(db,'logout',self.web)
   for _ in range(1002):auth.audit_in(db,'pair_rejected')
  first=self.events();self.assertEqual(first['retainedCount'],1000);self.assertEqual(len(first['events']),30)
  second=self.events(before=first['nextCursor']);self.assertLess(second['events'][0]['id'],first['events'][-1]['id'])
  self.assertEqual(len(auth.login_history(otherweb,'',self.root)['events']),1)
 def test_existing_events_migrate_once_without_invented_browser(self):
  actor=identity_key(self.web)
  with contextlib.closing(auth.connect(self.root)) as db,db:
   db.execute('DELETE FROM login_history');db.execute('DELETE FROM auth_migrations');db.execute('DELETE FROM security_events')
   db.execute('INSERT INTO security_events(at,kind,actor) VALUES (?,?,?)',(time.time()-100,'login_ok',actor))
   db.execute('INSERT INTO security_events(at,kind,actor) VALUES (?,?,NULL)',(time.time()-90,'login_rejected'))
  first=self.events();second=self.events();self.assertEqual(first['retainedCount'],1);self.assertEqual(second['retainedCount'],1)
  self.assertIn('未记录',first['events'][0]['browser']);self.assertEqual(first['events'][0]['sessionStatus'],'unrecorded')
 def test_individual_revoke_records_target_and_keeps_history(self):
  current=self.login('Macintosh Chrome');other=self.login('iPhone Safari')
  target=next(r for r in auth.logins(self.web,current,self.root) if not r['current'])
  auth.revoke_login(self.web,target['id'],current,self.root)
  result=self.events(current);self.assertEqual(result['events'][0]['kind'],'single_login_revoked');self.assertEqual(result['events'][0]['browser'],'iPhone · Safari')
  self.assertEqual(result['summary']['successful'],2);self.assertIsNotNone(auth.session(current,self.root));self.assertIsNone(auth.session(other,self.root))
 def test_endpoint_requires_login_and_does_not_touch_activity(self):
  app=create_app(FakeAdapter(),self.root,ORIGIN);c=app.test_client()
  self.assertEqual(c.get('/api/login-history',base_url=ORIGIN).status_code,401)
  code=auth.issue(ENV,self.root);r=c.post('/api/pair',json={'code':code,'password':PASSWORD},base_url=ORIGIN,headers={'Origin':ORIGIN,'User-Agent':'iPhone Safari'});self.assertEqual(r.status_code,200)
  with contextlib.closing(auth.connect(self.root)) as db,db:db.execute('UPDATE session_activity SET seen=?',(time.time()-100,))
  with contextlib.closing(auth.connect(self.root)) as db:seen=db.execute('SELECT seen FROM session_activity').fetchone()[0]
  response=c.get('/api/login-history',base_url=ORIGIN);self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'no-store')
  with contextlib.closing(auth.connect(self.root)) as db:self.assertEqual(db.execute('SELECT seen FROM session_activity').fetchone()[0],seen)
  for cursor in ('bad','0','9'*19,'-1'):
   self.assertEqual(c.get('/api/login-history?cursor='+cursor,base_url=ORIGIN).status_code,400)

if __name__=='__main__':unittest.main()
