"""
Week 3 — Monte Carlo Option Pricer
==================================
IEMS 302 consolidation project.

The idea
--------
An option is a "coupon on the future": a European CALL pays max(S_T - K, 0) at
expiry. We price it two ways and check they agree:
  1. Monte Carlo  — simulate thousands of random future prices, average the
                    payoff, discount to today. (The Week 2 trick, applied to
                    stock prices instead of cards.)
  2. Black-Scholes — the exact closed-form answer, used as ground truth.
Then we confirm the MC error shrinks like 1/sqrt(n) (the Central Limit Theorem
in action) and report 95% confidence intervals for every estimate.

The engine assumes returns are NORMAL (so prices are lognormal) — the very
assumption Week 1 showed is too thin-tailed. We use it knowing where it bends.

Outputs (in ./results/)
-----------------------
  sample_paths.png         : a handful of simulated price futures (the "dice")
  terminal_distribution.png: histogram of S_T with the strike and payoff region
  convergence.png          : MC price -> Black-Scholes, and error ~ 1/sqrt(n)
  results_table.md         : MC vs BS across strikes/maturities, with CIs

Run it:
    python pricer.py
"""

from __future__ import annotations
import os
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq
import matplotlib.pyplot as plt

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
TRADING_DAYS = 252


# ============================================================================
# PART A — Black-Scholes closed form (ground truth)
# ============================================================================
# No dividends, constant volatility and interest rate.
#   d1 = [ln(S0/K) + (r + sigma^2/2) T] / (sigma sqrt(T))
#   d2 = d1 - sigma sqrt(T)
#   Call = S0 N(d1) - K e^{-rT} N(d2)
#   Put  = K e^{-rT} N(-d2) - S0 N(-d1)

def black_scholes(S0, K, r, sigma, T, option="call") -> float:
    """Exact Black-Scholes price of a European option."""
    if T <= 0 or sigma <= 0:
        intrinsic = max(S0 - K, 0.0) if option == "call" else max(K - S0, 0.0)
        return intrinsic
    d1 = (np.log(S0 / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option == "call":
        return S0 * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    elif option == "put":
        return K * np.exp(-r * T) * norm.cdf(-d2) - S0 * norm.cdf(-d1)
    raise ValueError("option must be 'call' or 'put'")


# ============================================================================
# PART B — Geometric Brownian Motion simulation
# ============================================================================
# Under the risk-neutral measure, the terminal price is
#   S_T = S0 * exp[(r - sigma^2/2) T + sigma sqrt(T) Z],   Z ~ N(0, 1).
# Because Z is normal, ln(S_T) is normal => S_T is LOGNORMAL. This is the exact
# point where the "returns are normal" assumption enters the pricing.

def simulate_terminal(S0, r, sigma, T, n_paths, rng) -> np.ndarray:
    """Simulate n_paths terminal prices S_T in one vectorised numpy call."""
    Z = rng.standard_normal(n_paths)
    return S0 * np.exp((r - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * Z)

def simulate_paths(S0, r, sigma, T, n_paths, n_steps, rng) -> np.ndarray:
    """Full step-by-step price paths (for visualisation only).

    European pricing needs only the terminal price, but watching a few whole
    paths makes the "rolling dice on the future" idea concrete. Returns an array
    of shape (n_paths, n_steps + 1).
    """
    dt = T / n_steps
    Z = rng.standard_normal((n_paths, n_steps))
    increments = (r - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * Z
    log_paths = np.concatenate([np.zeros((n_paths, 1)), np.cumsum(increments, axis=1)], axis=1)
    return S0 * np.exp(log_paths)


# ============================================================================
# PART C — Monte Carlo pricing with error bars
# ============================================================================

def mc_price(S0, K, r, sigma, T, n_paths, option="call", rng=None) -> dict:
    """Monte Carlo price of a European option.

    Returns the price plus a standard error and 95% confidence interval. The CI
    comes straight from the Central Limit Theorem: the discounted payoffs are
    i.i.d., so their sample mean is approximately normal with
        SE = e^{-rT} * std(payoff) / sqrt(n).
    """
    if rng is None:
        rng = np.random.default_rng()
    S_T = simulate_terminal(S0, r, sigma, T, n_paths, rng)
    if option == "call":
        payoff = np.maximum(S_T - K, 0.0)
    else:
        payoff = np.maximum(K - S_T, 0.0)
    discount = np.exp(-r * T)
    discounted = discount * payoff
    price = discounted.mean()
    se = discounted.std(ddof=1) / np.sqrt(n_paths)
    return {
        "price": price,
        "std_error": se,
        "ci_low": price - 1.96 * se,
        "ci_high": price + 1.96 * se,
        "n_paths": n_paths,
    }


# ============================================================================
# PART D — Volatility (the key input)  — connects to Week 1
# ============================================================================

def historical_volatility(daily_log_returns: np.ndarray) -> float:
    """Annualised volatility from Week 1's daily log returns.

    sigma_annual = std(daily returns) * sqrt(252).
    """
    return float(np.std(daily_log_returns, ddof=1) * np.sqrt(TRADING_DAYS))

def implied_volatility(market_price, S0, K, r, T, option="call") -> float:
    """The sigma that makes Black-Scholes match an observed market price.

    Solved by root-finding. Comparing implied vs historical vol shows what the
    market thinks future risk is, versus what the past actually did.
    """
    f = lambda s: black_scholes(S0, K, r, s, T, option) - market_price
    try:
        return brentq(f, 1e-6, 5.0)
    except ValueError:
        return float("nan")


# ============================================================================
# PART E — Live data hooks (need internet / yfinance)
# ============================================================================

def load_spot_and_vol(ticker="GOOGL", years=2):
    """Fetch the current price and historical volatility for `ticker`.

    Requires yfinance + internet. Returns (S0, sigma_annual). The returned sigma
    is exactly the Week 1 historical-volatility estimate on live data.
    """
    import yfinance as yf
    hist = yf.download(ticker, period=f"{years}y", auto_adjust=True, progress=False)
    close = hist["Close"].dropna()
    log_ret = np.log(close / close.shift(1)).dropna().values.ravel()
    S0 = float(close.iloc[-1])
    return S0, historical_volatility(log_ret)


# ============================================================================
# PART F — Studies & plots
# ============================================================================

def convergence_study(S0, K, r, sigma, T, rng, option="call"):
    """MC price + SE across growing path counts; confirm error ~ 1/sqrt(n)."""
    bs = black_scholes(S0, K, r, sigma, T, option)
    ns = np.unique(np.round(np.logspace(2, 6, 25)).astype(int))
    prices, ses, errs = [], [], []
    for n in ns:
        res = mc_price(S0, K, r, sigma, T, int(n), option, rng)
        prices.append(res["price"]); ses.append(res["std_error"])
        errs.append(abs(res["price"] - bs))
    # Fit slope of log(SE) vs log(n): theory predicts -0.5.
    slope = np.polyfit(np.log(ns), np.log(ses), 1)[0]
    return {"ns": ns, "prices": np.array(prices), "ses": np.array(ses),
            "errs": np.array(errs), "bs": bs, "se_slope": slope}


def _plot_sample_paths(S0, r, sigma, T, rng, outdir):
    paths = simulate_paths(S0, r, sigma, T, 60, 252, rng)
    t = np.linspace(0, T, paths.shape[1])
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(t, paths.T, lw=0.6, alpha=0.5)
    ax.axhline(S0, color="black", lw=1, ls="--", label="Start price")
    ax.set_title("60 simulated price futures (Geometric Brownian Motion)")
    ax.set_xlabel("Years"); ax.set_ylabel("Price")
    ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "sample_paths.png"), dpi=130)
    plt.close(fig)


def _plot_terminal(S0, K, r, sigma, T, rng, outdir):
    S_T = simulate_terminal(S0, r, sigma, T, 200_000, rng)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(S_T, bins=160, density=True, color="0.6", alpha=0.6)
    ax.axvline(K, color="red", lw=2, label=f"Strike K = {K:.0f}")
    ax.set_title("Distribution of simulated terminal price $S_T$ (lognormal)")
    ax.set_xlabel("Terminal price $S_T$"); ax.set_ylabel("Density")
    ax.set_xlim(0, np.percentile(S_T, 99.5))
    ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "terminal_distribution.png"), dpi=130)
    plt.close(fig)


def _plot_convergence(conv, outdir):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    ns, prices, ses, bs = conv["ns"], conv["prices"], conv["ses"], conv["bs"]
    axes[0].plot(ns, prices, "o-", ms=3, color="0.4", label="Monte Carlo price")
    axes[0].fill_between(ns, prices - 1.96 * ses, prices + 1.96 * ses,
                         color="0.7", alpha=0.5, label="95% CI")
    axes[0].axhline(bs, color="red", lw=1.5, ls="--", label=f"Black-Scholes = {bs:.3f}")
    axes[0].set_xscale("log"); axes[0].set_xlabel("Number of paths (log)")
    axes[0].set_ylabel("Option price"); axes[0].set_title("MC price converges to Black-Scholes")
    axes[0].legend()

    axes[1].loglog(ns, ses, "o-", ms=3, color="0.4", label="Standard error")
    ref = ses[0] * np.sqrt(ns[0] / ns)            # reference 1/sqrt(n) line
    axes[1].loglog(ns, ref, "r--", label=r"$\propto 1/\sqrt{n}$ reference")
    axes[1].set_xlabel("Number of paths (log)"); axes[1].set_ylabel("Standard error (log)")
    axes[1].set_title(f"Error shrinks like $1/\\sqrt{{n}}$  (fitted slope = {conv['se_slope']:.3f})")
    axes[1].legend()
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "convergence.png"), dpi=130)
    plt.close(fig)


def _write_table(rows, path):
    header = ("| Option | K | T (yr) | Black-Scholes | MC price | 95% CI | within CI? |\n"
              "|:--|--:|--:|--:|--:|:--|:--:|\n")
    body = "\n".join(
        f"| {o} | {K:.0f} | {T:.2f} | {bs:.4f} | {mc:.4f} | "
        f"[{lo:.4f}, {hi:.4f}] | {'✓' if lo <= bs <= hi else '—'} |"
        for (o, K, T, bs, mc, lo, hi) in rows
    )
    with open(path, "w") as fh:
        fh.write(header + body + "\n")


# ============================================================================
# PART G — Orchestration
# ============================================================================

def main(S0=180.0, r=0.04, sigma=0.28, seed=7):
    """Demo with illustrative GOOGL-like parameters.

    S0 and sigma are placeholders; run `load_spot_and_vol('GOOGL')` with internet
    to use live values (sigma is then the Week 1 historical-vol estimate).
    """
    os.makedirs(RESULTS_DIR, exist_ok=True)
    rng = np.random.default_rng(seed)
    print(f"Parameters: S0={S0}, r={r}, sigma={sigma} (illustrative)\n")

    # --- Validate MC vs Black-Scholes across strikes & maturities
    rows = []
    print(f"{'opt':>4} {'K':>5} {'T':>5} {'Black-Scholes':>14} {'MC price':>12} {'95% CI':>22}")
    for option in ("call", "put"):
        for K in (160, 180, 200):
            for T in (0.25, 1.0):
                bs = black_scholes(S0, K, r, sigma, T, option)
                res = mc_price(S0, K, r, sigma, T, 500_000, option, rng)
                rows.append((option, K, T, bs, res["price"], res["ci_low"], res["ci_high"]))
                print(f"{option:>4} {K:>5} {T:>5.2f} {bs:>14.4f} {res['price']:>12.4f}"
                      f"   [{res['ci_low']:.4f}, {res['ci_high']:.4f}]")
    _write_table(rows, os.path.join(RESULTS_DIR, "results_table.md"))

    # --- Convergence + 1/sqrt(n) check (at-the-money call, 1y)
    conv = convergence_study(S0, 180, r, sigma, 1.0, rng, "call")
    _plot_convergence(conv, RESULTS_DIR)
    print(f"\nConvergence: Black-Scholes = {conv['bs']:.4f}; "
          f"fitted log(SE) vs log(n) slope = {conv['se_slope']:.3f} (theory -0.5)")

    # --- Illustrative plots
    _plot_sample_paths(S0, r, sigma, 1.0, rng, RESULTS_DIR)
    _plot_terminal(S0, 180, r, sigma, 1.0, rng, RESULTS_DIR)

    # --- Volatility demo (historical vs implied)
    fake_market_price = black_scholes(S0, 180, r, 0.32, 1.0, "call")  # market implies 32%
    iv = implied_volatility(fake_market_price, S0, 180, r, 1.0, "call")
    print(f"\nVolatility: historical (input) = {sigma:.3f}; "
          f"implied from a market price = {iv:.3f}")
    print("  -> implied > historical means the market expects MORE future risk "
          "than the past showed.")

    print(f"\nPlots + table written to: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
