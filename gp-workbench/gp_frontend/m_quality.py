"""Independent M extraction: normalized composition spectrum, counted modes, no peak rules."""
import csv
import hashlib
import io
import json
import numpy as np
from gp_eval.validation import number, require
from .quality import local_path, MAX_BYTES
from .raw import FORMULA

VERSION = 'composition-strength-1.0.0'

def validate_settings(raw):
    require(isinstance(raw, dict), '請填寫 M 的獨立設定。')
    s = {k:number(raw.get(k), 'M.'+k) for k in ('time_start','time_end','q_min','q_max','blocks')}
    require(s['time_start'] < s['time_end'], 'M 時間起點須小於終點。')
    require(0 <= s['q_min'] < s['q_max'], 'M 頻帶須滿足 0 ≤ 下限 < 上限；q=0 一律排除。')
    require(s['blocks'].is_integer() and 2 <= s['blocks'] <= 10, 'M 分段數須為 2–10 的整數。')
    s['blocks'] = int(s['blocks'])
    return s

def analyze_file(value, settings, metadata=None, q_unit=None, time_unit=None):
    path = local_path(value)
    require(path.is_file() and path.stat().st_size <= MAX_BYTES, 'M 需要不超過 64 MiB 的 S(q,t) CSV。')
    with path.open('rb') as f: data=f.read(MAX_BYTES+1)
    require(len(data)<=MAX_BYTES, 'S(q,t) CSV 太大。')
    digest=hashlib.sha256(data).hexdigest()
    if metadata is None:
        manifest=path.with_name('manifest.json')
        require(manifest.is_file(), 'M 需要同資料夾的 manifest.json（方向數與正規化紀錄）。請選原計算輸出的 sqt.csv，不能用普通 CSV 等權代替。')
        require(manifest.stat().st_size <= 8*1024*1024, 'M 計算紀錄超過大小上限。')
        metadata=json.loads(manifest.read_text(encoding='utf-8-sig'))
    require(isinstance(metadata,dict), 'M 計算紀錄格式錯誤。')
    rs=metadata.get('settings',{}); summary=metadata.get('summary',{})
    require(isinstance(rs,dict) and isinstance(summary,dict), 'M 計算紀錄格式錯誤。')
    require(metadata.get('csv_sha256')==digest, 'S(q,t) 與計算紀錄的指紋不符，無法確認 M 權重來源。')
    require(rs.get('normalization')=='scc_normalized' and metadata.get('formula')==FORMULA,
            'M 只接受 Scc/(cA*cB) 的組成結構因子；未正規化或 SANS/SAXS 曲線不適用。')
    require(rs.get('periodic') is True, 'M 第一版需週期盒計算紀錄。')
    require(q_unit==rs.get('length_unit','')+'^-1' and time_unit==rs.get('time_unit'), '研究 q／time 單位與 M 計算紀錄不符。')
    q=np.array(summary.get('q',[]),dtype=float)
    counts=np.array(summary.get('directions_full',[]),dtype=float)
    low=np.array(summary.get('q_low',[]),dtype=float); high=np.array(summary.get('q_high',[]),dtype=float)
    require(q.ndim==1 and len(q)>=2 and all(v.shape==q.shape for v in (counts,low,high)), 'M 缺少各分箱方向數或 q 範圍。')
    require(all(np.isfinite(v).all() for v in (q,counts,low,high)) and np.all(q>0) and np.all(np.diff(q)>0), 'M 的 q 網格無效。')
    require(np.all(counts>0) and np.all(counts==np.floor(counts)) and np.all(counts % 2==0), 'M 方向數必須為正偶數（含正負方向）。')
    eps=1e-12*max(1.,float(high.max()))
    require(np.all(low>0) and np.all(low<=q+eps) and np.all(q<=high+eps), 'M 分箱邊界與 q 中心不一致。')
    require(settings['q_max'] <= number(rs.get('q_max'),'計算 q 上限')+eps, 'M 頻帶超過已計算 q 上限，請先補足 S(q,t)。')
    for bound in (settings['q_min'],settings['q_max']):
        require(not np.any((low < bound-eps)&(high > bound+eps)), 'M 頻帶邊界切穿既有分箱；請選箱間邊界或以較細分箱重新計算。')
    mask=(q>=settings['q_min']-eps)&(q<=settings['q_max']+eps)
    require(int(mask.sum())>=2, 'M 頻帶內至少需要兩個有效分箱供曲線檢查。')
    reader=csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
    require(reader.fieldnames is not None and len(reader.fieldnames)==3 and set(reader.fieldnames)=={'time','q','S'}, 'M CSV 需要 time,q,S 三欄。')
    frames={}
    for line,row in enumerate(reader,2):
        require(line<=1_000_001 and None not in row, 'M CSV 列數或欄位格式無效。')
        t,x,y=(number(row[k],f'第 {line} 列 {k}') for k in ('time','q','S'))
        require(x>0 and y>=0, 'M 需要非負的正規化 S 與非零正 q。')
        if settings['time_start']<=t<=settings['time_end']:
            frame=frames.setdefault(t,{})
            require(x not in frame, 'M CSV 含重複的 (time,q)。')
            frame[x]=y
    times=np.array(sorted(frames))
    require(len(times)>=2*settings['blocks'], 'M 每個時間分段至少需要兩個 frame。')
    require(times[0]==settings['time_start'] and times[-1]==settings['time_end'], 'M 時間窗端點須對應實際 time。')
    require(np.allclose(np.diff(times),np.diff(times)[0],rtol=1e-6,atol=1e-12), 'M 第一版要求等時間間隔。')
    require(all(np.array_equal(np.array(sorted(frames[t])),q) for t in times), 'M 各 frame 的 q 網格須與計算紀錄完全一致。')
    x=q[mask]; n=counts[mask]; curves=np.array([[frames[t][v] for v in x] for t in times]); mean=curves.mean(0)
    m=float(np.average(mean-1,weights=n)); blocks=[]
    for idx in np.array_split(np.arange(len(times)),settings['blocks']):
        y=curves[idx].mean(0)
        blocks.append(dict(time_start=float(times[idx[0]]),time_end=float(times[idx[-1]]),n_frames=len(idx),mean=y.tolist(),m_value=float(np.average(y-1,weights=n))))
    values=[m]+[b['m_value'] for b in blocks];spread=max(values)-min(values)
    record=json.dumps(metadata,sort_keys=True,ensure_ascii=False,allow_nan=False).encode('utf-8')
    return dict(path=str(path),sha256=digest,size=len(data),target_kind='composition_strength',status='ready',reasons=[],
                m_value=m,q=x.tolist(),mean=mean.tolist(),n_frames=len(times),blocks=blocks,
                m_spread=spread,m_relative_spread=spread/abs(m) if abs(m)>1e-12 else None,
                directions_full=n.astype(int).tolist(),mode_count=int(n.sum()),actual_q_range=[float(low[mask].min()),float(high[mask].max())],
                actual_window=[float(times[0]),float(times[-1])],band=[settings['q_min'],settings['q_max']],
                manifest_sha256=hashlib.sha256(record).hexdigest(),raw_manifest=metadata,
                note='可計算只表示資料、正規化與方向權重一致。分段差距僅供診斷，沒有自動穩定門檻，不證明平衡、跨 seed 穩定或預測價值。M 可為負，物理下限為 -1；不是混合百分比。')
