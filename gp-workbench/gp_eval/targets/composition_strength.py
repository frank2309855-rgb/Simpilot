"""Dimensionless, mode-weighted composition fluctuation excess."""
import math
from statistics import fmean
from .base import GaussianScalarTarget
from ..validation import require

class CompositionStrengthTarget(GaussianScalarTarget):
    evaluator_id='composition_strength'
    diagnostic_fields=(dict(key='below_m_domain_mass',label='P(M < -1) 平均機率',format='percent'),)
    diagnostic_note='M 的物理下限為 -1；負值不等於無效。Gaussian 預測仍可能超出下限，不作截斷或套用 q* 長度診斷。'
    def validate_definition(self,target,protocol):
        super().validate_definition(target,protocol)
        require(target.get('units')=='dimensionless','M units must be dimensionless')
        require(target.get('extraction_order')=='time_average_then_mode_weighted_excess','M extraction order mismatch')
    def validate_observation(self,value,observation_id):
        require(value>=-1,f'{observation_id}: M truth must be >= -1')
    def observation_metrics(self,y,mu,sd):
        return dict(below_m_domain_mass=.5*math.erfc((mu+1)/(sd*math.sqrt(2))))
    def aggregate(self,records):
        return dict(below_m_domain_mass=fmean(r['below_m_domain_mass'] for r in records))
    def summarize(self,ratio_rows):
        return dict(below_m_domain_mass=fmean(r['below_m_domain_mass'] for r in ratio_rows))
    def warnings(self,protocol,records):
        return ['M 是固定頻帶的組成起伏超額，不是混合百分比。頻帶、鏈內相關與粒子定義會影響解讀；短窗口可計算不代表跨 seed 或跨階段驗證。']
    def describe(self,target):
        result=super().describe(target)
        result.update(axis_label='M',extraction_order='time_average_then_mode_weighted_excess',
                      extraction_order_label='先平均正規化 Scc，再按頻帶內各箱方向數加權平均並減 1')
        return result
