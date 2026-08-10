"""
Week 11 — Test suite for the capstone
=====================================
The capstone is where a wrong number is hardest to notice: every layer produces
plausible-looking output, and an error in the covariance or the utility scale
shows up as a slightly different recommendation rather than a crash. So the
tests check invariants that must hold whatever the data says, plus the specific
integration points where one layer hands work to the next.

Fast checks run on a small synthetic market with a KNOWN covariance, so the
estimators can be scored against truth. A final section runs the real pipeline.

Run:
    python test_capstone.py            # everything
    python test_capstone.py --fast     # skip the real-data pipeline
"""
from __future__ import annotations
import os, sys
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import capstone as cs                                    # noqa: E402
import robust as rb                                      # noqa: E402

PASS, FAIL = [], []


def check(name, got, want, tol=1e-9):
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        ok = abs(got - want) <= tol
    else:
        ok = got == want
    (PASS if ok else FAIL).append(name)
    g = f"{got:,.6f}" if isinstance(got, float) else repr(got)
    w = f"{want:,.6f}" if isinstance(want, float) else repr(want)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {g}, want {w}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


def synthetic_market(n_assets=6, n_days=1500, seed=3):
    """Returns drawn from a KNOWN covariance, so estimators can be scored."""
    rng = np.random.default_rng(seed)
    true_vol = np.linspace(0.10, 0.45, n_assets) / np.sqrt(cs.TRADING_DAYS)
    base_corr = 0.35
    corr = np.full((n_assets, n_assets), base_corr)
    np.fill_diagonal(corr, 1.0)
    true_cov = np.outer(true_vol, true_vol) * corr
    true_mu = np.linspace(0.02, 0.20, n_assets) / cs.TRADING_DAYS
    L = np.linalg.cholesky(true_cov)
    X = true_mu + rng.standard_normal((n_days, n_assets)) @ L.T
    return X, true_mu, true_cov


# ---------------------------------------------------------------------------
def test_ledoit_wolf():
    print("\n--- Ledoit-Wolf covariance shrinkage " + "-" * 39)
    X, _, true_cov = synthetic_market()
    lw = rb.ledoit_wolf_constant_correlation(X)

    check_true("shrinkage intensity in [0,1]", 0 <= lw["shrinkage"] <= 1,
               f"{lw['shrinkage']:.4f}")
    check_true("average correlation is recovered",
               abs(lw["avg_corr"] - 0.35) < 0.05, f"{lw['avg_corr']:.4f}")
    check_true("result is symmetric",
               np.allclose(lw["cov"], lw["cov"].T))
    ev = np.linalg.eigvalsh(lw["cov"])
    check_true("result is positive definite", ev.min() > 0, f"min eig {ev.min():.3e}")
    check_true("diagonal variances are preserved within a few percent",
               np.allclose(np.diag(lw["cov"]), np.diag(lw["sample_cov"]), rtol=0.05))

    # Shrinkage must improve the estimate when observations are scarce. With
    # T barely above N the sample covariance is badly conditioned and the
    # shrunk version should be measurably closer to the truth.
    Xs, _, tc = synthetic_market(n_assets=12, n_days=40, seed=5)
    lw_s = rb.ledoit_wolf_constant_correlation(Xs)
    err_sample = np.linalg.norm(lw_s["sample_cov"] - tc)
    err_shrunk = np.linalg.norm(lw_s["cov"] - tc)
    check_true("shrinkage beats the sample covariance when T is small",
               err_shrunk < err_sample,
               f"shrunk {err_shrunk:.3e} vs sample {err_sample:.3e}")
    check_true("shrinkage is heavy when data is scarce", lw_s["shrinkage"] > 0.2,
               f"{lw_s['shrinkage']:.3f}")
    check_true("conditioning improves",
               np.linalg.cond(lw_s["cov"]) < np.linalg.cond(lw_s["sample_cov"]),
               f"{np.linalg.cond(lw_s['cov']):.1f} vs "
               f"{np.linalg.cond(lw_s['sample_cov']):.1f}")


def test_bayes_stein():
    print("\n--- Bayes-Stein mean shrinkage " + "-" * 45)
    X, true_mu, true_cov = synthetic_market()
    mu_hat = X.mean(axis=0)
    cov_hat = np.cov(X, rowvar=False)
    bs = rb.bayes_stein_mean(mu_hat, cov_hat, X.shape[0])

    check_true("intensity in [0,1]", 0 <= bs["intensity"] <= 1,
               f"{bs['intensity']:.4f}")
    check_true("every shrunk mean lies between the sample mean and the target",
               all(min(m, bs["target"]) - 1e-12 <= s <= max(m, bs["target"]) + 1e-12
                   for m, s in zip(mu_hat, bs["mu"])))
    check_true("shrinking reduces the dispersion of means",
               bs["mu"].std() <= mu_hat.std() + 1e-12,
               f"{bs['mu'].std():.3e} vs {mu_hat.std():.3e}")

    # Short samples must shrink harder than long ones.
    short = rb.bayes_stein_mean(mu_hat, cov_hat, 30)
    long_ = rb.bayes_stein_mean(mu_hat, cov_hat, 5000)
    check_true("a shorter sample shrinks more",
               short["intensity"] > long_["intensity"],
               f"T=30 -> {short['intensity']:.3f}, T=5000 -> {long_['intensity']:.3f}")


def test_min_variance():
    print("\n--- Minimum-variance portfolio " + "-" * 45)
    _, _, cov = synthetic_market()
    w = rb.min_variance_weights(cov)
    check("weights sum to 1", float(w.sum()), 1.0, tol=1e-6)
    check_true("weights are non-negative", bool((w >= -1e-9).all()))
    v_mv = float(np.sqrt(w @ cov @ w))
    # No other long-only portfolio may have lower variance — spot-check against
    # equal weight and against each single asset.
    eq = np.full(len(w), 1 / len(w))
    check_true("beats equal weight", v_mv <= float(np.sqrt(eq @ cov @ eq)) + 1e-9)
    for i in range(len(w)):
        e = np.zeros(len(w)); e[i] = 1
        check_true(f"beats holding asset {i} alone",
                   v_mv <= float(np.sqrt(e @ cov @ e)) + 1e-9)


def test_optimizer():
    print("\n--- Markowitz optimizer " + "-" * 52)
    X, _, _ = synthetic_market()
    r = rb.robust_estimates(X)
    mu, cov = r["mu"], r["cov"]

    w = cs.solve_markowitz(mu, cov, gamma=5.0)
    check("weights sum to 1", float(w.sum()), 1.0, tol=1e-6)
    check_true("long-only constraint holds", bool((w >= -1e-9).all()))

    capped = cs.solve_markowitz(mu, cov, gamma=0.5, max_weight=0.25)
    check_true("max-weight constraint holds", bool((capped <= 0.25 + 1e-6).all()),
               f"max {capped.max():.4f}")
    check("capped weights still sum to 1", float(capped.sum()), 1.0, tol=1e-6)

    # Raising risk aversion must reduce both return and volatility.
    lo = cs.solve_markowitz(mu, cov, gamma=0.5)
    hi = cs.solve_markowitz(mu, cov, gamma=50.0)
    v_lo = float(np.sqrt(lo @ cov @ lo)); v_hi = float(np.sqrt(hi @ cov @ hi))
    check_true("higher gamma lowers volatility", v_hi < v_lo,
               f"{v_hi:.4f} < {v_lo:.4f}")
    check_true("higher gamma lowers expected return", mu @ hi < mu @ lo)

    fr = cs.efficient_frontier(mu, cov, gammas=np.logspace(-1, 2, 15))
    check_true("frontier is non-empty", len(fr) > 5, str(len(fr)))
    check_true("return and volatility move together along the frontier",
               bool((np.diff(fr.sort_values('vol')['ret'].values) >= -1e-6).all()))
    check_true("every frontier portfolio is fully invested",
               all(abs(w.sum() - 1) < 1e-6 for w in fr["weights"]))
    check_true("a very high gamma approaches minimum variance",
               abs(float(np.sqrt(hi @ cov @ hi))
                   - float(np.sqrt(rb.min_variance_weights(cov) @ cov
                                   @ rb.min_variance_weights(cov)))) < 0.02)


def test_certainty_equivalent_layer():
    print("\n--- Decision layer " + "-" * 57)
    X, _, _ = synthetic_market()
    r = rb.robust_estimates(X)
    mu, cov = r["mu"], r["cov"]
    n = len(mu)
    w = np.full(n, 1 / n)
    wealth = 100_000.0

    ce_neutral = cs.portfolio_certainty_equivalent(w, mu, cov, wealth, None, n=40_000)
    ce_averse = cs.portfolio_certainty_equivalent(w, mu, cov, wealth, 50_000, n=40_000)
    check_true("risk aversion lowers the certainty equivalent",
               ce_averse < ce_neutral, f"{ce_averse:,.0f} < {ce_neutral:,.0f}")
    ce_more = cs.portfolio_certainty_equivalent(w, mu, cov, wealth, 10_000, n=40_000)
    check_true("more risk aversion lowers it further", ce_more < ce_averse,
               f"{ce_more:,.0f} < {ce_averse:,.0f}")

    # A zero-volatility portfolio has CE equal to its certain outcome.
    zero_cov = np.zeros_like(cov)
    ce_certain = cs.portfolio_certainty_equivalent(
        np.eye(n)[0], np.array([0.10] + [0.0] * (n - 1)), zero_cov,
        wealth, 50_000, n=2000)
    check("a riskless portfolio's CE equals its certain value",
          ce_certain, wealth * np.exp(0.10), tol=1.0)

    fr = cs.efficient_frontier(mu, cov, gammas=np.logspace(-1, 2, 12),
                               max_weight=0.5)
    ch_averse = cs.choose_portfolio(fr, mu, cov, wealth, 5_000, seed=1)
    ch_tolerant = cs.choose_portfolio(fr, mu, cov, wealth, 500_000, seed=1)
    v_a = float(np.sqrt(ch_averse["weights"] @ cov @ ch_averse["weights"]))
    v_t = float(np.sqrt(ch_tolerant["weights"] @ cov @ ch_tolerant["weights"]))
    check_true("a risk-averse investor is steered to a lower-volatility portfolio",
               v_a < v_t, f"{v_a:.4f} < {v_t:.4f}")
    check_true("the chosen portfolio is on the frontier",
               any(np.allclose(ch_averse["weights"], ww) for ww in fr["weights"]))


def test_monte_carlo():
    print("\n--- Monte Carlo layer " + "-" * 54)
    X, _, _ = synthetic_market()
    r = rb.robust_estimates(X)
    mu, cov = r["mu"], r["cov"]
    w = np.full(len(mu), 1 / len(mu))

    mc = cs.simulate_forward(w, mu, cov, n_paths=40_000, seed=3)
    check_true("1% VaR is worse than 5% VaR", mc["var_1"] > mc["var_5"],
               f"{mc['var_1']:.4f} > {mc['var_5']:.4f}")
    check_true("1% CVaR is worse than 1% VaR", mc["cvar_1"] >= mc["var_1"])
    check_true("5% CVaR is worse than 5% VaR", mc["cvar_5"] >= mc["var_5"])
    check_true("P(loss) exceeds P(loss > 10%)",
               mc["p_loss_any"] >= mc["p_loss_10"])
    check_true("all probabilities are in [0,1]",
               all(0 <= mc[k] <= 1 for k in ("p_loss_any", "p_loss_10")))
    check_true("returns cannot fall below -100%", mc["returns"].min() > -1.0)
    check_true("the mean lies inside its own confidence interval",
               mc["ci_low"] <= mc["mean"] <= mc["ci_high"])
    # Log-normal-ish terminal wealth is right-skewed, so mean > median.
    check_true("mean exceeds median (right skew from compounding)",
               mc["mean"] > mc["median"])

    same = cs.simulate_forward(w, mu, cov, n_paths=20_000, seed=99)
    again = cs.simulate_forward(w, mu, cov, n_paths=20_000, seed=99)
    check("the same seed reproduces the same result", same["mean"], again["mean"])
    diff = cs.simulate_forward(w, mu, cov, n_paths=20_000, seed=100)
    check_true("a different seed gives a different draw", diff["mean"] != same["mean"])

    # A higher-volatility portfolio must have a worse VaR.
    vols = np.sqrt(np.diag(cov))
    w_safe = np.zeros(len(mu)); w_safe[np.argmin(vols)] = 1
    w_risky = np.zeros(len(mu)); w_risky[np.argmax(vols)] = 1
    mc_s = cs.simulate_forward(w_safe, mu, cov, n_paths=30_000, seed=4)
    mc_r = cs.simulate_forward(w_risky, mu, cov, n_paths=30_000, seed=4)
    check_true("the riskier portfolio has the worse 5% VaR",
               mc_r["var_5"] > mc_s["var_5"],
               f"{mc_r['var_5']:.3f} > {mc_s['var_5']:.3f}")

    t = cs.simulate_forward(w, mu, cov, n_paths=40_000, seed=3, t_df=4.0)
    check("t-model records its degrees of freedom", t["t_df"], 4.0)
    check("model label is set", t["model"], "student-t")
    check_true("both models give a similar mean (same variance)",
               abs(t["mean"] - mc["mean"]) < 0.06,
               f"{t['mean']:.4f} vs {mc['mean']:.4f}")


def test_alignment_and_describe():
    print("\n--- Allocation handling " + "-" * 52)
    alloc = pd.Series({"AAA": 0.5, "BBB": 0.3, "ZZZ": 0.2})
    w = cs.align_weights(alloc, ["AAA", "BBB", "CCC"])
    check("aligned weights renormalise to 1", float(w.sum()), 1.0, tol=1e-9)
    check("known holding keeps its relative share", float(w[0]), 0.5 / 0.8)
    check("absent holding gets zero weight", float(w[2]), 0.0)
    check("an empty allocation stays empty",
          float(cs.align_weights(pd.Series({"ZZZ": 1.0}), ["AAA"]).sum()), 0.0)

    _, _, cov = synthetic_market()
    mu = np.linspace(0.05, 0.3, cov.shape[0])
    ww = np.zeros(cov.shape[0]); ww[0] = 0.6; ww[1] = 0.4
    d = cs.describe(ww, mu, cov, [f"T{i}" for i in range(cov.shape[0])])
    check("describe counts holdings", d["n_holdings"], 2)
    check("describe computes the expected return", d["ret"], float(mu @ ww))
    check("describe reports the largest holding first", d["top"][0][0], "T0")


def test_real_pipeline():
    print("\n--- Real end-to-end pipeline " + "-" * 47)
    if not os.path.exists(cs.DB_PATH):
        print("  (skipped — no database)")
        return
    out = cs.run(n_paths=20_000, quiet=True)

    d = out["data"]
    check_true("returns matrix has no missing values",
               not d["returns"].isna().any().any())
    check_true("universe is non-trivial", len(out["tickers"]) >= 10,
               str(len(out["tickers"])))
    check_true("every universe member has a full return series",
               d["returns"].shape[0] == d["n_days"])
    check_true("excluded tickers really do have short histories",
               all(n < 400 for n in d["excluded"].values()), str(d["excluded"]))
    check_true("no ticker is both included and excluded",
               not (set(out["tickers"]) & set(d["excluded"])))

    m = out["moments"]
    check_true("shrunk covariance is positive definite",
               np.linalg.eigvalsh(m["cov"]).min() > 0)
    check_true("shrinkage improved the conditioning",
               m["cond_robust"] < m["cond_number"],
               f"{m['cond_robust']:,.0f} < {m['cond_number']:,.0f}")
    check_true("shrunk means are less dispersed than raw ones",
               m["mu"].std() < m["mu_naive"].std())

    rec = out["recommended"]
    w = np.asarray(rec["weights"])
    check("recommended weights sum to 1", float(w.sum()), 1.0, tol=1e-6)
    check_true("recommended weights are non-negative", bool((w >= -1e-9).all()))
    check_true("the max-weight cap is respected",
               bool((w <= out["max_weight"] + 1e-6).all()), f"max {w.max():.4f}")
    check_true("the recommendation is diversified",
               rec["n_holdings"] >= 3, str(rec["n_holdings"]))

    cur = out["current"]
    check_true("current allocation covers most of the portfolio",
               cur["covered"] > 0.5, f"{cur['covered']:.1%}")
    check_true("the recommendation has a higher certainty equivalent",
               rec["ce"] >= cur["ce"] - 1e-6,
               f"rec {rec['ce']:,.0f} vs cur {cur['ce']:,.0f}")
    check_true("the recommendation has a better Sharpe ratio",
               rec["sharpe"] >= cur["sharpe"],
               f"{rec['sharpe']:.3f} vs {cur['sharpe']:.3f}")

    check_true("all 20 assets reject normality (Week 1 result reproduced)",
               (out["diagnostics"]["best_fit"] != "Normal").all())
    check_true("the fitted t degrees of freedom are heavy-tailed",
               2 < out["median_t_df"] < 10, f"{out['median_t_df']:.2f}")

    sweep = out["sweep"]
    check_true("volatility rises monotonically with risk tolerance",
               bool((np.diff(sweep["vol"].values) >= -1e-6).all()),
               str([f"{v:.3f}" for v in sweep["vol"]]))
    check_true("the sweep spans a wide range of portfolios",
               sweep["vol"].max() / sweep["vol"].min() > 2,
               f"{sweep['vol'].min():.3f}..{sweep['vol'].max():.3f}")

    tail = out["tail_study"]
    check_true("fat tails hurt most at the shortest horizon",
               tail.iloc[0]["ratio"] >= tail.iloc[-1]["ratio"],
               f"1 day {tail.iloc[0]['ratio']:.3f} vs "
               f"1 year {tail.iloc[-1]['ratio']:.3f}")
    check_true("1% VaR grows with the horizon",
               bool((np.diff(tail["var1_normal"].values) > 0).all()))


def main():
    fast = "--fast" in sys.argv
    print("=" * 78)
    print("Week 11 capstone test suite")
    print("=" * 78)
    test_ledoit_wolf()
    test_bayes_stein()
    test_min_variance()
    test_optimizer()
    test_certainty_equivalent_layer()
    test_monte_carlo()
    test_alignment_and_describe()
    if not fast:
        test_real_pipeline()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
