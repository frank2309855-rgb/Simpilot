"""Small deterministic periodic fixtures, explicitly not MD or experiment."""
from pathlib import Path
import numpy as np


def make(root):
    base = Path(root)/"web_examples"/"raw_periodic_v1"
    base.mkdir(parents=True, exist_ok=True)
    lattice = np.array(list(np.ndindex(8,8,8)), dtype=float)
    rows=[]
    for i in range(5):
        folder=base/f"recipe_{i+1}"
        folder.mkdir(exist_ok=True)
        box=32.+2*i
        coords=(lattice+.25)/8*box
        types=np.where(np.cos(2*np.pi*2*coords[:,0]/box)>0,1,2)
        for t in range(4):
            path=folder/f"pos_{t:05}"
            if not path.exists():
                with path.open("x",encoding="utf-8") as f:
                    f.write(f"{t} {len(coords)} {box} {box} {box}\n")
                    np.savetxt(f,np.column_stack(((coords+t*.1)%box,types)),fmt=["%.12g"]*3+["%d"])
        rows.append(dict(label=f"raw 合成配方 {i+1}",amount_a=2*i+1,amount_b=9-2*i,
                         seed_id="synthetic_seed",path=str(folder.resolve())))
    return dict(project_format_version=3,label="Raw → GP｜週期合成流程測試",data_kind="synthetic_demo",
                source_mode="raw",ratio_encoding="fraction",rows=rows,
                ratio_definition="Synthetic control coordinate; not the actual particle fraction. All fixtures are 1:1 particles; boxes vary by design.",
                q_unit="simulation_length^-1",time_unit="step",time_origin="time = step",
                structure_definition="Synthetic periodic composition; Scc/(cA*cB), not MD, SANS or SAXS data.",
                conditions_note="Synthetic 512-particle grids with translated positions; four frames; no dynamics or experimental inference.",
                settings=dict(time_start=0,time_end=3,q_min=.21,q_max=.94,min_prominence=.1,
                              competitor_fraction=.9,stability_tolerance=.03,blocks=2),
                raw_settings=dict(type_a=1,type_b=2,step_start=0,step_end=3,stride=1,
                    length_scale=1,length_unit="simulation_length",time_scale=1,time_offset=0,time_unit="step",
                    q_max=1.,dq=.025,normalization="scc_normalized",periodic=True))
