"""Local targeted release scan. Prints categories/filenames, never matched values."""
import argparse
import hashlib
import json
import re
from pathlib import Path

PATTERNS={
 'personal_windows_path':r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s"<>]+',
 'personal_unix_path':r'/(?:home|Users)/[A-Za-z0-9_.-]+/',
 'drive_folder_identifier':r'https://drive\.google\.com/drive/(?:u/\d+/)?folders/[A-Za-z0-9_-]{10,}',
 'drive_file_identifier':r'https://drive\.google\.com/(?:file/d/|open\?id=)[A-Za-z0-9_-]{10,}',
 'google_client_id':r'[0-9]+-[A-Za-z0-9_-]+\.apps\.googleusercontent\.com',
 'google_access_token':r'ya29\.[A-Za-z0-9_-]{20,}',
 'google_api_key':r'AIza[0-9A-Za-z_-]{30,}',
 'github_token':r'(?:gh[pousr]_|github_pat_)[A-Za-z0-9_]{20,}',
 'aws_access_key':r'AKIA[0-9A-Z]{16}',
 'private_key':r'-----BEGIN [A-Z ]*PRIVATE KEY-----',
 'account_email':r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(?:com|edu|org|net|gov|io|tw|uk|de)\b',
}
SKIP={'runtime','.venv','.git','__pycache__','.pytest_cache'}
BAD_SUFFIX={'.pkl','.pickle','.joblib','.pem','.key','.log','.npz','.pyc','.zip'}

def scan(root,source_tree=False):
 root=Path(root).resolve();findings=[];count=0
 manifest=root/'RELEASE_FILES.json'
 declared=json.loads(manifest.read_text(encoding='utf-8'))['files'] if manifest.exists() and not source_tree else None
 files=[root/name for name in declared] if declared is not None else sorted(root.rglob('*'))
 for path in files:
  if any(part in SKIP for part in path.relative_to(root).parts):continue
  if not path.is_file():
   if declared is not None:findings.append(dict(file=str(path.relative_to(root)),category='missing_file'))
   continue
  rel=path.relative_to(root).as_posix();count+=1
  if path.suffix.lower() in BAD_SUFFIX or path.name.startswith('.env') or any(x in path.name.lower() for x in ['client_secret','credentials.json','token.json']):findings.append(dict(file=rel,category='excluded_file_type'))
  try:text=path.read_text(encoding='utf-8-sig')
  except UnicodeError:
   findings.append(dict(file=rel,category='unexpected_binary'));continue
  if declared is not None and hashlib.sha256(path.read_bytes()).hexdigest()!=declared[rel]['sha256']:
   findings.append(dict(file=rel,category='checksum_mismatch'))
  # The scanner's own regular expressions describe forbidden patterns; they contain no live values.
  if rel=='scripts/check_release.py':continue
  for label,pattern in PATTERNS.items():
   if re.search(pattern,text):findings.append(dict(file=rel,category=label))

 return dict(files_scanned=count,findings=findings,scope='Targeted public-release scan; not proof of absence of all secrets.')

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--source-tree',action='store_true',help='Scan current non-runtime files including additions, ignoring the immutable release list');args=p.parse_args()
 result=scan(args.root,args.source_tree);print(json.dumps(result,indent=2));raise SystemExit(bool(result['findings']))
