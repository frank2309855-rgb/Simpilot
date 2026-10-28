"""Train early-observation models; refuses condition or unclassified configurations."""
from train_gp import main

if __name__ == "__main__":
    raise SystemExit(main(expected_kind="early"))
