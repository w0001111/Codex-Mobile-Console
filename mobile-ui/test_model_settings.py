# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib,copy,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
from adapter import Adapter,Entry,identity_key
from model_settings import current_settings,turn_settings,ModelCatalog,SettingsIPC,SettingsStore,SettingsError,apply_settings
from desktop_ipc import IPCError
from test_security import SecurityTests,ORIGIN

def state():
 return {'id':'test-thread','cwd':'/work','modelProvider':'openai','latestModel':'model-a','latestReasoningEffort':'high','latestCollaborationMode':{'mode':'plan','settings':{'model':'model-a','reasoning_effort':'high','developer_instructions':'keep'}},'latestThreadSettings':{'model':'model-a','effort':'high','cwd':'/work','approvalPolicy':'on-request','sandboxPolicy':{'type':'workspace-write'},'collaborationMode':{'mode':'plan','settings':{'model':'model-a','reasoning_effort':'high','developer_instructions':'keep'}}},'currentPermissions':{'policy':'unchanged'},'threadRuntimeStatus':{'type':'idle'},'turns':[]}

class ModelSettingsTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=SettingsStore(Path(self.temp.name));self.state=state();self.calls=[]
 def tearDown(self):self.temp.cleanup()
 def factory(self,fail=False,tamper=False):
  outer=self
  class Fake:
   def __init__(self,**kw):pass
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def connect_thread(self,tid,open_if_needed=False):outer.calls.append(('connect',tid,open_if_needed));return 'owner',copy.deepcopy(outer.state)
   def update_model(self,tid,owner,model,effort):
    outer.calls.append(('update',tid,model,effort))
    if fail:raise IPCError('timeout')
    outer.state['latestThreadSettings'].update(model=model,effort=effort)
    if tamper:outer.state['cwd']='/other'
   def snapshot(self,tid,owner):return copy.deepcopy(outer.state)
  return Fake
 def apply(self,rid=None,expected=None,**kw):return apply_settings('test-thread','actor',rid or str(uuid.uuid4()),'model-b','low',expected or current_settings(self.state)['revision'],self.store,ipc_factory=self.factory(**kw))
 def test_current_settings_and_historical_inference_not_confused(self):
  current=current_settings(self.state);self.assertEqual(current['model'],'model-a');self.assertEqual(current['effort'],'high');self.assertEqual(len(current['revision']),64)
  t={'params':{'model':'model-a','effort':'high'},'permissionParamsSource':'inferred'};self.assertIsNone(turn_settings(t))
  del t['permissionParamsSource'];self.assertEqual(turn_settings(t)['model'],'model-a');self.assertIsNone(turn_settings({'items':[]}))
  self.state['latestThreadSettings']['effort']=None;self.assertIsNone(current_settings(self.state)['effort'])
 def test_narrow_protocol_only_sends_model_and_effort(self):
  ipc=SettingsIPC()
  with patch.object(ipc,'request',return_value={'ok':True}) as request:
   ipc.update_model('tid','owner','model-b','low')
   request.assert_called_once_with('thread-follower-update-thread-settings',{'conversationId':'tid','threadSettings':{'model':'model-b','effort':'low'}},'owner')
  self.assertNotIn('thread-follower-start-turn',ipc.VERSIONS)
  for method in ('thread/start','thread/resume','thread-follower-command-approval-decision'):
   with self.assertRaises(IPCError):ipc.request(method,{})
 def test_idle_settings_confirmed_and_duplicate_never_reapplied(self):
  rid=str(uuid.uuid4());expected=current_settings(self.state)['revision'];r=self.apply(rid,expected);self.assertEqual(r['status'],'confirmed');self.assertEqual(r['settings']['model'],'model-b')
  self.assertEqual(self.state['latestThreadSettings']['approvalPolicy'],'on-request');self.assertEqual(self.state['currentPermissions'],{'policy':'unchanged'})
  again=self.apply(rid,expected);self.assertTrue(again['replayed']);self.assertEqual(len([c for c in self.calls if c[0]=='update']),1)
 def test_running_waiting_and_stale_revision_rejected_before_write(self):
  for kind in ('running','waiting','stale'):
   self.state=state()
   if kind=='running':self.state['threadRuntimeStatus']['type']='active'
   if kind=='waiting':self.state['requests']=[{'id':'approval'}]
   with self.assertRaises(SettingsError):self.apply(expected='0'*64 if kind=='stale' else None)
  self.assertFalse(any(c[0]=='update' for c in self.calls))
 def test_uncertain_write_never_claims_success_or_retries(self):
  rid=str(uuid.uuid4());expected=current_settings(self.state)['revision'];self.assertEqual(self.apply(rid,expected,fail=True)['status'],'uncertain')
  self.assertTrue(self.apply(rid,expected)['replayed']);self.assertEqual(len([c for c in self.calls if c[0]=='update']),1)
  self.assertEqual(self.apply(tamper=True)['status'],'uncertain')
 def test_request_is_bound_to_actor_thread_and_payload(self):
  self.store.save('a','t','r','d',{'status':'uncertain'})
  self.assertIsNone(self.store.previous('b','t','r','d'))
  for tid,digest in [('other','d'),('t','changed')]:
   with self.assertRaises(SettingsError):self.store.previous('a',tid,'r',digest)
 def test_models_are_live_filtered_and_efforts_validated(self):
  rows={'data':[{'model':'model-a','displayName':'A','supportedReasoningEfforts':[{'reasoningEffort':'low'},{'reasoningEffort':'high'}],'defaultReasoningEffort':'low'}, {'model':'hidden','hidden':True,'supportedReasoningEfforts':[{'reasoningEffort':'high'}]}]}
  class API:
   def request(self,*args):return rows
   def close(self):pass
  catalog=ModelCatalog()
  with patch('model_settings.ModelAPI',API):
   self.assertEqual([r['id'] for r in catalog.listing()],['model-a']);catalog.validate('model-a','high')
   for model,effort in [('model-a','ultra'),('hidden','high'),('invented','low')]:
    with self.assertRaises(SettingsError):catalog.validate(model,effort)
 def test_cross_actor_task_reference_blocks_model_write(self):
  from test_security import ENV
  root=Path(self.temp.name);a=Adapter(root);tid=str(uuid.uuid4());actor=identity_key(ENV)
  with contextlib.closing(Entry(state_dir=root/'entry')) as entry:
   with entry.catalog.db:entry.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(actor,1,tid,'fixture','/work'))
  realEntry=Entry
  with patch('adapter.Entry',lambda:realEntry(state_dir=root/'entry')),patch.object(a.models,'validate') as validate:
   with self.assertRaises(IPCError):a.set_model({**ENV,'user_id':'other'},1,'model-b','low','a'*64,str(uuid.uuid4()))
   validate.assert_not_called()
  a.pool.shutdown()

class ModelEndpointTests(SecurityTests):
 def test_model_routes_require_auth_csrf_and_reject_extra_settings(self):
  data={'model':'model-a','effort':'low','expectedRevision':'a'*64,'requestId':str(uuid.uuid4())}
  self.assertEqual(self.client.get('/api/models',base_url=ORIGIN).status_code,401)
  self.assertEqual(self.post('/api/tasks/1/model-settings',data).status_code,401)
  csrf=self.login();self.assertEqual(self.post('/api/tasks/1/model-settings',data).status_code,403)
  for extra in ({'approvalPolicy':'never'},{'activeTurnId':'turn'},{'cwd':'/'}):
   self.assertEqual(self.post('/api/tasks/1/model-settings',{**data,**extra},headers={'X-CSRF-Token':csrf}).status_code,400)
 def test_model_endpoint_identity_is_server_bound(self):
  csrf=self.login();calls=[]
  self.adapter.set_model=lambda *args:calls.append(args) or {'status':'confirmed'}
  data={'model':'model-a','effort':'low','expectedRevision':'a'*64,'requestId':str(uuid.uuid4())}
  response=self.post('/api/tasks/9/model-settings',data,headers={'X-CSRF-Token':csrf})
  self.assertEqual(response.status_code,200);self.assertTrue(calls[0][0]['web_account']);self.assertEqual(calls[0][1],9)
