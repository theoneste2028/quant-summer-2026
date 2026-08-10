"""
Week 12 — Export capstone results for the portfolio site
========================================================
Precomputes everything in Python and writes a single JSON file, which the site
renders. No Python runs at request time; the page is static and instant, which
is what the existing static-site architecture wants.

PRIVACY: absolute dollar amounts are withheld by default. The analysis is fully
demonstrable in percentages and index terms — a recruiter wants to see that you
can build the pipeline, not what your net worth is. `--absolute` opts in to real
dollars if you decide otherwise.

Run:
    python export_results.py                     # site/capstone.json (normalised)
    python export_results.py --absolute          # include real dollar amounts
    python export_results.py --out path.json
"""
from __future__ import annotations
import os, sys, json, argparse
from datetime import datetime, timezone

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import capstone as cs                                    # noqa: E402
from charts import simulate_wealth_paths                 # noqa: E402

DEFAULT_OUT = os.path.join(REPO, "site", "capstone.json")


def _f(x, nd=6):
    """Round floats for a compact, diff-friendly JSON."""
    if isinstance(x, (np.floating, float)):
        return round(float(x), nd)
    if isinstance(x, (np.integer, int)):
        return int(x)
    return x


def build_payload(out, absolute=False, fan_paths=4000) -> dict:
    tickers = out["tickers"]
    rec_w = np.asarray(out["recommended"]["weights"], float)
    cur_w = np.asarray(out["current"]["weights"], float)
    wealth = out["wealth"]
    # Index everything to 100 unless real dollars were explicitly requested.
    scale = 1.0 if absolute else 100.0 / wealth
    unit = "USD" if absolute else "index (start = 100)"

    fr = out["frontier"]
    frn = out["frontier_naive"]

    # Fan chart percentiles, monthly, so the site ships a small array rather
    # than thousands of paths.
    paths = simulate_wealth_paths(rec_w, out["moments"]["mu"], out["moments"]["cov"],
                                  wealth, n_paths=fan_paths,
                                  t_df=out["median_t_df"], seed=21)
    step = max(1, paths.shape[1] // 60)
    cols = list(range(0, paths.shape[1], step))
    if cols[-1] != paths.shape[1] - 1:
        cols.append(paths.shape[1] - 1)
    months = [round(c / (paths.shape[1] - 1) * 12, 3) for c in cols]
    pct = {f"p{q}": [_f(v * scale, 3) for v in np.percentile(paths[:, cols], q, axis=0)]
           for q in (5, 10, 25, 50, 75, 90, 95)}

    diag = out["diagnostics"]
    mc_n, mc_t, mc_cur = out["mc_normal"], out["mc_t"], out["mc_current"]

    payload = {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "window_start": out["data"]["start"],
            "window_end": out["data"]["end"],
            "n_days": out["data"]["n_days"],
            "n_assets": len(tickers),
            "absolute_values": absolute,
            "value_unit": unit,
            "risk_tolerance_pct_of_wealth": _f(out["R"] / wealth),
            "max_weight": _f(out["max_weight"]),
            "wealth": _f(wealth * scale, 2),
        },
        "universe": {
            "tickers": tickers,
            "held": [t for t in out["data"]["held"] if t in tickers],
            "candidates": [t for t in out["data"]["candidates"] if t in tickers],
            "excluded": {k: int(v) for k, v in out["data"]["excluded"].items()},
            "coverage": _f(out["current"]["covered"]),
        },
        "statistics": {
            "obs_per_asset": _f(out["moments"]["obs_per_asset"], 2),
            "mean_shrinkage": _f(out["moments"]["mean_shrinkage"], 4),
            "mean_target": _f(out["moments"]["mean_target"], 4),
            "cov_shrinkage": _f(out["moments"]["cov_shrinkage"], 4),
            "avg_correlation": _f(out["moments"]["avg_corr"], 4),
            "cond_naive": _f(out["moments"]["cond_number"], 1),
            "cond_robust": _f(out["moments"]["cond_robust"], 1),
            "median_t_df": _f(out["median_t_df"], 3),
            "n_reject_normal": int((diag["best_fit"] != "Normal").sum()),
            "per_asset": [
                {"ticker": r.ticker, "ann_vol": _f(r.ann_vol, 4),
                 "skew": _f(r.skew, 3), "excess_kurtosis": _f(r.excess_kurtosis, 3),
                 "t_df": _f(r.t_df, 2), "best_fit": r.best_fit}
                for r in diag.itertuples()],
        },
        "frontier": {
            "robust": [{"vol": _f(r.vol, 5), "ret": _f(r.ret, 5),
                        "sharpe": _f(r.sharpe, 4), "gamma": _f(r.gamma, 4),
                        "n_holdings": int(r.n_holdings),
                        "ce": _f(r.ce * scale, 2)} for r in fr.itertuples()],
            "naive": [{"vol": _f(r.vol, 5), "ret": _f(r.ret, 5),
                       "n_holdings": int(r.n_holdings)} for r in frn.itertuples()],
        },
        "portfolios": {
            "recommended": {
                "ret": _f(out["recommended"]["ret"], 5),
                "vol": _f(out["recommended"]["vol"], 5),
                "sharpe": _f(out["recommended"]["sharpe"], 4),
                "ce": _f(out["recommended"]["ce"] * scale, 2),
                "gamma": _f(out["recommended"]["gamma"], 4),
                "n_holdings": int(out["recommended"]["n_holdings"]),
                "weights": {t: _f(w, 5) for t, w in zip(tickers, rec_w) if w > 1e-4},
            },
            "current": {
                "ret": _f(out["current"]["ret"], 5),
                "vol": _f(out["current"]["vol"], 5),
                "sharpe": _f(out["current"]["sharpe"], 4),
                "ce": _f(out["current"]["ce"] * scale, 2),
                "n_holdings": int(out["current"]["n_holdings"]),
                "weights": {t: _f(w, 5) for t, w in zip(tickers, cur_w) if w > 1e-4},
            },
            "min_variance": {
                "ret": _f(out["min_variance"]["ret"], 5),
                "vol": _f(out["min_variance"]["vol"], 5),
                "sharpe": _f(out["min_variance"]["sharpe"], 4),
            },
        },
        "monte_carlo": {
            "recommended_normal": {k: _f(mc_n[k], 5) for k in
                                   ("mean", "median", "std", "p_loss_any",
                                    "p_loss_10", "var_5", "cvar_5", "var_1",
                                    "cvar_1", "ci_low", "ci_high")},
            "recommended_t": {k: _f(mc_t[k], 5) for k in
                              ("mean", "median", "std", "p_loss_any", "p_loss_10",
                               "var_5", "cvar_5", "var_1", "cvar_1")},
            "current_t": {k: _f(mc_cur[k], 5) for k in
                          ("mean", "median", "p_loss_any", "p_loss_10",
                           "var_5", "var_1")},
            "fan": {"months": months, **pct},
            "horizon_tails": [
                {"horizon": r.horizon, "var1_normal": _f(r.var1_normal, 5),
                 "var1_t": _f(r.var1_t, 5), "ratio": _f(r.ratio, 4)}
                for r in out["tail_study"].itertuples()],
        },
        "risk_sweep": [
            {"r_fraction": _f(r.R_fraction, 4), "ret": _f(r.ret, 5),
             "vol": _f(r.vol, 5), "sharpe": _f(r.sharpe, 4),
             "n_holdings": int(r.n_holdings), "top": r.top,
             "ce": _f(r.ce * scale, 2)}
            for r in out["sweep"].itertuples()],
    }
    return payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--absolute", action="store_true",
                    help="include real dollar amounts (default: indexed to 100)")
    ap.add_argument("--paths", type=int, default=100_000)
    a = ap.parse_args()

    out = cs.run(n_paths=a.paths, quiet=True)
    payload = build_payload(out, absolute=a.absolute)

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as fh:
        json.dump(payload, fh, indent=1)
    size = os.path.getsize(a.out) / 1024
    print(f"wrote {a.out}  ({size:.1f} KB)")
    print(f"  window        {payload['meta']['window_start']} .. "
          f"{payload['meta']['window_end']}  ({payload['meta']['n_days']} days)")
    print(f"  universe      {payload['meta']['n_assets']} assets")
    print(f"  values        {payload['meta']['value_unit']}")
    print(f"  recommended   ret {payload['portfolios']['recommended']['ret']:.2%}, "
          f"vol {payload['portfolios']['recommended']['vol']:.2%}")
    print(f"  current       ret {payload['portfolios']['current']['ret']:.2%}, "
          f"vol {payload['portfolios']['current']['vol']:.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
