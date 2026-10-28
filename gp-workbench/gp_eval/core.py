"""Metric definitions, strict input validation, and paired descriptive comparisons.

All means across ratios are macro averages: each ratio has the same weight.
This module never trains a GP and cannot verify the provenance of submitted fits.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, fmean

from .targets import get_target
from .validation import ValidationError, require, number, nonempty

LEVELS = (50, 80, 90)
NORMAL = NormalDist()


def load_csv(path, required, optional=()):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        require(len(headers) == len(set(headers)), f"{path}: duplicate column names")
        require(set(required) <= set(headers), f"{path}: required columns: {', '.join(required)}")
        require(set(headers) <= set(required) | set(optional), f"{path}: unexpected columns")
        rows = list(reader)
    require(bool(rows), f"{path}: no data rows")
    require(all(None not in row for row in rows), f"{path}: too many values in a CSV row")
    return rows


def load_inputs(observations_path, predictions_path, protocol_path):
    with Path(protocol_path).open(encoding="utf-8-sig") as stream:
        protocol = json.load(stream)
    observations = load_csv(observations_path,
                            ("observation_id", "ratio", "seed_id", "y_true", "target_n"))
    predictions = load_csv(predictions_path,
                           ("model_id", "fold_id", "observation_id", "pred_mean", "pred_std"))
    return observations, predictions, protocol


def validate(observations, predictions, protocol):
    require(isinstance(protocol, dict), "protocol must be an object")
    require(protocol.get("schema_version") in ("1.0", "1.1"), "schema_version must be 1.0 or 1.1")
    nonempty(protocol.get("dataset_label"), "dataset_label")
    require(protocol.get("data_kind") in ("real", "synthetic_demo"), "data_kind must be real or synthetic_demo")
    evaluator = get_target(protocol)
    target = protocol["target"]
    evaluator.validate_definition(target, protocol)
    kind = target.get("estimand")
    validation = protocol.get("validation", {})
    require(isinstance(validation, dict), "validation must be an object")
    require(validation.get("scheme") == "leave_one_ratio_out", "requires leave_one_ratio_out")
    require(validation.get("preprocessing") == "training_only", "preprocessing must be declared training_only")
    require(validation.get("inputs_available_at_prediction_time") is True,
            "inputs_available_at_prediction_time must be declared true")
    require(validation.get("selection_context") in ("exploratory", "predeclared", "nested"),
            "selection_context must be exploratory, predeclared, or nested")
    nonempty(validation.get("fit_selection_protocol"), "validation.fit_selection_protocol")
    thresholds = protocol.get("practical_thresholds", {})
    require(isinstance(thresholds, dict), "practical_thresholds must be an object")
    require(set(thresholds) <= {"mae_improvement", "crps_improvement", "acceptable_mae"}, "unknown practical threshold name")
    for key in ("mae_improvement", "crps_improvement", "acceptable_mae"):
        if thresholds.get(key) is not None:
            require(number(thresholds[key], key) >= 0, f"{key} must be nonnegative")

    models = protocol.get("models")
    require(isinstance(models, list) and len(models) >= 2, "at least two model specifications are required")
    model_map = {}
    for model in models:
        require(isinstance(model, dict), "each model must be an object")
        mid = nonempty(model.get("model_id"), "model_id")
        require(mid not in model_map, f"duplicate model_id: {mid}")
        for key in ("label", "kernel", "pipeline_id", "fit_notes"):
            nonempty(model.get(key), f"{mid}.{key}")
        inputs = model.get("inputs")
        require(isinstance(inputs, list) and bool(inputs), f"{mid}.inputs must be a nonempty list")
        for item in inputs:
            nonempty(item, f"{mid}.input")
        require(len(inputs) == len(set(inputs)), f"{mid}: duplicate input names")
        require(model.get("kind") in ("gp", "baseline", "illustrative"), f"{mid}: unknown model kind")
        model_map[mid] = model
    baselines = protocol.get("baseline_ids")
    require(isinstance(baselines, list) and bool(baselines), "baseline_ids must identify at least one model")
    require(len(baselines) == len(set(baselines)), "duplicate baseline_ids")
    require(all(mid in model_map and model_map[mid]["kind"] == "baseline" for mid in baselines),
            "every baseline_id must identify a declared baseline model")

    obs_map, seen_seeds = {}, set()
    by_ratio = defaultdict(set)
    for raw in observations:
        oid = nonempty(raw.get("observation_id"), "observation_id")
        require(oid not in obs_map, f"duplicate observation_id: {oid}")
        ratio = number(raw.get("ratio"), f"{oid}.ratio")
        y = number(raw.get("y_true"), f"{oid}.y_true")
        evaluator.validate_observation(y, oid)
        seed = nonempty(raw.get("seed_id"), f"{oid}.seed_id")
        n = number(raw.get("target_n"), f"{oid}.target_n")
        require(n.is_integer() and n >= 1, f"{oid}: target_n must be a positive integer")
        if kind == "individual_run":
            require(n == 1, f"{oid}: individual_run requires target_n=1")
            require((ratio, seed) not in seen_seeds, f"{oid}: duplicate seed within ratio")
            seen_seeds.add((ratio, seed))
        else:
            require(n >= 2, f"{oid}: observed_seed_mean requires target_n>=2")
        obs_map[oid] = dict(observation_id=oid, ratio=ratio, seed_id=seed, y_true=y, target_n=int(n))
        by_ratio[ratio].add(oid)
    require(len(by_ratio) >= 2, "at least two distinct ratios are required")
    if kind == "observed_seed_mean":
        require(all(len(ids) == 1 for ids in by_ratio.values()), "observed_seed_mean requires exactly one target row per ratio")

    folds = protocol.get("folds")
    require(isinstance(folds, list) and bool(folds), "folds must list train_ids and test_ids")
    fold_map, expected_fold = {}, {}
    all_ids = set(obs_map)
    for fold in folds:
        require(isinstance(fold, dict), "each fold must be an object")
        fid = nonempty(fold.get("fold_id"), "fold_id")
        require(fid not in fold_map, f"duplicate fold_id: {fid}")
        for key in ("train_ids", "test_ids"):
            ids = fold.get(key)
            require(isinstance(ids, list) and bool(ids), f"{fid}.{key} must be a nonempty list")
            require(all(isinstance(x, str) for x in ids), f"{fid}.{key}: IDs must be strings")
            require(len(ids) == len(set(ids)), f"{fid}.{key}: repeated IDs")
            require(set(ids) <= all_ids, f"{fid}.{key}: unknown observation IDs")
        train, test = set(fold["train_ids"]), set(fold["test_ids"])
        require(not train & test, f"{fid}: train/test overlap")
        ratios = {obs_map[oid]["ratio"] for oid in test}
        require(len(ratios) == 1, f"{fid}: test must contain exactly one ratio")
        ratio = next(iter(ratios))
        require(test == by_ratio[ratio], f"{fid}: all seeds of the held-out ratio must be tested together")
        require(train == all_ids - test, f"{fid}: LORO training IDs must equal all other ratios")
        require(not set(expected_fold) & test, f"{fid}: repeated test observations across folds")
        train_ratios = [obs_map[oid]["ratio"] for oid in train]
        scope = "ratio_interpolation" if min(train_ratios) < ratio < max(train_ratios) else "ratio_extrapolation"
        fold_map[fid] = dict(fold_id=fid, ratio=ratio, scope=scope)
        for oid in test:
            expected_fold[oid] = fid
    require(set(expected_fold) == all_ids, "every observation must be held out exactly once")

    records, seen = [], set()
    for raw in predictions:
        mid, fid, oid = (nonempty(raw.get(key), key) for key in ("model_id", "fold_id", "observation_id"))
        require(mid in model_map, f"unknown model_id: {mid}")
        require(oid in obs_map, f"unknown observation_id: {oid}")
        require(fid == expected_fold[oid], f"{mid}/{oid}: prediction fold does not match held-out observation")
        require((mid, oid) not in seen, f"duplicate prediction: {mid}/{oid}")
        seen.add((mid, oid))
        mu = number(raw.get("pred_mean"), f"{mid}/{oid}.pred_mean")
        sd = number(raw.get("pred_std"), f"{mid}/{oid}.pred_std")
        require(sd > 0, f"{mid}/{oid}: pred_std must be strictly positive")
        records.append({**obs_map[oid], **fold_map[fid], "model_id": mid, "pred_mean": mu, "pred_std": sd})
    require(seen == set(itertools.product(model_map, obs_map)),
            "models must predict the identical complete target set; missing/failed predictions cannot be silently dropped")
    return records, model_map


def normal_metrics(y, mu, sd):
    require(all(math.isfinite(x) for x in (y, mu, sd)) and sd > 0, "invalid Gaussian parameters")
    error = mu - y
    z = (y - mu) / sd
    require(math.isfinite(z), "standardized residual overflow; verify prediction scale and pred_std")
    a = abs(z)
    phi = math.exp(-0.5 * a * a) / math.sqrt(2 * math.pi)
    # Phi(-a) is evaluated via erfc to retain accuracy near zero and in tails.
    crps = abs(error) * math.erf(a / math.sqrt(2)) + sd * (2 * phi - 1 / math.sqrt(math.pi))
    values = dict(error=error, abs_error=abs(error), squared_error=error * error,
                  crps=max(0.0, crps), nlpd=0.5 * math.log(2 * math.pi) + math.log(sd) + 0.5 * z * z,
                  z=z, z_squared=z*z, pit=0.5 * math.erfc(-z / math.sqrt(2)))
    for level in LEVELS:
        radius = NORMAL.inv_cdf((1 + level / 100) / 2) * sd
        lower, upper = mu - radius, mu + radius
        values.update({f"lower_{level}": lower, f"upper_{level}": upper,
                       f"coverage_{level}": float(lower <= y <= upper), f"width_{level}": 2 * radius})
    require(all(math.isfinite(v) for v in values.values()), "metric overflow; verify physical units and predictive uncertainty")
    return values


def aggregate(records):
    """One row per ratio before pooling: RMSE = sqrt(macro mean of MSE)."""
    out = {name: fmean(row[source] for row in records) for name, source in (
        ("mae", "abs_error"), ("mse", "squared_error"), ("bias", "error"),
        ("crps", "crps"), ("nlpd", "nlpd"), ("z_mean", "z"), ("z_second", "z_squared"))}
    out["rmse"] = math.sqrt(out["mse"])
    out["z_std"] = math.sqrt(max(0, out["z_second"] - out["z_mean"] ** 2))
    for level in LEVELS:
        for name in ("coverage", "width"):
            key = f"{name}_{level}"
            out[key] = fmean(row[key] for row in records)
    out["max_abs_error"] = max(row["abs_error"] for row in records)
    out["n_observations"] = len(records)
    return out


def summarize(ratio_rows):
    result = {key: fmean(row[key] for row in ratio_rows) for key in (
        "mae", "mse", "bias", "crps", "nlpd", "z_mean", "z_second",
        *(f"{name}_{level}" for level in LEVELS for name in ("coverage", "width")))}
    result["rmse"] = math.sqrt(result["mse"])
    result["z_std"] = math.sqrt(max(0, result["z_second"] - result["z_mean"] ** 2))
    result["n_ratios"] = len(ratio_rows)
    result["n_observations"] = sum(row["n_observations"] for row in ratio_rows)
    result["worst_ratio_mae"] = max(row["mae"] for row in ratio_rows)
    result["max_abs_error"] = max(row["max_abs_error"] for row in ratio_rows)
    return result


def add_target_metrics(common, extra):
    """Extensions may add diagnostics, never overwrite shared scoring or IDs."""
    require(not set(common) & set(extra), "target metrics cannot overwrite common fields")
    for key, value in extra.items():
        require(value is None or (isinstance(value, (int, float)) and math.isfinite(value)),
                f"target metric {key}: expected finite number or None")
    common.update(extra)
    return common


def attribution(a, b):
    if a["pipeline_id"] != b["pipeline_id"]:
        return "pipeline_or_multiple_changes"
    same_inputs = set(a["inputs"]) == set(b["inputs"])
    same_kernel = a["kernel"] == b["kernel"]
    if same_inputs and not same_kernel:
        return "kernel_only_as_declared"
    if same_kernel and not same_inputs:
        return "input_set_only_as_declared"
    if same_kernel and same_inputs:
        return "same_declared_specification"
    return "input_and_kernel_changes"


def relation(a, b):
    d_mae, d_crps = a["mae"] - b["mae"], a["crps"] - b["crps"]
    if d_mae == 0 and d_crps == 0:
        return "equal_on_observed_primary_metrics"
    if d_mae <= 0 and d_crps <= 0:
        return "A_descriptively_dominates"
    if d_mae >= 0 and d_crps >= 0:
        return "B_descriptively_dominates"
    return "tradeoff"


def evaluate(observations, predictions, protocol):
    records, models = validate(observations, predictions, protocol)
    evaluator = get_target(protocol)
    for row in records:
        try:
            row.update(normal_metrics(row["y_true"], row["pred_mean"], row["pred_std"]))
            add_target_metrics(row, evaluator.observation_metrics(row["y_true"], row["pred_mean"], row["pred_std"]))
        except (ValueError, OverflowError) as exc:
            raise ValidationError(f"{row['model_id']}/{row['observation_id']}: {exc}") from exc
    records.sort(key=lambda r: (r["model_id"], r["ratio"], r["observation_id"]))
    groups = defaultdict(list)
    for row in records:
        groups[row["model_id"], row["ratio"]].append(row)
    ratio_rows = []
    for (mid, ratio), rows in sorted(groups.items()):
        row = dict(model_id=mid, ratio=ratio, fold_id=rows[0]["fold_id"], scope=rows[0]["scope"], **aggregate(rows))
        ratio_rows.append(add_target_metrics(row, evaluator.aggregate(rows)))
    summaries = []
    thresholds = protocol.get("practical_thresholds", {})
    for scope in ("ratio_interpolation", "ratio_extrapolation", "all_supplementary"):
        for mid in sorted(models):
            selected = [r for r in ratio_rows if r["model_id"] == mid and (scope == "all_supplementary" or r["scope"] == scope)]
            if not selected:
                continue
            row = dict(scope=scope, model_id=mid, **summarize(selected))
            add_target_metrics(row, evaluator.summarize(selected))
            threshold = thresholds.get("acceptable_mae")
            row["mae_tolerance_status"] = "not_configured" if threshold is None else ("observed_mean_within_tolerance" if row["mae"] <= float(threshold) else "observed_mean_exceeds_tolerance")
            summaries.append(row)
    pairs, pair_ratios = [], []
    for scope in ("ratio_interpolation", "ratio_extrapolation", "all_supplementary"):
        scoped = {r["model_id"]: r for r in summaries if r["scope"] == scope}
        for a, b in itertools.combinations(sorted(scoped), 2):
            pa, pb = scoped[a], scoped[b]
            entry = dict(scope=scope, model_a=a, model_b=b, n_ratios=pa["n_ratios"],
                         relation=relation(pa, pb), attribution=attribution(models[a], models[b]),
                         includes_baseline=a in protocol["baseline_ids"] or b in protocol["baseline_ids"])
            for metric in ("mae", "crps", "rmse", "nlpd"):
                entry[f"delta_{metric}_a_minus_b"] = pa[metric] - pb[metric]
            da, dc = thresholds.get("mae_improvement"), thresholds.get("crps_improvement")
            dm, dp = entry["delta_mae_a_minus_b"], entry["delta_crps_a_minus_b"]
            if da is None or dc is None:
                practical = "thresholds_not_configured"
            elif abs(dm) <= float(da) and abs(dp) <= float(dc):
                practical = "observed_differences_within_declared_bounds"
            elif dm <= float(da) and dp <= float(dc) and (dm < -float(da) or dp < -float(dc)):
                practical = "observed_practical_advantage_A"
            elif dm >= -float(da) and dp >= -float(dc) and (dm > float(da) or dp > float(dc)):
                practical = "observed_practical_advantage_B"
            else:
                practical = "practical_tradeoff"
            entry["practical_comparison"] = practical
            ra = {r["ratio"]: r for r in ratio_rows if r["model_id"] == a and (scope == "all_supplementary" or r["scope"] == scope)}
            rb = {r["ratio"]: r for r in ratio_rows if r["model_id"] == b and (scope == "all_supplementary" or r["scope"] == scope)}
            differences = []
            for ratio in sorted(ra):
                item = dict(scope=scope, model_a=a, model_b=b, ratio=ratio)
                for metric in ("mae", "crps", "nlpd"):
                    item[f"delta_{metric}_a_minus_b"] = ra[ratio][metric] - rb[ratio][metric]
                pair_ratios.append(item)
                differences.append(item)
            for metric in ("mae", "crps"):
                values = [r[f"delta_{metric}_a_minus_b"] for r in differences]
                # Sensitivity of the SUMMARY only; no model refitting and no CI.
                omit = [fmean(values[:i] + values[i+1:]) for i in range(len(values))] if len(values) >= 2 else []
                entry[f"omit_one_ratio_delta_{metric}_min"] = min(omit) if omit else None
                entry[f"omit_one_ratio_delta_{metric}_max"] = max(omit) if omit else None
                entry[f"omit_one_ratio_{metric}_sign_flip"] = (min(omit) < 0 < max(omit)) if omit else None
            pairs.append(entry)
        for row in scoped.values():
            row["on_descriptive_pareto_front"] = not any(
                other["mae"] <= row["mae"] and other["crps"] <= row["crps"] and
                (other["mae"] < row["mae"] or other["crps"] < row["crps"])
                for other in scoped.values())
    warnings = [
        "已檢查提交的 train/test 名單；實際模型擬合與前處理的來源尚未獨立驗證。",
        "插值／外插標籤只針對 precursor ratio；其他 input 維度仍可能超出訓練範圍。",
        "指標與 Pareto 關係僅供描述。重疊的 CV folds 不等於獨立試驗；本報告沒有 p 值、信賴區間或統計等價結論。",
        "使用本報告選模後，仍需要巢狀選模流程或新的 held-out ratios 確認表現。",
    ]
    warnings.extend(evaluator.warnings(protocol, records))
    if protocol["data_kind"] == "synthetic_demo":
        warnings.insert(0, "合成資料示範：數值不代表真實研究資料或已訓練 GP 的表現。")
    if thresholds.get("mae_improvement") is None or thresholds.get("crps_improvement") is None:
        warnings.append("尚未設定完整的實務改善門檻，故不進行實務等價判定。")
    if protocol["target"]["estimand"] == "observed_seed_mean":
        warnings.append("本次評估有限 seeds 的樣本平均；它仍有抽樣變異，pred_std 必須對應 target_n，不能視為無噪音的族群平均。")
    return dict(protocol=protocol, target_evaluation=evaluator.describe(protocol["target"]),
                observations=records, by_ratio=ratio_rows, summary=summaries,
                pairwise=pairs, paired_by_ratio=pair_ratios, warnings=warnings)


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_csv(path, rows):
    require(bool(rows), f"no rows to write: {path}")
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
