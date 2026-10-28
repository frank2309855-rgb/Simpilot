"""Bounded, read-only time-window inspection of derived CSV files."""
import csv
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from .quality import local_path, MAX_BYTES
from .path_probe import friendly_error
from gp_eval.validation import number, require

def inspect_windows(paths):
    require(isinstance(paths,list) and len(paths)==5, '請完整填入五份 S(q,t) CSV 路徑。')
    frames=[]
    for i,value in enumerate(paths,1):
        try:
            path=local_path(value)
            require(path.suffix.lower()==".csv", "請選已完成的 S(q,t) .csv 檔案，不是 raw 位置檔或資料夾。")
            require(path.is_file() and path.stat().st_size<=MAX_BYTES,'需要不超過 64 MiB 的 CSV 檔案。')
            with path.open('rb') as f: data=f.read(MAX_BYTES+1)
            require(len(data)<=MAX_BYTES,'CSV 超過 64 MiB。')
            reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
            require(reader.fieldnames is not None and len(reader.fieldnames)==3 and set(reader.fieldnames)=={'time','q','S'},'CSV 必須有 time,q,S 三欄。')
            times=set()
            for line,row in enumerate(reader,2):
                require(line<=1_000_001 and None not in row and all(v is not None for v in row.values()),'CSV 列數或欄位不完整。')
                times.add(number(row['time'],f'第 {line} 列 time'))
            require(len(times)>=2,'至少需要兩個不同時間點。')
            frames.append(times)
        except (ValueError,OSError,UnicodeError) as exc:
            raise ValueError(f'配方 {i}：{friendly_error(exc)}') from exc
    common=sorted(set.intersection(*frames))
    require(len(common)>=2,'五份 CSV 沒有至少兩個共同的實際時間點，未套用設定。')
    start,end=common[0],common[-1]
    counts=[sum(start<=t<=end for t in ts) for ts in frames]
    return dict(range=dict(time_start=start,time_end=end),minFrames=min(counts),maxBlocks=min(10,min(counts)//2),frameCounts=counts,
                note='只讀取 CSV 的時間欄；完整 q 網格、數值及正規化仍需後續資料檢查。共同範圍不代表穩定時間窗。')

def run_window_probe(paths,timeout=10):
    require(isinstance(paths,list) and len(paths)==5,'請完整填入五份 S(q,t) CSV 路徑。')
    try:
        r=subprocess.run([sys.executable,'-X','utf8','-m','gp_frontend.csv_window'],
            input=json.dumps(dict(paths=paths),ensure_ascii=False),text=True,encoding='utf-8',capture_output=True,timeout=timeout,
            cwd=Path(__file__).resolve().parents[1],creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except subprocess.TimeoutExpired:
        raise ValueError('CSV 時間窗讀取逾時，已停止；設定未變更。請確認檔案可讀，或手動填寫時間窗。') from None
    require(r.returncode==0,'CSV 時間窗檢查未完成，設定未變更。請重新啟動工作台。')
    result=json.loads(r.stdout)
    require('error' not in result,result.get('error',''))
    return result

if __name__=='__main__':
    try: result=inspect_windows(json.load(sys.stdin).get('paths'))
    except Exception as exc: result=dict(error=friendly_error(exc))
    print(json.dumps(result,ensure_ascii=False))
