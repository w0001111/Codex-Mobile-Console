# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import unittest
from test_desktop_link import EntryTests, TID, OTHER
from wechat_entry import describe

class MenuTests(EntryTests):
    def command(self,*args,mid=None):
        return self.entry.handle({**self.env,'message_id':mid or 'cmd-'+'-'.join(args),'args':list(args)})
    def route(self,text='hello',mid='plain1',**extra):
        return self.entry.route_message({**self.env,'message_id':mid,'args':[text],**extra})
    def test_no_implicit_migration_of_old_readonly_selection(self):
        self.assertFalse(self.route()['handled']);self.assertEqual(self.ipc.calls,[])
    def test_switch_number_then_plain_exact_text(self):
        self.assertIn('已切换',self.command('select','9'))
        text='T0009 is literal text\n$(touch /tmp/no)'
        self.assertTrue(self.route(text)['handled']);self.assertEqual(self.ipc.calls[0][2],text)
    def test_exit_restores_default_and_duplicate_send_stays_handled(self):
        self.command('select','9');first=self.route()
        self.assertIn('已退出',self.command('leave'))
        self.assertFalse(self.route(mid='different')['handled'])
        self.assertEqual(first,self.route());self.assertEqual(len(self.ipc.calls),1)
    def test_duplicate_switch_does_not_reenter_after_exit(self):
        self.command('select','9');self.command('leave');self.command('select','9')
        self.assertFalse(self.route()['handled'])
    def test_media_rejected_and_never_falls_back(self):
        self.command('select','9');r=self.route(has_attachments=True)
        self.assertTrue(r['handled']);self.assertIn('附件未发送',r['response']);self.assertEqual(self.ipc.calls,[])
    def test_busy_direct_message_is_not_fallback(self):
        self.command('select','9');self.ipc.state['threadRuntimeStatus']={'type':'active'}
        r=self.route();self.assertTrue(r['handled']);self.assertIn('未发送',r['response'])
    def test_number_not_cross_actor(self):
        self.command('select','9')
        self.assertFalse(self.route(user_id='different')['handled'])
    def test_name_does_not_rename_desktop(self):
        self.assertIn('示例任务',self.command('name','9','示例任务'))
        self.assertIn('示例任务',self.command('select','9'));self.assertEqual(self.ipc.calls,[])
    def test_directory_preserves_number_and_marks_selected(self):
        self.command('select','9')
        self.entry.api.request=lambda *a:{'data':[{'id':TID,'name':'Test','cwd':'/tmp/project'},{'id':OTHER,'name':'Other'}],'nextCursor':'next'}
        result=self.command('list')
        self.assertIn('▶ T0009',result);self.assertIn('T0010',result);self.assertIn('下一页',result)
    def test_menu_explains_current_destination(self):
        self.assertIn('原消息平台助手',self.command('help'))
        self.command('select','9');self.assertIn('当前直聊目标',self.command('help'))
    def test_progress_uses_latest_commentary(self):
        s={'threadRuntimeStatus':{'type':'active'},'turns':[{'turnId':'x','status':'inProgress','items':[{'type':'agentMessage','text':'正在运行测试'}]}]}
        result=describe('Test','id',s)
        self.assertIn('正在运行测试',result);self.assertNotIn('已完成',result)
    def test_completed_means_turn_not_whole_project(self):
        s={'threadRuntimeStatus':{'type':'idle'},'turns':[{'turnId':'x','status':'completed','items':[]}]}
        self.assertIn('最近一轮已完成',describe('Test','id',s))

if __name__=='__main__':unittest.main()
