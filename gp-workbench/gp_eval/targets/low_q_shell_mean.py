"""Normalized concentration spectrum: equal-shell band average, no baseline subtraction."""
import math
from statistics import fmean
from .base import GaussianScalarTarget
from ..validation import require

class LowQShellMeanTarget(GaussianScalarTarget):
    evaluator_id='low_q_shell_mean'
    diagnostic_fields=(dict(key='below_low_q_domain_mass',label='P(低 q 平均 < 0) 平均機率',format='percent'),)
    diagnostic_note='低 q 平均非負；Gaussian 預測落在負值的機率用於診斷，不截斷預測。數值 1 不是聚合物混合度門檻。'
    def validate_definition(self,target,protocol):
        super().validate_definition(target,protocol)
        require(target.get('units')=='dimensionless','low-q units must be dimensionless')
        require(target.get('extraction_order')=='time_average_then_equal_shell_mean','low-q extraction order mismatch')
    def validate_observation(self,value,observation_id):
        require(value>=0,f'{observation_id}: low-q truth must be >= 0')
    def observation_metrics(self,y,mu,sd):
        return dict(below_low_q_domain_mass=.5*math.erfc(mu/(sd*math.sqrt(2))))
    def aggregate(self,records):
        return dict(below_low_q_domain_mass=fmean(r['below_low_q_domain_mass'] for r in records))
    def summarize(self,ratio_rows):
        return dict(below_low_q_domain_mass=fmean(r['below_low_q_domain_mass'] for r in ratio_rows))
    def warnings(self,protocol,records):
        return ['低 q 平均以固定頻帶、完整 shell 等權平均定義；不是 q→0 極限、混合百分比或實驗 SAXS/SANS 強度。鏈內相關也有貢獻，不能單獨證明相分離。不可將不同目標的原始誤差直接排名。']
    def describe(self,target):
        result=super().describe(target)
        result.update(axis_label='低 q 正規化 Scc 平均',extraction_order='time_average_then_equal_shell_mean',extraction_order_label='時間平均後，在固定頻帶內對完整 shell 等權平均；q=0 排除，不減 1')
        return result
