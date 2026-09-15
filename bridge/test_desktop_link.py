# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from desktop_ipc import DesktopIPC, IPCError, ensure_idle, latest_result
from wechat_entry import Entry, identity

TID='699a6a3b-9538-484b-8f4f-a4fa3b47740f'
OTHER='8d5f8cb7-d7b1-4143-8d4c-326a66fd93ca'


class FakeIPC:
    def __init__(self):
        self.state={'id':TID,'hostId':'local','threadRuntimeStatus':{'type':'idle'},'turns':[],'requests':[]}
        self.calls=[]
        self.error=None
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def connect_thread(self,tid,open_if_needed=False):return 'owner',self.state
    def start(self,tid,owner,prompt,mid):
        self.calls.append((tid,owner,prompt,mid))
        if self.error:raise self.error
        return {'result':{'result':{'turn':{'id':'test-turn'}}}}


class EntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.ipc=FakeIPC()
        self.entry=Entry(self.tmp.name,ipc_factory=lambda:self.ipc,check=lambda tid:None)
        self.env=dict(version=1,project='project',platform='weixin',session_key='chat',user_id='admin',message_id='m1',args=['send','T0009','hello'])
        self.actor=identity(self.env)[0]
        with self.entry.catalog.db:
            self.entry.catalog.db.execute('INSERT INTO refs VALUES (?,?,?,?,?)',(self.actor,9,TID,'test','/tmp'))
            self.entry.catalog.db.execute('INSERT INTO choices VALUES (?,?)',(self.actor,9))
    def tearDown(self):self.entry.close();self.tmp.cleanup()
    def test_exact_target_and_no_new_thread(self):
        self.assertIn('已送入',self.entry.handle(self.env));self.assertEqual(self.ipc.calls[0][0],TID)
    def test_same_message_runs_once(self):
        a=self.entry.handle(self.env);b=self.entry.handle(self.env)
        self.assertEqual(a,b);self.assertEqual(len(self.ipc.calls),1)
    def test_changed_content_same_id_rejected(self):
        self.entry.handle(self.env);self.env['args'][-1]='changed'
        self.assertIn('拒绝',self.entry.handle(self.env));self.assertEqual(len(self.ipc.calls),1)
    def test_duplicate_survives_process_restart(self):
        self.entry.handle(self.env);self.entry.close()
        self.entry=Entry(self.tmp.name,ipc_factory=lambda:self.ipc,check=lambda tid:None)
        self.entry.handle(self.env);self.assertEqual(len(self.ipc.calls),1)
    def test_selected_target_is_frozen_for_duplicate(self):
        self.env['args']=['send','hello'];self.entry.handle(self.env)
        with self.entry.catalog.db:
            self.entry.catalog.db.execute('UPDATE refs SET thread_id=? WHERE actor=?',(OTHER,self.actor))
        self.entry.handle(self.env);self.assertEqual(len(self.ipc.calls),1);self.assertEqual(self.ipc.calls[0][0],TID)
    def test_cross_actor_ref_rejected(self):
        self.env['user_id']='someone-else'
        with self.assertRaises(IPCError):self.entry.handle(self.env)
        self.assertEqual(self.ipc.calls,[])
    def test_wrong_platform_rejected(self):
        self.env['platform']='feishu'
        with self.assertRaises(IPCError):self.entry.handle(self.env)
    def test_missing_identity(self):
        del self.env['message_id']
        with self.assertRaises(IPCError):self.entry.handle(self.env)
    def test_busy_rejected_without_claim(self):
        self.ipc.state['threadRuntimeStatus']={'type':'active'}
        self.assertIn('未发送',self.entry.handle(self.env));self.assertEqual(self.ipc.calls,[])
        self.assertEqual(self.entry.db.execute('SELECT count(*) FROM sends').fetchone()[0],0)
    def test_approval_pending(self):
        self.ipc.state['requests']=[{'requestId':'approval'}]
        self.assertIn('等待确认',self.entry.handle(self.env));self.assertEqual(self.ipc.calls,[])
    def test_unknown_status(self):
        self.ipc.state['threadRuntimeStatus']={}
        self.assertIn('未发送',self.entry.handle(self.env));self.assertEqual(self.ipc.calls,[])
    def test_archived_preflight(self):
        def fail(tid):raise IPCError('archived')
        self.entry.check=fail
        with self.assertRaises(IPCError):self.entry.handle(self.env)
        self.assertEqual(self.ipc.calls,[])
    def test_uncertain_delivery_never_retried(self):
        self.ipc.error=TimeoutError('lost ack')
        self.assertIn('待核实',self.entry.handle(self.env));self.entry.handle(self.env)
        self.assertEqual(len(self.ipc.calls),1)
    def test_crash_after_claim_never_retried(self):
        actor,args,digest=identity(self.env)
        with self.entry.db:
            self.entry.db.execute('INSERT INTO sends VALUES (?,?,?,?,?,?,?,?)',(actor,'m1',digest,TID,'dispatching','',None,0))
        self.assertIn('不会自动重发',self.entry.handle(self.env));self.assertEqual(self.ipc.calls,[])
    def test_shell_characters_are_plain_text(self):
        self.env['args']=['send','T0009','$(touch /tmp/no) `id` ; hello\nworld']
        self.entry.handle(self.env);self.assertEqual(self.ipc.calls[0][2],self.env['args'][2])
    def test_empty_prompt(self):
        self.env['args']=['send','T0009']
        with self.assertRaises(IPCError):self.entry.handle(self.env)
    def test_database_private(self):
        self.assertEqual((Path(self.tmp.name)/'desktop-sends.sqlite3').stat().st_mode&0o777,0o600)


class ProtocolTests(unittest.TestCase):
    def test_start_preserves_settings(self):
        c=DesktopIPC()
        with patch.object(c,'request',return_value={}) as call:
            c.start(TID,'owner','hello','unique-id')
            method,params,target=call.call_args.args
            self.assertEqual(method,'thread-follower-start-turn');self.assertEqual(target,'owner')
            self.assertEqual(params['conversationId'],TID)
            self.assertEqual(params['turnStart']['request']['threadId'],TID)
            self.assertEqual(set(params['turnStart']['request']),{'threadId','input','clientUserMessageId'})
            self.assertTrue(params['turnStart']['context']['inheritThreadSettings'])
    def test_no_resume_or_approval_capability(self):
        c=DesktopIPC()
        for method in ['thread/resume','thread/start','thread-follower-command-approval-decision']:
            with self.assertRaises(IPCError):c.request(method,{})
    def test_canonical_history_result(self):
        s={'turnHistory':{'kind':'canonical','history':{'entitiesByKey':{'x':{'turnId':'x','turnStartedAtMs':2,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'remembered'}]}}}}}
        turn,text=latest_result(s);self.assertEqual(text,'remembered');self.assertEqual(turn['turnId'],'x')
    def test_old_output_not_returned_for_new_running_turn(self):
        s={'turns':[{'turnId':'old','turnStartedAtMs':1,'items':[{'type':'agentMessage','text':'old'}]}, {'turnId':'new','turnStartedAtMs':2,'items':[]}]}
        turn,text=latest_result(s);self.assertEqual(turn['turnId'],'new');self.assertEqual(text,'')
    def test_in_progress_turn_overrides_idle_status(self):
        with self.assertRaises(IPCError):ensure_idle({'threadRuntimeStatus':{'type':'idle'},'turns':[{'status':'inProgress'}]})


if __name__=='__main__':unittest.main()
