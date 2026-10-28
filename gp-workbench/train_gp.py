"""Train configurable GPs with leave-one-ratio-out evaluation and final models."""
import argparse
import json
import sys

from gp_eval.validation import ValidationError
from gp_model.workflow import train_experiment


def main(expected_kind=None):
    parser = argparse.ArgumentParser(description="GP 訓練、leave-one-ratio-out 驗證與比較報告")
    parser.add_argument("--data", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True, help="New output directory")
    parser.add_argument("--task", choices=("condition", "early"), help="Require an explicit task; outputs are separated under OUT/task")
    args = parser.parse_args()
    try:
        if expected_kind is not None and args.task not in (None, expected_kind):
            raise ValidationError("task mismatch with this entry point")
        report = train_experiment(args.data, args.config, args.out, expected_kind=expected_kind or args.task,
                                  progress=lambda message: print(message, flush=True))
    except (ValidationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"GP training stopped: {exc}", file=sys.stderr)
        return 2
    print(f"Completed: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
