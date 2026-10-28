"""Generate a draft fold manifest; target/model details must be filled before evaluation."""
import argparse
import json
from pathlib import Path

from gp_eval.core import ValidationError, load_csv, number, require
from gp_eval.targets import TARGETS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--target", choices=sorted(TARGETS), default="q_peak",
                        help="Target evaluator (default: q_peak)")
    args = parser.parse_args()
    try:
        out = Path(args.out)
        require(not out.exists(), "Choose a new protocol path to preserve earlier settings")
        rows = load_csv(args.observations, ("observation_id", "ratio", "seed_id", "y_true", "target_n"))
        ids = [r["observation_id"] for r in rows]
        require(all(ids) and len(ids) == len(set(ids)), "observation IDs must be nonempty and unique")
        ratios = {r["observation_id"]: number(r["ratio"], "ratio") for r in rows}
        require(len(set(ratios.values())) >= 2, "at least two ratios required")
        folds = [dict(fold_id=f"hold_ratio_{i+1:02}", train_ids=[oid for oid in ids if ratios[oid] != ratio],
                      test_ids=[oid for oid in ids if ratios[oid] == ratio])
                 for i, ratio in enumerate(sorted(set(ratios.values())))]
        draft = dict(schema_version="1.1", dataset_label=None, data_kind="real",
                     target=TARGETS[args.target].draft_definition(),
                     validation=dict(scheme="leave_one_ratio_out", preprocessing=None,
                                     inputs_available_at_prediction_time=None, selection_context="exploratory", fit_selection_protocol=None),
                     practical_thresholds=dict(mae_improvement=None, crps_improvement=None, acceptable_mae=None),
                     baseline_ids=[], models=[], folds=folds)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Draft created: {out}. Fill target/model/provenance fields before evaluation.")
    except (OSError, ValidationError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
