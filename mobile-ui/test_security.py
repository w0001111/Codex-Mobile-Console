# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch
import auth
from adapter import Adapter,identity_key
from server import create_app
ENV={'project':'test','platform':'weixin','session_key':'test-session','user_id':'owner'}
ORIGIN='https://mobile.example.test'
PASSWORD='Test-only-password-2026!'
class FakeAdapter:
 def __init__(self):self.calls=[]
 def current(self,e):return None
 def listing(self,e,q,c):self.calls.append(e);return {'tasks':[]}
 def action(self,e,n,a,t,r):self.calls.append((e,n,a,t,r));return {'response':'ok'}
 def detail(self,e,n):self.calls.append((e,n));return {'number':n}
class SecurityTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name);self.adapter=FakeAdapter()
  self.app=create_app(self.adapter,self.state,ORIGIN);self.client=self.app.test_client()
  auth.set_password(ENV,PASSWORD,self.state)
 def tearDown(self):self.temp.cleanup()
 def post(self,path,data,**kw):
  if path=='/api/pair':data={'password':PASSWORD,**data}
  headers={'Origin':ORIGIN};headers.update(kw.pop('headers',{}))
  return self.client.post(path,json=data,base_url=ORIGIN,headers=headers,**kw)
 def login(self):
  code=auth.issue(ENV,self.state);r=self.post('/api/pair',{'code':code});self.assertEqual(r.status_code,200);return r.json['csrf']
 def test_every_private_api_needs_session(self):
  for url in ['/api/tasks','/api/tasks/1','/api/session']:self.assertEqual(self.client.get(url,base_url=ORIGIN).status_code,401)
  self.assertEqual(self.post('/api/action',{}).status_code,401);self.assertEqual(self.adapter.calls,[])
 def test_pair_cookie_is_secure_and_one_use(self):
  code=auth.issue(ENV,self.state);r=self.post('/api/pair',{'code':code})
  for flag in ['Secure','HttpOnly','SameSite=Strict']:self.assertIn(flag,r.headers['Set-Cookie'])
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,401)
 def test_pair_expiry_and_rate_limit(self):
  code=auth.issue(ENV,self.state)
  with contextlib.closing(auth.connect(self.state)) as db,db:db.execute('UPDATE pairs SET expires=0')
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,401)
  for _ in range(30):self.post('/api/pair',{'code':'wrong'})
  self.assertEqual(self.post('/api/pair',{'code':'wrong'}).status_code,429)
 def test_pair_concurrent_exchange_only_one_session(self):
  code=auth.issue(ENV,self.state)
  with ThreadPoolExecutor(max_workers=2) as p:results=list(p.map(lambda _:auth.exchange(code,self.state,password=PASSWORD)[1],range(2)))
  self.assertEqual(results.count('ok'),1)
 def test_host_origin_csrf_boundaries(self):
  csrf=self.login();data={'action':'send','number':1,'requestId':str(uuid.uuid4()),'text':'hello'}
  self.assertEqual(self.post('/api/action',data).status_code,403)
  self.assertEqual(self.post('/api/action',data,headers={'X-CSRF-Token':csrf,'Origin':'https://evil.test'}).status_code,403)
  self.assertEqual(self.client.get('/api/tasks',base_url='https://evil.test').status_code,403);self.assertEqual(self.adapter.calls,[])
 def test_browser_identity_ignored_and_target_explicit(self):
  csrf=self.login();data={'action':'send','number':9,'requestId':str(uuid.uuid4()),'text':'hello','identity':{'user_id':'attacker'}}
  r=self.post('/api/action',data,headers={'X-CSRF-Token':csrf});self.assertEqual(r.status_code,200)
  self.assertEqual(self.adapter.calls[0][0],auth.web_identity(ENV));self.assertEqual(self.adapter.calls[0][1],9)
 def test_no_generic_ipc_or_config_proxy_and_traversal(self):
  csrf=self.login()
  for action in ['shell','thread/start','approve','archive','config']:
   self.assertEqual(self.post('/api/action',{'action':action,'number':1,'requestId':str(uuid.uuid4())},headers={'X-CSRF-Token':csrf}).status_code,400)
  for path in ['/api/v1/config','/private/auth.sqlite3','/assets/../../auth.py']:self.assertEqual(self.client.get(path,base_url=ORIGIN).status_code,404)
 def test_logout_revokes_session_and_read_headers(self):
  csrf=self.login();r=self.client.get('/api/tasks',base_url=ORIGIN)
  self.assertEqual(r.headers['Cache-Control'],'no-store');self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy'])
  self.assertEqual(self.post('/api/logout',{},headers={'X-CSRF-Token':csrf}).status_code,200)
  self.assertEqual(self.client.get('/api/tasks',base_url=ORIGIN).status_code,401)
 def test_cross_actor_reference_rejected(self):
  from wechat_entry import target,Entry
  from desktop_ipc import IPCError
  with contextlib.closing(Entry(state_dir=self.state/'catalog')) as entry:
   actor=identity_key(ENV)
   with entry.catalog.db:entry.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(actor,9,str(uuid.uuid4()),'test','/tmp'))
   with self.assertRaises(IPCError):target(entry.catalog.db,identity_key({**ENV,'user_id':'other'}),['T0009'])
 def test_adapter_uses_existing_idempotent_explicit_send(self):
  seen=[]
  class Stub:
   def __init__(self):self.db=self;self.catalog=self
   def handle(self,envelope):seen.append(envelope);return 'test'
   def close(self):pass
   def execute(self,*a):return self
   def fetchone(self):return ('accepted',)
  a=Adapter(self.state)
  with patch('adapter.Entry',Stub),patch('adapter.target',return_value=('test-thread',None,None,None)),patch.object(a,'current',return_value=None):
   rid=str(uuid.uuid4());r=a.action(ENV,9,'send','text',rid)
  self.assertEqual(seen[0]['args'],['send','T0009','text']);self.assertEqual(seen[0]['message_id'],'mobile-'+rid);self.assertEqual(r['delivery'],'accepted');a.pool.shutdown()
 def test_web_identity_is_independent_of_wechat_selection(self):
  from wechat_entry import Entry
  source=identity_key(ENV);web=identity_key(auth.web_identity(ENV))
  self.assertNotEqual(source,web)
  self.assertEqual(auth.web_identity(ENV),auth.web_identity(dict(ENV)))
  with contextlib.closing(Entry(state_dir=self.state/'routes')) as entry:
   with entry.db:
    entry.db.execute('INSERT INTO direct_routes VALUES (?,?)',(source,13))
    entry.db.execute('INSERT INTO direct_routes VALUES (?,?)',(web,12))
   self.assertEqual(entry.selected(source),(13,));self.assertEqual(entry.selected(web),(12,))
 def test_absolute_and_idle_expiry(self):
  self.login()
  with contextlib.closing(auth.connect(self.state)) as db,db:
   db.execute('UPDATE session_activity SET seen=0')
  self.assertEqual(self.client.get('/api/session',base_url=ORIGIN).status_code,401)
  self.login()
  with contextlib.closing(auth.connect(self.state)) as db,db:
   db.execute('UPDATE sessions SET expires=0')
  self.assertEqual(self.client.get('/api/session',base_url=ORIGIN).status_code,401)
 def test_revoke_all_is_owner_scoped_and_revokes_pending_code(self):
  csrf=self.login();other=self.app.test_client()
  otherenv={**ENV,'user_id':'other'};auth.set_password(otherenv,PASSWORD,self.state);code=auth.issue(otherenv,self.state)
  self.assertEqual(other.post('/api/pair',json={'code':code,'password':PASSWORD},base_url=ORIGIN,headers={'Origin':ORIGIN}).status_code,200)
  pending=auth.issue(ENV,self.state)
  self.assertEqual(self.post('/api/logout-all',{},headers={'X-CSRF-Token':csrf}).status_code,200)
  self.assertEqual(self.client.get('/api/session',base_url=ORIGIN).status_code,401)
  self.assertEqual(other.get('/api/session',base_url=ORIGIN).status_code,200)
  self.assertEqual(auth.exchange(pending,self.state,password=PASSWORD)[1],'invalid')
 def test_no_public_account_enrollment_or_totp_routes(self):
  self.login()
  for path in ['/api/login','/api/register','/api/setup-challenge']:
   self.assertEqual(self.post(path,{}).status_code,403)
  csrf=self.login()
  for path in ['/api/login','/api/register','/api/setup-challenge']:
   self.assertEqual(self.post(path,{},headers={'X-CSRF-Token':csrf}).status_code,404)
 def test_audit_does_not_store_login_code(self):
  code=auth.issue(ENV,self.state);self.post('/api/pair',{'code':code})
  with contextlib.closing(auth.connect(self.state)) as db:
   rows=db.execute('SELECT kind,actor FROM security_events').fetchall()
  self.assertTrue(any(r[0]=='login_ok' for r in rows));self.assertNotIn(code,str(rows));self.assertNotIn(PASSWORD,str(rows));self.assertNotIn(ENV['session_key'],str(rows))
 def test_both_credentials_required_without_consuming_code_on_typo(self):
  code=auth.issue(ENV,self.state)
  for data in [{'code':code},{'code':code,'password':'wrong-long-password'},{'password':PASSWORD}]:
   r=self.client.post('/api/pair',json=data,base_url=ORIGIN,headers={'Origin':ORIGIN})
   self.assertEqual(r.status_code,401);self.assertNotIn('Set-Cookie',r.headers)
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,200)
 def test_password_unconfigured_fails_closed(self):
  other={**ENV,'user_id':'unconfigured'};code=auth.issue(other,self.state)
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,401)
 def test_password_guess_limit_survives_new_pair_code(self):
  for _ in range(5):
   code=auth.issue(ENV,self.state)
   self.assertEqual(self.post('/api/pair',{'code':code,'password':'wrong-long-password'}).status_code,401)
  code=auth.issue(ENV,self.state)
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,429)
  with contextlib.closing(auth.connect(self.state)) as db,db:db.execute("UPDATE attempts SET expires=0 WHERE bucket LIKE 'password:%'")
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,200)
 def test_old_code_only_sessions_rejected(self):
  self.login()
  with contextlib.closing(auth.connect(self.state)) as db,db:db.execute('DELETE FROM password_sessions')
  self.assertEqual(self.client.get('/api/tasks',base_url=ORIGIN).status_code,401)
 def test_local_reset_revokes_sessions_and_codes_and_uses_new_secret(self):
  self.login();code=auth.issue(ENV,self.state);new='Another-independent-secret!'
  auth.set_password(ENV,new,self.state)
  self.assertEqual(self.client.get('/api/session',base_url=ORIGIN).status_code,401)
  self.assertEqual(self.post('/api/pair',{'code':code,'password':new}).status_code,401)
  code=auth.issue(ENV,self.state)
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,401)
  self.assertEqual(self.post('/api/pair',{'code':code,'password':new}).status_code,200)
 def test_passwords_are_salted_and_not_plaintext(self):
  other={**ENV,'user_id':'other'};auth.set_password(other,PASSWORD,self.state)
  with contextlib.closing(auth.connect(self.state)) as db:rows=db.execute('SELECT salt,verifier FROM web_passwords').fetchall()
  self.assertEqual(len(rows),2);self.assertNotEqual(rows[0],rows[1]);self.assertNotIn(PASSWORD.encode(),(self.state/'auth.sqlite3').read_bytes())
  for bad in ['', 'short', 'x'*129]:
   with self.assertRaises(ValueError):auth.set_password(ENV,bad,self.state)
 def test_other_owners_password_cannot_unlock_pair(self):
  other={**ENV,'user_id':'other'};auth.set_password(other,'Other-owner-secret!',self.state)
  code=auth.issue(other,self.state)
  self.assertEqual(self.post('/api/pair',{'code':code}).status_code,401)
  self.assertEqual(self.post('/api/pair',{'code':code,'password':'Other-owner-secret!'}).status_code,200)
 def test_no_http_password_reset_even_with_valid_session(self):
  csrf=self.login()
  for path in ['/api/set-password','/api/reset-password','/api/forgot-password']:
   self.assertEqual(self.post(path,{'password':PASSWORD},headers={'X-CSRF-Token':csrf}).status_code,404)

 def test_unset_password_never_locks_or_consumes_code(self):
  other={**ENV,'user_id':'not-enrolled'};code=auth.issue(other,self.state)
  bucket='password:'+identity_key(other)
  with contextlib.closing(auth.connect(self.state)) as db,db:
   db.execute('INSERT INTO attempts VALUES (?,?,?)',(bucket,5,__import__('time').time()+900))
  for _ in range(6):
   r=self.post('/api/pair',{'code':code});self.assertEqual(r.status_code,401);self.assertIn('尚未设置网页登录密码',r.json['error'])
  with contextlib.closing(auth.connect(self.state)) as db:
   self.assertIsNone(db.execute('SELECT 1 FROM attempts WHERE bucket=?',(bucket,)).fetchone())
   self.assertIsNotNone(db.execute('SELECT 1 FROM pairs WHERE digest=?',(auth.digest(code),)).fetchone())
   self.assertEqual(db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0],0)
  auth.set_password(other,PASSWORD,self.state);newcode=auth.issue(other,self.state)
  self.assertEqual(self.post('/api/pair',{'code':newcode}).status_code,200)
 def test_invalid_code_does_not_disclose_password_setup(self):
  r=self.post('/api/pair',{'code':'invalid'})
  self.assertEqual(r.status_code,401);self.assertNotIn('尚未设置网页登录密码',r.json['error'])

 def test_nine_character_password_boundary(self):
  for short in ('12345678','短'*8):
   with self.assertRaises(ValueError):auth.set_password(ENV,short,self.state)
  password='Test-9abc';self.assertEqual(len(password),9)
  auth.set_password(ENV,password,self.state)
  code=auth.issue(ENV,self.state)
  self.assertEqual(self.post('/api/pair',{'code':code,'password':password}).status_code,200)
  code=auth.issue(ENV,self.state)
  self.assertEqual(self.post('/api/pair',{'code':code,'password':'wrongpass'}).status_code,401)

if __name__=='__main__':unittest.main()
