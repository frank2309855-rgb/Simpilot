"""Small offline/local checks for public-package boundaries; no Google account."""
import hashlib,http.client,json,re,tempfile,threading,unittest
from pathlib import Path
from gp_frontend.examples import project
from gp_frontend.low_q_quality import analyze_file
from gp_frontend.server import create_server
from gp_frontend.service import Workbench

ROOT=Path(__file__).resolve().parents[1]
class ReleaseTests(unittest.TestCase):
 def test_clean_manifests_preserve_five_labels(self):
  p=project();expected=[1.506739003326183,4.254390943144394,7.368493116649271,9.747441175885513,10.322069270105628]
  for row,value in zip(p['rows'],expected):
   path=Path(row['path']);meta=json.loads(path.with_name('manifest.json').read_text(encoding='utf-8'))
   self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),meta['csv_sha256']);self.assertNotIn('sources',meta)
   result=analyze_file(str(path),p['settings'],q_unit=p['q_unit'],time_unit=p['time_unit'])
   self.assertAlmostEqual(result['low_q_value'],value,places=12);self.assertEqual(result['shell_count'],5)
 def test_http_guards_and_example_loader(self):
  with tempfile.TemporaryDirectory() as tmp:
   server=create_server(Path(tmp),0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();port=server.server_port
   def request(method,path,body=None,headers=None):
    h={'Host':f'127.0.0.1:{port}',**(headers or {})}
    if body is not None:h['Content-Type']='application/json';body=json.dumps(body)
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=15);c.request(method,path,body,headers=h);reply=c.getresponse();result=(reply.status,reply.getheaders(),reply.read());c.close();return result
   try:
    status,headers,body=request('GET','/');self.assertEqual(status,200)
    self.assertIn(b'loadExample',body);self.assertIn(b'navQualityLabel',body)
    token=re.search(rb"WORKBENCH_TOKEN='([^']+)'",body).group(1).decode();cookie=dict(headers)['Set-Cookie'].split(';')[0]
    self.assertIn('HttpOnly',dict(headers)['Set-Cookie']);self.assertIn('SameSite=Strict',dict(headers)['Set-Cookie'])
    self.assertEqual(request('GET','/',headers={'Host':'untrusted.invalid'})[0],403)
    self.assertEqual(request('GET','/',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
    self.assertEqual(request('GET','/api/history')[0],403)
    auth={'X-Workbench-Token':token}
    self.assertEqual(request('POST','/api/example-project',{},dict(auth,Origin='https://untrusted.invalid'))[0],403)
    status,_,body=request('POST','/api/example-project',{},auth);self.assertEqual(status,200)
    self.assertEqual(len(json.loads(body)['rows']),5)
    fake=Path(tmp)/'web_runs/20261027_010101_aaaaaa/condition/evaluation';fake.mkdir(parents=True);(fake/'report.html').write_text('fixture')
    url='/runs/20261027_010101_aaaaaa/condition/evaluation/report.html'
    self.assertEqual(request('GET',url)[0],403);self.assertEqual(request('GET',url,headers={'Cookie':cookie})[0],200)
    self.assertEqual(request('GET','/runs/20261027_010101_aaaaaa/../../unavailable.json',headers={'Cookie':cookie})[0],404)
   finally:
    server.shutdown();server.server_close();server.workbench.pool.shutdown(wait=True);thread.join(timeout=5)
 def test_scoped_delete_preserves_source(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);run_id='20261027_010101_aaaaaa';run=root/'web_runs'/run_id;run.mkdir(parents=True)
   (run/'workbench_result.json').write_text(json.dumps(dict(run_id=run_id,label='fixture')));(run/'model.json').write_text('{}')
   source=root/'source.csv';source.write_text('preserve');app=Workbench(root)
   try:
    preview=app.preview_run_deletion(run_id)
    with self.assertRaises(ValueError):app.delete_run(dict(run_id=run_id,fingerprint=preview['fingerprint']))
    with self.assertRaises(ValueError):app.delete_run(dict(run_id='../source.csv',fingerprint=preview['fingerprint'],confirmed=True))
    result=app.delete_run(dict(run_id=run_id,fingerprint=preview['fingerprint'],confirmed=True));self.assertTrue(result['deleted'])
    self.assertFalse(run.exists());self.assertEqual(source.read_text(),'preserve')
   finally:app.pool.shutdown(wait=True)

if __name__=='__main__':unittest.main()
