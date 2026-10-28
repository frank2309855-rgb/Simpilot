"""Load only the bundled, reviewed five-recipe example; no remote access."""
import json
from pathlib import Path
from gp_eval.validation import require

ROOT=Path(__file__).resolve().parents[1]
TARGETS=('q_peak','composition_strength','low_q_shell_mean')

def project(kind='low_q_shell_mean'):
    require(kind in TARGETS,'Unknown bundled example target')
    value=json.loads((ROOT/'examples'/f'project_{kind}.json').read_text(encoding='utf-8'))
    for row in value['rows']:
        path=(ROOT/row['path']).resolve()
        require((ROOT/'examples').resolve() in path.parents and path.is_file(),'Bundled example path is invalid')
        row['path']=str(path)
    return value
