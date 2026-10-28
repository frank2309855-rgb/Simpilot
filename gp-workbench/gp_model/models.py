"""Fold-local preprocessing and observed-target uncertainty for GP and baselines."""
import copy
import warnings

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, WhiteKernel
from sklearn.preprocessing import StandardScaler

from gp_eval.validation import require, number
from .kernels import build_kernel, bounds, positive

DEFAULT_TRAINING = dict(random_state=20261006, n_restarts_optimizer=2, optimize=True,
                        jitter=1e-10, signal_variance=1., signal_variance_bounds=[1e-3, 1e3],
                        noise_variance=.05, noise_variance_bounds=[1e-6, 1.])


def training_settings(value=None):
    require(value is None or isinstance(value, dict), "training must be an object")
    require(not set(value or {}) - set(DEFAULT_TRAINING), "unknown training setting")
    settings = {**copy.deepcopy(DEFAULT_TRAINING), **copy.deepcopy(value or {})}
    for key in ("random_state", "n_restarts_optimizer"):
        v = number(settings[key], key)
        require(v.is_integer() and v >= 0, f"{key} must be a nonnegative integer")
        settings[key] = int(v)
    require(settings["random_state"] < 2**32, "random_state must be less than 2**32")
    require(isinstance(settings["optimize"], bool), "optimize must be true or false")
    for key in ("signal_variance", "noise_variance"):
        settings[key] = positive(settings[key], key)
        limits = bounds(settings[key+"_bounds"], settings[key], key+"_bounds")
        settings[key+"_bounds"] = list(limits) if isinstance(limits, tuple) else limits
    settings["jitter"] = positive(settings["jitter"], "jitter")
    noise_floor = (settings["noise_variance"] if settings["noise_variance_bounds"] == "fixed"
                   else settings["noise_variance_bounds"][0])
    require(settings["jitter"] <= min(1e-6, noise_floor),
            "jitter is numerical stabilization: must be <= 1e-6 and <= noise variance lower bound")
    return settings


class FittedModel:
    """Small common interface: fit(X,y), predict(X), diagnostics().

    Predictions describe a new individual-run target. GP hyperparameter uncertainty
    is not integrated. All feature and target transforms are fitted on supplied rows.
    """
    def __init__(self, spec, settings=None):
        require(isinstance(spec, dict) and spec.get("kind") in ("gp", "mean", "linear"), "unsupported model kind")
        inputs = spec.get("inputs")
        require(isinstance(inputs, list) and bool(inputs) and all(isinstance(x, str) and x for x in inputs),
                "model inputs must be nonempty feature names")
        require(len(inputs) == len(set(inputs)), "duplicate model inputs")
        self.spec = copy.deepcopy(spec)
        self.settings = training_settings(settings)
        self.warnings = []

    def fit(self, X, y, frozen_theta=None):
        X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
        require(X.ndim == 2 and y.ndim == 1 and len(X) == len(y) and len(y) >= 2,
                "fit requires a 2D X and aligned 1D y with at least two rows")
        require(X.shape[1] == len(self.spec["inputs"]), "input dimension mismatch")
        require(np.isfinite(X).all() and np.isfinite(y).all(), "nonfinite training data")
        self.X, self.y = X.copy(), y.copy()
        self.scaler = StandardScaler().fit(X)
        z = self.scaler.transform(X)
        self.y_mean = float(np.mean(y))
        self.y_scale = float(np.std(y)) or 1.
        self.warnings = []
        if np.std(y) == 0:
            self.warnings.append("Training targets are constant; target scale set to 1 physical unit.")
        constant = [name for name, v in zip(self.spec["inputs"], self.scaler.var_) if v == 0]
        if constant:
            self.warnings.append("Constant training features: " + ", ".join(constant))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            if self.spec["kind"] == "gp":
                s = self.settings
                signal = build_kernel(self.spec["kernel"], X.shape[1])
                kernel = ConstantKernel(s["signal_variance"],
                            bounds(s["signal_variance_bounds"], s["signal_variance"], "signal_variance_bounds"))*signal
                kernel += WhiteKernel(s["noise_variance"],
                            bounds(s["noise_variance_bounds"], s["noise_variance"], "noise_variance_bounds"))
                if frozen_theta is not None:
                    theta = np.asarray(frozen_theta, dtype=float)
                    require(theta.shape == kernel.theta.shape and np.isfinite(theta).all(), "invalid frozen kernel parameters")
                    if theta.size:
                        require(np.all(theta >= kernel.bounds[:,0]-1e-8) and np.all(theta <= kernel.bounds[:,1]+1e-8),
                                "frozen kernel parameters outside declared bounds")
                    kernel = kernel.clone_with_theta(theta)
                optimize = s["optimize"] and frozen_theta is None
                self.gp = GaussianProcessRegressor(kernel=kernel, alpha=s["jitter"], normalize_y=False,
                    optimizer="fmin_l_bfgs_b" if optimize else None,
                    n_restarts_optimizer=s["n_restarts_optimizer"] if optimize else 0,
                    random_state=s["random_state"])
                self.gp.fit(z, (y-self.y_mean)/self.y_scale)
                self.noise_variance = float(self.gp.kernel_.k2.noise_level)*self.y_scale**2
            else:
                self.design = (np.ones((len(y), 1)) if self.spec["kind"] == "mean"
                               else np.column_stack((np.ones(len(y)), z)))
                self.coef, _, rank, _ = np.linalg.lstsq(self.design, y, rcond=None)
                require(rank == self.design.shape[1] and len(y) > rank,
                        "linear/mean baseline needs full-rank design and positive residual degrees of freedom")
                residual = y-self.design@self.coef
                variance = float(residual@residual/(len(y)-rank))
                floor = (self.settings["noise_variance"] if self.settings["noise_variance_bounds"] == "fixed"
                         else self.settings["noise_variance_bounds"][0])*self.y_scale**2
                self.noise_variance = max(variance, floor)
                if variance < floor:
                    self.warnings.append("Baseline residual variance reached the declared scaled variance floor.")
                self.design_inverse = np.linalg.pinv(self.design.T@self.design)
            self.warnings.extend(f"{w.category.__name__}: {w.message}" for w in caught)
        return self

    def predict(self, X):
        require(hasattr(self, "scaler"), "model must be fitted before prediction")
        X = np.asarray(X, dtype=float)
        require(X.ndim == 2 and X.shape[1] == len(self.spec["inputs"]) and len(X) > 0,
                "query input dimension mismatch or empty query")
        require(np.isfinite(X).all(), "nonfinite query features")
        z = self.scaler.transform(X)
        if self.spec["kind"] == "gp":
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                mean, sd = self.gp.predict(z, return_std=True)
                self.warnings.extend(f"{w.category.__name__}: {w.message}" for w in caught)
            mean = mean*self.y_scale+self.y_mean
            variance = (sd*self.y_scale)**2  # WhiteKernel already includes new-run noise.
            latent = variance-self.noise_variance
            tolerance = 1e-8 * max(self.y_scale**2, self.noise_variance)
            require(np.all(latent >= -tolerance), "negative latent variance beyond rounding tolerance")
            latent = np.maximum(latent, 0.)
            variance = latent+self.noise_variance
        else:
            design = np.ones((len(X), 1)) if self.spec["kind"] == "mean" else np.column_stack((np.ones(len(X)), z))
            mean = design@self.coef
            latent = self.noise_variance*np.einsum("ij,jk,ik->i", design, self.design_inverse, design)
            latent = np.maximum(latent, 0.)
            variance = latent+self.noise_variance
        require(np.isfinite(mean).all() and np.isfinite(variance).all() and np.all(variance > 0),
                "invalid predictive distribution")
        return dict(pred_mean=mean, pred_std=np.sqrt(variance), latent_std=np.sqrt(latent),
                    noise_std=np.full(len(X), np.sqrt(self.noise_variance)))

    def diagnostics(self):
        out = dict(x_mean=self.scaler.mean_.tolist(), x_scale=self.scaler.scale_.tolist(),
                   y_mean=self.y_mean, y_scale=self.y_scale, noise_variance=self.noise_variance,
                   feature_min=self.X.min(axis=0).tolist(), feature_max=self.X.max(axis=0).tolist(),
                   n_training_rows=len(self.y), warnings=list(dict.fromkeys(self.warnings)))
        if self.spec["kind"] == "gp":
            out.update(fitted_kernel=str(self.gp.kernel_), theta=self.gp.kernel_.theta.tolist(),
                       log_marginal_likelihood_normalized=float(self.gp.log_marginal_likelihood_value_))
        else:
            out.update(coefficients=self.coef.tolist())
        return out
