"""Synthetic training inputs and configurations; no MD data are fabricated as real."""
import argparse
import copy
import math
import random
from pathlib import Path

from gp_eval.core import save_csv
from gp_eval.targets import TARGETS
from gp_model.models import DEFAULT_TRAINING
from gp_model.workflow import write_json


def demo_dataset():
    rng = random.Random(20261006)
    data = []
    for i in range(9):
        ratio = round(.1*(i+1), 2)
        temperature = 280+10*((i*3) % 5)
        mean = .2+.05*ratio+.035*math.sin(6*ratio)+.0005*(temperature-300)
        for seed in range((3, 4, 3, 5, 4, 3, 4, 3, 5)[i]):
            data.append(dict(observation_id=f"r{i+1:02}_s{seed+1:02}", ratio=ratio,
                             seed_id=f"s{seed+1:02}", target_n=1, temperature=temperature,
                             q_peak=mean+rng.gauss(0, .004)))
    config = dict(gp_config_version="1.0", dataset_label="GP 合成訓練示範（不是 MD 結果）", data_kind="synthetic_demo",
                  target=dict(evaluator="q_peak", column="q_peak", name="q_peak", units="nm^-1 (synthetic)",
                    observation_time="Synthetic scalar example; no real time window",
                    extraction_order="synthetic_scalar", extraction_rule="Analytic function plus seeded Gaussian noise; no S(q,t) extraction",
                    estimand="individual_run", distribution="gaussian_physical_scale", predictive_sd="observed_target"),
                  feature_definitions={
                    "ratio": dict(available_at_prediction=True, description="Synthetic precursor ratio, known before simulation"),
                    "temperature": dict(available_at_prediction=True, description="Synthetic prescribed temperature; example feature only")},
                  models=[
                    dict(model_id="gp_ratio_matern32", label="Ratio · Matérn 3/2", inputs=["ratio"],
                         kernel=dict(type="matern", nu=1.5)),
                    dict(model_id="gp_ratio_rbf", label="Ratio · RBF", inputs=["ratio"], kernel=dict(type="rbf")),
                    dict(model_id="gp_ratio_temperature_matern32", label="Ratio + Temperature · Matérn 3/2", inputs=["ratio", "temperature"],
                         kernel=dict(type="matern", nu=1.5, ard=True))],
                  baseline_inputs=["ratio"], training=copy.deepcopy(DEFAULT_TRAINING), selection_context="exploratory",
                  practical_thresholds=dict(mae_improvement=None, crps_improvement=None, acceptable_mae=None))
    queries = [dict(query_id=f"query_{i+1}", ratio=r, temperature=300) for i, r in enumerate((.15, .45, .95))]
    return data, config, queries


def real_template():
    _, config, _ = demo_dataset()
    config["dataset_label"] = None
    config["data_kind"] = "real"
    config["target"] = dict(TARGETS["q_peak"].draft_definition(), column="q_peak")
    config["models"] = config["models"][:2]
    config["feature_definitions"] = {"ratio": dict(available_at_prediction=True,
                                                 description="Precursor ratio; confirm definition and units from MD files")}
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        parser.error("choose a new output directory")
    out.mkdir(parents=True)
    data, config, queries = demo_dataset()
    save_csv(out / "training_data.csv", data)
    save_csv(out / "new_formulas.csv", queries)
    write_json(out / "config.json", config)
    write_json(out / "real_config_template.json", real_template())
    print(f"Synthetic GP example created: {out}")


if __name__ == "__main__":
    main()
