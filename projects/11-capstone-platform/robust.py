"""
Week 11 — Robust estimation for the optimizer
=============================================
Markowitz optimization applied to raw sample estimates is famously an ERROR
MAXIMIZER (Michaud 1989). The optimizer cannot tell a genuinely high expected
return from a lucky one, so it concentrates on whichever asset had the noisiest
favourable estimate — which is exactly the one most likely to disappoint.

On this portfolio the effect is stark. Over the available window PL, ONDS, NBIS
and MU realised 116-131% annualised; the naive optimizer puts 100% of the
recommendation into those four names and reports a 124% expected return, which
is momentum extrapolation dressed up as optimization.

Two standard corrections, implemented here rather than imported because
scikit-learn is not a dependency of this project:

  JORION BAYES-STEIN shrinks the mean vector toward the return of the minimum-
  variance portfolio. Means are the estimates optimization is most sensitive to
  and the ones estimated least precisely, so pulling them together removes most
  of the damage.

  LEDOIT-WOLF shrinks the sample covariance toward a constant-correlation
  target, with an analytically optimal intensity. This conditions the matrix,
  which matters here because the sample covariance has only ~22 observations
  per asset.

A third correction is not statistical at all: a maximum position weight. It
encodes the judgement that no estimate is good enough to justify betting the
whole portfolio on one name.

References:
  Jorion (1986), "Bayes-Stein Estimation for Portfolio Analysis"
  Ledoit & Wolf (2004), "Honey, I Shrunk the Sample Covariance Matrix"
"""
from __future__ import annotations
import numpy as np


def ledoit_wolf_constant_correlation(returns: np.ndarray) -> dict:
    """Shrink a sample covariance toward the constant-correlation target.

    Target F keeps each asset's own variance but replaces every pairwise
    correlation with the average correlation across all pairs. The optimal
    intensity balances the target's bias against the sample estimate's variance,
    and is computed analytically — no cross-validation needed.

    `returns` is T x N (rows = periods).
    """
    X = np.asarray(returns, dtype=float)
    T, N = X.shape
    if T < 2:
        raise ValueError("need at least 2 observations")
    Xc = X - X.mean(axis=0)
    S = (Xc.T @ Xc) / T                       # MLE covariance, as the paper uses

    var = np.diag(S)
    sd = np.sqrt(var)
    outer_sd = np.outer(sd, sd)
    with np.errstate(divide="ignore", invalid="ignore"):
        corr = np.where(outer_sd > 0, S / outer_sd, 0.0)
    # Average off-diagonal correlation.
    off = ~np.eye(N, dtype=bool)
    r_bar = corr[off].mean() if N > 1 else 0.0

    F = r_bar * outer_sd
    np.fill_diagonal(F, var)

    # pi: sum of asymptotic variances of the sample covariance entries.
    Xc2 = Xc ** 2
    pi_mat = (Xc2.T @ Xc2) / T - S ** 2
    pi_hat = pi_mat.sum()

    # rho: sum of asymptotic covariances between the sample entries and the
    # target. Diagonal terms contribute pi_ii; off-diagonal terms need the
    # derivative of the target with respect to each variance.
    theta_ii = ((Xc ** 3).T @ Xc) / T - var[:, None] * S
    theta_jj = (Xc.T @ (Xc ** 3)) / T - var[None, :] * S
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio_i = np.where(var[None, :] > 0, np.sqrt(np.outer(1 / np.maximum(var, 1e-300), var)), 0.0)
        ratio_j = np.where(var[:, None] > 0, np.sqrt(np.outer(var, 1 / np.maximum(var, 1e-300))), 0.0)
    rho_off = (r_bar / 2.0) * (ratio_i * theta_ii + ratio_j * theta_jj)
    rho_hat = np.diag(pi_mat).sum() + rho_off[off].sum()

    # gamma: how badly the target misspecifies the sample matrix.
    gamma_hat = float(((F - S) ** 2).sum())

    if gamma_hat <= 0:
        delta = 0.0
    else:
        kappa = (pi_hat - rho_hat) / gamma_hat
        delta = float(np.clip(kappa / T, 0.0, 1.0))

    Sigma = delta * F + (1 - delta) * S
    # Restore the unbiased scaling so the result is comparable to np.cov.
    Sigma = Sigma * T / (T - 1)
    return {"cov": Sigma, "shrinkage": delta, "avg_corr": float(r_bar),
            "sample_cov": S * T / (T - 1), "target": F * T / (T - 1)}


def min_variance_weights(cov: np.ndarray, long_only=True) -> np.ndarray:
    """Global minimum-variance portfolio.

    Useful twice over: as the shrinkage target for the mean, and as a benchmark
    that uses NO expected-return estimates at all. If a mean-driven portfolio
    cannot beat it out of sample, the means were not adding information.
    """
    n = cov.shape[0]
    if long_only:
        import cvxpy as cp
        w = cp.Variable(n)
        prob = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(cov))),
                          [cp.sum(w) == 1, w >= 0])
        prob.solve()
        v = np.asarray(w.value).ravel()
        v = np.clip(v, 0, None)
        return v / v.sum()
    inv = np.linalg.pinv(cov)
    ones = np.ones(n)
    v = inv @ ones
    return v / (ones @ v)


def bayes_stein_mean(mu: np.ndarray, cov: np.ndarray, T: int,
                     target: float | None = None) -> dict:
    """Jorion's Bayes-Stein shrinkage of the mean vector.

    Shrinks every asset's mean toward a common target — by default the expected
    return of the minimum-variance portfolio, which is the natural "no view"
    anchor. The intensity rises when the sample is short (small T) or the
    dispersion of means is small relative to their estimation error, i.e.
    exactly when the differences between assets are least believable.
    """
    mu = np.asarray(mu, dtype=float)
    n = len(mu)
    if target is None:
        w_mv = min_variance_weights(cov, long_only=False)
        target = float(mu @ w_mv)
    diff = mu - target
    inv = np.linalg.pinv(cov)
    quad = float(diff @ inv @ diff)
    if quad <= 0:
        intensity = 1.0
    else:
        lam = (n + 2) / quad
        intensity = float(lam / (T + lam))
    intensity = float(np.clip(intensity, 0.0, 1.0))
    return {"mu": (1 - intensity) * mu + intensity * target,
            "intensity": intensity, "target": float(target)}


def robust_estimates(returns, trading_days=252) -> dict:
    """Annualised robust mean and covariance, plus the raw ones for comparison."""
    X = np.asarray(returns, dtype=float)
    T = X.shape[0]

    mu_daily = X.mean(axis=0)
    cov_sample_daily = np.cov(X, rowvar=False)
    lw = ledoit_wolf_constant_correlation(X)
    cov_daily = lw["cov"]

    bs = bayes_stein_mean(mu_daily, cov_daily, T)

    return {
        "mu": bs["mu"] * trading_days,
        "cov": cov_daily * trading_days,
        "mu_naive": mu_daily * trading_days,
        "cov_naive": cov_sample_daily * trading_days,
        "mean_shrinkage": bs["intensity"],
        "mean_target": bs["target"] * trading_days,
        "cov_shrinkage": lw["shrinkage"],
        "avg_corr": lw["avg_corr"],
        "cond_naive": float(np.linalg.cond(cov_sample_daily)),
        "cond_robust": float(np.linalg.cond(cov_daily)),
    }
