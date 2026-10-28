"""Create reproducible synthetic examples; no GP is fitted by this script."""
from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from statistics import fmean

from gp_eval.core import save_csv


def demo_data():
    rng = random.Random(20261005)
    observations = []
    for i in range(9):
        ratio = .1 + i * .1
        truth_mean = .17 + .15 * ratio + .038 * math.tanh((ratio - .50) * 14)
        for s in range((3, 4, 3, 5, 4, 3, 4, 3, 5)[i]):
            observations.append(dict(observation_id=f"r{i+1:02}_s{s+1:02}", ratio=round(ratio, 2),
                                     seed_id=f"s{s+1:02}", y_true=truth_mean+rng.gauss(0, .009), target_n=1))
    ratios = sorted({r["ratio"] for r in observations})
    models = [
        dict(model_id="mean_baseline", label="平均值基準", inputs=["ratio"], kernel="none", kind="baseline",
             pipeline_id="constant_mean", fit_notes="Training-ratio balanced mean and Gaussian predictive approximation."),
        dict(model_id="linear_baseline", label="線性基準", inputs=["ratio"], kernel="none", kind="baseline",
             pipeline_id="linear_ols", fit_notes="OLS on training-ratio means; Gaussian predictive approximation, not a fitted GP."),
        dict(model_id="local_example", label="示範內插器", inputs=["ratio"], kernel="none", kind="illustrative",
             pipeline_id="local_interpolation", fit_notes="Two-neighbor linear interpolation; training-only seed noise estimate. Not a GP."),
        dict(model_id="confident_example", label="示範過度自信", inputs=["ratio"], kernel="none", kind="illustrative",
             pipeline_id="local_interpolation_sd_scaled", fit_notes="Same means as local_example, predictive SD multiplied by 0.18. Not a GP."),
    ]
    folds, predictions = [], []
    for i, ratio in enumerate(ratios):
        train = [r for r in observations if r["ratio"] != ratio]
        test = [r for r in observations if r["ratio"] == ratio]
        fid = f"hold_ratio_{i+1:02}"
        folds.append(dict(fold_id=fid, train_ids=[r["observation_id"] for r in train], test_ids=[r["observation_id"] for r in test]))
        tx = sorted({r["ratio"] for r in train})
        ty = [fmean(r["y_true"] for r in train if r["ratio"] == x) for x in tx]
        mx, my = fmean(tx), fmean(ty)
        sxx = sum((x-mx)**2 for x in tx)
        slope = sum((x-mx)*(y-my) for x, y in zip(tx, ty))/sxx
        intercept = my-slope*mx
        linear_mean = intercept+slope*ratio
        mean_var = fmean(fmean((r["y_true"]-my)**2 for r in train if r["ratio"] == x) for x in tx)
        linear_var = fmean(fmean((r["y_true"]-(intercept+slope*x))**2 for r in train if r["ratio"] == x) for x in tx)
        mean_sd = math.sqrt(mean_var*(1+1/len(tx)))
        linear_sd = math.sqrt(linear_var*(1+1/len(tx)+(ratio-mx)**2/sxx))
        below = [j for j, x in enumerate(tx) if x < ratio]
        above = [j for j, x in enumerate(tx) if x > ratio]
        j1, j2 = (below[-1], above[0]) if below and above else ((0, 1) if not below else (len(tx)-2, len(tx)-1))
        local_mean = ty[j1]+(ty[j2]-ty[j1])*(ratio-tx[j1])/(tx[j2]-tx[j1])
        noise_var = fmean(fmean((r["y_true"]-y)**2 for r in train if r["ratio"] == x) for x, y in zip(tx, ty))
        local_sd = math.sqrt(noise_var+(.05*(tx[j2]-tx[j1]))**2)
        distributions = dict(mean_baseline=(my, mean_sd), linear_baseline=(linear_mean, linear_sd),
                             local_example=(local_mean, local_sd), confident_example=(local_mean, local_sd*.18))
        for mid, (mu, sd) in distributions.items():
            for row in test:
                predictions.append(dict(model_id=mid, fold_id=fid, observation_id=row["observation_id"], pred_mean=mu, pred_std=sd))
    protocol = dict(schema_version="1.1", dataset_label="合成資料示範 · 9 ratios / 34 targets",
                    data_kind="synthetic_demo",
                    target=dict(evaluator="q_peak", name="q_peak", units="nm^-1 (synthetic)", observation_time="Synthetic fixed observation time; not a research value",
                                extraction_order="synthetic_scalar",
                                extraction_rule="Synthetic scalar from a smooth transition function plus independent Gaussian noise; no trajectory extraction",
                                estimand="individual_run", distribution="gaussian_physical_scale", predictive_sd="observed_target"),
                    validation=dict(scheme="leave_one_ratio_out", preprocessing="training_only", inputs_available_at_prediction_time=True,
                                    selection_context="exploratory", fit_selection_protocol="Deterministic, training-only illustrative forecasts. No GP training or hyperparameter search."),
                    practical_thresholds=dict(mae_improvement=None, crps_improvement=None, acceptable_mae=None),
                    baseline_ids=["mean_baseline", "linear_baseline"], models=models, folds=folds)
    protocol["dataset_label"] = f"合成資料示範 · {len(ratios)} ratios / {len(observations)} targets"
    return observations, predictions, protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="New example-data directory")
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        parser.error("Choose a new directory; existing data will not be overwritten.")
    obs, pred, protocol = demo_data()
    out.mkdir(parents=True)
    save_csv(out / "observations.csv", obs)
    save_csv(out / "predictions.csv", pred)
    (out / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Synthetic demonstration written to {out}")


if __name__ == "__main__":
    main()
