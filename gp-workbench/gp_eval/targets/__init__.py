"""Explicit target registry. JSON selects known IDs; it never imports user code."""
from .base import GaussianScalarTarget
from .q_peak import QPeakTarget
from .composition_strength import CompositionStrengthTarget
from .low_q_shell_mean import LowQShellMeanTarget
from ..validation import nonempty, require

TARGETS = {"q_peak": QPeakTarget(), "composition_strength": CompositionStrengthTarget(), "low_q_shell_mean": LowQShellMeanTarget()}


def get_target(protocol):
    target = protocol.get("target", {})
    require(isinstance(target, dict), "target must be an object")
    evaluator_id = target.get("evaluator", "q_peak" if protocol.get("schema_version") == "1.0" else None)
    nonempty(evaluator_id, "target.evaluator")
    require(evaluator_id in TARGETS, f"Unknown target.evaluator: {evaluator_id}; available: {', '.join(TARGETS)}")
    return TARGETS[evaluator_id]
