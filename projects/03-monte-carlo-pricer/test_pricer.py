"""
Week 3 — Assertion-based tests for the Monte Carlo option pricer
================================================================
`pricer.py` prints a validation table; this asserts it. The checks fall into
three groups, and the third is the one that matters most:

  * Black-Scholes against identities that hold regardless of implementation —
    put-call parity, monotonicity in each input, the T=0 and sigma=0 limits.
  * Monte Carlo against Black-Scholes, using the CONFIDENCE INTERVAL rather than
    a fixed tolerance, so the test is calibrated to the estimator's own noise.
  * The convergence rate itself: standard error must fall like 1/sqrt(n). A
    pricer can produce right answers and still have a broken error estimate,
    and that is what silently invalidates every confidence interval it reports.

Run:
    python test_pricer.py
"""
from __future__ import annotations
import os, sys, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pricer as pc                                     # noqa: E402

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


def test_black_scholes_identities():
    print("\n--- Black-Scholes: identities that must hold " + "-" * 31)
    c = pc.black_scholes(S0, K, R, SIG, T, "call")
    p = pc.black_scholes(S0, K, R, SIG, T, "put")

    # Put-call parity: C - P = S0 - K e^{-rT}. Independent of sigma entirely.
    check("put-call parity", c - p, S0 - K * math.exp(-R * T), tol=1e-9)
    for k2 in (140.0, 200.0, 260.0):
        c2 = pc.black_scholes(S0, k2, R, SIG, T, "call")
        p2 = pc.black_scholes(S0, k2, R, SIG, T, "put")
        check(f"parity holds at K={k2:.0f}", c2 - p2,
              S0 - k2 * math.exp(-R * T), tol=1e-9)

    # Arbitrage bounds on a European call.
    check_true("call price is non-negative", c >= 0)
    check_true("call is worth less than the stock", c < S0)
    check_true("call exceeds its discounted intrinsic value",
               c >= max(S0 - K * math.exp(-R * T), 0) - 1e-9)
    check_true("put is bounded by the discounted strike", p <= K * math.exp(-R * T))

    # Monotonicity.
    check_true("call falls as the strike rises",
               pc.black_scholes(S0, 160, R, SIG, T) > pc.black_scholes(S0, 200, R, SIG, T))
    check_true("call rises with volatility",
               pc.black_scholes(S0, K, R, 0.40, T) > pc.black_scholes(S0, K, R, 0.20, T))
    check_true("call rises with time to expiry",
               pc.black_scholes(S0, K, R, SIG, 2.0) > pc.black_scholes(S0, K, R, SIG, 0.5))
    check_true("call rises with the spot price",
               pc.black_scholes(200, K, R, SIG, T) > pc.black_scholes(160, K, R, SIG, T))

    # Degenerate limits collapse to intrinsic value.
    check("T=0 call equals intrinsic", pc.black_scholes(200, 180, R, SIG, 0.0),
          20.0, tol=1e-12)
    check("T=0 put out of the money is worthless",
          pc.black_scholes(200, 180, R, SIG, 0.0, "put"), 0.0, tol=1e-12)
    check("sigma=0 call equals discounted intrinsic",
          pc.black_scholes(200, 180, R, 0.0, T), 20.0, tol=1e-12)

    # Deep in/out of the money.
    check_true("deep ITM call approaches S0 - K e^{-rT}",
               abs(pc.black_scholes(500, 180, R, SIG, T)
                   - (500 - 180 * math.exp(-R * T))) < 0.5)
    check_true("deep OTM call is nearly worthless",
               pc.black_scholes(50, 180, R, SIG, T) < 0.05)

    raised = False
    try:
        pc.black_scholes(S0, K, R, SIG, T, "straddle")
    except ValueError:
        raised = True
    check_true("an unknown option type is rejected", raised)


def test_gbm_simulation():
    print("\n--- GBM simulation " + "-" * 57)
    rng = np.random.default_rng(11)
    n = 400_000
    ST = pc.simulate_terminal(S0, R, SIG, T, n, rng)

    check_true("all simulated prices are positive", bool(np.all(ST > 0)))
    # Under the risk-neutral measure E[S_T] = S0 e^{rT}.
    want = S0 * math.exp(R * T)
    se = float(ST.std(ddof=1)) / math.sqrt(n)
    check_true("E[S_T] = S0 e^{rT} within 4 SE",
               abs(ST.mean() - want) <= 4 * se,
               f"{ST.mean():.3f} vs {want:.3f} (4SE={4*se:.3f})")
    # log(S_T) must be normal with mean ln S0 + (r - sig^2/2)T and sd sig sqrt(T).
    logret = np.log(ST / S0)
    check_true("log-return mean matches the drift",
               abs(logret.mean() - (R - 0.5 * SIG ** 2) * T) < 4 * logret.std(ddof=1) / math.sqrt(n))
    check_true("log-return sd matches sigma sqrt(T)",
               abs(logret.std(ddof=1) - SIG * math.sqrt(T)) < 0.01,
               f"{logret.std(ddof=1):.4f} vs {SIG*math.sqrt(T):.4f}")

    paths = pc.simulate_paths(S0, R, SIG, T, 500, 50, rng)
    check("path array shape", paths.shape, (500, 51))
    check_true("every path starts at S0",
               bool(np.allclose(paths[:, 0], S0)))
    check_true("all path values are positive", bool(np.all(paths > 0)))
    # The terminal values of full paths must have the same law as the one-step
    # simulation — otherwise the Week 4 Asian pricer is built on a different model.
    check_true("path terminals match the direct terminal law",
               abs(paths[:, -1].mean() - S0 * math.exp(R * T)) <
               5 * paths[:, -1].std(ddof=1) / math.sqrt(500),
               f"{paths[:, -1].mean():.2f} vs {S0*math.exp(R*T):.2f}")


def test_mc_matches_black_scholes():
    print("\n--- Monte Carlo vs Black-Scholes (CI-calibrated) " + "-" * 27)
    rng = np.random.default_rng(2026)
    n_in_ci = n_total = 0
    for opt in ("call", "put"):
        for k in (160.0, 180.0, 200.0):
            for t in (0.25, 1.0):
                bs = pc.black_scholes(S0, k, R, SIG, t, opt)
                res = pc.mc_price(S0, k, R, SIG, t, 300_000, opt, rng)
                inside = res["ci_low"] <= bs <= res["ci_high"]
                n_total += 1
                n_in_ci += int(inside)
                check_true(f"{opt} K={k:.0f} T={t}: BS inside the MC 95% CI", inside,
                           f"BS={bs:.4f} CI=[{res['ci_low']:.4f},{res['ci_high']:.4f}]")
    # With 12 independent 95% intervals, expect ~11.4 hits; require at least 10.
    check_true("coverage is consistent with 95% intervals", n_in_ci >= 10,
               f"{n_in_ci}/{n_total}")

    res = pc.mc_price(S0, K, R, SIG, T, 50_000, "call", np.random.default_rng(5))
    check_true("standard error is positive", res["std_error"] > 0)
    check("CI is symmetric about the estimate",
          (res["ci_high"] + res["ci_low"]) / 2, res["price"], tol=1e-9)
    check("CI half-width is 1.96 SE",
          (res["ci_high"] - res["ci_low"]) / 2, 1.96 * res["std_error"], tol=1e-9)
    check_true("prices are non-negative", res["price"] >= 0)

    # Put-call parity must survive Monte Carlo too, using COMMON random numbers.
    # With shared draws, C - P collapses to disc*(mean(S_T) - K), so its sampling
    # error is disc*sd(S_T)/sqrt(n) — about 0.076 here. Testing against a fixed
    # 0.05 would fail roughly half the time on noise alone, so the tolerance is
    # derived from the estimator rather than guessed.
    n_par = 400_000
    rng2 = np.random.default_rng(99)
    Z = rng2.standard_normal(n_par)
    ST = S0 * np.exp((R - 0.5 * SIG ** 2) * T + SIG * math.sqrt(T) * Z)
    disc = math.exp(-R * T)
    c = disc * np.maximum(ST - K, 0).mean()
    p = disc * np.maximum(K - ST, 0).mean()
    se_par = disc * float(ST.std(ddof=1)) / math.sqrt(n_par)
    check_true("MC put-call parity within 4 SE",
               abs((c - p) - (S0 - K * disc)) <= 4 * se_par,
               f"diff={abs((c-p)-(S0-K*disc)):.4f}, 4SE={4*se_par:.4f}")


def test_convergence_rate():
    print("\n--- Convergence: SE must fall like 1/sqrt(n) " + "-" * 31)
    conv = pc.convergence_study(S0, K, R, SIG, T, np.random.default_rng(3), "call")
    check_true("fitted log-log slope is close to -0.5",
               abs(conv["se_slope"] + 0.5) < 0.03, f"{conv['se_slope']:.4f}")
    check_true("standard error shrinks overall",
               conv["ses"][-1] < conv["ses"][0] / 10,
               f"{conv['ses'][0]:.4f} -> {conv['ses'][-1]:.4f}")
    # Again calibrated to the run's own reported standard error, not a guess:
    # at 1e6 paths the SE is ~0.037, so a fixed 0.05 threshold sits at 1.4 SE
    # and would fail on noise about 16% of the time.
    check_true("the largest run lands within 4 SE of Black-Scholes",
               abs(conv["prices"][-1] - conv["bs"]) <= 4 * conv["ses"][-1],
               f"{conv['prices'][-1]:.4f} vs {conv['bs']:.4f}, "
               f"4SE={4*conv['ses'][-1]:.4f}")
    # Quadrupling the sample should roughly halve the error.
    a = pc.mc_price(S0, K, R, SIG, T, 25_000, "call", np.random.default_rng(1))
    b = pc.mc_price(S0, K, R, SIG, T, 100_000, "call", np.random.default_rng(1))
    ratio = a["std_error"] / b["std_error"]
    check_true("4x the paths roughly halves the SE", 1.7 < ratio < 2.3, f"{ratio:.3f}")


def test_volatility():
    print("\n--- Volatility " + "-" * 61)
    # Historical vol: a series with known daily sd annualises by sqrt(252).
    rng = np.random.default_rng(4)
    daily = rng.normal(0, 0.02, 300_000)
    hv = pc.historical_volatility(daily)
    check_true("historical vol annualises by sqrt(252)",
               abs(hv - 0.02 * math.sqrt(252)) < 0.005,
               f"{hv:.4f} vs {0.02*math.sqrt(252):.4f}")

    # Implied vol must invert Black-Scholes exactly.
    for true_sig in (0.15, 0.28, 0.45, 0.80):
        price = pc.black_scholes(S0, K, R, true_sig, T, "call")
        iv = pc.implied_volatility(price, S0, K, R, T, "call")
        check(f"implied vol recovers sigma={true_sig}", iv, true_sig, tol=1e-6)

    iv_put = pc.implied_volatility(
        pc.black_scholes(S0, K, R, 0.33, T, "put"), S0, K, R, T, "put")
    check("implied vol works for puts", iv_put, 0.33, tol=1e-6)

    # A price below intrinsic has no implied vol; must return NaN, not crash.
    bad = pc.implied_volatility(0.0001, S0, 100.0, R, T, "call")
    check_true("an unattainable price yields NaN", math.isnan(bad), str(bad))


def main():
    print("=" * 78)
    print("Week 3 Monte Carlo pricer test suite")
    print("=" * 78)
    test_black_scholes_identities()
    test_gbm_simulation()
    test_mc_matches_black_scholes()
    test_convergence_rate()
    test_volatility()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
