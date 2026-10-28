"""Predict a new individual-run target using a previously fitted model."""
import argparse
import json
import sys

from gp_eval.validation import ValidationError
from gp_model.workflow import predict_file


def main(expected_kind=None):
    parser = argparse.ArgumentParser(description="以已訓練 GP 預測新配方")
    parser.add_argument("--model", required=True, help="Saved model JSON")
    parser.add_argument("--queries", required=True, help="CSV with query_id, ratio and selected features")
    parser.add_argument("--out", required=True, help="New output directory")
    parser.add_argument("--task", choices=("condition", "early"), help="Reject models from the other task or legacy models without a task")
    args = parser.parse_args()
    try:
        if expected_kind is not None and args.task not in (None, expected_kind):
            raise ValidationError("task mismatch with this entry point")
        output = predict_file(args.model, args.queries, args.out, expected_kind=expected_kind or args.task)
    except (ValidationError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"GP prediction stopped: {exc}", file=sys.stderr)
        return 2
    print(f"Predictions written: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
