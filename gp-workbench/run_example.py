"""Run the bundled example locally without Google, raw coordinates or a browser."""
import argparse
import json
import time
from pathlib import Path
from gp_frontend.examples import project
from gp_frontend.service import Workbench


def wait(app,kind,payload):
    job=app.start(kind,payload)['job_id']
    while True:
        result=app.job(job)
        if result['status']=='failed':raise RuntimeError(result['error'])
        if result['status']=='complete':return result['result']
        time.sleep(.05)


def run(out,target='low_q_shell_mean',kernels=None):
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    app=Workbench(out)
    try:
        value=project(target)
        if kernels:value['kernel_choices']=kernels
        review=wait(app,'analyze',value)
        if not review['ready']:
            raise ValueError('Example target did not pass its declared extraction rules. Inspect quality_review.json; do not force labels.')
        result=wait(app,'train',dict(analysis_id=review['id'],reviewed=True,
             review_note='Bundled five-recipe reproducibility run; declared frequency and time window; one seed per recipe.'))
        return result
    finally:
        app.pool.shutdown(wait=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'runtime')
    p.add_argument('--target',choices=['low_q_shell_mean','composition_strength','q_peak'],default='low_q_shell_mean')
    p.add_argument('--kernels',nargs='+',choices=['linear','rbf','matern_32','matern_52','rational_quadratic'])
    args=p.parse_args()
    result=run(args.out,args.target,args.kernels)
    print(json.dumps(dict(run_id=result['run_id'],folder=result['folder'],target=result['target_kind']),indent=2))
    print('Report: '+str(Path(result['folder'])/'condition/evaluation/report.html'))

if __name__=='__main__':main()
