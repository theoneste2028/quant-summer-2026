"""
Week 4 — Options Extensions + Bayesian Mini-Project
===================================================
IEMS 302 consolidation project. Extends the Week 3 Monte Carlo pricer.

This module REUSES the validated Week 3 engine (it imports `pricer.py`) and adds:
  1. Asian options  — payoff depends on the AVERAGE price over the path, so it
                      needs full trajectories and has NO closed-form formula.
                      This is where Week 3's validation pays off: we trust the
                      method here precisely because we proved it where a formula
                      existed.
  2. Antithetic variates — a variance-reduction trick that gives a tighter
                      estimate for the same number of paths, attacking Week 3's
                      expensive 1/sqrt(n) convergence.
  3. Greeks (Delta, Vega) — sensitivities via finite differences with COMMON
                      RANDOM NUMBERS, validated against closed-form Black-Scholes.
  4. Bayesian updater — P(up tomorrow) via a Beta-Binomial conjugate model; the
                      posterior narrows as data arrives (Bayes' Rule in action).

Outputs (in ./results/)
-----------------------
  antithetic.png   : standard error, plain MC vs antithetic, across path counts
  greeks.png       : finite-difference Delta/Vega vs analytical, across spot
  bayes_posterior.png : posterior distribution narrowing as data accumulates
  results_table.md : Asian vs European prices, antithetic speedup, Greeks check

Run it:
    python options_extensions.py
"""

from __future__ import annotations
import os
import sys
import numpy as np
from scipy.stats import norm, beta as beta_dist
import matplotlib.pyplot as plt

# --- Import and reuse the validated Week 3 engine -------------------------
_W3 = os.path.join(os.path.dirname(__file__), "..", "03-monte-carlo-pricer")
sys.path.insert(0, _W3)
from pricer import simulate_paths, black_scholes, mc_price, simulate_terminal  # type: ignore  # noqa: E402


RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
TRADING_DAYS = 252


# ============================================================================
# PART 1 — Asian options (path-dependent; no Black-Scholes formula)
# ============================================================================

def mc_price_asian(S0, K, r, sigma, T, n_paths=200_000, n_steps=252,
                   option="call", rng=None) -> dict:
    """Arithmetic-average Asian option price by Monte Carlo.

    Payoff = max(avg(S) - K, 0) for a call, where avg(S) is the mean of the
    monitored prices ALONG the path (excluding the start price S0). Because the
    payoff uses the whole trajectory, we need full paths, and there is no simple
    closed-form Black-Scholes value -- so this relies on the Week 3 validation.
    """
    if rng is None:
        rng = np.random.default_rng()
    paths = simulate_paths(S0, r, sigma, T, n_paths, n_steps, rng)
    avg = paths[:, 1:].mean(axis=1)                      # average after t=0
    if option == "call":
        payoff = np.maximum(avg - K, 0.0)
    else:
        payoff = np.maximum(K - avg, 0.0)
    discounted = np.exp(-r * T) * payoff
    price = discounted.mean()
    se = discounted.std(ddof=1) / np.sqrt(n_paths)
    return {"price": price, "std_error": se,
            "ci_low": price - 1.96 * se, "ci_high": price + 1.96 * se}


# ============================================================================
# PART 2 — Antithetic variates (variance reduction)
# ============================================================================

def mc_price_antithetic(S0, K, r, sigma, T, n_paths=500_000,
                        option="call", rng=None) -> dict:
    """European MC price using antithetic variates.

    For each random draw Z we also use -Z (its mirror image). The two payoffs
    are negatively correlated, so averaging them within each pair cancels much
    of the noise. With m = n_paths/2 pairs we still simulate n_paths futures but
    get a smaller variance than plain MC for the same compute.
    """
    if rng is None:
        rng = np.random.default_rng()
    m = n_paths // 2
    Z = rng.standard_normal(m)
    disc = np.exp(-r * T)
    drift = (r - 0.5 * sigma**2) * T
    diff = sigma * np.sqrt(T)

    def payoff(z):
        S_T = S0 * np.exp(drift + diff * z)
        return np.maximum(S_T - K, 0.0) if option == "call" else np.maximum(K - S_T, 0.0)

    pair_value = disc * 0.5 * (payoff(Z) + payoff(-Z))   # one value per pair
    price = pair_value.mean()
    se = pair_value.std(ddof=1) / np.sqrt(m)
    return {"price": price, "std_error": se,
            "ci_low": price - 1.96 * se, "ci_high": price + 1.96 * se}


def antithetic_comparison(S0, K, r, sigma, T, option="call", seed=7):
    """Compare standard error of plain vs antithetic MC across path counts."""
    ns = np.array([2_000, 10_000, 50_000, 200_000, 1_000_000])
    rows = []
    for n in ns:
        plain = mc_price(S0, K, r, sigma, T, int(n), option, np.random.default_rng(seed))
        anti = mc_price_antithetic(S0, K, r, sigma, T, int(n), option, np.random.default_rng(seed))
        var_reduction = (plain["std_error"] / anti["std_error"]) ** 2
        rows.append((int(n), plain["std_error"], anti["std_error"], var_reduction))
    return rows


# ============================================================================
# PART 3 — Greeks via finite differences (common random numbers)
# ============================================================================
# Delta = d(price)/d(S0),  Vega = d(price)/d(sigma), by central difference:
#     g'(x) ~ [g(x+h) - g(x-h)] / (2h).
# CRITICAL: use the SAME random draws Z for the bumped and base prices ("common
# random numbers"), so the simulation noise cancels in the subtraction. Without
# it, MC Greeks are hopelessly noisy.

def _euro_price_given_Z(Z, S0, K, r, sigma, T, option="call"):
    S_T = S0 * np.exp((r - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * Z)
    payoff = np.maximum(S_T - K, 0.0) if option == "call" else np.maximum(K - S_T, 0.0)
    return np.exp(-r * T) * payoff.mean()

def mc_delta(S0, K, r, sigma, T, n_paths=1_000_000, option="call", h=0.5, rng=None):
    rng = rng or np.random.default_rng()
    Z = rng.standard_normal(n_paths)                     # one draw set, reused
    up = _euro_price_given_Z(Z, S0 + h, K, r, sigma, T, option)
    dn = _euro_price_given_Z(Z, S0 - h, K, r, sigma, T, option)
    return (up - dn) / (2 * h)

def mc_vega(S0, K, r, sigma, T, n_paths=1_000_000, option="call", h=0.005, rng=None):
    rng = rng or np.random.default_rng()
    Z = rng.standard_normal(n_paths)
    up = _euro_price_given_Z(Z, S0, K, r, sigma + h, T, option)
    dn = _euro_price_given_Z(Z, S0, K, r, sigma - h, T, option)
    return (up - dn) / (2 * h)

def bs_greeks(S0, K, r, sigma, T, option="call"):
    """Closed-form Black-Scholes Greeks, to validate the MC finite differences."""
    d1 = (np.log(S0 / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    delta = norm.cdf(d1) if option == "call" else norm.cdf(d1) - 1.0
    vega = S0 * np.sqrt(T) * norm.pdf(d1)                 # same for call and put
    return {"delta": delta, "vega": vega}


# ============================================================================
# PART 4 — Bayesian updater: P(stock up tomorrow) via Beta-Binomial
# ============================================================================
# Prior:  p ~ Beta(a0, b0).  Each day is Bernoulli(up=1/down=0).
# Conjugacy: after seeing #up ones and #down zeros,
#     posterior = Beta(a0 + #up, b0 + #down).
# The posterior is our full belief about p; it narrows as data accumulates.

def bayesian_update(outcomes: np.ndarray, a0=1.0, b0=1.0):
    """Return posterior (a, b), mean, and 95% credible interval after each day."""
    a = a0 + np.cumsum(outcomes)
    b = b0 + np.cumsum(1 - outcomes)
    mean = a / (a + b)
    lo = beta_dist.ppf(0.025, a, b)
    hi = beta_dist.ppf(0.975, a, b)
    return {"a": a, "b": b, "mean": mean, "ci_low": lo, "ci_high": hi}

def load_up_down(ticker="GOOGL", years=2):
    """Daily up(1)/down(0) outcomes from real returns (needs yfinance)."""
    import yfinance as yf
    close = yf.download(ticker, period=f"{years}y", auto_adjust=True, progress=False)["Close"].dropna()
    log_ret = np.log(close / close.shift(1)).dropna().values.ravel()
    return (log_ret > 0).astype(int)


# ============================================================================
# Plots
# ============================================================================

def _plot_antithetic(rows, outdir):
    ns = [r[0] for r in rows]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.loglog(ns, [r[1] for r in rows], "o-", color="0.4", label="Plain MC")
    ax.loglog(ns, [r[2] for r in rows], "s--", color="0.7", label="Antithetic MC")
    ax.set_xlabel("Number of paths (log)"); ax.set_ylabel("Standard error (log)")
    ax.set_title("Antithetic variates cut the standard error (same path count)")
    ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "antithetic.png"), dpi=130)
    plt.close(fig)

def _plot_greeks(S0, K, r, sigma, T, outdir, rng):
    spots = np.linspace(0.7 * K, 1.3 * K, 13)
    mc_d = [mc_delta(s, K, r, sigma, T, 400_000, "call", rng=np.random.default_rng(1)) for s in spots]
    bs_d = [bs_greeks(s, K, r, sigma, T, "call")["delta"] for s in spots]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(spots, bs_d, "-", color="red", lw=2, label="Black-Scholes Delta")
    ax.plot(spots, mc_d, "o", color="0.4", ms=5, label="MC finite-diff Delta")
    ax.axvline(K, color="0.6", ls=":", label=f"Strike K={K:.0f}")
    ax.set_xlabel("Spot price $S_0$"); ax.set_ylabel("Delta")
    ax.set_title("Finite-difference Delta matches Black-Scholes")
    ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "greeks.png"), dpi=130)
    plt.close(fig)

def _plot_bayes(outcomes, post, outdir):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    grid = np.linspace(0, 1, 400)
    for day in (10, 50, 200):
        d = min(day, len(outcomes)) - 1
        a, b = post["a"][d], post["b"][d]
        axes[0].plot(grid, beta_dist.pdf(grid, a, b), label=f"after {day} days")
    axes[0].axvline(0.5, color="0.6", ls=":")
    axes[0].set_title("Posterior for P(up) narrows as data arrives")
    axes[0].set_xlabel("P(up tomorrow)"); axes[0].set_ylabel("Density"); axes[0].legend()

    t = np.arange(1, len(outcomes) + 1)
    axes[1].plot(t, post["mean"], color="0.3", label="Posterior mean")
    axes[1].fill_between(t, post["ci_low"], post["ci_high"], color="0.7",
                         alpha=0.5, label="95% credible interval")
    axes[1].axhline(0.5, color="red", ls="--", label="Coin-flip (0.5)")
    axes[1].set_title("Belief about P(up) over time")
    axes[1].set_xlabel("Trading day"); axes[1].set_ylabel("P(up)"); axes[1].legend()
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "bayes_posterior.png"), dpi=130)
    plt.close(fig)


# ============================================================================
# Orchestration
# ============================================================================

def main(S0=180.0, r=0.04, sigma=0.28, seed=7):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    rng = np.random.default_rng(seed)
    K, T = 180, 1.0
    table_lines = []

    # ---- Part 1: Asian vs European
    asian = mc_price_asian(S0, K, r, sigma, T, 200_000, 252, "call", rng)
    euro = mc_price(S0, K, r, sigma, T, 200_000, "call", rng)
    print("PART 1 — Asian options (no closed-form formula)")
    print(f"  Asian call    = {asian['price']:.4f}  95% CI [{asian['ci_low']:.4f}, {asian['ci_high']:.4f}]")
    print(f"  European call = {euro['price']:.4f}")
    print(f"  Asian < European? {asian['price'] < euro['price']}  "
          "(averaging lowers effective volatility -> cheaper)\n")
    table_lines.append("### Asian vs European call (K=180, T=1)\n")
    table_lines.append(f"- Asian call: **{asian['price']:.4f}** (95% CI [{asian['ci_low']:.4f}, {asian['ci_high']:.4f}])")
    table_lines.append(f"- European call: **{euro['price']:.4f}**")
    table_lines.append(f"- Asian < European: **{asian['price'] < euro['price']}**\n")

    # ---- Part 2: Antithetic variates
    print("PART 2 — Antithetic variates (variance reduction)")
    rows = antithetic_comparison(S0, K, r, sigma, T, "call", seed)
    _plot_antithetic(rows, RESULTS_DIR)
    print(f"  {'paths':>9} {'SE plain':>10} {'SE anti':>10} {'var. reduction':>15}")
    table_lines.append("### Antithetic variance reduction (European call)\n")
    table_lines.append("| Paths | SE plain | SE antithetic | Variance reduction |")
    table_lines.append("|--:|--:|--:|--:|")
    for n, se_p, se_a, vr in rows:
        print(f"  {n:>9} {se_p:>10.5f} {se_a:>10.5f} {vr:>14.2f}x")
        table_lines.append(f"| {n:,} | {se_p:.5f} | {se_a:.5f} | {vr:.2f}x |")
    # correctness: antithetic still matches BS
    bs = black_scholes(S0, K, r, sigma, T, "call")
    anti = mc_price_antithetic(S0, K, r, sigma, T, 1_000_000, "call", np.random.default_rng(3))
    print(f"  correctness: BS={bs:.4f} inside antithetic CI "
          f"[{anti['ci_low']:.4f}, {anti['ci_high']:.4f}]? "
          f"{anti['ci_low'] <= bs <= anti['ci_high']}\n")
    table_lines.append(f"\nCorrectness: Black-Scholes {bs:.4f} inside antithetic 95% CI "
                       f"[{anti['ci_low']:.4f}, {anti['ci_high']:.4f}] -> "
                       f"{anti['ci_low'] <= bs <= anti['ci_high']}\n")

    # ---- Part 3: Greeks
    print("PART 3 — Greeks via finite differences (vs analytical)")
    d_mc = mc_delta(S0, K, r, sigma, T, 1_000_000, "call", rng=np.random.default_rng(5))
    v_mc = mc_vega(S0, K, r, sigma, T, 1_000_000, "call", rng=np.random.default_rng(6))
    g = bs_greeks(S0, K, r, sigma, T, "call")
    print(f"  Delta:  MC {d_mc:.4f}  vs  BS {g['delta']:.4f}  (diff {abs(d_mc-g['delta']):.4f})")
    print(f"  Vega:   MC {v_mc:.4f}  vs  BS {g['vega']:.4f}  (diff {abs(v_mc-g['vega']):.4f})\n")
    _plot_greeks(S0, K, r, sigma, T, RESULTS_DIR, rng)
    table_lines.append("### Greeks: finite-difference MC vs Black-Scholes\n")
    table_lines.append("| Greek | MC | Black-Scholes | abs diff |")
    table_lines.append("|:--|--:|--:|--:|")
    table_lines.append(f"| Delta | {d_mc:.4f} | {g['delta']:.4f} | {abs(d_mc-g['delta']):.4f} |")
    table_lines.append(f"| Vega | {v_mc:.4f} | {g['vega']:.4f} | {abs(v_mc-g['vega']):.4f} |\n")

    # ---- Part 4: Bayesian updater
    print("PART 4 — Bayesian updater (Beta-Binomial)")
    try:
        outcomes = load_up_down("GOOGL", 2)
        src = "live GOOGL data"
    except Exception:
        outcomes = (np.random.default_rng(0).random(300) < 0.53).astype(int)
        src = "synthetic data (p=0.53), offline"
    post = bayesian_update(outcomes, a0=1.0, b0=1.0)
    _plot_bayes(outcomes, post, RESULTS_DIR)
    print(f"  source: {src}; {len(outcomes)} days")
    print(f"  final posterior mean P(up) = {post['mean'][-1]:.4f} "
          f"(95% CI [{post['ci_low'][-1]:.4f}, {post['ci_high'][-1]:.4f}])")
    width0 = post['ci_high'][9] - post['ci_low'][9]
    widthN = post['ci_high'][-1] - post['ci_low'][-1]
    print(f"  credible-interval width shrank from {width0:.3f} (day 10) to {widthN:.3f} (final)\n")
    table_lines.append("### Bayesian P(up tomorrow)\n")
    table_lines.append(f"- Source: {src}, {len(outcomes)} days")
    table_lines.append(f"- Final posterior mean: **{post['mean'][-1]:.4f}** "
                       f"(95% CI [{post['ci_low'][-1]:.4f}, {post['ci_high'][-1]:.4f}])")
    table_lines.append(f"- Credible interval narrowed from {width0:.3f} (day 10) to {widthN:.3f}\n")

    with open(os.path.join(RESULTS_DIR, "results_table.md"), "w") as fh:
        fh.write("\n".join(table_lines))
    print(f"Plots + table written to: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
