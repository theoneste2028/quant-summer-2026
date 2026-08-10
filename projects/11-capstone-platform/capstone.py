"""
Week 11 — Capstone: Utility-Based Portfolio Optimizer
=====================================================
The four-layer pipeline that ties all three courses together, run end to end on
a real portfolio.

    LAYER 1  DATA          (CS 217, Weeks 5-8)
             Returns come from the SQLite database, never from a fresh
             yfinance call. The database is the single source of truth, which
             is the entire point of having built it.

    LAYER 2  STATISTICS    (IEMS 302, Weeks 1-4)
             Mean vector and covariance matrix, plus the Week 1 distribution
             fits used to say honestly how wrong the normality assumption is
             before anything is built on top of it.

    LAYER 3  OPTIMIZATION  (CivEnv 205 + CVXPY)
             Markowitz:  max  mu'w - (gamma/2) w'Sigma w
                         s.t. sum(w) = 1,  w >= 0
             solved across a grid of risk-aversion values to trace the frontier.

    LAYER 4  DECISION      (Week 10)
             A frontier is a menu, not an answer. The certainty-equivalent
             machinery picks the single portfolio that a given risk tolerance
             should actually hold.

    LAYER 5  MONTE CARLO   (Week 3)
             Forward simulation of the chosen portfolio: P(loss > 10%), 5% VaR,
             and expected value with confidence intervals — reported under BOTH
             a normal and a fat-tailed model, because Week 1 showed which one
             the data actually supports.

Run:
    python capstone.py                 # full pipeline, writes results/
    python capstone.py --risk 250000   # a different risk tolerance
"""
from __future__ import annotations
import os, sys, json, sqlite3, argparse
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB_PATH = os.path.join(REPO, "data", "portfolio.db")
RESULTS = os.path.join(HERE, "results")

# Reuse the earlier weeks rather than reimplementing them. If these imports
# break, the capstone is no longer integrating anything.
sys.path.insert(0, os.path.join(REPO, "projects", "01-distribution-fitting"))
sys.path.insert(0, os.path.join(REPO, "projects", "10-decision-analysis"))
from distribution_fitting import fit_all, moments as w1_moments   # noqa: E402
from decision_analysis import certainty_equivalent               # noqa: E402

TRADING_DAYS = 252

# Broad candidates the portfolio does not currently hold. Including a bond fund
# and gold matters: with an all-equity universe every asset is ~0.7 correlated
# and the "efficient" frontier is a straight line of slightly different betas.
CANDIDATE_ETFS = ["VOO", "QQQM", "VXUS", "SCHD", "XLK", "VTI", "BND", "GLD",
                  "SMH", "ITA", "FDVV"]


# ===========================================================================
# LAYER 1 — Data (CS 217)
# ===========================================================================
def load_returns(db_path=DB_PATH, min_days=400, extra=None) -> dict:
    """Build a returns matrix from the SQLite prices table.

    Universe = currently-held positions with enough price history, plus the
    broad candidate ETFs. Holdings with short histories are EXCLUDED and
    reported rather than silently dropped, because excluding an asset changes
    what the optimizer is allowed to recommend and the reader deserves to know.
    """
    con = sqlite3.connect(db_path)
    held = [r[0] for r in con.execute("""
        SELECT ticker FROM trades GROUP BY ticker
        HAVING SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END) > 1e-9
        ORDER BY ticker""")]
    counts = dict(con.execute(
        "SELECT ticker, COUNT(*) FROM prices GROUP BY ticker").fetchall())

    candidates = list(extra if extra is not None else CANDIDATE_ETFS)
    universe = [t for t in held + candidates if counts.get(t, 0) >= min_days]
    excluded = {t: counts.get(t, 0) for t in held + candidates
                if counts.get(t, 0) < min_days}

    rows = con.execute(
        f"SELECT ticker, date, close FROM prices WHERE ticker IN "
        f"({','.join('?' * len(universe))}) ORDER BY date",
        universe).fetchall()
    con.close()

    px = (pd.DataFrame(rows, columns=["ticker", "date", "close"])
          .pivot(index="date", columns="ticker", values="close")
          .sort_index())
    # Intersection of dates: every asset must have a price, or the covariance
    # is being estimated from different periods for different pairs.
    px = px.dropna(how="any")
    rets = np.log(px / px.shift(1)).dropna(how="any")

    return {"prices": px, "returns": rets, "universe": list(rets.columns),
            "held": held, "candidates": candidates, "excluded": excluded,
            "start": str(rets.index[0]), "end": str(rets.index[-1]),
            "n_days": len(rets)}


def current_allocation(db_path=DB_PATH) -> pd.Series:
    """The actual portfolio today, by market value, from the database.

    Same FIFO open-position logic as the Week 6 cost_basis query, expressed
    here in Python because it feeds an array rather than a report.
    """
    con = sqlite3.connect(db_path)
    q = """
    WITH sold AS (SELECT ticker, SUM(quantity) tot FROM trades
                  WHERE side='SELL' GROUP BY ticker),
    buys AS (SELECT ticker, price, quantity,
                    SUM(quantity) OVER w - quantity AS lo,
                    SUM(quantity) OVER w            AS hi
             FROM trades WHERE side='BUY'
             WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)),
    open_lots AS (SELECT b.ticker,
                         MAX(0, b.hi - MAX(b.lo, COALESCE(s.tot,0))) AS q
                  FROM buys b LEFT JOIN sold s ON s.ticker=b.ticker),
    latest AS (SELECT ticker, close FROM
                 (SELECT ticker, close,
                         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) rn
                  FROM prices) WHERE rn=1)
    SELECT o.ticker, SUM(o.q) * l.close AS mv
    FROM open_lots o JOIN latest l ON l.ticker=o.ticker
    GROUP BY o.ticker HAVING SUM(o.q) > 1e-9 AND mv > 0
    """
    df = pd.read_sql_query(q, con)
    con.close()
    s = df.set_index("ticker")["mv"]
    return s / s.sum()


def portfolio_value(db_path=DB_PATH) -> float:
    """Total market value of open positions — the wealth the utility scale uses."""
    con = sqlite3.connect(db_path)
    q = """
    WITH sold AS (SELECT ticker, SUM(quantity) tot FROM trades
                  WHERE side='SELL' GROUP BY ticker),
    buys AS (SELECT ticker, quantity,
                    SUM(quantity) OVER w - quantity AS lo,
                    SUM(quantity) OVER w            AS hi
             FROM trades WHERE side='BUY'
             WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)),
    open_lots AS (SELECT b.ticker,
                         MAX(0, b.hi - MAX(b.lo, COALESCE(s.tot,0))) AS q
                  FROM buys b LEFT JOIN sold s ON s.ticker=b.ticker),
    latest AS (SELECT ticker, close FROM
                 (SELECT ticker, close,
                         ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) rn
                  FROM prices) WHERE rn=1)
    SELECT COALESCE(SUM(o.q * l.close), 0)
    FROM open_lots o JOIN latest l ON l.ticker=o.ticker
    """
    v = con.execute(q).fetchone()[0]
    con.close()
    return float(v)


# ===========================================================================
# LAYER 2 — Statistics (IEMS 302)
# ===========================================================================
def estimate_moments(rets: pd.DataFrame) -> dict:
    """Annualised moments, both naive and shrunk.

    Both are returned deliberately. The naive pair is what a textbook Markowitz
    implementation uses and what Layer 3 shows failing; the shrunk pair is what
    the recommendation is actually built on. Reporting only one would hide the
    single most important thing this pipeline learned.
    """
    from robust import robust_estimates
    n_obs, n_assets = rets.shape
    r = robust_estimates(rets.values, TRADING_DAYS)
    return {
        "tickers": list(rets.columns),
        "mu": r["mu"], "cov": r["cov"],
        "mu_naive": r["mu_naive"], "cov_naive": r["cov_naive"],
        "vol": np.sqrt(np.diag(r["cov"])),
        "corr": rets.corr().values,
        "n_obs": n_obs, "n_assets": n_assets,
        # T/N decides whether a sample covariance is usable at all. Below ~10 it
        # is noisy; below 1 it is singular and the optimizer feeds on the noise.
        "obs_per_asset": n_obs / n_assets,
        "cond_number": r["cond_naive"], "cond_robust": r["cond_robust"],
        "mean_shrinkage": r["mean_shrinkage"], "mean_target": r["mean_target"],
        "cov_shrinkage": r["cov_shrinkage"], "avg_corr": r["avg_corr"],
    }


def normality_diagnostics(rets: pd.DataFrame) -> pd.DataFrame:
    """Week 1's fits, rerun here so the normality assumption is stated, not assumed.

    The optimizer below uses only the mean and covariance, which is a complete
    description of risk ONLY if returns are normal. They are not. This table is
    what turns that from a hidden assumption into a documented caveat, and it
    drives the fat-tailed Monte Carlo in Layer 5.
    """
    rows = []
    for t in rets.columns:
        x = rets[t].values
        m = w1_moments(x)
        f = fit_all(x)
        rows.append({
            "ticker": t,
            "ann_vol": float(np.std(x, ddof=1) * np.sqrt(TRADING_DAYS)),
            "skew": m["skewness"],
            "excess_kurtosis": m["excess_kurtosis"],
            "t_df": f["fits"]["Student-t"]["params"][0],
            "best_fit": f["best_by_aic"],
        })
    return pd.DataFrame(rows).sort_values("excess_kurtosis", ascending=False)


# ===========================================================================
# LAYER 3 — Optimization (CivEnv 205 + CVXPY)
# ===========================================================================
def solve_markowitz(mu, cov, gamma, long_only=True, max_weight=None):
    """max mu'w - (gamma/2) w'Sigma w   s.t. sum(w)=1, w>=0."""
    import cvxpy as cp
    n = len(mu)
    w = cp.Variable(n)
    # psd_wrap tells CVXPY to trust the matrix is PSD; a sample covariance can
    # have tiny negative eigenvalues from floating-point error that would
    # otherwise make the problem non-convex.
    risk = cp.quad_form(w, cp.psd_wrap(cov))
    obj = cp.Maximize(mu @ w - (gamma / 2.0) * risk)
    cons = [cp.sum(w) == 1]
    if long_only:
        cons.append(w >= 0)
    if max_weight is not None:
        cons.append(w <= max_weight)
    prob = cp.Problem(obj, cons)
    prob.solve()
    if w.value is None:
        return None
    weights = np.asarray(w.value).ravel()
    weights[np.abs(weights) < 1e-8] = 0.0     # scrub solver dust
    if long_only:
        weights = np.clip(weights, 0, None)
    weights = weights / weights.sum()
    return weights


def efficient_frontier(mu, cov, gammas=None, **kw) -> pd.DataFrame:
    """Trace the frontier by sweeping risk aversion."""
    gammas = gammas if gammas is not None else np.logspace(-1, 2.7, 40)
    rows = []
    for g in gammas:
        w = solve_markowitz(mu, cov, g, **kw)
        if w is None:
            continue
        r = float(mu @ w)
        v = float(np.sqrt(w @ cov @ w))
        rows.append({"gamma": float(g), "ret": r, "vol": v,
                     "sharpe": r / v if v > 0 else np.nan,
                     "n_holdings": int((w > 1e-4).sum()), "weights": w})
    return pd.DataFrame(rows)


# ===========================================================================
# LAYER 4 — Decision (Week 10)
# ===========================================================================
def portfolio_certainty_equivalent(w, mu, cov, wealth, R, n=60_000, seed=0,
                                   t_df=None) -> float:
    """CE of holding `w` for one year, in dollars, at risk tolerance R.

    A frontier gives a menu of (return, risk) pairs and no way to choose between
    them. The certainty equivalent collapses each to one number on the scale the
    investor actually cares about: the certain dollar amount that feels as good
    as the uncertain outcome.
    """
    rng = np.random.default_rng(seed)
    port_mu = float(mu @ w)
    port_var = float(w @ cov @ w)
    port_sd = np.sqrt(port_var)
    if t_df is None:
        r = rng.normal(port_mu, port_sd, n)
    else:
        r = _t_draws(port_mu, port_sd, t_df, n, rng)
    # Log returns compound: terminal wealth is W0 * exp(r).
    terminal = wealth * np.exp(r)
    return certainty_equivalent(terminal, np.full(n, 1.0 / n), R)


def _t_draws(mean, sd, df, n, rng):
    """Student-t draws rescaled so their standard deviation is `sd`."""
    if df <= 2:
        raise ValueError("t_df must exceed 2 for a finite variance")
    raw = rng.standard_t(df, size=n)
    return mean + raw / np.sqrt(df / (df - 2)) * sd


def choose_portfolio(frontier: pd.DataFrame, mu, cov, wealth, R,
                     t_df=None, seed=0) -> dict:
    """Pick the frontier point with the highest certainty equivalent."""
    ces = [portfolio_certainty_equivalent(row.weights, mu, cov, wealth, R,
                                          seed=seed, t_df=t_df)
           for row in frontier.itertuples()]
    f = frontier.copy()
    f["ce"] = ces
    best = f.loc[f["ce"].idxmax()]
    return {"frontier": f, "best": best, "weights": best.weights,
            "gamma": float(best.gamma), "ce": float(best.ce)}


def risk_tolerance_sweep(frontier, mu, cov, tickers, wealth, t_df=None,
                         seed=0, fractions=None) -> pd.DataFrame:
    """How the recommendation changes as risk tolerance varies.

    More useful than any single recommendation. R is not observable — nobody
    knows their own risk tolerance to two significant figures — so the honest
    deliverable is the map from R to the portfolio it implies, letting the
    reader locate themselves on it rather than trusting one guessed number.

    R is expressed as a fraction of wealth, which makes it comparable across
    portfolio sizes.
    """
    fractions = fractions if fractions is not None else [
        0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00, 4.00]
    rows = []
    for frac in fractions:
        R = wealth * frac
        ch = choose_portfolio(frontier, mu, cov, wealth, R, t_df=t_df, seed=seed)
        w = ch["weights"]
        d = describe(w, mu, cov, tickers, top=3)
        rows.append({
            "R_fraction": frac, "R": R, "gamma": ch["gamma"], "ce": ch["ce"],
            "ret": d["ret"], "vol": d["vol"], "sharpe": d["sharpe"],
            "n_holdings": d["n_holdings"],
            "top": ", ".join(f"{t} {v:.0%}" for t, v in d["top"]),
            "weights": w,
        })
    return pd.DataFrame(rows)


# ===========================================================================
# LAYER 5 — Monte Carlo (Week 3)
# ===========================================================================
def simulate_forward(w, mu, cov, horizon=1.0, n_paths=200_000, n_steps=252,
                     seed=7, t_df=None) -> dict:
    """Simulate the portfolio forward and report the risk numbers.

    Correlated asset returns are drawn each step and aggregated by the weights,
    so the covariance matrix does real work rather than being collapsed to a
    single portfolio sigma up front. Under `t_df` the innovations are
    fat-tailed, which is what Week 1's fits say the data actually looks like.
    """
    rng = np.random.default_rng(seed)
    n_assets = len(w)
    dt = horizon / n_steps
    mu_step = (mu - 0.5 * np.diag(cov)) * dt        # log-space drift
    L = np.linalg.cholesky(cov * dt + np.eye(n_assets) * 1e-12)

    log_growth = np.zeros(n_paths)
    for _ in range(n_steps):
        if t_df is None:
            z = rng.standard_normal((n_paths, n_assets))
        else:
            z = rng.standard_t(t_df, size=(n_paths, n_assets))
            z = z / np.sqrt(t_df / (t_df - 2))
        step = mu_step + z @ L.T
        # Portfolio is rebalanced to `w` each step, so the portfolio's simple
        # return is the weighted average of asset simple returns.
        port_simple = (np.exp(step) - 1.0) @ w
        log_growth += np.log1p(np.maximum(port_simple, -0.999999))

    total = np.exp(log_growth) - 1.0
    se = total.std(ddof=1) / np.sqrt(n_paths)
    return {
        "returns": total,
        "mean": float(total.mean()),
        "median": float(np.median(total)),
        "std": float(total.std(ddof=1)),
        "se": float(se),
        "ci_low": float(total.mean() - 1.96 * se),
        "ci_high": float(total.mean() + 1.96 * se),
        "p_loss_10": float((total < -0.10).mean()),
        "p_loss_any": float((total < 0).mean()),
        "var_5": float(-np.percentile(total, 5)),
        "cvar_5": float(-total[total <= np.percentile(total, 5)].mean()),
        # The 1% tail is reported alongside the 5% because that is where fat
        # tails actually show up. Rescaled to the same variance, a t(3.8) is
        # LESS extreme than a normal at the 5th percentile — its mass sits
        # nearer the centre — and only becomes worse from roughly the 2nd
        # percentile inward. Quoting a 5% VaR alone would make fat tails look
        # harmless, which is precisely the error Week 1 warned about.
        "var_1": float(-np.percentile(total, 1)),
        "cvar_1": float(-total[total <= np.percentile(total, 1)].mean()),
        "p05": float(np.percentile(total, 5)),
        "p95": float(np.percentile(total, 95)),
        "model": "student-t" if t_df else "normal",
        "t_df": t_df,
    }


# ===========================================================================
# Comparison
# ===========================================================================
def horizon_tail_study(w, mu, cov, t_df, n_paths=100_000, seed=11) -> pd.DataFrame:
    """Where do fat tails actually change the risk number?

    Motivated by an initially surprising result: at a one-year horizon the
    fat-tailed model gives almost the same VaR as the normal one. That is not a
    bug — it is the Central Limit Theorem. A one-year return is the sum of 252
    daily draws, and sums of i.i.d. heavy-tailed variables (with finite
    variance) converge to normality, so the tail behaviour of the daily
    distribution is progressively washed out as the horizon grows.

    The practical reading: fat tails dominate SHORT-horizon risk. At long
    horizons the danger is not fat tails per se but DEPENDENCE — volatility
    clustering, correlations rising in crashes — which an i.i.d. simulation
    does not model and which this table therefore understates.
    """
    rows = []
    for label, horizon, steps in [("1 day", 1 / TRADING_DAYS, 1),
                                  ("1 week", 5 / TRADING_DAYS, 5),
                                  ("1 month", 21 / TRADING_DAYS, 21),
                                  ("1 year", 1.0, TRADING_DAYS)]:
        n = simulate_forward(w, mu, cov, horizon=horizon, n_paths=n_paths,
                             n_steps=steps, seed=seed)
        t = simulate_forward(w, mu, cov, horizon=horizon, n_paths=n_paths,
                             n_steps=steps, seed=seed, t_df=t_df)
        rows.append({
            "horizon": label, "steps": steps,
            "var1_normal": n["var_1"], "var1_t": t["var_1"],
            "ratio": t["var_1"] / n["var_1"] if n["var_1"] else np.nan,
            "var5_normal": n["var_5"], "var5_t": t["var_5"],
        })
    return pd.DataFrame(rows)


def align_weights(alloc: pd.Series, tickers) -> np.ndarray:
    """Project an allocation onto the optimizer's universe and renormalise.

    Holdings outside the universe (too little price history) cannot be modelled,
    so they are dropped and the remainder rescaled. The fraction dropped is
    reported by the caller — it bounds how much of the comparison is missing.
    """
    w = np.array([float(alloc.get(t, 0.0)) for t in tickers])
    return w / w.sum() if w.sum() > 0 else w


def describe(w, mu, cov, tickers, top=8) -> dict:
    r = float(mu @ w)
    v = float(np.sqrt(w @ cov @ w))
    order = np.argsort(-w)
    return {
        "ret": r, "vol": v, "sharpe": r / v if v else np.nan,
        "n_holdings": int((w > 1e-4).sum()),
        "top": [(tickers[i], float(w[i])) for i in order[:top] if w[i] > 1e-4],
    }


# ===========================================================================
# Orchestration
# ===========================================================================
def run(db_path=DB_PATH, wealth=None, R=None, seed=7, n_paths=100_000,
        min_days=400, quiet=False):
    def say(*a):
        if not quiet:
            print(*a)

    say("=" * 78)
    say("CAPSTONE — Utility-Based Portfolio Optimizer")
    say("=" * 78)

    # ---- Layer 1 --------------------------------------------------------
    d = load_returns(db_path, min_days=min_days)
    rets, tickers = d["returns"], d["universe"]
    say(f"\nLAYER 1 — DATA (from SQLite, no live API calls)")
    say(f"  window            {d['start']} .. {d['end']}  ({d['n_days']} days)")
    say(f"  universe          {len(tickers)} assets "
        f"({len([t for t in d['held'] if t in tickers])} held, "
        f"{len([t for t in d['candidates'] if t in tickers])} candidates)")
    if d["excluded"]:
        say(f"  excluded          {len(d['excluded'])} with < {min_days} days: "
            + ", ".join(f"{t}({n})" for t, n in sorted(d["excluded"].items())))

    alloc = current_allocation(db_path)
    covered = sum(alloc.get(t, 0.0) for t in tickers)
    say(f"  current portfolio {len(alloc)} positions; "
        f"{covered:.1%} of its value is modellable")

    # ---- Layer 2 --------------------------------------------------------
    m = estimate_moments(rets)
    mu, cov = m["mu"], m["cov"]
    say(f"\nLAYER 2 — STATISTICS")
    say(f"  observations/asset  {m['obs_per_asset']:.1f}")
    say(f"  mean shrinkage      {m['mean_shrinkage']:.1%} toward "
        f"{m['mean_target']:.2%}  (Jorion Bayes-Stein)")
    say(f"  covariance shrinkage {m['cov_shrinkage']:.1%} toward constant "
        f"correlation {m['avg_corr']:.2f}  (Ledoit-Wolf)")
    say(f"  condition number    {m['cond_number']:,.0f} -> {m['cond_robust']:,.0f}")
    diag = normality_diagnostics(rets)
    n_fat = int((diag["best_fit"] != "Normal").sum())
    say(f"  normality check     {n_fat}/{len(diag)} assets reject the Normal "
        f"(median excess kurtosis {diag['excess_kurtosis'].median():.1f})")
    med_df = float(diag["t_df"].median())
    say(f"  median fitted t df  {med_df:.1f}  -> drives the fat-tailed VaR below")

    # ---- Layer 3 --------------------------------------------------------
    say(f"\nLAYER 3 — OPTIMIZATION (CVXPY, long-only, fully invested)")
    from robust import min_variance_weights
    max_w = 0.25

    # The naive frontier is computed only to be shown failing. Markowitz on raw
    # sample means is an error maximizer: it cannot distinguish a high expected
    # return from a lucky one, so it concentrates on the noisiest estimates.
    fr_naive = efficient_frontier(m["mu_naive"], m["cov_naive"])
    fr = efficient_frontier(mu, cov, max_weight=max_w)

    say(f"  naive (raw sample estimates):")
    say(f"    return range      {fr_naive['ret'].min():.2%} .. {fr_naive['ret'].max():.2%}")
    say(f"    holdings at the aggressive end: "
        f"{int(fr_naive.iloc[-1]['n_holdings'])}")
    say(f"  robust (shrunk estimates, max weight {max_w:.0%}):")
    say(f"    return range      {fr['ret'].min():.2%} .. {fr['ret'].max():.2%}")
    say(f"    volatility range  {fr['vol'].min():.2%} .. {fr['vol'].max():.2%}")
    say(f"    holdings at the aggressive end: {int(fr.iloc[-1]['n_holdings'])}")
    best_sharpe = fr.loc[fr["sharpe"].idxmax()]
    say(f"    max Sharpe        {best_sharpe['sharpe']:.3f} at "
        f"ret {best_sharpe['ret']:.2%}, vol {best_sharpe['vol']:.2%}")

    # A benchmark that uses NO expected-return estimates at all. If a mean-driven
    # portfolio cannot beat this, the means were not carrying information.
    w_mv = min_variance_weights(cov)
    mv = describe(w_mv, mu, cov, tickers)
    say(f"  minimum-variance benchmark (uses no return estimates): "
        f"ret {mv['ret']:.2%}, vol {mv['vol']:.2%}, Sharpe {mv['sharpe']:.3f}")

    # ---- Layer 4 --------------------------------------------------------
    # Default wealth is the portfolio's own market value, so the utility scale
    # is anchored to the real money at stake rather than a round number.
    if wealth is None:
        wealth = float(portfolio_value(db_path))
    # Default risk tolerance is a quarter of wealth. R is measured in dollars:
    # setting R equal to wealth means being willing to stake essentially the
    # whole portfolio on a coin flip, which is not what most people mean by
    # "moderately aggressive".
    if R is None:
        R = 0.25 * wealth

    say(f"\nLAYER 4 — DECISION (certainty equivalent, R=${R:,.0f} = "
        f"{R/wealth:.0%} of wealth ${wealth:,.0f})")
    ch = choose_portfolio(fr, mu, cov, wealth, R, t_df=med_df, seed=seed)
    w_rec = ch["weights"]
    rec = describe(w_rec, mu, cov, tickers)
    say(f"  chosen gamma       {ch['gamma']:.3f}")
    say(f"  certainty equiv    ${ch['ce']:,.0f}  (vs ${wealth:,.0f} held in cash)")
    say(f"  recommended        ret {rec['ret']:.2%}, vol {rec['vol']:.2%}, "
        f"Sharpe {rec['sharpe']:.3f}, {rec['n_holdings']} holdings")
    for t, wt in rec["top"]:
        say(f"      {t:<6} {wt:6.2%}")

    sweep = risk_tolerance_sweep(fr, mu, cov, tickers, wealth,
                                 t_df=med_df, seed=seed)
    say(f"\n  How the recommendation moves with risk tolerance:")
    say(f"    {'R/wealth':>9}{'ret':>9}{'vol':>9}{'Sharpe':>9}{'held':>6}  top holdings")
    for r in sweep.itertuples():
        mark = " <-" if abs(r.R - R) < 1e-6 else ""
        say(f"    {r.R_fraction:>8.0%}{r.ret:>9.1%}{r.vol:>9.1%}"
            f"{r.sharpe:>9.2f}{r.n_holdings:>6}  {r.top}{mark}")

    # ---- Layer 5 --------------------------------------------------------
    say(f"\nLAYER 5 — MONTE CARLO (1 year forward, {n_paths:,} paths)")
    mc_n = simulate_forward(w_rec, mu, cov, n_paths=n_paths, seed=seed)
    mc_t = simulate_forward(w_rec, mu, cov, n_paths=n_paths, seed=seed, t_df=med_df)
    say(f"  {'':22}{'normal':>12}{'student-t':>12}")
    for label, key, fmt in [("expected return", "mean", "{:.2%}"),
                            ("median return", "median", "{:.2%}"),
                            ("P(loss)", "p_loss_any", "{:.1%}"),
                            ("P(loss > 10%)", "p_loss_10", "{:.1%}"),
                            ("5% VaR", "var_5", "{:.2%}"),
                            ("1% VaR", "var_1", "{:.2%}"),
                            ("1% CVaR", "cvar_1", "{:.2%}")]:
        say(f"  {label:<22}{fmt.format(mc_n[key]):>12}{fmt.format(mc_t[key]):>12}")
    say(f"  expected return 95% CI  [{mc_n['ci_low']:.2%}, {mc_n['ci_high']:.2%}]")
    tail = horizon_tail_study(w_rec, mu, cov, med_df,
                              n_paths=min(n_paths, 100_000), seed=seed)
    say(f"\n  Where fat tails actually matter (1% VaR, normal vs t):")
    say(f"    {'horizon':<10}{'normal':>10}{'t':>10}{'ratio':>9}")
    for r in tail.itertuples():
        say(f"    {r.horizon:<10}{r.var1_normal:>10.2%}{r.var1_t:>10.2%}"
            f"{r.ratio:>9.2f}x")
    say(f"    Fat tails dominate SHORT horizons. Over a year the return is a sum")
    say(f"    of 252 draws and the CLT pulls it back toward normal, so the gap")
    say(f"    closes. At long horizons the real danger is dependence — volatility")
    say(f"    clustering, correlations rising in crashes — which this i.i.d.")
    say(f"    simulation does not model and therefore understates.")

    # ---- Comparison -----------------------------------------------------
    w_cur = align_weights(alloc, tickers)
    cur = describe(w_cur, mu, cov, tickers)
    ce_cur = portfolio_certainty_equivalent(w_cur, mu, cov, wealth, R,
                                            seed=seed, t_df=med_df)
    mc_cur = simulate_forward(w_cur, mu, cov, n_paths=n_paths, seed=seed, t_df=med_df)
    say(f"\nRECOMMENDED vs ACTUAL "
        f"(actual covers {covered:.0%} of portfolio value)")
    say(f"  {'':24}{'actual':>14}{'recommended':>14}")
    say(f"  {'expected return':<24}{cur['ret']:>13.2%}{rec['ret']:>14.2%}")
    say(f"  {'volatility':<24}{cur['vol']:>13.2%}{rec['vol']:>14.2%}")
    say(f"  {'Sharpe':<24}{cur['sharpe']:>13.3f}{rec['sharpe']:>14.3f}")
    say(f"  {'holdings':<24}{cur['n_holdings']:>13}{rec['n_holdings']:>14}")
    say(f"  {'certainty equivalent':<24}${ce_cur:>12,.0f}${ch['ce']:>13,.0f}")
    say(f"  {'P(loss > 10%)':<24}{mc_cur['p_loss_10']:>13.1%}{mc_t['p_loss_10']:>14.1%}")
    say(f"  {'5% VaR':<24}{mc_cur['var_5']:>13.2%}{mc_t['var_5']:>14.2%}")

    return {
        "data": d, "moments": m, "diagnostics": diag, "frontier": ch["frontier"],
        "frontier_naive": fr_naive, "max_weight": max_w,
        "min_variance": {"weights": w_mv, **mv},
        "recommended": {"weights": w_rec, "gamma": ch["gamma"], "ce": ch["ce"], **rec},
        "current": {"weights": w_cur, "ce": ce_cur, "covered": covered, **cur},
        "mc_normal": mc_n, "mc_t": mc_t, "mc_current": mc_cur, "sweep": sweep,
        "tail_study": tail,
        "tickers": tickers, "wealth": wealth, "R": R, "median_t_df": med_df,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--risk", type=float, default=None,
                    help="risk tolerance R in dollars")
    ap.add_argument("--wealth", type=float, default=None)
    ap.add_argument("--paths", type=int, default=100_000)
    ap.add_argument("--no-charts", action="store_true")
    a = ap.parse_args()

    out = run(a.db, wealth=a.wealth, R=a.risk, n_paths=a.paths)
    if not a.no_charts:
        from charts import make_all_charts
        make_all_charts(out, RESULTS)
        print(f"\nCharts written to {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
