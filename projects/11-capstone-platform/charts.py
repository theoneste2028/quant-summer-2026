"""
Week 11 — Charts for the capstone
=================================
Five figures, each answering one question a reader will actually have:

  frontier.png          What is the risk-return menu, and where do the
                        recommended and current portfolios sit on it?
  frontier_naive.png    What does the optimizer do without shrinkage?
  allocation.png        What would actually change in the portfolio?
  fan_chart.png         What could a year look like?
  risk_sweep.png        How does the answer depend on risk tolerance?
"""
from __future__ import annotations
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TRADING_DAYS = 252


def _fmt_pct(ax, axis="both"):
    from matplotlib.ticker import FuncFormatter
    f = FuncFormatter(lambda v, _: f"{v:.0%}")
    if axis in ("x", "both"):
        ax.xaxis.set_major_formatter(f)
    if axis in ("y", "both"):
        ax.yaxis.set_major_formatter(f)


def plot_frontier(out, path):
    fr = out["frontier"]
    rec, cur, mv = out["recommended"], out["current"], out["min_variance"]
    fig, ax = plt.subplots(figsize=(9.5, 6))

    ax.plot(fr["vol"], fr["ret"], "-", color="0.3", lw=2,
            label="Efficient frontier (shrunk estimates)", zorder=2)
    sc = ax.scatter(fr["vol"], fr["ret"], c=fr["ce"], cmap="viridis", s=26,
                    zorder=3, label="_nolegend_")
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("Certainty equivalent ($)")

    ax.scatter([rec["vol"]], [rec["ret"]], marker="*", s=420, color="#d62728",
               zorder=5, edgecolor="white", linewidth=1.2,
               label=f"Recommended (CE ${rec['ce']:,.0f})")
    ax.scatter([cur["vol"]], [cur["ret"]], marker="X", s=200, color="#1f77b4",
               zorder=5, edgecolor="white", linewidth=1.2,
               label=f"Current portfolio (CE ${cur['ce']:,.0f})")
    ax.scatter([mv["vol"]], [mv["ret"]], marker="o", s=110, color="0.15",
               zorder=5, edgecolor="white", linewidth=1.0,
               label="Minimum variance (no return estimates)")

    ax.annotate("", xy=(rec["vol"], rec["ret"]), xytext=(cur["vol"], cur["ret"]),
                arrowprops=dict(arrowstyle="->", color="0.45", lw=1.4,
                                linestyle="--"), zorder=4)

    ax.set_xlabel("Annualised volatility")
    ax.set_ylabel("Expected annual return")
    ax.set_title("Efficient frontier: where the portfolio is, and where it could be")
    _fmt_pct(ax)
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_frontier_naive(out, path):
    """The headline methodological result: shrinkage tames the optimizer."""
    fr, frn = out["frontier"], out["frontier_naive"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))

    ax = axes[0]
    ax.plot(frn["vol"], frn["ret"], "-", color="#d62728", lw=2,
            label="Naive (raw sample estimates)")
    ax.plot(fr["vol"], fr["ret"], "-", color="0.3", lw=2,
            label="Robust (shrunk + 25% cap)")
    ax.set_xlabel("Annualised volatility"); ax.set_ylabel("Expected annual return")
    ax.set_title("The naive frontier promises far more")
    _fmt_pct(ax); ax.grid(alpha=0.3); ax.legend(fontsize=9)

    ax = axes[1]
    ax.plot(frn["vol"], frn["n_holdings"], "-", color="#d62728", lw=2,
            label="Naive")
    ax.plot(fr["vol"], fr["n_holdings"], "-", color="0.3", lw=2, label="Robust")
    ax.set_xlabel("Annualised volatility"); ax.set_ylabel("Number of holdings")
    ax.set_title("...by concentrating into fewer names")
    _fmt_pct(ax, axis="x"); ax.grid(alpha=0.3); ax.legend(fontsize=9)

    fig.suptitle("Markowitz is an error maximizer without shrinkage", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_allocation(out, path):
    tickers = out["tickers"]
    w_rec = np.asarray(out["recommended"]["weights"], float)
    w_cur = np.asarray(out["current"]["weights"], float)
    keep = (w_rec > 1e-4) | (w_cur > 1e-4)
    idx = np.where(keep)[0]
    idx = idx[np.argsort(-(w_rec[idx] + w_cur[idx]))]
    labels = [tickers[i] for i in idx]

    y = np.arange(len(idx))
    h = 0.38
    fig, ax = plt.subplots(figsize=(9.5, 0.46 * len(idx) + 2.6))
    ax.barh(y + h / 2, w_cur[idx], h, color="#1f77b4", label="Current")
    ax.barh(y - h / 2, w_rec[idx], h, color="#d62728", label="Recommended")
    ax.set_yticks(y); ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.set_xlabel("Portfolio weight")
    ax.set_title("Recommended vs current allocation")
    _fmt_pct(ax, axis="x"); ax.grid(axis="x", alpha=0.3)
    ax.legend(fontsize=9)
    for yy, i in zip(y, idx):
        if w_rec[i] > 1e-4:
            ax.text(w_rec[i] + 0.004, yy - h / 2, f"{w_rec[i]:.0%}",
                    va="center", fontsize=8, color="#d62728")
        if w_cur[i] > 1e-4:
            ax.text(w_cur[i] + 0.004, yy + h / 2, f"{w_cur[i]:.0%}",
                    va="center", fontsize=8, color="#1f77b4")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def simulate_wealth_paths(w, mu, cov, wealth, n_paths=3000, n_steps=TRADING_DAYS,
                          seed=21, t_df=None):
    """Wealth paths for the fan chart (kept separate: it stores the whole path)."""
    rng = np.random.default_rng(seed)
    n_assets = len(w)
    dt = 1.0 / n_steps
    mu_step = (mu - 0.5 * np.diag(cov)) * dt
    L = np.linalg.cholesky(cov * dt + np.eye(n_assets) * 1e-12)
    logw = np.zeros((n_paths, n_steps + 1))
    for s in range(1, n_steps + 1):
        if t_df is None:
            z = rng.standard_normal((n_paths, n_assets))
        else:
            z = rng.standard_t(t_df, size=(n_paths, n_assets))
            z = z / np.sqrt(t_df / (t_df - 2))
        step = mu_step + z @ L.T
        port = (np.exp(step) - 1.0) @ w
        logw[:, s] = logw[:, s - 1] + np.log1p(np.maximum(port, -0.999999))
    return wealth * np.exp(logw)


def plot_fan(out, path):
    w = np.asarray(out["recommended"]["weights"], float)
    mu, cov = out["moments"]["mu"], out["moments"]["cov"]
    wealth = out["wealth"]
    paths = simulate_wealth_paths(w, mu, cov, wealth, t_df=out["median_t_df"])
    t = np.linspace(0, 12, paths.shape[1])

    fig, ax = plt.subplots(figsize=(10, 6))
    bands = [(5, 95, 0.16), (10, 90, 0.22), (25, 75, 0.30)]
    for lo, hi, alpha in bands:
        ax.fill_between(t, np.percentile(paths, lo, axis=0),
                        np.percentile(paths, hi, axis=0),
                        color="#1f77b4", alpha=alpha, lw=0,
                        label=f"{hi-lo}% of outcomes")
    ax.plot(t, np.percentile(paths, 50, axis=0), color="#08306b", lw=2.2,
            label="Median path")
    ax.axhline(wealth, color="black", lw=1.2, ls="--",
               label=f"Starting value ${wealth:,.0f}")
    ax.axhline(wealth * 0.9, color="#d62728", lw=1.2, ls=":",
               label="-10% threshold")
    for i in range(12):
        ax.plot(t, paths[i], color="0.35", lw=0.5, alpha=0.5)

    mc = out["mc_t"]
    ax.set_title(f"One year forward — P(loss > 10%) = {mc['p_loss_10']:.1%}, "
                 f"5% VaR = {mc['var_5']:.1%}, 1% VaR = {mc['var_1']:.1%}")
    ax.set_xlabel("Months ahead"); ax.set_ylabel("Portfolio value ($)")
    ax.set_xlim(0, 12)
    ax.grid(alpha=0.3)
    ax.legend(loc="upper left", fontsize=9)
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}"))
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def plot_risk_sweep(out, path):
    s = out["sweep"]
    fig, ax = plt.subplots(figsize=(10, 6))
    x = s["R_fraction"] * 100
    ax.plot(x, s["ret"], "o-", color="#2ca02c", lw=2, label="Expected return")
    ax.plot(x, s["vol"], "s--", color="#d62728", lw=2, label="Volatility")
    ax.set_xscale("log")
    ax.set_xlabel("Risk tolerance R, as % of wealth (log scale)")
    ax.set_ylabel("Annualised")
    _fmt_pct(ax, axis="y")
    ax.grid(alpha=0.3)

    chosen = out["R"] / out["wealth"] * 100
    ax.axvline(chosen, color="black", lw=1.2, ls=":")
    ax.annotate(f"chosen R = {chosen:.0f}% of wealth",
                xy=(chosen, ax.get_ylim()[1] * 0.92), fontsize=9,
                rotation=90, va="top", ha="right")

    ax2 = ax.twinx()
    ax2.plot(x, s["n_holdings"], "^:", color="0.45", lw=1.5,
             label="Number of holdings")
    ax2.set_ylabel("Number of holdings", color="0.45")

    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)
    ax.set_title("The recommendation is a function of risk tolerance, not a fact")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def make_all_charts(out, outdir):
    os.makedirs(outdir, exist_ok=True)
    plot_frontier(out, os.path.join(outdir, "frontier.png"))
    plot_frontier_naive(out, os.path.join(outdir, "frontier_naive.png"))
    plot_allocation(out, os.path.join(outdir, "allocation.png"))
    plot_fan(out, os.path.join(outdir, "fan_chart.png"))
    plot_risk_sweep(out, os.path.join(outdir, "risk_sweep.png"))
