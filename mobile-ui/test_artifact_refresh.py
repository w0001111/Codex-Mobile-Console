# SPDX-License-Identifier: MIT
# Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import contextlib,json,tempfile,time,unittest,uuid
from pathlib import Path
from artifacts import ArtifactStore,output_references
from adapter import Adapter
from mobile_reads import ReadJobs

class ArtifactRefreshTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='artifact-fixture-',dir=Path(__file__).parent);self.root=Path(self.temp.name);self.project=self.root/'project';self.project.mkdir();self.store=ArtifactStore(self.root/'state')
 def tearDown(self):self.temp.cleanup()
 def turn(self,text,status='completed',role='agentMessage',phase='final_answer'):
  return {'id':'turn','status':status,'items':[{'id':'reply','type':role,'phase':phase,'text':text}]}
 def test_explicit_inline_image_discovered_without_file_change(self):
  p=self.project/'图 1.png';p.write_bytes(b'\x89PNG\r\n\x1a\nfixture')
  turn=self.turn(f'![图表](<{p}>)')
  self.assertEqual(self.store.discover('owner','task',str(self.project),[turn]),0)
  files=self.store.listing('owner','task');self.assertEqual(len(files),1);self.assertEqual(files[0]['sourcePath'],str(p))
  self.assertEqual(self.store.read('owner','task',files[0]['id'])[2],'image/png')
  self.assertEqual(self.store.listing('other','task'),[])
  with self.assertRaises(FileNotFoundError):self.store.read('owner','other',files[0]['id'])
 def test_inputs_unfinished_ordinary_links_and_commentary_not_outputs(self):
  p=self.project/'image.png';p.write_bytes(b'png')
  for turn in [self.turn(f'[reference]({p})'),self.turn(f'![image]({p})',status='inProgress'),self.turn(f'![image]({p})',role='userMessage'),self.turn(f'![image]({p})',phase='commentary')]:
   self.assertEqual(output_references(turn,str(self.project)),[])
 def test_image_discovery_keeps_scope_sensitive_and_symlink_checks(self):
  p=self.root/'outside.png';p.write_bytes(b'png');link=self.project/'link.png';link.symlink_to(p)
  for raw in [str(p),str(link),str(self.project/'secret.png'),'https://external.invalid/image.png','/etc/passwd.png']:
   self.assertEqual(self.store.discover('owner','task',str(self.project),[self.turn(f'![image]({raw})')]),1)
  self.assertEqual(self.store.listing('owner','task'),[])
 def test_old_snapshot_acquires_image_mapping_without_changing_bytes(self):
  p=self.project/'image.gif';p.write_bytes(b'GIF89afixture');t=self.turn(':codex-file-citation{path='+json.dumps(str(p))+' purpose="output"}')
  self.store.discover('a','t',str(self.project),[t]);aid=self.store.listing('a','t')[0]['id']
  with contextlib.closing(self.store.connect()) as db,db:db.execute('DELETE FROM artifact_sources')
  p.write_bytes(b'GIF89achanged');self.store.discover('a','t',str(self.project),[t])
  self.assertEqual(self.store.listing('a','t')[0]['sourcePath'],str(p));self.assertEqual(self.store.read('a','t',aid)[1],b'GIF89afixture')
 def test_refresh_reads_new_results_before_cache_expires_and_reuses_poll_job(self):
  a=object.__new__(Adapter);a.file_jobs=ReadJobs(capacity=1,max_entries=32);a.read_key=lambda *args:('actor','thread',None)
  data=['first'];calls=[]
  def read(*args):calls.append(1);return {'files':list(data)}
  a.files=read
  def poll(token=None):
   for _ in range(100):
    result=a.file_page({},1,refresh=token)
    if not result.get('loading'):return result
    time.sleep(.01)
   self.fail('job did not finish')
  self.assertEqual(poll()['files'],['first']);data.append('second')
  self.assertEqual(poll()['files'],['first'])
  token=str(uuid.uuid4());self.assertEqual(poll(token)['files'],['first','second']);self.assertEqual(poll(token)['files'],['first','second']);self.assertEqual(len(calls),2)

if __name__=='__main__':unittest.main()
