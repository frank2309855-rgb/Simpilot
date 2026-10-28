"""Run: python evaluate.py --observations ... --predictions ... --protocol ... --out ..."""
from __future__ import annotations

import argparse
import json
import platform
import sys
import shutil
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from gp_eval import __version__
from gp_eval.core import ValidationError, evaluate, load_inputs, save_csv, sha256
from gp_eval.report import render_report


@contextmanager
def staging_directory(parent):
    """Inherit parent ACLs (compatible with Windows Anaconda and restricted tokens)."""
    parent = Path(parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    # Nested task/report staging otherwise exceeds Windows MAX_PATH in this workspace.
    # mkdir remains exclusive: a collision fails rather than reusing another run.
    directory = parent / (".gp_eval_" + uuid.uuid4().hex[:12])
    directory.mkdir()
    try:
        yield directory
    finally:
        # Never recursively remove a path outside the explicitly supplied parent.
        if directory.exists():
            if directory.resolve().parent != parent or not directory.name.startswith(".gp_eval_"):
                raise ValidationError("Unexpected staging path; cleanup refused")
            shutil.rmtree(directory)


def run(observations, predictions, protocol, out):
    out = Path(out).resolve()
    if out.exists():
        raise ValidationError(f"Output path already exists: {out}. Choose a new directory to preserve previous reports.")
    result = evaluate(*load_inputs(observations, predictions, protocol))
    root = Path(__file__).resolve().parent
    code_files = [root / "evaluate.py", *sorted((root / "gp_eval").rglob("*.py")), root / "gp_eval" / "report_template.html"]
    audit = dict(version=__version__, python=platform.python_version(),
                 generated_utc=datetime.now(timezone.utc).isoformat(),
                 input_sha256={name: dict(path=str(Path(path).resolve()), sha256=sha256(path)) for name, path in
                               (("observations", observations), ("predictions", predictions), ("protocol", protocol))},
                 implementation_sha256={str(path.relative_to(root)): sha256(path) for path in code_files},
                 audit_scope="Submitted membership and complete predictions checked; fit provenance is declared, not verified.",
                 aggregation="equal weight per ratio; RMSE=sqrt(mean over ratios of within-ratio MSE)",
                 statistical_inference="none; omission ranges are summary sensitivity, not confidence intervals")
    audit["target_evaluator"] = {key: result["target_evaluation"][key] for key in ("evaluator", "version")}
    result["audit"] = audit
    out.parent.mkdir(parents=True, exist_ok=True)
    # Assemble all outputs first so an error does not leave a partial report.
    with staging_directory(out.parent) as temporary:
        stage = temporary / "report"
        stage.mkdir()
        for filename, key in (("metrics_by_scope.csv", "summary"), ("metrics_by_ratio.csv", "by_ratio"),
                              ("observation_diagnostics.csv", "observations"), ("pairwise_comparisons.csv", "pairwise"),
                              ("paired_by_ratio.csv", "paired_by_ratio")):
            save_csv(stage / filename, result[key])
        for filename, data in (("results.json", result), ("audit.json", audit), ("protocol_snapshot.json", result["protocol"])):
            (stage / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
        render_report(result, stage / "report.html")
        stage.rename(out)
    return out / "report.html"


def main(argv=None):
    parser = argparse.ArgumentParser(description="GP 模型評估：MAE / CRPS / 逐 ratio 比較（Python 3.10+，無額外套件）")
    parser.add_argument("--observations", required=True, help="Reference observations CSV")
    parser.add_argument("--predictions", required=True, help="Held-out model predictions CSV")
    parser.add_argument("--protocol", required=True, help="Evaluation protocol JSON, including fold membership")
    parser.add_argument("--out", required=True, help="New report directory; existing paths are not overwritten")
    args = parser.parse_args(argv)
    try:
        report = run(args.observations, args.predictions, args.protocol, args.out)
    except (ValidationError, OSError, json.JSONDecodeError) as exc:
        print(f"Evaluation stopped: {exc}", file=sys.stderr)
        return 2
    print(f"Report created: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
