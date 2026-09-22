# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import copy,contextlib,unittest
from unittest.mock import patch
from adapter import Adapter
from desktop_ipc import IPCError,ensure_can_send,ensure_idle

class FailedResumeTests(unittest.TestCase):
 def state(self,runtime='systemError',status='failed'):
  return {'threadRuntimeStatus':{'type':runtime},'turns':[{'turnId':'failed-turn','turnStartedAtMs':10,'status':status,'items':[]}],'requests':[]}
 def test_terminal_error_accepts_new_message_without_mutating_state(self):
  for status in ['failed','interrupted']:
   state=self.state(status=status);before=copy.deepcopy(state);ensure_can_send(state);self.assertEqual(state,before)
   with self.assertRaises(IPCError):ensure_idle(state)
 def test_recovery_does_not_allow_running_unknown_unfinished_or_empty(self):
  states=[self.state(runtime=r) for r in ['active','unknown','notLoaded']]+[self.state(status=s) for s in ['completed','inProgress',None]]
  states.append({'threadRuntimeStatus':{'type':'systemError'},'turns':[]})
  state=self.state();state['turns'].insert(0,{'turnId':'other','turnStartedAtMs':1,'status':'inProgress'});states.append(state)
  for state in states:
   with self.subTest(state=state),self.assertRaises(IPCError):ensure_can_send(state)
 def test_approval_and_goal_confirmation_still_block(self):
  for field in ['requests','threadGoalResumeConfirmation']:
   state=self.state();state[field]=[{'pending':True}]
   with self.assertRaisesRegex(IPCError,'thread-needs-user-input'):ensure_can_send(state)
 def test_idle_terminal_turn_remains_sendable(self):
  for status in ['completed','failed','interrupted']:ensure_can_send(self.state('idle',status))
 def test_canonical_failed_history_is_supported(self):
  state=self.state();state['turnHistory']={'kind':'canonical','history':{'entitiesByKey':{'t':state.pop('turns')[0]}}};ensure_can_send(state)


class FailedResumeIntegrationTests(unittest.TestCase):
 def test_observer_enables_only_new_message_and_preserves_failed_status(self):
  import tempfile
  from pathlib import Path
  state=FailedResumeTests().state()
  class IPC:
   def __init__(self,**kw):pass
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def owner(self,tid):return 'owner'
   def snapshot(self,*a):return state
  with tempfile.TemporaryDirectory() as folder:
   a=Adapter(Path(folder))
   try:
    with patch('adapter.check_saved'),patch('adapter.StatusIPC',IPC):result=a.observe('test')
    self.assertTrue(result['canSend']);self.assertFalse(result['canChangeModel']);self.assertEqual(result['status'],'error');self.assertEqual(result['statusLabel'],'上轮失败，可继续')
    state['requests']=[{'id':'approval'}]
    with patch('adapter.check_saved'),patch('adapter.StatusIPC',IPC):result=a.observe('test')
    self.assertFalse(result['canSend']);self.assertEqual(result['status'],'needs_input')
   finally:a.pool.shutdown()
 def test_explicit_new_message_reaches_original_thread_once(self):
  from test_desktop_link import EntryTests,TID
  fixture=EntryTests();fixture.setUp()
  try:
   fixture.ipc.state.update(FailedResumeTests().state())
   fixture.env['args'][-1]='请根据失败原因继续';fixture.env['message_id']='new-after-failure'
   result=fixture.entry.handle(fixture.env);self.assertIn('已送入',result)
   fixture.entry.handle(fixture.env)
   self.assertEqual(len(fixture.ipc.calls),1);self.assertEqual(fixture.ipc.calls[0][0],TID);self.assertEqual(fixture.ipc.calls[0][2],'请根据失败原因继续')
  finally:fixture.tearDown()

if __name__=='__main__':unittest.main()
