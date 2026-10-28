# Feature inventory

| Capability | Interface / entry point | Status and required input |
|---|---|---|
| Latest research UI | `gp_frontend/static/` | Current target selector, consistent numbered navigation, streamlined text and foldout methods retained |
| Bundled five-recipe workflow | Header button; `run_example.py` | Included; no credentials or original data paths |
| q* | Target selector | Time average then interior-peak screening; diagnostics can block training |
| M | Target selector | Mode-count weighted normalized spectral excess; requires matching manifest |
| Low-q mean | Target selector | Equal complete-shell mean in declared band; requires matching manifest and comparable shell grids |
| Five signal kernels | Model selection | Linear, RBF, Matérn 3/2, Matérn 5/2, Rational Quadratic |
| Mean / linear baselines | Every training run | Included alongside selected GPs |
| Validation and reports | Training / results | Leave one recipe ratio out; training-fold scaling; interpolation vs endpoint extrapolation; Gaussian scoring/calibration |
| Regression display | Report | Full-data fit and held-out predictions shown separately for GPs and baselines |
| Project persistence | Save/import settings | Portable bundled relative paths; custom sources use own absolute paths |
| Time-window discovery | Data check | Five CSVs or completed raw calculation; does not select equilibrium automatically |
| Local raw processing | Raw source mode | Own coordinates needed; fixed orthorhombic periodic box; bounded grids / selected time sampling |
| Drive source | Optional source mode | Own desktop OAuth credentials, explicit account-wide read-only consent and permitted account |
| Partial terms / SANS / SAXS | Optional raw result panel | Own raw data and scattering amplitudes / tables; experiment data not included |
| Synthetic examples | Two header buttons; `make_*demo.py` | Marked synthetic, independent of the five real derived curves |
| History and deletion | Results/history | Confirmed deletion of one completed run; rejects active work and redirected paths |
| Condition model CLI | `train_condition_gp.py`, `predict_condition_gp.py` | Available for configured feature columns and validated JSON models |
| Early-observation model CLI | `train_early_gp.py`, `predict_early_gp.py` | Available; requires separately supplied features and explicit time metadata |
| Protocol / external predictions | `prepare_protocol.py`, `evaluate.py` | Available as separate evaluator entry points |
| Additional feature/kernel specifications | `gp_model/` and CLI configuration | Existing engine supports declared inputs; GUI currently uses ratio only |
| New arbitrary ratio GUI form | — | Not implemented; saved-model prediction is available through CLI |
| Stage 1 → stage 3 predictive model | — | Not scientifically validated or trained by this release |
| Experimental absolute-intensity fit | — | Not implemented; weighted curves are preparation only |
| Automatic model winner | — | No predeclared scientific winner thresholds; comparisons are exploratory |
| Hosted multi-user deployment | — | Not supported; loopback-only trusted local research tool |

The existing q*, M and low-q extraction code is retained; the release changes packaging, example loading, privacy and HTTP access checks rather than replacing scientific definitions.
