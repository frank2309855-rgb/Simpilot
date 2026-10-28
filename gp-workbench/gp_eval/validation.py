"""Shared validation primitives; independent of evaluation and target modules."""
import math


class ValidationError(ValueError):
    """An input cannot be used for a fair comparison."""


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def number(value, name):
    try:
        require(not isinstance(value, bool), f"{name}: boolean is not a number")
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{name}: expected a finite number, got {value!r}") from exc
    require(math.isfinite(result), f"{name}: NaN/infinity is not allowed")
    return result


def nonempty(value, name):
    require(isinstance(value, str) and bool(value.strip()), f"{name}: nonempty text required")
    return value.strip()
