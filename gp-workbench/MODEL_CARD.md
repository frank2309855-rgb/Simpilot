# Model card: recipe-to-low-q Gaussian Process demonstration

## Identity and intended use

This condition-prediction benchmark in the APCN Gaussian Process Workbench maps a declared recipe coordinate to a structural target and compares GP candidates with simple baselines. It supports exploratory analysis and reproducibility review, not automated scientific acceptance or process control.

The workbench separately implements q* and composition-fluctuation-excess M. This numerical benchmark covers **low-q mean only**. Other targets do not inherit these scores.

## Inputs, outputs and data

| Item | Contract |
|---|---|
| Input | One continuous feature, `ratio = A/(A+B)` |
| Benchmark input range | 0.0454545455-0.6818181818 |
| Training data | Five supplied real derived S(q,t) curves, one seed per recipe |
| Recipe labels | 1:21, 5:17, 8:14, 11:11, 15:7 |
| Target | Time-average normalized concentration structure factor, then equal mean of five complete nonzero shells |
| Target window / band | Steps 1490-1499; `0 < q <= 0.11` inverse simulation length |
| Output | Predictive mean and Gaussian observed-target standard deviation, dimensionless |
| Validation | Five leave-one-ratio-out folds: four training rows, one held-out row |
| Task | Stage-1 condition prediction, separate from early-trajectory / cross-stage prediction |

The coordinate is not confirmed to be a physical bead/volume/chain fraction. Particle type 1/2 material identities remain unconfirmed. Concentration normalization uses actual particle counts separately from the recipe coordinate. Ten adjacent frames and two time blocks do not increase the training sample count.

## Construction and training

GP covariance is `signal_variance * signal_kernel + WhiteKernel(noise_variance)`, with `alpha = 1e-10` numerical jitter. X is standardized using training-fold mean/standard deviation. GP y is centered/scaled using the training-fold population mean/standard deviation; predictions return to original units.

| Candidate | Signal kernel / initial specification |
|---|---|
| Linear GP | DotProduct with fixed `sigma_0 = 1` in standardized input space |
| RBF GP | Initial length scale 1, optimized within `[0.01, 100]` |
| Matern 3/2 GP | `nu = 1.5`; initial length scale 1, optimized within `[0.01, 100]` |
| Mean baseline | Training mean with Gaussian plug-in predictive uncertainty |
| Linear baseline | Ordinary least squares with intercept, residual and coefficient uncertainty |

Signal variance starts at 1 within `[0.001, 1000]`; noise variance starts at 0.05 within `[1e-6, 1]` in standardized-target units. Optimization uses scikit-learn L-BFGS-B log marginal likelihood with two restarts. The benchmark base random state is **20261020**; zero-based fold i adds i. Full-data fits use the base state. Exact specifications are in [fit_details.json](benchmarks/five_recipe_low_q/fit_details.json).

Baselines use residual degrees of freedom and the declared variance floor. Their intervals are Gaussian approximations, not Student-t intervals. Matern 5/2 and Rational Quadratic are also selectable in the GUI but were not run in this benchmark.

## Full-data covariance summaries

These fits use all five observations and do not supply validation scores. Rounded strings below refer to standardized inputs/targets. Exact log-parameters (`theta`), scaling and original-scale noise variance are in [fit_details.json](benchmarks/five_recipe_low_q/fit_details.json).

| Model | Rounded fitted covariance |
|---|---|
| Linear GP | `0.674**2 * DotProduct(sigma_0=1) + WhiteKernel(noise_level=0.0922)` |
| RBF GP | `1.17**2 * RBF(length_scale=1.64) + WhiteKernel(noise_level=1e-06)` |
| Matérn 3/2 GP | `1.56**2 * Matern(length_scale=3.43, nu=1.5) + WhiteKernel(noise_level=1e-06)` |

## Evaluation and uncertainty

[Recorded benchmark](BENCHMARK.md) includes score tables, figures and all 25 held-out predictions. Interior interpolation (3 recipes), endpoint extrapolation (2 recipes) and the supplementary pooled summary stay distinct. All candidates share folds with training-only preprocessing/optimization.

Metrics include MAE, RMSE, bias, Gaussian CRPS/NLPD, residual and interval diagnostics, plus Gaussian mass below the nonnegative target domain. Intervals condition on fitted hyperparameters; no hyperparameter posterior is integrated. One seed per recipe does not identify between-seed variability independently.

RBF has the smallest recorded errors on this dataset. Selection is exploratory, no acceptance threshold was configured and no independent confirmation is supplied. Twelve RBF/Matern noise lower-bound warnings are preserved; these do not prove zero simulation noise.

## Uses and limits

Use this example to inspect target checks, model comparison and provenance. New predictions require the same scientific definitions and user judgment. Endpoint leave-out results do not justify arbitrary distant extrapolation.

The benchmark does not validate equilibrium, morphology/connectivity, material identity, new seeds, other stages, experimental scattering agreement, MD savings or agent latency. q* or low-q magnitude alone does not establish phase separation. Stage-1-to-stage-3 prediction and autonomous agent orchestration remain future work.

## Reproduction, artifacts and privacy

Runtime: Python 3.13.9, NumPy 2.3.5, SciPy 1.16.3, scikit-learn 1.7.2; full requirements are pinned. [metadata.json](benchmarks/five_recipe_low_q/metadata.json) records data/code fingerprints.

This package includes readable fit specifications/diagnostics, not preloaded trained models. Running the example generates validated JSON model artifacts locally; [README.md](README.md) describes CLI prediction. No pickle/joblib loading is used. Private reports, local paths, Drive identities, credentials and raw trajectories are excluded.

Read [LICENSING.md](LICENSING.md) before public distribution. No software or dataset open-source license has been selected.
