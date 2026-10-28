"""Separate, paired synthetic datasets. No real MD or window choices are implied."""
import argparse
import copy
import random
from pathlib import Path

from gp_eval.core import save_csv
from gp_model.tasks import metadata
from gp_model.workflow import write_json
from make_gp_demo import demo_dataset, real_template


def task_datasets():
    data, base, queries = demo_dataset()
    rng = random.Random(20261009)
    # A synthetic early state precedes the target: never derive a feature from y.
    for row in data:
        state = rng.gauss(0, 1)
        row["state_t0"] = state + rng.gauss(0, .15)
        row["state_t10"] = .3*row["ratio"] + state + rng.gauss(0, .15)
        row["state_t20"] = .6*row["ratio"] + state + rng.gauss(0, .15)
        row["q_peak"] += .008*state
    for row in queries:
        state = rng.gauss(0, 1)
        for time in (0, 10, 20):
            row[f"state_t{time}"] = .03*time*row["ratio"] + state + rng.gauss(0, .15)
    datasets = {}
    for kind in ("condition", "early"):
        config = copy.deepcopy(base)
        config["gp_config_version"] = "1.1"
        config["dataset_label"] = "獨立任務合成示範（不是 MD 結果）"
        config["prediction_task"] = dict(kind=kind, stage="stage1_demo", time_unit="synthetic_time",
                                         time_origin="synthetic_start", target_window=[80, 100])
        config["target"]["observation_time"] = "Synthetic late window [80,100]; analytic scalar, no S(q,t) extraction"
        config["target"]["extraction_rule"] = "Analytic late target with synthetic latent state plus seeded noise; no actual trajectory extraction"
        for entry in config["feature_definitions"].values():
            entry["source"] = "condition"
        config["models"] = config["models"][:2]
        if kind == "early":
            config["prediction_task"]["observation_window"] = [0, 20]
            for time in (0, 10, 20):
                config["feature_definitions"][f"state_t{time}"] = dict(
                    source="trajectory", sample_time=time, available_at_prediction=True,
                    description=f"Synthetic state sampled at t={time}; not a validated physical descriptor")
            config["models"] = [
                dict(model_id="gp_early_endpoint_matern32", label="Early endpoint · Matérn 3/2",
                     inputs=["ratio", "state_t20"], kernel=dict(type="matern", nu=1.5, ard=True)),
                dict(model_id="gp_early_history_matern32", label="Early history · Matérn 3/2",
                     inputs=["ratio", "state_t0", "state_t10", "state_t20"],
                     kernel=dict(type="matern", nu=1.5, ard=True))]
        task = config["prediction_task"]
        # Condition files physically omit every early-state feature column.
        def selected(row):
            return dict({k: v for k, v in row.items() if kind == "early" or not k.startswith("state_")}, **metadata(task))
        datasets[kind] = ([selected(r) for r in data], config, [selected(q) for q in queries])
    return datasets


def real_task_template(kind):
    config = real_template()
    config["gp_config_version"] = "1.1"
    config["prediction_task"] = dict(kind=kind, stage="stage1", time_unit=None,
                                     time_origin=None, target_window=[None, None])
    config["feature_definitions"]["ratio"]["source"] = "condition"
    if kind == "early":
        config["prediction_task"]["observation_window"] = [None, None]
        config["feature_definitions"]["early_descriptor"] = dict(source="trajectory",
                source_window=[None, None], available_at_prediction=True,
                description="PLACEHOLDER: define physical descriptor, units, extraction and source window before use")
        config["models"] = [dict(model_id="gp_early_matern32", label="Early · Matérn 3/2",
            inputs=["ratio", "early_descriptor"], kernel=dict(type="matern", nu=1.5, ard=True))]
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        parser.error("choose a new output directory")
    for kind, (rows, config, queries) in task_datasets().items():
        dest = out / kind
        dest.mkdir(parents=True)
        save_csv(dest / "training_data.csv", rows)
        save_csv(dest / "queries.csv", queries)
        write_json(dest / "config.json", config)
        write_json(dest / "real_config_template.json", real_task_template(kind))
    print(f"Separate synthetic datasets created: {out}")


if __name__ == "__main__":
    main()
