# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib,json,os,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import auth
from adapter import Adapter,Entry,identity_key
from artifacts import ArtifactStore,allowed_path,output_references
from delivery import DeliveryStore,resolve,turn_receipts
from server import create_app,COOKIE
from test_security import ENV,ORIGIN,PASSWORD,FakeAdapter

class Batch2Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='batch2-fixture-',dir=Path(__file__).parent)
  self.root=Path(self.temp.name);self.state=self.root/'state';self.project=self.root/'project';self.project.mkdir()
 def tearDown(self):self.temp.cleanup()
 def output(self,path,kind='output'):
  return {'id':'turn1','status':'completed','items':[{'id':'message1','type':'agentMessage','phase':'final_answer','text':':codex-file-citation{path='+json.dumps(str(path))+' purpose="'+kind+'"}'}]}
 def test_receipt_exact_turn_and_client_no_unrelated_completion(self):
  rid=str(uuid.uuid4());r={'requestId':rid,'phase':'uncertain','createdAt':0}
  turns=[{'id':'unrelated','status':'completed','hasReply':True}]
  self.assertEqual(resolve('a',r,{'status':'accepted','turnId':'wanted'},turns)['phase'],'accepted')
  self.assertEqual(resolve('a',r,None,turns)['phase'],'uncertain')
  turns.append({'id':'wanted','status':'inProgress','hasReply':False})
  self.assertEqual(resolve('a',r,{'status':'accepted','turnId':'wanted'},turns)['phase'],'executing')
  turns[-1].update(status='completed',hasReply=True)
  self.assertEqual(resolve('a',r,{'status':'accepted','turnId':'wanted'},turns)['phase'],'completed')
  cid=str(uuid.uuid5(uuid.NAMESPACE_URL,'a\0mobile-'+rid));turns[-1]['clientIds']=[cid]
  self.assertEqual(resolve('a',r,None,turns)['phase'],'completed')
  self.assertEqual(resolve('b',r,None,turns)['phase'],'uncertain')
 def test_commentary_is_not_final_reply_and_timeout(self):
  turns=turn_receipts([{'id':'t','status':'completed','items':[{'type':'agentMessage','phase':'commentary','text':'still working'}]}])
  r={'requestId':str(uuid.uuid4()),'phase':'sending','createdAt':0}
  self.assertEqual(resolve('a',r,None,[],now=46)['phase'],'uncertain')
  self.assertEqual(resolve('a',r,{'status':'accepted','turnId':'t'},turns)['phase'],'ended')
  for status in ('failed','interrupted'):
   turns[0]['status']=status;self.assertEqual(resolve('a',r,{'turnId':'t'},turns)['phase'],status)
 def test_receipts_scoped_and_duplicate_request_cannot_move(self):
  s=DeliveryStore(self.state);s.begin('a','t','r');s.phase('a','t','r','accepted');s.begin('a','t','r')
  self.assertEqual(s.records('a','t')[0]['phase'],'accepted');self.assertEqual(s.records('b','t'),[])
  with self.assertRaises(ValueError):s.begin('a','other','r')
 def test_output_proof_required_inputs_links_and_unfinished_ignored(self):
  p=self.project/'report.pdf';p.write_bytes(b'%PDF-fixture')
  self.assertEqual(output_references(self.output(p,'input'),str(self.project)),[])
  t=self.output(p);t['items'][0]['text']=f'[report]({p})'
  self.assertEqual(output_references(t,str(self.project)),[])
  t['items'].append({'type':'fileChange','status':'completed','changes':[{'path':str(p),'kind':{'type':'add'}}]})
  self.assertEqual(len(output_references(t,str(self.project))),1)
  t['status']='inProgress';self.assertEqual(output_references(t,str(self.project)),[])
 def test_artifact_snapshot_immutable_and_owner_thread_isolated(self):
  p=self.project/'report.pdf';p.write_bytes(b'%PDF-first');s=ArtifactStore(self.state)
  self.assertEqual(s.discover('a','t',str(self.project),[self.output(p)]),0)
  aid=s.listing('a','t')[0]['id'];p.write_bytes(b'%PDF-changed');s.discover('a','t',str(self.project),[self.output(p)])
  self.assertEqual(s.read('a','t',aid)[1],b'%PDF-first');self.assertEqual(len(s.listing('a','t')),1)
  for actor,tid in [('b','t'),('a','other')]:
   with self.assertRaises(FileNotFoundError):s.read(actor,tid,aid)
  (self.state/'artifact-cache'/aid).write_bytes(b'tampered')
  with self.assertRaises(ValueError):s.read('a','t',aid)
 def test_artifact_path_symlink_hardlink_and_size_rejected(self):
  s=ArtifactStore(self.state);p=self.project/'good.txt';p.write_text('safe')
  for path in [self.root/'outside.pdf',self.project/'../outside.pdf',self.project/'.env.txt',self.project/'credentials.txt',self.project/'x.html']:
   with self.assertRaises(ValueError):allowed_path(str(path),str(self.project))
  link=self.project/'link.txt';link.symlink_to(p)
  hard=self.project/'hard.txt';os.link(p,hard)
  for path in (link,hard):self.assertEqual(s.discover('a','t',str(self.project),[self.output(path)]),1)
  hard.unlink();link.unlink()
  with patch('artifacts.MAX_FILE',2):self.assertEqual(s.discover('a','t',str(self.project),[self.output(p)]),1)
  with patch('artifacts.MAX_CACHE',2):self.assertEqual(s.discover('a','t',str(self.project),[self.output(p)]),1)
 def login(self,app,env=ENV,ua='iPhone Safari'):
  auth.set_password(env,PASSWORD,self.state) if not getattr(self,'password_set',False) else None
  self.password_set=True;client=app.test_client();code=auth.issue(env,self.state)
  r=client.post('/api/pair',json={'code':code,'password':PASSWORD},base_url=ORIGIN,headers={'Origin':ORIGIN,'User-Agent':ua})
  self.assertEqual(r.status_code,200);return client,r.json['csrf']
 def test_login_list_and_single_revoke_preserve_other_logins(self):
  app=create_app(FakeAdapter(),self.state,ORIGIN);a,csrf=self.login(app);b,_=self.login(app,ua='Macintosh Chrome')
  rows=a.get('/api/logins',base_url=ORIGIN).json['logins'];self.assertEqual(len(rows),2);self.assertTrue(rows[0]['current']);self.assertEqual(rows[0]['label'],'iPhone · Safari')
  self.assertNotIn('digest',str(rows));self.assertNotIn('csrf',str(rows))
  other=next(r for r in rows if not r['current'])
  url='/api/logins/'+other['id']+'/revoke'
  self.assertEqual(a.post(url,json={},base_url=ORIGIN,headers={'Origin':ORIGIN}).status_code,403)
  self.assertEqual(a.post(url,json={},base_url=ORIGIN,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf}).status_code,200)
  self.assertEqual(b.get('/api/session',base_url=ORIGIN).status_code,401);self.assertEqual(a.get('/api/session',base_url=ORIGIN).status_code,200)
  mine=rows[0]['id'];r=a.post('/api/logins/'+mine+'/revoke',json={},base_url=ORIGIN,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf});self.assertTrue(r.json['current']);self.assertEqual(a.get('/api/logins',base_url=ORIGIN).status_code,401)
 def test_cross_owner_revoke_denied_and_legacy_metadata_migrated(self):
  app=create_app(FakeAdapter(),self.state,ORIGIN);a,csrf=self.login(app);other={**ENV,'user_id':'different'};auth.set_password(other,PASSWORD,self.state);b,_=self.login(app,other)
  with contextlib.closing(auth.connect(self.state)) as db,db:db.execute('DELETE FROM session_metadata')
  mine=a.get('/api/logins',base_url=ORIGIN).json['logins'];theirs=b.get('/api/logins',base_url=ORIGIN).json['logins'];self.assertEqual(len(mine),1);self.assertEqual(mine[0]['label'],'升级前的浏览器登录')
  r=a.post('/api/logins/'+theirs[0]['id']+'/revoke',json={},base_url=ORIGIN,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf});self.assertEqual(r.status_code,404);self.assertEqual(b.get('/api/session',base_url=ORIGIN).status_code,200)
 def test_file_routes_auth_attachment_preview_and_revocation(self):
  s=ArtifactStore(self.state);p=self.project/'report.pdf';p.write_bytes(b'%PDF-report');s.discover(identity_key(auth.web_identity(ENV)),'t',str(self.project),[self.output(p)])
  aid=s.listing(identity_key(auth.web_identity(ENV)),'t')[0]['id']
  class Facade(FakeAdapter):
   def file(self,env,n,i):return s.read(identity_key(env),'t' if n==1 else 'other',i)
  app=create_app(Facade(),self.state,ORIGIN);guest=app.test_client();url='/api/tasks/1/files/'+aid
  for path in [url,'/api/tasks/1/files','/api/tasks/1/deliveries','/api/logins']:self.assertEqual(guest.get(path,base_url=ORIGIN).status_code,401)
  a,csrf=self.login(app);r=a.get(url,base_url=ORIGIN);self.assertEqual(r.data,b'%PDF-report');self.assertIn('attachment',r.headers['Content-Disposition']);self.assertEqual(r.headers['Cache-Control'],'no-store')
  self.assertEqual(a.get(url+'/preview',base_url=ORIGIN).status_code,415);self.assertEqual(a.get(url.replace('/1/','/2/'),base_url=ORIGIN).status_code,404)
  a.post('/api/logout',json={},base_url=ORIGIN,headers={'Origin':ORIGIN,'X-CSRF-Token':csrf});self.assertEqual(a.get(url,base_url=ORIGIN).status_code,401)
 def test_adapter_receipt_reconciles_persisted_ack_exactly(self):
  adapter=Adapter(self.state);rid=str(uuid.uuid4());tid=str(uuid.uuid4());actor=identity_key(ENV)
  with contextlib.closing(Entry(state_dir=self.root/'entry')) as e:
   with e.catalog.db:e.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(actor,1,tid,'test',str(self.project)))
   with e.db:e.db.execute('INSERT INTO sends VALUES (?,?,?,?,?,?,?,?)',(actor,'mobile-'+rid,'digest',tid,'accepted','accepted','right-turn',time.time()))
  adapter.receipts.begin(actor,tid,rid);adapter.cache[tid]={'live':True,'turnReceipts':[{'id':'other-turn','status':'completed','hasReply':True}]}
  realEntry=Entry
  with patch('adapter.Entry',lambda:realEntry(state_dir=self.root/'entry')):
   self.assertEqual(adapter.deliveries(ENV,1,refresh=False)['deliveries'][0]['phase'],'accepted')
   adapter.cache[tid]['turnReceipts'].append({'id':'right-turn','status':'completed','hasReply':True})
   self.assertEqual(adapter.deliveries(ENV,1,refresh=False)['deliveries'][0]['phase'],'completed')
  adapter.pool.shutdown()

if __name__=='__main__':unittest.main()
