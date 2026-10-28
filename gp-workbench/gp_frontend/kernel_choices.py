"""Versioned, explicit kernel choices exposed by the local workbench."""
import copy
from gp_eval.validation import require

VERSION='workbench-kernels-1.0'
KERNELS={
 'linear':dict(label='Linear',spec=dict(type='linear',sigma_0=1.,sigma_0_bounds='fixed')),
 'rbf':dict(label='RBF',spec=dict(type='rbf',length_scale=1.,length_scale_bounds=[.01,100.])),
 'matern_32':dict(label='Matérn 3/2',spec=dict(type='matern',nu=1.5,length_scale=1.,length_scale_bounds=[.01,100.])),
 'matern_52':dict(label='Matérn 5/2',spec=dict(type='matern',nu=2.5,length_scale=1.,length_scale_bounds=[.01,100.])),
 'rational_quadratic':dict(label='Rational Quadratic',spec=dict(type='rational_quadratic',length_scale=1.,length_scale_bounds=[.01,100.],alpha=1.,alpha_bounds=[.01,100.])),
}

def validate_choices(value):
 require(isinstance(value,list) and 1<=len(value)<=len(KERNELS),'請至少選一個 kernel，最多五種。')
 require(all(isinstance(v,str) and v in KERNELS for v in value),'不支援的 kernel 選項。')
 require(len(set(value))==len(value),'kernel 選項不可重複。')
 return list(value)

def model_specs(choices):
 return [dict(model_id='gp_ratio_'+key,label='Ratio · '+KERNELS[key]['label']+' GP',inputs=['ratio'],kernel=copy.deepcopy(KERNELS[key]['spec'])) for key in validate_choices(choices)]
