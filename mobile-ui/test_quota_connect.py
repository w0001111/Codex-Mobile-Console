# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import adapter
from mobile_reads import ConnectIPC
from desktop_ipc import IPCError
from quota import normalize_limits,UsageAPI
from test_security import ENV,ORIGIN,PASSWORD,FakeAdapter
from server import create_app
import auth

class QuotaConnectTests(unittest.TestCase):
 def test_quota_remaining_null_clamping_and_no_secrets(self):
  r=normalize_limits({'accountId':'SECRET','rateLimitsByLimitId':{'codex':{'primary':{'usedPercent':55,'windowDurationMins':10080,'resetsAt':1000},'secondary':{'usedPercent':None},'credits':{'balance':'SECRET'}}}})
  windows=r['buckets'][0]['windows'];self.assertEqual(windows[0]['remainingPercent'],45);self.assertIsNone(windows[1]['remainingPercent']);self.assertNotIn('SECRET',str(r))
  for used,want in [(-5,100),(105,0),(float('nan'),None),(True,None)]:
   r=normalize_limits({'rateLimits':{'primary':{'usedPercent':used}}});self.assertEqual(r['buckets'][0]['windows'][0]['remainingPercent'],want)
 def test_quota_prefer_multi_bucket_and_missing_is_unavailable(self):
  self.assertFalse(normalize_limits({})['available'])
  r=normalize_limits({'rateLimits':{'primary':{'usedPercent':100}},'rateLimitsByLimitId':{'x':{'primary':{'usedPercent':25}}}})
  self.assertEqual(r['buckets'][0]['windows'][0]['remainingPercent'],75)
  with self.assertRaises(ValueError):UsageAPI().request('account/rateLimitResetCredit/consume',{})
 def test_quota_endpoint_requires_login_and_does_not_expose_identity(self):
  class F(FakeAdapter):
   def quota(self):return {'buckets':[],'available':False}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);app=create_app(F(),root,ORIGIN);client=app.test_client();self.assertEqual(client.get('/api/quota',base_url=ORIGIN).status_code,401)
   auth.set_password(ENV,PASSWORD,root);code=auth.issue(ENV,root)
   client.post('/api/pair',json={'code':code,'password':PASSWORD},base_url=ORIGIN,headers={'Origin':ORIGIN})
   self.assertEqual(client.get('/api/quota',base_url=ORIGIN).json,{'buckets':[],'available':False})
 def test_explicit_connect_opens_only_requested_thread_and_never_starts_turn(self):
  tid=str(uuid.uuid4());ipc=ConnectIPC();state={'id':tid,'hostId':'local'}
  with patch('subprocess.run') as opened,patch.object(ipc,'owner',side_effect=[IPCError('no-client-found'),'owner']),patch.object(ipc,'snapshot',return_value=state):
   self.assertEqual(ipc.connect_thread(tid,True),('owner',state))
   self.assertEqual(opened.call_args.args[0],['/usr/bin/open','-g','codex://threads/'+tid])
  with self.assertRaises(IPCError):ipc.request('thread-follower-start-turn',{})
  with patch('subprocess.run') as opened:
   with self.assertRaises(ValueError):ipc.connect_thread('not-a-thread',True)
   opened.assert_not_called()
 def test_connect_without_open_does_not_navigate(self):
  tid=str(uuid.uuid4());ipc=ConnectIPC()
  with patch('subprocess.run') as opened,patch.object(ipc,'owner',return_value='owner'),patch.object(ipc,'snapshot',return_value={'id':tid}):
   ipc.connect_thread(tid,False);opened.assert_not_called()

if __name__=='__main__':unittest.main()
