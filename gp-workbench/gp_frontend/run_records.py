"""Deletion is restricted to one completed, direct-child workbench run."""
import hashlib
import json
import os
import re
import shutil
import stat
from pathlib import Path
from gp_eval.validation import require

RUN_ID=re.compile(r'[0-9]{8}_[0-9]{6}_[a-f0-9]{6}')
MARKER='workbench_result.json'

def _regular_path(path,base):
    st=path.lstat()
    require(not stat.S_ISLNK(st.st_mode) and not (getattr(st,'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024)),
            '紀錄包含連結或重新導向的資料夾；平台不會刪除，請人工確認。')
    require(path.resolve()==path and (path==base or base in path.parents),'執行紀錄路徑超出允許範圍。')
    require(stat.S_ISDIR(st.st_mode) or stat.S_ISREG(st.st_mode),'執行紀錄含不支援的檔案類型。')
    return st

def run_path(root,run_id):
    require(isinstance(run_id,str) and RUN_ID.fullmatch(run_id) is not None,'執行紀錄 ID 格式錯誤。')
    base=Path(root).resolve()/'web_runs'
    _regular_path(base,base)
    folder=base/run_id
    _regular_path(folder,base)
    require(folder.is_dir() and folder.parent==base,'只允許刪除 web_runs 內單次執行資料夾。')
    return folder

def describe(root,run_id):
    folder=run_path(root,run_id); marker=folder/MARKER
    _regular_path(marker,folder)
    require(marker.is_file() and marker.stat().st_size<=8*1024*1024,'這不是完整的已保存執行紀錄。')
    data_bytes=marker.read_bytes();data=json.loads(data_bytes.decode('utf-8-sig'))
    require(isinstance(data,dict) and data.get('run_id')==run_id,'紀錄 ID 與資料夾不一致；未允許刪除。')
    entries=[];size=0;files=0
    for parent,dirs,names in os.walk(folder,followlinks=False):
        for name in sorted(dirs+names):
            path=Path(parent)/name;st=_regular_path(path,folder)
            entries.append((str(path.relative_to(folder)),st.st_size,st.st_mtime_ns,st.st_ino))
            if stat.S_ISREG(st.st_mode):size+=st.st_size;files+=1
    fingerprint=hashlib.sha256(data_bytes+json.dumps(sorted(entries)).encode()).hexdigest()
    return dict(run_id=run_id,label=data.get('label',run_id),target_kind=data.get('target_kind','q_peak'),
                kernel_choices=data.get('kernel_choices',['linear']),folder=str(folder),file_count=files,size_bytes=size,fingerprint=fingerprint)

def delete(root,run_id,fingerprint,confirmed):
    require(confirmed is True,'請先確認要刪除的執行紀錄。')
    current=describe(root,run_id)
    require(isinstance(fingerprint,str) and fingerprint==current['fingerprint'],'紀錄內容已改變，請重新查看刪除範圍後確認。')
    folder=Path(current['folder']);base=Path(root).resolve()/'web_runs'
    # Verify resolved targets before any recursive deletion. No metadata-supplied path is followed.
    require(folder.parent==base and folder.resolve()==folder,'刪除目標超出 web_runs。')
    try:
        # Keep the history marker until last so a locked-file failure can be retried from the UI.
        for child in list(folder.iterdir()):
            if child.name==MARKER:continue
            _regular_path(child,folder)
            if child.is_dir():shutil.rmtree(child)
            else:child.unlink()
        (folder/MARKER).unlink()
        folder.rmdir()
    except OSError as exc:
        raise ValueError('刪除未完成，部分檔案可能仍保留。請關閉使用這份紀錄的程式、重新整理紀錄後再試。') from exc
    return dict(deleted=True,run_id=run_id,file_count=current['file_count'],size_bytes=current['size_bytes'])
