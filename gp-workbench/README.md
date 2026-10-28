# APCN Gaussian Process Workbench

A local research workbench for extracting structural targets from simulation curves, comparing Gaussian Process kernels, and inspecting held-out predictions. The application includes its full Python computation engine and HTML/CSS/JavaScript interface. It uses scikit-learn, NumPy and SciPy, with a Python standard-library HTTP server.

**Start with the five bundled recipe CSVs. No Google account, H: drive, Anaconda installation, raw coordinates or API key is needed.** The interface is primarily Traditional Chinese; this README provides the evaluation steps in English. [繁中快速說明](QUICKSTART_zh-TW.md).

## Architecture, model information and recorded results

![Implemented local architecture](docs/assets/architecture.svg)

- [System architecture](ARCHITECTURE.md): implemented components and local data flow; editable Mermaid source included.
- [Model card](MODEL_CARD.md): inputs/outputs, kernels, optimizer and fitted parameters, and evidence limits.
- [Recorded benchmark](BENCHMARK.md): actual five-recipe held-out results and full-precision CSVs.
- [Software/reproducibility validation](VALIDATION.md): environment and checks actually completed.

The shipped product is the GP workbench. LLM agent orchestration, active learning and automated MD dispatch are future integration work.

![Recorded held-out comparison](docs/assets/model_comparison.svg)

Three GP kernels and two baselines are compared on five recipes, one seed each. Interior interpolation (n=3) and endpoint extrapolation (n=2) are separate. These exploratory results do not measure simulation savings or independently establish model superiority.

## Install

Reference runtime: **CPython 3.13.9, 64-bit**. See [VALIDATION.md](VALIDATION.md) for the actual tested environment; other operating systems are not claimed as tested. The runtime requirements are fully pinned, including transitive dependencies. Internet access is needed to install wheels; the bundled CSV workflow does not make network requests after installation.

Clone the repository (or extract the ZIP) and open a terminal in the `gp-workbench` folder. Create a dedicated environment:

Windows:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 local_app.py
```

macOS/Linux command equivalents (provided, not validated on those systems):

```sh
python3.13 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python -X utf8 local_app.py
```

Alternatively, create the separate Conda environment declared in `environment.yml`. Do not install into a shared base environment. Wheel-only installation avoids executing dependency source-build scripts. Review this repository before running it; do not execute untrusted modifications.

The browser opens at `http://127.0.0.1:8765`. Keep the terminal open; Ctrl+C stops the service. `start_workbench.cmd` uses `.venv` when available. The shell launcher can be run as `sh start_workbench.sh`.

If the port is occupied, use `python local_app.py --port 8766`. The service binds only to `127.0.0.1`; there is no public-host option. Do not expose it with port forwarding or a tunnel.

## Evaluate the five recipes in the interface

1. Click **載入五配方範例** (Load five-recipe example) in the header. This loads the low-q target, the five local CSV paths, numerical recipe encoding and declared calculation settings.
2. Open **02 · 低 q 資料檢查** (Data check). Settings are already populated: time **1490–1499**, **2** diagnostic blocks, and **0 < q ≤ 0.11** in inverse simulation-length units.
3. Click **計算低 q 平均並檢查五個配方**. Inspect the average curves, shell counts and block differences. Each recipe should have five complete shells.
4. Open **模型設定**. The example selects **Linear**, **RBF** and **Matérn 3/2**. Mean and ordinary linear baselines are always included. Matérn 5/2 and Rational Quadratic can also be selected.
5. Inspect the results, check **我已確認…**, and enter a brief review note. Click **執行五比例驗證與保存模型**.
6. Open **結果與紀錄**. The report provides regression curves, observed points, leave-one-recipe-out predictions, uncertainty diagnostics, error metrics and model comparisons. The three interior recipe coordinates and two endpoint extrapolations are reported separately.

Expected low-q values, **not model predictions**, for the bundled time window:

| Recipe label A:B | Numeric input A/(A+B) | Seed | Low-q mean |
|---|---:|---|---:|
| 1:21 | 0.0454545455 | 1 | 1.5067390033 |
| 5:17 | 0.2272727273 | 1 | 4.2543909431 |
| 8:14 | 0.3636363636 | 1 | 7.3684931166 |
| 11:11 | 0.5 | 1 | 9.7474411759 |
| 15:7 | 0.6818181818 | 1 | 10.3220692701 |

The material identities of particle types 1/2 and the physical basis of the recipe label are not confirmed. `A/(A+B)` is a declared recipe coordinate; concentration normalization uses actual particle counts from the simulation, independently of that coordinate. See [DATA_AND_METHODS.md](DATA_AND_METHODS.md).

## Reproduce without a browser

```sh
python run_example.py --out runtime --target low_q_shell_mean --kernels linear rbf matern_32
```

This runs the same Workbench analysis and training implementation used by the interface. Output includes `runtime/web_runs/<run_id>/condition/evaluation/report.html`. It does not call Drive or download raw coordinates.

To use M, either select M in the interface and set its window/band, import `examples/project_composition_strength.json`, or run:

```sh
python run_example.py --out runtime --target composition_strength
```

The q* option remains available. Weak or boundary peaks can fail its declared screening rules; the bundled data are not guaranteed to supply usable q* labels for all recipes. A failed physical screening result must not be bypassed simply to train a model.

## Full capabilities and optional inputs

[FEATURES.md](FEATURES.md) distinguishes interface functions, CLI functions, optional external inputs and work not implemented. This is the full platform, rather than a low-q-only demo.

- Targets: q*, mode-weighted composition fluctuation excess M, equal-shell normalized low-q mean.
- GP kernels: Linear, RBF, Matérn 3/2, Matérn 5/2, Rational Quadratic; shared fold-local scaling and two baselines.
- Inputs: derived CSVs, local raw position directories, optional read-only Google Drive.
- Raw processing: periodic orthorhombic-box Fourier modes, radial binning, concentration structure factor and partial correlation terms.
- Experiment preparation: independent SANS/SAXS weighted curves with user-supplied effective amplitudes or q-dependent tables. No experimental dataset is bundled.
- Separate condition and early-observation CLI training/prediction entry points. The current GUI trains condition models; it does not provide an arbitrary-new-ratio prediction form.
- Local project settings, history, report downloads and confirmed per-run deletion.

### Use a saved model from the CLI

Models are **JSON**, reconstructed with validated specifications and frozen parameters; no pickle/joblib deserialization is used. Use only artifacts you trust; a maliciously oversized JSON can still consume resources. Loading requires matching recorded scientific-library versions.

```sh
python predict_condition_gp.py --model runtime/web_runs/RUN_ID/condition/models/model__gp_ratio_rbf.json --queries examples/query_condition.csv --out runtime/new_predictions
```

Replace `RUN_ID` with the generated run identifier, and choose an available model file. The query example includes `query_id,ratio,task_kind`; input definitions must match the saved model. Early prediction is a separate contract, with an explicit observation window strictly before its target window. See `make_task_demo.py --help`, `train_early_gp.py --help`, and `predict_early_gp.py --help`.

### Optional Drive and raw data

Own local raw data require a file header `step N Lx Ly Lz`, then `x y z type` particle rows. The provided curves do not contain reconstructable raw positions or bonds.

Drive is optional. Supply your own Google desktop OAuth JSON and explicitly consent to `drive.readonly`, which is account-wide read access, not access limited to five folders. Tokens stay in the running process; no credentials are included. Keep your credentials outside this repository. Computation is local, raw frames are transferred to memory, and derived data are cached locally. This release has not been validated against a live Google account. No organizer needs this option for the bundled example.

## Outputs and deletion

The default output workspace is `runtime/`, excluded by `.gitignore`:

- `web_runs/<run_id>/`: training CSV, configuration, audit, models, predictions and evaluation.
- `web_reviews/<analysis_id>/`: independent target extraction reviews.
- `raw_runs/`, `raw_cache/`, `drive_cache/`, `scattering_runs/`, `web_examples/`: generated optional-feature data.

You can select another output directory with `python local_app.py --workspace /your/output/folder`. Absolute source paths and user-supplied notes appear in newly generated local audits; do not upload these outputs without a separate privacy review.

In the history list, **刪除紀錄** previews the exact run folder and size. **確認永久刪除** permanently removes that run, not its input data or other runs. There is no recycling-bin recovery. Failed or incomplete folders and independent reviews are not automatically removed.

## Security, provenance and licensing

- Read [SECURITY.md](SECURITY.md) and [SECURITY_REVIEW.md](SECURITY_REVIEW.md) before publishing or extending the service.
- `RELEASE_FILES.json` enumerates the public package. Private logs, caches, original models/reports, OAuth files and Git history are excluded. `.gitignore` alone is not a secret scanner.
- Example CSV bytes are unchanged from their supplied derived data. Cleaned manifests retain normalization, units, box geometry, q shells, direction counts and CSV hashes; original source identifiers are intentionally omitted. See `examples/PROVENANCE.json`.
- `RELEASE_SOURCE_FILES.json` records hashes of the original source files used as the release base. Release changes are documented; the private research working copy is separate.
- **No software or dataset open-source license has been chosen.** See [LICENSING.md](LICENSING.md) and confirm software/data distribution rights before making a repository public.

This folder is the GP Workbench component of the SimPilot repository. Only the contents of this release folder are published; the original research directory is not uploaded.
