"""
Week 1 — Distribution Fitting on Real Market Returns
====================================================
IEMS 302 consolidation project.

Problem it solves
-----------------
Black-Scholes, Markowitz, and simple VaR all assume returns are normally
distributed. Real returns have FAT TAILS: extreme moves happen far more often
than the bell curve predicts. This script measures, on real holdings, how wrong
the normality assumption is — by fitting Normal, Student-t, and Laplace
distributions to daily log returns and comparing them with formal tests.

What it produces (in ./results/)
---------------------------------
  - <TICKER>_fit.png    : return histogram with the three fitted PDFs overlaid
  - <TICKER>_qq.png     : QQ-plots (Normal vs Student-t) for the same returns
  - excess_kurtosis.png : bar chart of excess kurtosis across all tickers
  - results.csv         : the full results table
  - results_table.md    : the same table as Markdown (paste into your summary)

Run it:
    python distribution_fitting.py
"""

from __future__ import annotations
import os
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
TICKERS = ["GOOGL", "PLTR", "VRT", "STX", "SPY", "MU", "IREN", "NBIS", "TQQQ"]
YEARS = 5
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# The three candidate distributions. Each entry: (scipy distribution, name).
# We fit each one to the data and compare how well it explains the fat tails.
CANDIDATES = {
    "Normal":   stats.norm,      # 2 params (loc, scale) — the assumption we're testing
    "Student-t": stats.t,        # 3 params (df, loc, scale) — df controls tail fatness
    "Laplace":  stats.laplace,   # 2 params (loc, scale) — peaked, fatter-than-normal tails
}


# ----------------------------------------------------------------------------
# 1. Data loading  (Task 1)
# ----------------------------------------------------------------------------
def load_prices(tickers=TICKERS, years=YEARS) -> pd.DataFrame:
    """Download `years` of daily adjusted-close prices for `tickers`.

    auto_adjust=True makes the 'Close' column already adjusted for splits and
    dividends, which is what we want for return analysis.
    """
    import yfinance as yf  # imported here so the rest of the file runs without it
    raw = yf.download(tickers, period=f"{years}y", auto_adjust=True, progress=False)
    prices = raw["Close"].dropna(how="all")
    # Keep only tickers that actually returned data, preserve requested order.
    prices = prices[[t for t in tickers if t in prices.columns and prices[t].notna().any()]]
    return prices


def to_log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Daily log returns: r_t = ln(P_t / P_{t-1}).  (Task 2)

    Log returns are used (instead of simple % returns) because they add up
    cleanly over time and are the form assumed by Black-Scholes / GBM.
    """
    return np.log(prices / prices.shift(1)).dropna(how="all")


# ----------------------------------------------------------------------------
# 2. Moments  (Task 3)
# ----------------------------------------------------------------------------
def moments(returns: np.ndarray) -> dict:
    """Mean, variance, skewness, and kurtosis of a 1-D return series.

    kurtosis_raw uses the Pearson convention where the NORMAL benchmark is 3.
    excess_kurtosis = kurtosis_raw - 3, so positive => fatter tails than normal.
    """
    return {
        "n": len(returns),
        "mean": np.mean(returns),
        "variance": np.var(returns, ddof=1),
        "std": np.std(returns, ddof=1),
        "skewness": stats.skew(returns),
        "kurtosis_raw": stats.kurtosis(returns, fisher=False),   # normal = 3
        "excess_kurtosis": stats.kurtosis(returns, fisher=True),  # normal = 0
    }


# ----------------------------------------------------------------------------
# 3. Fit distributions + goodness of fit  (Tasks 4 & 5)
# ----------------------------------------------------------------------------
def fit_one(dist, name: str, returns: np.ndarray) -> dict:
    """Fit a single distribution and score it.

    Returns the fitted parameters plus three scores:
      - ks_stat / ks_p : Kolmogorov-Smirnov distance and p-value
      - loglik          : maximised log-likelihood (higher = better fit)
      - aic             : Akaike Information Criterion = 2k - 2*loglik
                          (LOWER = better; penalises extra parameters so the
                           3-param t doesn't win just for being more flexible)
    """
    params = dist.fit(returns)
    k = len(params)                       # number of fitted parameters
    loglik = np.sum(dist.logpdf(returns, *params))
    aic = 2 * k - 2 * loglik
    # KS test: largest gap between the empirical CDF and the fitted CDF.
    ks_stat, ks_p = stats.kstest(returns, dist.cdf, args=params)
    return {
        "name": name, "params": params, "k": k,
        "ks_stat": ks_stat, "ks_p": ks_p, "loglik": loglik, "aic": aic,
    }


def fit_all(returns: np.ndarray) -> dict:
    """Fit every candidate distribution and identify the best by AIC."""
    fits = {name: fit_one(dist, name, returns) for name, dist in CANDIDATES.items()}
    best = min(fits.values(), key=lambda f: f["aic"])["name"]
    return {"fits": fits, "best_by_aic": best}


# ----------------------------------------------------------------------------
# 4. Plots  (Tasks 5 & 6)
# ----------------------------------------------------------------------------
def plot_fit(ticker: str, returns: np.ndarray, fits: dict, outdir: str):
    """Histogram of returns with the three fitted PDFs overlaid."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(returns, bins=120, density=True, alpha=0.4,
            color="0.6", label="Empirical returns")
    x = np.linspace(returns.min(), returns.max(), 1000)
    styles = {"Normal": "-", "Student-t": "--", "Laplace": ":"}
    for name, f in fits.items():
        dist = CANDIDATES[name]
        ax.plot(x, dist.pdf(x, *f["params"]), styles[name], linewidth=2, label=name)
    ax.set_title(f"{ticker}: daily log returns vs fitted distributions")
    ax.set_xlabel("Daily log return")
    ax.set_ylabel("Density")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"{ticker}_fit.png"), dpi=130)
    plt.close(fig)


def plot_qq(ticker: str, returns: np.ndarray, t_df: float, outdir: str):
    """QQ-plots: Normal (left) vs Student-t (right).

    On a QQ-plot, points on the straight red line mean the distribution fits.
    Points curving AWAY at the ends (an S-shape) are the visual fingerprint of
    fat tails: real extreme returns are more extreme than the model expects.
    """
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))
    stats.probplot(returns, dist="norm", plot=axes[0])
    axes[0].set_title(f"{ticker}: QQ vs Normal")
    stats.probplot(returns, dist=stats.t, sparams=(t_df,), plot=axes[1])
    axes[1].set_title(f"{ticker}: QQ vs Student-t (df={t_df:.1f})")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, f"{ticker}_qq.png"), dpi=130)
    plt.close(fig)


def plot_kurtosis_bar(table: pd.DataFrame, outdir: str):
    """Bar chart of excess kurtosis across tickers (0 = normal)."""
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(table["ticker"], table["excess_kurtosis"], color="0.5")
    ax.axhline(0, color="black", linewidth=1)
    ax.set_title("Excess kurtosis by ticker (0 = normal; higher = fatter tails)")
    ax.set_ylabel("Excess kurtosis")
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "excess_kurtosis.png"), dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
# 5. Orchestration
# ----------------------------------------------------------------------------
def analyze(returns_df: pd.DataFrame, outdir: str = RESULTS_DIR) -> pd.DataFrame:
    """Run the full analysis on a DataFrame of returns (columns = tickers).

    This function is deliberately independent of the data source so it can be
    tested with synthetic data. Returns a tidy results table and writes all
    plots + CSV + Markdown table to `outdir`.
    """
    os.makedirs(outdir, exist_ok=True)
    rows = []
    for ticker in returns_df.columns:
        r = returns_df[ticker].dropna().values
        m = moments(r)
        result = fit_all(r)
        fits = result["fits"]
        t_df = fits["Student-t"]["params"][0]   # degrees of freedom for the t fit

        plot_fit(ticker, r, fits, outdir)
        plot_qq(ticker, r, t_df, outdir)

        rows.append({
            "ticker": ticker,
            "n_days": m["n"],
            "mean": m["mean"],
            "std": m["std"],
            "skewness": m["skewness"],
            "excess_kurtosis": m["excess_kurtosis"],
            "t_df": t_df,
            "ks_normal": fits["Normal"]["ks_stat"],
            "ks_t": fits["Student-t"]["ks_stat"],
            "ks_laplace": fits["Laplace"]["ks_stat"],
            "aic_normal": fits["Normal"]["aic"],
            "aic_t": fits["Student-t"]["aic"],
            "aic_laplace": fits["Laplace"]["aic"],
            "best_fit": result["best_by_aic"],
        })

    table = pd.DataFrame(rows)
    plot_kurtosis_bar(table, outdir)

    # Save machine-readable + human-readable copies of the results.
    table.to_csv(os.path.join(outdir, "results.csv"), index=False)
    _write_markdown_table(table, os.path.join(outdir, "results_table.md"))
    return table


def _write_markdown_table(table: pd.DataFrame, path: str):
    """Write a compact Markdown table you can paste straight into the summary."""
    show = table[["ticker", "std", "skewness", "excess_kurtosis",
                  "t_df", "ks_normal", "ks_t", "best_fit"]].copy()
    show["std"] = (show["std"] * 100).round(2).astype(str) + "%"
    show["skewness"] = show["skewness"].round(2)
    show["excess_kurtosis"] = show["excess_kurtosis"].round(1)
    show["t_df"] = show["t_df"].round(1)
    show["ks_normal"] = show["ks_normal"].round(4)
    show["ks_t"] = show["ks_t"].round(4)
    show.columns = ["Ticker", "Daily σ", "Skew", "Excess kurt.",
                    "t df", "KS (Normal)", "KS (t)", "Best fit (AIC)"]
    with open(path, "w") as fh:
        fh.write(show.to_markdown(index=False))


def main():
    print("Downloading prices ...")
    prices = load_prices()
    returns = to_log_returns(prices)
    print(f"Got {len(returns)} trading days for {list(returns.columns)}")
    table = analyze(returns)
    pd.set_option("display.width", 140)
    print("\n=== Results ===")
    print(table.to_string(index=False))
    print(f"\nPlots and tables written to: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
