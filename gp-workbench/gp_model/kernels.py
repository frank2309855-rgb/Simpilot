"""Build signal kernels from declarative JSON; never evaluate code strings."""
import numpy as np
from sklearn.gaussian_process.kernels import RBF, Matern, RationalQuadratic, DotProduct

from gp_eval.validation import number, require


def positive(value, name):
    result = number(value, name)
    require(result > 0, f"{name} must be positive")
    return result


def bounds(value, initial, name):
    if value == "fixed":
        return "fixed"
    require(isinstance(value, list) and len(value) == 2, f"{name}: use [lower, upper] or 'fixed'")
    lo, hi = (positive(v, name) for v in value)
    require(lo < hi, f"{name}: lower must be less than upper")
    require(all(lo <= x <= hi for x in np.atleast_1d(initial)), f"{name}: initial value outside bounds")
    return (lo, hi)


def build_kernel(spec, n_features, depth=0):
    require(isinstance(spec, dict), "kernel must be a JSON object")
    require(depth <= 8, "kernel composition is too deep")
    kind = spec.get("type")
    require(isinstance(kind, str), "kernel.type must be a string")
    if kind in ("sum", "product"):
        require(set(spec) <= {"type", "terms"}, f"unknown {kind} kernel field")
        terms = spec.get("terms")
        require(isinstance(terms, list) and len(terms) >= 2, f"{kind} requires at least two terms")
        kernel = build_kernel(terms[0], n_features, depth+1)
        for term in terms[1:]:
            other = build_kernel(term, n_features, depth+1)
            kernel = kernel + other if kind == "sum" else kernel * other
        return kernel
    allowed = {
        "rbf": {"type", "length_scale", "length_scale_bounds", "ard"},
        "matern": {"type", "length_scale", "length_scale_bounds", "ard", "nu"},
        "rational_quadratic": {"type", "length_scale", "length_scale_bounds", "alpha", "alpha_bounds"},
        "linear": {"type", "sigma_0", "sigma_0_bounds"},
    }
    require(kind in allowed, f"unsupported kernel.type: {kind}")
    require(set(spec) <= allowed[kind], f"unknown fields in {kind} kernel: {set(spec)-allowed[kind]}")
    if kind == "linear":
        sigma = positive(spec.get("sigma_0", 1.), "sigma_0")
        return DotProduct(sigma, bounds(spec.get("sigma_0_bounds", [1e-3, 1e3]), sigma, "sigma_0_bounds"))
    ard = spec.get("ard", False)
    require(isinstance(ard, bool), "ard must be true or false")
    value = spec.get("length_scale", 1.)
    if isinstance(value, list):
        require(ard and len(value) == n_features, "length_scale vector requires ard=true and one value per input")
        length = np.array([positive(v, "length_scale") for v in value])
    else:
        length = positive(value, "length_scale")
        if ard:
            length = np.repeat(length, n_features)
    limit = bounds(spec.get("length_scale_bounds", [1e-2, 1e2]), length, "length_scale_bounds")
    if kind == "rbf":
        return RBF(length, limit)
    if kind == "matern":
        nu = number(spec.get("nu", 1.5), "nu")
        require(nu in (.5, 1.5, 2.5), "supported Matern nu values: 0.5, 1.5, 2.5")
        return Matern(length, limit, nu=nu)
    alpha = positive(spec.get("alpha", 1.), "rational_quadratic.alpha")
    return RationalQuadratic(length, alpha, limit,
                             bounds(spec.get("alpha_bounds", [1e-2, 1e2]), alpha, "alpha_bounds"))
