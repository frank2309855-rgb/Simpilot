"""Query only an explicitly saved early model with matching observation-window metadata."""
from predict_gp import main

if __name__ == "__main__":
    raise SystemExit(main(expected_kind="early"))
