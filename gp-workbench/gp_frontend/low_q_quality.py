"""Equal exact-shell mean in a declared q band; independent of peak and M rules."""
from functools import lru_cache
import numpy as np
from gp_eval.validation import number, require
from . import m_quality, raw

VERSION = 'low-q-shell-mean-1.0.0'

def validate_settings(value):
    require(isinstance(value, dict), '請填寫低 q 平均的獨立設定。')
    s = {k:number(value.get(k), 'low_q.'+k) for k in ('time_start','time_end','q_min','q_max','blocks')}
    require(s['time_start'] < s['time_end'], '低 q 時間起點須小於終點。')
    require(0 <= s['q_min'] < s['q_max'], '低 q 頻帶須滿足 0 ≤ 下限 < 上限；q=0 一律排除。')
    require(s['blocks'].is_integer() and 2 <= s['blocks'] <= 10, '低 q 分段數須為 2–10 的整數。')
    s['blocks'] = int(s['blocks'])
    return s

@lru_cache(maxsize=8)
def _geometry(box, scale, qmax, dq):
    # Geometry only: no trajectory download, coordinates, or structure-factor calculation.
    return raw.reciprocal_grid(box, dict(length_scale=scale, q_max=qmax, dq=dq))

def analyze_file(value, settings, metadata=None, q_unit=None, time_unit=None):
    # Reuse the strict CSV/provenance checks without changing the existing M extractor.
    try:
        r=m_quality.analyze_file(value, settings, metadata, q_unit, time_unit)
    except ValueError as exc:
        raise ValueError(str(exc).replace('M ', '低 q 平均 ').replace('M.', 'low_q.')) from exc
    meta=r['raw_manifest']; summary=meta['summary']; rs=meta['settings']
    box=np.asarray(summary.get('box_raw', []), dtype=float)
    require(box.shape==(3,) and np.isfinite(box).all() and np.all(box>0), '低 q 平均需要三個盒長，以核對完整 shell。')
    scale=number(rs.get('length_scale'), 'length_scale'); dq=number(rs.get('dq'), 'dq')
    require(scale>0 and dq>0, '長度換算與分箱寬度須為正數。')
    expected=_geometry(tuple(box),scale,number(rs.get('q_max'),'q_max'),dq)
    for key in ('q','q_low','q_high'):
        actual=np.asarray(summary[key]); ref=expected[key]
        require(actual.shape==ref.shape and np.allclose(actual,ref,rtol=1e-11,atol=1e-13), '計算紀錄的 q 網格與盒長不符或缺少 shell；不能計算低 q 平均。')
    require(np.array_equal(np.asarray(summary['directions_full']),2*expected['counts']), '計算紀錄缺少方向或方向數與盒長不符。')
    q=np.asarray(summary['q']); eps=1e-12*max(1.,float(q.max()))
    mask=(q>=settings['q_min']-eps)&(q<=settings['q_max']+eps)
    lo=np.asarray(summary['q_low'])[mask]; hi=np.asarray(summary['q_high'])[mask]
    require(np.allclose(lo,hi,rtol=1e-11,atol=1e-13), '低 q 區間有分箱混合不同 shell，無法還原等 shell 平均。請以較細分箱重新計算；不會用前五個分箱代替。')
    # Group numerically identical shells if a floating-point bin edge split directions.
    groups=[]
    for j,x in enumerate(r['q']):
        if groups and np.isclose(x,r['q'][groups[-1][0]],rtol=1e-11,atol=1e-13): groups[-1].append(j)
        else: groups.append([j])
    weights=np.asarray(r['directions_full'])
    def shell_means(y):
        return np.array([np.average(np.asarray(y)[g],weights=weights[g]) for g in groups])
    shell_q=shell_means(r['q']); counts=np.array([sum(weights[g]) for g in groups])
    require(len(groups)>=2, '低 q 平均至少需要兩個完整 shell 供曲線診斷。')
    mean=shell_means(r['mean']); result=float(mean.mean()); blocks=[]
    for b in r['blocks']:
        y=shell_means(b['mean'])
        blocks.append(dict(time_start=b['time_start'],time_end=b['time_end'],n_frames=b['n_frames'],mean=y.tolist(),low_q_value=float(y.mean())))
    vals=[result]+[b['low_q_value'] for b in blocks]; spread=max(vals)-min(vals)
    for key in ('m_value','m_spread','m_relative_spread'): r.pop(key,None)
    r.update(target_kind='low_q_shell_mean',low_q_value=result,q=shell_q.tolist(),mean=mean.tolist(),blocks=blocks,
        directions_full=counts.astype(int).tolist(),shell_count=len(groups),shell_weights=[1/len(groups)]*len(groups),
        low_q_spread=spread,low_q_relative_spread=spread/result if result>1e-12 else None,
        definition_version=VERSION,normalization='Scc/(c1*c2)',shell_weighting='equal_exact_shell',
        note='固定頻帶內，先平均時間、每個完整 shell 等權平均；不減 1，不尋峰。數值非負，1 僅為獨立隨機粒子的參考值，不是聚合物混合度門檻。分段差距不是信賴區間，也不證明平衡、跨 seed 或跨階段預測能力。')
    return r

def check_comparable(results):
    good=[r for r in results if r.get('status')=='ready']
    if not good: return
    ref=good[0]
    for r in good[1:]:
        same=len(r['q'])==len(ref['q']) and np.allclose(r['q'],ref['q'],rtol=1e-11,atol=1e-13) and r['directions_full']==ref['directions_full']
        if not same:
            for item in good:
                item['status']='review';item['reasons'].append('配方間的低 q shell 網格或方向數不同；請使用相同盒長、單位與完整 shell 後再比較。')
            break
