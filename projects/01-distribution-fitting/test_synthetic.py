"""
Week 1 — Assertion-based tests for the distribution-fitting pipeline
====================================================================
Verify the pipeline end-to-end on synthetic data whose true distribution is
known, so "Student-t fits best" can be checked rather than believed.

The most important test here is the NEGATIVE CONTROL: given genuinely normal
data, the pipeline must pick the Normal. A method that always answers
"Student-t" would look perfect on real market returns and be worthless, because
it would not be measuring anything.

Run:
    python test_synthetic.py
"""
from __future__ import annotations
import os, sys, tempfile
import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import distribution_fitting as df_                      # noqa: E402

PASS, FAIL = [], []


def check(name, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    (PASS if ok else FAIL).append(name)
    g = f"{got:.6f}" if isinstance(got, float) else repr(got)
    w = f"{want:.6f}" if isinstance(want, float) else repr(want)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {g}, want {w}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


def t_sample(n, dfree, sigma, rng):
    """Student-t draws rescaled to unit variance, then to `sigma`."""
    raw = stats.t.rvs(dfree, size=n, random_state=rng)
    return raw / np.sqrt(dfree / (dfree - 2)) * sigma


def test_log_returns():
    print("\n--- Log returns " + "-" * 60)
    prices = pd.DataFrame({"X": [100.0, 110.0, 121.0]})
    r = df_.to_log_returns(prices)
    check("one fewer return than prices", len(r), 2)
    check("log return of a 10% rise", float(r["X"].iloc[0]), np.log(1.1))
    check_true("equal proportional moves give equal log returns",
               abs(float(r["X"].iloc[0]) - float(r["X"].iloc[1])) < 1e-12)
    # Log returns add across periods; simple returns do not.
    check("log returns are additive", float(r["X"].sum()),
          float(np.log(121.0 / 100.0)), tol=1e-12)


def test_moments():
    print("\n--- Moments " + "-" * 64)
    rng = np.random.default_rng(1)
    normal = rng.normal(0.001, 0.02, 200_000)
    m = df_.moments(normal)
    check("n is the sample size", m["n"], 200_000)
    check_true("mean is recovered", abs(m["mean"] - 0.001) < 0.001, f"{m['mean']:.5f}")
    check_true("std is recovered", abs(m["std"] - 0.02) < 0.001, f"{m['std']:.5f}")
    check_true("variance is std squared", abs(m["variance"] - m["std"] ** 2) < 1e-12)
    check_true("normal data has ~zero excess kurtosis",
               abs(m["excess_kurtosis"]) < 0.06, f"{m['excess_kurtosis']:.4f}")
    check_true("raw kurtosis is excess + 3",
               abs(m["kurtosis_raw"] - m["excess_kurtosis"] - 3) < 1e-9)
    check_true("normal data has ~zero skew", abs(m["skewness"]) < 0.05,
               f"{m['skewness']:.4f}")

    fat = t_sample(200_000, 4.0, 0.02, np.random.default_rng(2))
    mf = df_.moments(fat)
    check_true("t(4) data has large positive excess kurtosis",
               mf["excess_kurtosis"] > 1.0, f"{mf['excess_kurtosis']:.3f}")
    check_true("fat tails exceed normal kurtosis",
               mf["excess_kurtosis"] > m["excess_kurtosis"])


def test_fit_recovers_truth():
    print("\n--- Fitting recovers the generating distribution " + "-" * 27)
    rng = np.random.default_rng(11)
    for true_df in (3.0, 5.0, 8.0):
        x = t_sample(60_000, true_df, 0.02, rng)
        res = df_.fit_all(x)
        fits = res["fits"]
        check(f"t({true_df:.0f}) data: Student-t wins on AIC",
              res["best_by_aic"], "Student-t")
        got_df = fits["Student-t"]["params"][0]
        check_true(f"t({true_df:.0f}) data: recovered df is close",
                   abs(got_df - true_df) / true_df < 0.25,
                   f"recovered {got_df:.2f} vs true {true_df:.1f}")
        check_true(f"t({true_df:.0f}) data: t has a smaller KS stat than Normal",
                   fits["Student-t"]["ks_stat"] < fits["Normal"]["ks_stat"],
                   f"{fits['Student-t']['ks_stat']:.4f} vs "
                   f"{fits['Normal']['ks_stat']:.4f}")
        check_true(f"t({true_df:.0f}) data: t has a higher log-likelihood",
                   fits["Student-t"]["loglik"] > fits["Normal"]["loglik"])


def test_negative_control():
    print("\n--- NEGATIVE CONTROL: normal data must select the Normal " + "-" * 19)
    rng = np.random.default_rng(21)
    for sd in (0.005, 0.02, 0.05):
        x = rng.normal(0.0, sd, 80_000)
        res = df_.fit_all(x)
        check(f"normal(sd={sd}) data: Normal wins on AIC",
              res["best_by_aic"], "Normal")
        fits = res["fits"]
        n_ks, t_ks, l_ks = (fits["Normal"]["ks_stat"], fits["Student-t"]["ks_stat"],
                            fits["Laplace"]["ks_stat"])
        # NOT asserted: that the Normal has the strictly smallest KS statistic.
        # It often will not, and that is correct — KS rewards goodness of fit
        # with no penalty for complexity, so the 3-parameter t can always match
        # or marginally beat the 2-parameter Normal by using its extra freedom
        # on sampling noise. What must hold is that the two are INDISTINGUISHABLE
        # (here they agree to ~4 decimals) while Laplace is plainly wrong.
        check_true(f"normal(sd={sd}): Normal and t are indistinguishable on KS",
                   abs(n_ks - t_ks) < 0.10 * min(n_ks, t_ks),
                   f"|N-t|={abs(n_ks-t_ks):.2e} = "
                   f"{abs(n_ks-t_ks)/min(n_ks, t_ks):.1%} of the smaller")
        check_true(f"normal(sd={sd}): Laplace is far worse than both",
                   l_ks > 10 * max(n_ks, t_ks),
                   f"L={l_ks:.6f} vs max(N,t)={max(n_ks, t_ks):.6f}")
        # AIC is what actually separates Normal from t, and it does so through
        # the parameter penalty: the extra parameter costs 2 and buys almost no
        # log-likelihood, so the gap sits just under 2k = 2.
        gap = fits["Student-t"]["aic"] - fits["Normal"]["aic"]
        check_true(f"normal(sd={sd}): AIC favours Normal by roughly the penalty",
                   0 < gap <= 2.05, f"AIC(t) - AIC(N) = {gap:.4f}, expected 0 < gap <= 2")
        # A t fitted to normal data should report very large degrees of freedom,
        # since t -> Normal as df -> infinity.
        check_true(f"normal(sd={sd}): fitted t df is large",
                   fits["Student-t"]["params"][0] > 15,
                   f"df={fits['Student-t']['params'][0]:.1f}")

    # Laplace data must select Laplace — a third arm, so the choice is not just
    # binary between "normal" and "fat".
    lap = stats.laplace.rvs(loc=0, scale=0.02, size=80_000,
                            random_state=np.random.default_rng(31))
    check("Laplace data selects Laplace", df_.fit_all(lap)["best_by_aic"], "Laplace")


def test_fit_scoring():
    print("\n--- Fit scoring mechanics " + "-" * 50)
    rng = np.random.default_rng(41)
    x = rng.normal(0, 0.02, 20_000)
    res = df_.fit_all(x)
    for name, f in res["fits"].items():
        check_true(f"{name}: KS statistic in [0,1]", 0 <= f["ks_stat"] <= 1)
        check_true(f"{name}: AIC = 2k - 2logL",
                   abs(f["aic"] - (2 * f["k"] - 2 * f["loglik"])) < 1e-9)
    check("Normal has 2 parameters", res["fits"]["Normal"]["k"], 2)
    check("Student-t has 3 parameters", res["fits"]["Student-t"]["k"], 3)
    check("Laplace has 2 parameters", res["fits"]["Laplace"]["k"], 2)
    best = res["best_by_aic"]
    check_true("best_by_aic really is the minimum",
               all(res["fits"][best]["aic"] <= f["aic"] for f in res["fits"].values()))


def test_analyze_pipeline():
    print("\n--- End-to-end analyze() " + "-" * 51)
    rng = np.random.default_rng(7)
    spec = {"GOOGL": (0.018, 4.5), "PLTR": (0.045, 3.0), "VRT": (0.035, 3.5),
            "STX": (0.028, 3.8), "SPY": (0.011, 5.5)}
    returns = pd.DataFrame({tk: t_sample(1260, dfree, sig, rng) + 0.0004
                            for tk, (sig, dfree) in spec.items()})

    outdir = tempfile.mkdtemp(prefix="wk1_")
    table = df_.analyze(returns, outdir=outdir)

    check("one row per ticker", len(table), len(spec))
    check_true("all tickers present", set(table["ticker"]) == set(spec))
    for col in ("ticker", "n_days", "std", "skewness", "excess_kurtosis",
                "t_df", "ks_normal", "ks_t", "best_fit"):
        check_true(f"table has column {col!r}", col in table.columns)
    check_true("every ticker prefers a fat-tailed fit",
               set(table["best_fit"]) <= {"Student-t", "Laplace"},
               str(table["best_fit"].tolist()))
    check_true("KS(t) beats KS(normal) for every ticker",
               bool((table["ks_t"] < table["ks_normal"]).all()))
    check_true("all excess kurtoses are positive",
               bool((table["excess_kurtosis"] > 0).all()))
    # Sigma recovery is deliberately given a wide band. For a Student-t with
    # df <= 4 the FOURTH moment is infinite, which means the sample standard
    # deviation has infinite variance and is a genuinely noisy estimator — VRT
    # (df=3.5) lands ~16% off at n=1260 and that is correct behaviour, not a
    # bug. It is also the point of the whole week: with tails this heavy, the
    # summary statistics people quote are themselves unstable.
    errs = {tk: abs(table.set_index("ticker").loc[tk, "std"] - sig) / sig
            for tk, (sig, _) in spec.items()}
    check_true("recovered sigma is within 25% for every ticker",
               all(e < 0.25 for e in errs.values()),
               ", ".join(f"{tk}:{e:+.1%}" for tk, e in errs.items()))
    # And the heavy-tailed names should be the badly estimated ones.
    low_df = [tk for tk, (_, d) in spec.items() if d <= 4.0]
    high_df = [tk for tk, (_, d) in spec.items() if d > 4.0]
    check_true("low-df tickers are estimated less precisely than high-df ones",
               max(errs[t] for t in low_df) > min(errs[t] for t in high_df),
               f"low-df max {max(errs[t] for t in low_df):.1%} vs "
               f"high-df min {min(errs[t] for t in high_df):.1%}")

    for fname in ("results.csv", "results_table.md", "excess_kurtosis.png"):
        check_true(f"analyze wrote {fname}",
                   os.path.exists(os.path.join(outdir, fname)))
    for tk in spec:
        check_true(f"analyze wrote plots for {tk}",
                   os.path.exists(os.path.join(outdir, f"{tk}_fit.png")) and
                   os.path.exists(os.path.join(outdir, f"{tk}_qq.png")))


def main():
    print("=" * 78)
    print("Week 1 distribution fitting test suite")
    print("=" * 78)
    test_log_returns()
    test_moments()
    test_fit_recovers_truth()
    test_negative_control()
    test_fit_scoring()
    test_analyze_pipeline()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
