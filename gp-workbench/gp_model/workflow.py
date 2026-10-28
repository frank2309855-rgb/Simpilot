"""Leave-one-ratio-out experiments, final fits, safe JSON checkpoints and prediction."""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist
from time import perf_counter

import numpy as np
import scipy
import sklearn

from evaluate import run as run_evaluation, staging_directory
from gp_eval.core import save_csv, sha256
from gp_eval.report import render_report
from gp_eval.targets import get_target
from gp_eval.validation import ValidationError, nonempty, number, require
from . import __version__
from .kernels import build_kernel
from .models import FittedModel, training_settings
from .regression import regression_plot
from .tasks import (ROW_METADATA, describe, expected_task, task_directory,
                    validate_row, validate_task)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def versions():
    return dict(gp_model=__version__, python=platform.python_version(), numpy=np.__version__,
                scipy=scipy.__version__, sklearn=sklearn.__version__)


def read_table(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = reader.fieldnames or []
        require(len(headers) == len(set(headers)), "duplicate CSV headers")
        require(set(required) <= set(headers), f"missing CSV columns: {set(required)-set(headers)}")
        rows = list(reader)
    require(bool(rows), "CSV contains no data rows")
    require(all(None not in row for row in rows), "extra values in CSV row")
    return rows


def normalize_config(config):
    require(isinstance(config, dict), "GP config must be an object")
    allowed = {"gp_config_version", "dataset_label", "data_kind", "target", "feature_definitions",
               "models", "baseline_inputs", "training", "selection_context", "practical_thresholds", "prediction_task"}
    require(not set(config)-allowed, f"unknown config fields: {set(config)-allowed}")
    require(config.get("gp_config_version") in ("1.0", "1.1"), "gp_config_version must be 1.0 or 1.1")
    if config["gp_config_version"] == "1.0":
        require("prediction_task" not in config, "prediction_task requires gp_config_version 1.1")
    config = copy.deepcopy(config)
    nonempty(config.get("dataset_label"), "dataset_label")
    require(config.get("data_kind") in ("real", "synthetic_demo"), "data_kind must be real or synthetic_demo")
    target = config.get("target")
    require(isinstance(target, dict), "target must be an object")
    nonempty(target.get("column"), "target.column")
    definition = dict(schema_version="1.1", data_kind=config["data_kind"], target=target)
    get_target(definition).validate_definition(target, definition)
    require(target["estimand"] == "individual_run",
            "GP training v0.1 supports individual_run only; do not pass seed means as individual runs")
    require(target["column"] not in {"observation_id", "ratio", "seed_id", "target_n"},
            "target column cannot be an identity/grouping field")
    context = config.get("selection_context", "exploratory")
    require(context in ("exploratory", "predeclared"), "trainer supports exploratory or predeclared, not nested selection")
    config["selection_context"] = context
    config["training"] = training_settings(config.get("training"))
    config.setdefault("practical_thresholds", {})
    thresholds = config["practical_thresholds"]
    require(isinstance(thresholds, dict) and not set(thresholds)-{"mae_improvement", "crps_improvement", "acceptable_mae"},
            "invalid practical_thresholds")
    for key, value in thresholds.items():
        if value is not None:
            require(number(value, key) >= 0, f"{key} must be nonnegative")
    config.setdefault("baseline_inputs", ["ratio"])
    definitions = config.get("feature_definitions")
    require(isinstance(definitions, dict), "feature_definitions required")

    def check_features(inputs):
        require(isinstance(inputs, list) and bool(inputs), "inputs must be a nonempty list")
        for name in inputs:
            nonempty(name, "input name")
            require(name not in {target["column"], "observation_id", "seed_id", "target_n"} | ROW_METADATA,
                    f"identity/target field cannot be used as input: {name}")
            entry = definitions.get(name)
            require(isinstance(entry, dict) and entry.get("available_at_prediction") is True,
                    f"feature {name}: available_at_prediction must be declared true")
            nonempty(entry.get("description"), f"feature {name}.description")
        require(len(inputs) == len(set(inputs)), "duplicate input names")

    check_features(config["baseline_inputs"])
    specs = config.get("models")
    require(isinstance(specs, list) and bool(specs), "at least one GP model required")
    seen = {"baseline_mean", "baseline_linear"}
    for spec in specs:
        require(isinstance(spec, dict) and not set(spec)-{"model_id", "label", "inputs", "kernel"}, "invalid GP model specification")
        mid = nonempty(spec.get("model_id"), "model_id")
        require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", mid) is not None, "model_id must be a short ASCII identifier")
        require(mid not in seen, f"duplicate/reserved model_id: {mid}")
        seen.add(mid)
        nonempty(spec.get("label"), f"{mid}.label")
        check_features(spec.get("inputs"))
        build_kernel(spec.get("kernel"), len(spec["inputs"]))
    if config["gp_config_version"] == "1.1":
        config["prediction_task"] = validate_task(config.get("prediction_task"), definitions, specs)
        # The linear baseline may use condition-only features, but cannot use undeclared ones.
        validate_task(config["prediction_task"], definitions,
                      [dict(kind="linear", inputs=config["baseline_inputs"])])
    return config


def model_specs(config):
    specs = [dict(spec, kind="gp") for spec in config["models"]]
    specs.extend([dict(model_id="baseline_mean", label="平均值基準", kind="mean", inputs=config["baseline_inputs"]),
                  dict(model_id="baseline_linear", label="線性基準", kind="linear", inputs=config["baseline_inputs"])])
    return specs


def load_training_rows(path, config):
    features = sorted({name for spec in model_specs(config) for name in spec["inputs"]})
    target = config["target"]
    evaluator = get_target(dict(schema_version="1.1", target=target))
    raw = read_table(path, ["observation_id", "ratio", "seed_id", target["column"], *features])
    task = config.get("prediction_task")
    rows, seen, seeds = [], set(), set()
    for row in raw:
        oid = nonempty(row["observation_id"], "observation_id")
        if task:
            validate_row(row, task, oid)
        else:
            require(row.get("task_kind") in (None, ""), "task-marked data requires explicit prediction_task config")
        seed = nonempty(row["seed_id"], f"{oid}.seed_id")
        ratio = number(row["ratio"], f"{oid}.ratio")
        require(oid not in seen and (ratio, seed) not in seeds, f"duplicate observation or seed within ratio: {oid}")
        seen.add(oid)
        seeds.add((ratio, seed))
        y = number(row[target["column"]], f"{oid}.{target['column']}")
        evaluator.validate_observation(y, oid)
        require(number(row.get("target_n", 1), f"{oid}.target_n") == 1, "individual_run requires target_n=1 (not frame count)")
        clean = dict(observation_id=oid, ratio=ratio, seed_id=seed, target_n=1, y_true=y)
        if row.get("amount_a") not in (None, "") and row.get("amount_b") not in (None, ""):
            a = number(row["amount_a"], f"{oid}.amount_a")
            b = number(row["amount_b"], f"{oid}.amount_b")
            clean["ratio_label"] = f"{a:g}:{b:g}"
        clean["features"] = {name: number(row[name], f"{oid}.{name}") for name in features}
        rows.append(clean)
    require(len({row["ratio"] for row in rows}) >= 3,
            "this experiment requires at least three ratios for grouped validation and linear baseline")
    return sorted(rows, key=lambda row: (row["ratio"], row["observation_id"]))


def matrix(rows, features):
    return np.asarray([[row["features"][name] for name in features] for row in rows], dtype=float)


def make_protocol(config, rows, folds, specs):
    target = {key: value for key, value in config["target"].items() if key != "column"}
    task = config.get("prediction_task")
    pipeline_hash = hashlib.sha256(json.dumps(dict(training=config["training"], task=task), sort_keys=True).encode()).hexdigest()[:12]
    models = []
    for spec in specs:
        is_gp = spec["kind"] == "gp"
        models.append(dict(model_id=spec["model_id"], label=spec["label"],
                           inputs=spec["inputs"] if spec["kind"] != "mean" else ["constant_intercept"],
                           kernel=json.dumps(spec["kernel"], sort_keys=True) if is_gp else "none",
                           kind="gp" if is_gp else "baseline", pipeline_id=f"{spec['kind']}_{pipeline_hash}",
                           fit_notes=("Fold-local X scaling and y scaling; constant mean, signal amplitude plus learned "
                                      "homoscedastic WhiteKernel; LML optimization on training only; observed-target SD; "
                                      "hyperparameter uncertainty not integrated." if is_gp else
                                      "Training-only Gaussian plug-in approximation with residual and coefficient uncertainty; "
                                      "mean baseline ignores features. Not a Student-t predictive distribution.")))
    label = (describe(task) + "｜" + config["dataset_label"]) if task else config["dataset_label"]
    return dict(schema_version="1.1", dataset_label=label, data_kind=config["data_kind"], target=target,
                validation=dict(scheme="leave_one_ratio_out", preprocessing="training_only",
                    inputs_available_at_prediction_time=True, selection_context=config["selection_context"],
                    fit_selection_protocol="Each held-out ratio excludes all its seeds. Kernel and noise optimized only on remaining rows. "
                        "No automatic winner or nested selection. Final models fit all rows separately from held-out evaluation."),
                practical_thresholds=config["practical_thresholds"], models=models,
                baseline_ids=["baseline_mean", "baseline_linear"], folds=folds)


def train_experiment(data_path, config_path, out, progress=None, expected_kind=None):
    config = normalize_config(json.loads(Path(config_path).read_text(encoding="utf-8-sig")))
    task = config.get("prediction_task")
    expected_task(task, expected_kind)
    out = task_directory(out, task)
    require(not out.exists(), "output already exists; choose a new directory")
    rows = load_training_rows(data_path, config)
    specs = model_specs(config)
    ratios = sorted({row["ratio"] for row in rows})
    folds = [dict(fold_id=f"hold_ratio_{i+1:02}",
                  train_ids=[r["observation_id"] for r in rows if r["ratio"] != ratio],
                  test_ids=[r["observation_id"] for r in rows if r["ratio"] == ratio]) for i, ratio in enumerate(ratios)]
    protocol = make_protocol(config, rows, folds, specs)
    held_out, uncertainty, logs = [], [], []
    for i, (ratio, fold) in enumerate(zip(ratios, folds)):
        train = [row for row in rows if row["ratio"] != ratio]
        test = [row for row in rows if row["ratio"] == ratio]
        for spec in specs:
            if progress:
                progress(f"Fold {i+1}/{len(ratios)} | held-out ratio={ratio:g} | {spec['model_id']}")
            settings = dict(config["training"], random_state=(config["training"]["random_state"]+i) % 2**32)
            start = perf_counter()
            model = FittedModel(spec, settings).fit(matrix(train, spec["inputs"]), [row["y_true"] for row in train])
            fitted = perf_counter()
            predictions = model.predict(matrix(test, spec["inputs"]))
            predicted = perf_counter()
            logs.append(dict(model_id=spec["model_id"], fold_id=fold["fold_id"], train_ids=fold["train_ids"],
                             test_ids=fold["test_ids"], fit_seconds=fitted-start, predict_seconds=predicted-fitted,
                             random_state=settings["random_state"], **model.diagnostics()))
            for j, row in enumerate(test):
                item = dict(model_id=spec["model_id"], fold_id=fold["fold_id"], observation_id=row["observation_id"],
                            pred_mean=float(predictions["pred_mean"][j]), pred_std=float(predictions["pred_std"][j]))
                held_out.append(item)
                uncertainty.append(dict(item, latent_std=float(predictions["latent_std"][j]),
                                        noise_std=float(predictions["noise_std"][j])))
    root = Path(__file__).resolve().parents[1]
    audit = dict(version=__version__, runtime=versions(), prediction_task=task,
                 generated_utc=datetime.now(timezone.utc).isoformat(),
                 input_sha256={key: dict(path=str(Path(path).resolve()), sha256=sha256(path)) for key, path in
                               (("data", data_path), ("config", config_path))},
                 implementation_sha256={str(path.relative_to(root)): sha256(path) for path in
                    [root / name for name in ("train_gp.py", "predict_gp.py", "train_condition_gp.py", "train_early_gp.py",
                                             "predict_condition_gp.py", "predict_early_gp.py")] +
                    sorted((root / "gp_model").rglob("*.py"))},
                 training=config["training"], fold_fits=logs,
                 fit_weighting="each seed row contributes to likelihood; evaluator weights ratios equally",
                 noise_model="one learned Gaussian noise variance per GP fit; original target scale; jitter is numerical only",
                 uncertainty="conditional on fitted hyperparameters; observed new-run SD includes WhiteKernel noise exactly once",
                 selection="all candidates reported and refitted; no winner chosen; no nested model selection",
                 feature_provenance="Task sources/windows and row metadata checked when task is explicit. Numerical feature provenance is declared, not independently reconstructed from MD.")
    with staging_directory(out.parent) as temporary:
        stage = temporary / "experiment"
        stage.mkdir()
        save_csv(stage / "observations.csv", [{key: row[key] for key in
                   ("observation_id", "ratio", "seed_id", "y_true", "target_n")} for row in rows])
        save_csv(stage / "predictions.csv", held_out)
        save_csv(stage / "uncertainty_components.csv", uncertainty)
        write_json(stage / "protocol.json", protocol)
        write_json(stage / "config_snapshot.json", config)
        write_json(stage / "task_manifest.json", dict(prediction_task=task, description=describe(task),
                   feature_definitions=config["feature_definitions"], target=config["target"],
                   limitation="Declared temporal provenance only; no raw trajectory extraction or nested window selection."))
        run_evaluation(stage / "observations.csv", stage / "predictions.csv", stage / "protocol.json", stage / "evaluation")
        # The whole experiment will move atomically; record its final input paths.
        report_result = json.loads((stage / "evaluation/results.json").read_text(encoding="utf-8"))
        for key in ("observations", "predictions", "protocol"):
            report_result["audit"]["input_sha256"][key]["path"] = str(out / (key + (".json" if key == "protocol" else ".csv")))
        write_json(stage / "evaluation/results.json", report_result)
        write_json(stage / "evaluation/audit.json", report_result["audit"])
        render_report(report_result, stage / "evaluation/report.html")
        (stage / "models").mkdir()
        final_fits = []
        regression_plots = []
        for spec in specs:
            if progress:
                progress(f"Final fit (all rows) | {spec['model_id']}")
            start = perf_counter()
            model = FittedModel(spec, config["training"]).fit(matrix(rows, spec["inputs"]), [r["y_true"] for r in rows])
            regression_plots.append(regression_plot(model, rows, held_out))
            diagnostics = model.diagnostics()
            checkpoint = dict(artifact_version="1.1" if task else "1.0", runtime=versions(),
                              prediction_task=task, feature_definitions=config["feature_definitions"],
                              model=spec, training=config["training"],
                              target=protocol["target"], data_kind=config["data_kind"], dataset_label=config["dataset_label"],
                              X=model.X.tolist(), y=model.y.tolist(), theta=diagnostics.get("theta"),
                              ratios=ratios, training_observation_ids=[r["observation_id"] for r in rows],
                              diagnostics=diagnostics, purpose="full-data fit for new predictions; not held-out evaluation")
            filename = f"model__{spec['model_id']}.json"
            write_json(stage / "models" / filename, checkpoint)
            final_fits.append(dict(model_id=spec["model_id"], fit_seconds=perf_counter()-start,
                                   path="models/"+filename, sha256=sha256(stage / "models" / filename), **diagnostics))
        report_result["regression"] = dict(
            models=regression_plots,
            ratio_definition=config["feature_definitions"].get("ratio", {}).get("description", "ratio"),
            scope="all_ratios", interval_level=.9,
            note="Full-data fit curves are descriptive. Held-out points are produced by separate fold models; only held-out predictions enter evaluation metrics.")
        curve_rows = [dict(model_id=plot["model_id"], **point)
                      for plot in regression_plots for point in plot["curve"]]
        if curve_rows:
            save_csv(stage / "evaluation/regression_curves.csv", curve_rows)
        audit["final_fits"] = final_fits
        audit["warning_count"] = sum(len(entry["warnings"]) for entry in logs+final_fits)
        write_json(stage / "training_audit.json", audit)
        report_result["warnings"].append(
            f"GP 訓練共有 {audit['warning_count']} 筆提示（包含參數界限、最佳化或基準變異下限）；"
            "完整記錄位於上一層 training_audit.json，未因此移除模型或樣本。")
        report_result["warnings"].append(describe(task))
        if task:
            report_result["warnings"].append("時間與特徵來源檢查依據輸入者宣告；尚未從原始軌跡驗證。兩類任務分開訓練與出報告。")
        write_json(stage / "evaluation/results.json", report_result)
        render_report(report_result, stage / "evaluation/report.html")
        stage.rename(out)
    return out / "evaluation/report.html"


def load_fitted_model(path, expected_kind=None):
    artifact = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    require(artifact.get("artifact_version") in ("1.0", "1.1"), "unsupported model artifact version")
    task = artifact.get("prediction_task")
    if artifact["artifact_version"] == "1.1":
        artifact["prediction_task"] = task = validate_task(task, artifact.get("feature_definitions"), [artifact["model"]])
    else:
        require(task is None, "legacy artifact cannot claim an explicit prediction task")
    expected_task(task, expected_kind)
    for dependency in ("gp_model", "numpy", "scipy", "sklearn"):
        recorded = artifact.get("runtime", {}).get(dependency)
        compatible_legacy = dependency == "gp_model" and recorded == "0.1.0" and artifact["artifact_version"] == "1.0"
        require(recorded == versions()[dependency] or compatible_legacy,
                f"model requires recorded {dependency} version; use the original environment or refit")
    spec = artifact["model"]
    require(spec.get("kind") in ("gp", "mean", "linear"), "unsupported saved model kind")
    require(artifact.get("target", {}).get("estimand") == "individual_run", "saved model target is not individual_run")
    if spec["kind"] == "gp":
        require(artifact.get("theta") is not None, "saved GP is missing fitted parameters")
    # Rebuild the covariance with frozen hyperparameters; never load executable pickle data.
    model = FittedModel(spec, artifact["training"]).fit(artifact["X"], artifact["y"], frozen_theta=artifact.get("theta"))
    return model, artifact


def predict_file(model_path, query_path, out, expected_kind=None):
    model, artifact = load_fitted_model(model_path, expected_kind=expected_kind)
    task = artifact.get("prediction_task")
    out = task_directory(out, task)
    require(not out.exists(), "prediction output already exists; choose a new directory")
    names = model.spec["inputs"]
    raw = read_table(query_path, ["query_id", "ratio", *names])
    rows, seen = [], set()
    for row in raw:
        qid = nonempty(row["query_id"], "query_id")
        if task:
            validate_row(row, task, qid)
        else:
            require(row.get("task_kind") in (None, ""), "task-marked queries require an explicit task model")
        require(qid not in seen, f"duplicate query_id: {qid}")
        seen.add(qid)
        rows.append(dict(query_id=qid, ratio=number(row["ratio"], f"{qid}.ratio"),
                         features={name: number(row[name], f"{qid}.{name}") for name in names}))
    X = matrix(rows, names)
    start = perf_counter()
    predictions = model.predict(X)
    elapsed = perf_counter()-start
    evaluator = get_target(dict(schema_version="1.1", target=artifact["target"]))
    ratios = artifact["ratios"]
    lower, upper = model.X.min(axis=0), model.X.max(axis=0)
    radius = NormalDist().inv_cdf(.95)
    outputs = []
    for i, row in enumerate(rows):
        mean, sd = float(predictions["pred_mean"][i]), float(predictions["pred_std"][i])
        try:
            evaluator.validate_observation(mean, row["query_id"])
            valid_mean = True
        except ValidationError:
            valid_mean = False
        ratio_scope = ("seen_ratio" if row["ratio"] in ratios else
                       "ratio_interpolation" if min(ratios) < row["ratio"] < max(ratios) else "ratio_extrapolation")
        outside = [name for j, name in enumerate(names) if X[i,j] < lower[j] or X[i,j] > upper[j]]
        outputs.append(dict(query_id=row["query_id"], ratio=row["ratio"], model_id=model.spec["model_id"],
                            pred_mean=mean, pred_std=sd, lower_90=mean-radius*sd, upper_90=mean+radius*sd,
                            latent_std=float(predictions["latent_std"][i]), noise_std=float(predictions["noise_std"][i]),
                            ratio_scope=ratio_scope, outside_feature_ranges=", ".join(outside),
                            mean_in_target_domain=valid_mean))
        if task:
            outputs[-1]["task_kind"] = task["kind"]
    with staging_directory(out.parent) as temporary:
        stage = temporary / "prediction"
        stage.mkdir()
        save_csv(stage / "predictions.csv", outputs)
        write_json(stage / "prediction_info.json", dict(target=artifact["target"], runtime=versions(),
                    prediction_task=task, feature_definitions=artifact.get("feature_definitions"),
                    data_kind=artifact["data_kind"], dataset_label=artifact["dataset_label"],
                    model_sha256=sha256(model_path), query_sha256=sha256(query_path), prediction_seconds=elapsed,
                    uncertainty="new individual-run target, including fitted observation noise; conditional on fitted parameters",
                    domain_note="ratio and per-feature ranges are descriptive only, not a joint-domain or accuracy guarantee",
                    warnings=list(dict.fromkeys(model.warnings))))
        stage.rename(out)
    return out / "predictions.csv"
