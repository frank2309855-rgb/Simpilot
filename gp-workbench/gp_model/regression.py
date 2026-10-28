"""Report-only predictions; never used for held-out scoring or model selection."""
from statistics import NormalDist

import numpy as np


def regression_plot(model, rows, held_out):
    spec = model.spec
    points_by_id = {r["observation_id"]: r for r in rows}
    points = []
    for prediction in held_out:
        if prediction["model_id"] != spec["model_id"]:
            continue
        row = points_by_id[prediction["observation_id"]]
        points.append(dict(observation_id=row["observation_id"], ratio=row["ratio"],
                           ratio_label=row.get("ratio_label", ""), seed_id=row["seed_id"],
                           y_true=row["y_true"], pred_mean=prediction["pred_mean"],
                           pred_std=prediction["pred_std"], fold_id=prediction["fold_id"]))
    result = dict(model_id=spec["model_id"], label=spec["label"], kind=spec["kind"],
                  points=points, curve=[], available=False)
    if spec["inputs"] != ["ratio"]:
        result["reason"] = "此模型包含其他輸入；未指定其他輸入的取值，因此不繪製單一 ratio 回歸曲線。留出結果仍在下方評估圖中。"
        return result
    ratios = sorted({r["ratio"] for r in rows})
    grid = np.unique(np.r_[np.linspace(ratios[0], ratios[-1], 201), ratios])
    prediction = model.predict(grid.reshape(-1, 1))
    z = NormalDist().inv_cdf(.95)
    for x, mean, sd in zip(grid, prediction["pred_mean"], prediction["pred_std"]):
        result["curve"].append(dict(ratio=float(x), pred_mean=float(mean), pred_std=float(sd),
                                  lower_90=float(mean-z*sd), upper_90=float(mean+z*sd)))
    result.update(available=True, interval_level=.9,
                  curve_source="full_data_fit", point_source="leave_one_ratio_out",
                  interval_definition="Gaussian plug-in prediction interval for a new individual run; includes observation noise; not a confidence band for the mean.")
    return result
