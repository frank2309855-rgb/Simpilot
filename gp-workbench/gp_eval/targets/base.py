"""Extension interface for scalar targets with Gaussian predictions.

The engine owns MAE/CRPS, Gaussian calibration, grouped validation and comparisons.
Targets own physical constraints, additional diagnostics and their presentation.
Curves, classification and non-Gaussian distributions need a separate engine change.
"""
from ..validation import nonempty, require


class GaussianScalarTarget:
    evaluator_id = ""
    version = "1.0.0"
    diagnostic_fields = ()
    diagnostic_note = ""

    def draft_definition(self):
        return dict(evaluator=self.evaluator_id, name=None, units=None,
                    observation_time=None, extraction_rule=None, estimand=None,
                    distribution="gaussian_physical_scale", predictive_sd=None)

    def validate_definition(self, target, protocol):
        for key in ("name", "units", "observation_time", "extraction_rule"):
            nonempty(target.get(key), f"target.{key}")
        require(target.get("estimand") in ("individual_run", "observed_seed_mean"),
                "target.estimand must be individual_run or observed_seed_mean")
        require(target.get("distribution") == "gaussian_physical_scale",
                "supports only Gaussian distributions on the original physical target scale")
        require(target.get("predictive_sd") == "observed_target",
                "pred_std must describe the observed target, not latent-function uncertainty alone")

    def validate_observation(self, value, observation_id):
        """The engine has already checked that value is a finite number."""

    def observation_metrics(self, y, mu, sd):
        return {}

    def aggregate(self, records):
        """Extra within-ratio metrics; records include observation_metrics fields."""
        return {}

    def summarize(self, ratio_rows):
        """Extra between-ratio metrics. Preserve equal weight per ratio."""
        return {}

    def warnings(self, protocol, records):
        return []

    def describe(self, target):
        """JSON-safe metadata used by reports and audit; labels are escaped by UI."""
        return dict(evaluator=self.evaluator_id, version=self.version,
                    name=target["name"], axis_label=target["name"],
                    units=target["units"], observation_time=target["observation_time"],
                    extraction_rule=target["extraction_rule"], estimand=target["estimand"],
                    diagnostic_fields=list(self.diagnostic_fields),
                    diagnostic_note=self.diagnostic_note)
