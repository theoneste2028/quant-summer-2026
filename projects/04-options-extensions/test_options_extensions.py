"""
Week 4 — Assertion-based tests for the options extensions
=========================================================
The hard part of Week 4 is that Asian options have no closed form, so there is
no ground truth to compare against. The tests work around that the way the
project itself does: by checking properties that must hold whatever the true
price is (an Asian call is worth less than its European twin; averaging over one
monitoring date makes them identical), and by pinning the components that DO
have closed forms — the antithetic estimator must still bracket Black-Scholes,
and the finite-difference Greeks must match the analytic ones.

Run:
    python test_options_extensions.py
"""
from __future__ import annotations
import os, sys, math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import options_extensions as ox                          # noqa: E402
from pricer import black_scholes, mc_price               # noqa: E402

PASS, FAIL = [], []
S0, R, SIG, T, K = 180.0, 0.04, 0.28, 1.0, 180.0


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


def test_asian_options():
    print("\n--- Asian options (no closed form to check against) " + "-" * 24)
    rng = np.random.default_rng(42)
    asian = ox.mc_price_asian(S0, K, R, SIG, T, 120_000, 252, "call", rng)
    euro = mc_price(S0, K, R, SIG, T, 120_000, "call", np.random.default_rng(43))

    check_true("Asian call is cheaper than the European",
               asian["price"] < euro["price"],
               f"{asian['price']:.4f} vs {euro['price']:.4f}")
    check_true("Asian price is positive", asian["price"] > 0)
    check_true("Asian CI is well formed",
               asian["ci_low"] < asian["price"] < asian["ci_high"])
    check_true("Asian price is below the spot", asian["price"] < S0)

    # With ONE monitoring date the average IS the terminal price, so the Asian
    # option must collapse onto the European. This is the closest thing to an
    # analytic anchor available for a path-dependent payoff.
    a1 = ox.mc_price_asian(S0, K, R, SIG, T, 200_000, 1, "call",
                           np.random.default_rng(7))
    bs = black_scholes(S0, K, R, SIG, T, "call")
    check_true("a 1-step Asian equals the European (BS inside its CI)",
               a1["ci_low"] <= bs <= a1["ci_high"],
               f"BS={bs:.4f} CI=[{a1['ci_low']:.4f},{a1['ci_high']:.4f}]")

    # More monitoring dates means more averaging, so a lower price.
    few = ox.mc_price_asian(S0, K, R, SIG, T, 120_000, 4, "call", np.random.default_rng(9))
    many = ox.mc_price_asian(S0, K, R, SIG, T, 120_000, 252, "call", np.random.default_rng(9))
    check_true("more averaging dates lower the price",
               many["price"] < few["price"],
               f"252 steps {many['price']:.4f} < 4 steps {few['price']:.4f}")

    put = ox.mc_price_asian(S0, K, R, SIG, T, 80_000, 252, "put", np.random.default_rng(11))
    check_true("Asian put is positive", put["price"] > 0)
    check_true("Asian put is cheaper than the European put",
               put["price"] < black_scholes(S0, K, R, SIG, T, "put"))


def test_antithetic():
    print("\n--- Antithetic variates " + "-" * 52)
    rows = ox.antithetic_comparison(S0, K, R, SIG, T, "call", seed=7)
    for n, se_plain, se_anti, vr in rows:
        check_true(f"n={n:,}: antithetic SE is lower", se_anti < se_plain,
                   f"{se_anti:.5f} < {se_plain:.5f}")
        check_true(f"n={n:,}: variance reduction exceeds 1", vr > 1.0, f"{vr:.2f}x")

    # The reduction factor should be stable across sample sizes — it is a
    # property of the payoff's symmetry, not of how many paths you draw.
    factors = [vr for *_, vr in rows]
    spread = max(factors) - min(factors)
    check_true("variance reduction is stable across sample sizes", spread < 0.35,
               f"factors={[f'{f:.2f}' for f in factors]}")

    # Correctness must survive the variance reduction.
    bs = black_scholes(S0, K, R, SIG, T, "call")
    anti = ox.mc_price_antithetic(S0, K, R, SIG, T, 800_000, "call",
                                  np.random.default_rng(3))
    check_true("Black-Scholes lies inside the antithetic CI",
               anti["ci_low"] <= bs <= anti["ci_high"],
               f"BS={bs:.4f} CI=[{anti['ci_low']:.4f},{anti['ci_high']:.4f}]")
    check("antithetic CI is symmetric",
          (anti["ci_high"] + anti["ci_low"]) / 2, anti["price"], tol=1e-9)

    # It must also work for puts.
    anti_p = ox.mc_price_antithetic(S0, K, R, SIG, T, 400_000, "put",
                                    np.random.default_rng(4))
    bs_p = black_scholes(S0, K, R, SIG, T, "put")
    check_true("antithetic put brackets Black-Scholes",
               anti_p["ci_low"] <= bs_p <= anti_p["ci_high"],
               f"BS={bs_p:.4f} CI=[{anti_p['ci_low']:.4f},{anti_p['ci_high']:.4f}]")


def test_greeks():
    print("\n--- Greeks: finite differences vs analytic " + "-" * 33)
    g = ox.bs_greeks(S0, K, R, SIG, T, "call")
    d_mc = ox.mc_delta(S0, K, R, SIG, T, 800_000, "call", rng=np.random.default_rng(5))
    v_mc = ox.mc_vega(S0, K, R, SIG, T, 800_000, "call", rng=np.random.default_rng(6))

    check_true("MC delta matches analytic within 0.005",
               abs(d_mc - g["delta"]) < 0.005, f"{d_mc:.4f} vs {g['delta']:.4f}")
    check_true("MC vega matches analytic within 0.5",
               abs(v_mc - g["vega"]) < 0.5, f"{v_mc:.4f} vs {g['vega']:.4f}")

    # Structural properties of the analytic Greeks.
    check_true("call delta lies in (0,1)", 0 < g["delta"] < 1, f"{g['delta']:.4f}")
    check_true("vega is positive", g["vega"] > 0)
    check_true("put delta lies in (-1,0)",
               -1 < ox.bs_greeks(S0, K, R, SIG, T, "put")["delta"] < 0)
    check("call and put delta differ by exactly 1",
          g["delta"] - ox.bs_greeks(S0, K, R, SIG, T, "put")["delta"], 1.0, tol=1e-12)
    check("vega is identical for calls and puts",
          g["vega"], ox.bs_greeks(S0, K, R, SIG, T, "put")["vega"], tol=1e-12)

    # Delta must increase with spot, and approach 1 / 0 at the extremes.
    deltas = [ox.bs_greeks(s, K, R, SIG, T, "call")["delta"]
              for s in (100, 140, 180, 220, 260)]
    check_true("delta increases with spot",
               all(deltas[i] < deltas[i + 1] for i in range(len(deltas) - 1)))
    check_true("deep ITM delta approaches 1",
               ox.bs_greeks(600, K, R, SIG, T, "call")["delta"] > 0.99)
    check_true("deep OTM delta approaches 0",
               ox.bs_greeks(40, K, R, SIG, T, "call")["delta"] < 0.01)

    # Vega peaks near the money — that is why at-the-money options are the
    # volatility instrument of choice.
    v_atm = ox.bs_greeks(S0, 180, R, SIG, T)["vega"]
    check_true("vega is largest near the money",
               v_atm > ox.bs_greeks(S0, 120, R, SIG, T)["vega"] and
               v_atm > ox.bs_greeks(S0, 260, R, SIG, T)["vega"])

    # Common random numbers are what make finite-difference Greeks usable: with
    # independent draws the estimate is far noisier. Demonstrate the difference.
    def delta_independent(seed):
        h = 0.5
        up = ox._euro_price_given_Z(np.random.default_rng(seed).standard_normal(200_000),
                                    S0 + h, K, R, SIG, T)
        dn = ox._euro_price_given_Z(np.random.default_rng(seed + 1000).standard_normal(200_000),
                                    S0 - h, K, R, SIG, T)
        return (up - dn) / (2 * h)

    crn = [ox.mc_delta(S0, K, R, SIG, T, 200_000, "call", rng=np.random.default_rng(s))
           for s in range(6)]
    ind = [delta_independent(s) for s in range(6)]
    check_true("common random numbers cut the Greek's noise dramatically",
               np.std(crn) < np.std(ind) / 10,
               f"sd(CRN)={np.std(crn):.5f} vs sd(independent)={np.std(ind):.5f}")


def test_bayesian_updater():
    print("\n--- Bayesian Beta-Binomial updater " + "-" * 41)
    # Beta(1,1) prior with k successes in n trials -> posterior Beta(1+k, 1+n-k),
    # whose mean is (1+k)/(2+n). Check against that closed form exactly.
    outcomes = np.array([1, 0, 1, 1, 0])
    post = ox.bayesian_update(outcomes, a0=1.0, b0=1.0)
    check("posterior a after 5 obs", float(post["a"][-1]), 1 + 3)
    check("posterior b after 5 obs", float(post["b"][-1]), 1 + 2)
    check("posterior mean = (1+k)/(2+n)", float(post["mean"][-1]), 4 / 7)
    check("running arrays have one entry per observation", len(post["mean"]), 5)

    check_true("credible interval brackets the mean",
               bool(np.all(post["ci_low"] <= post["mean"]) and
                    np.all(post["mean"] <= post["ci_high"])))
    check_true("posterior mean always stays a probability",
               bool(np.all((post["mean"] >= 0) & (post["mean"] <= 1))))

    # The interval must narrow as evidence accumulates, and the mean must
    # converge on the true rate.
    rng = np.random.default_rng(2)
    true_p = 0.62
    big = (rng.random(20_000) < true_p).astype(int)
    pb = ox.bayesian_update(big, 1.0, 1.0)
    w_early = pb["ci_high"][99] - pb["ci_low"][99]
    w_late = pb["ci_high"][-1] - pb["ci_low"][-1]
    check_true("credible interval narrows with data", w_late < w_early / 5,
               f"{w_early:.4f} -> {w_late:.4f}")
    check_true("posterior mean converges to the true rate",
               abs(pb["mean"][-1] - true_p) < 0.02,
               f"{pb['mean'][-1]:.4f} vs {true_p}")

    # A strong prior must visibly pull a small sample.
    weak = ox.bayesian_update(np.array([1, 1, 1]), 1.0, 1.0)
    strong = ox.bayesian_update(np.array([1, 1, 1]), 50.0, 50.0)
    check_true("a strong prior resists a small sample",
               strong["mean"][-1] < weak["mean"][-1],
               f"strong={strong['mean'][-1]:.4f} weak={weak['mean'][-1]:.4f}")
    check_true("a strong symmetric prior stays near 0.5",
               abs(strong["mean"][-1] - 0.5) < 0.05)


def main():
    print("=" * 78)
    print("Week 4 options extensions test suite")
    print("=" * 78)
    test_asian_options()
    test_antithetic()
    test_greeks()
    test_bayesian_updater()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
