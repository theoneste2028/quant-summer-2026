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

Structure:
    The computation is split into stage functions (stage_data, stage_statistics,
    stage_optimize, stage_decide, stage_simulate) that `pipeline()` composes and
    `print_report()` describes. The CLI and `export_results.py` go through
    `run()`, which is `pipeline()` + `print_report()`; the research app
    (`app.py`) calls the stages directly so it can cache each one and recompute
    only what a changed control actually affects.
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

# What the recommendation can be built on: shrunk estimates (the default and
# the published result) or raw sample estimates (to see the failure directly).
ESTIMATES = ("robust", "naive")

# Risk tolerances, as fractions of wealth, that the sweep reports by default.
SWEEP_FRACTIONS = (0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 1.00, 4.00)


class InsufficientDataError(SystemExit):
    """Too little price history to run the optimizer.

    A SystemExit subclass so the CLI behaves exactly as before (the message is
    printed and the process exits non-zero), while the research app can catch
    this one case specifically and show the explanation instead of crashing.
    """


# ===========================================================================
# LAYER 1 — Data (CS 217)
# ===========================================================================
def _held(con) -> list[str]:
    """Tickers with a positive net share count, alphabetically."""
    return [r[0] for r in con.execute("""
        SELECT ticker FROM trades GROUP BY ticker
        HAVING SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END) > 1e-9
        ORDER BY ticker""")]


def held_tickers(db_path=DB_PATH) -> list[str]:
    """The currently-held tickers — the same list `load_returns` starts from."""
    con = sqlite3.connect(db_path)
    try:
        return _held(con)
    finally:
        con.close()


def held_positions(db_path=DB_PATH) -> dict[str, float]:
    """{ticker: net shares} for open positions, alphabetically.

    Net shares (buys minus sells) equal the FIFO open quantity that
    `current_allocation` values, since FIFO only decides WHICH lots remain.
    """
    con = sqlite3.connect(db_path)
    try:
        return dict(con.execute("""
            SELECT ticker,
                   SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END) AS q
            FROM trades GROUP BY ticker HAVING q > 1e-9 ORDER BY ticker"""))
    finally:
        con.close()


def normalize_positions(positions) -> tuple:
    """Positions as a sorted tuple of (TICKER, shares) with shares > 0.

    Accepts a dict or an iterable of pairs. Tickers are stripped and
    upper-cased; a ticker listed twice has its shares added; zero-share rows
    are dropped (a position you no longer hold). Blank tickers, negative or
    non-finite share counts raise ValueError: the pipeline is long-only, and a
    short position entered by mistake should be an error, not silently zero.
    """
    pairs = positions.items() if isinstance(positions, dict) else positions
    total: dict[str, float] = {}
    for t, q in pairs:
        t = str(t).strip().upper()
        if not t:
            raise ValueError("A position has no ticker.")
        try:
            q = float(q)
        except (TypeError, ValueError):
            raise ValueError(f"{t}: shares must be a number, got {q!r}") from None
        if not np.isfinite(q) or q < 0:
            raise ValueError(f"{t}: shares must be zero or more, got {q}")
        total[t] = total.get(t, 0.0) + q
    return tuple(sorted((t, q) for t, q in total.items() if q > 1e-9))


def read_positions(path: str) -> tuple:
    """Positions from a CSV with columns `ticker,shares`."""
    import csv
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if rows and not {"ticker", "shares"} <= set(rows[0]):
        raise ValueError(f"{path}: expected columns 'ticker,shares'")
    return normalize_positions((r["ticker"], r["shares"]) for r in rows)


def write_positions(path: str, positions) -> None:
    """Write positions as `ticker,shares` CSV (the format read_positions reads).
    `repr` keeps every digit, so a round trip returns identical floats."""
    import csv
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "shares"])
        for t, q in normalize_positions(positions):
            w.writerow([t, repr(float(q))])


def _db_tickers(con) -> set[str]:
    """Every ticker with at least one price in this database."""
    return {r[0] for r in con.execute("SELECT DISTINCT ticker FROM prices")}


def _open_extra(extra_db):
    """Read-only connection to the research price cache, or None if absent."""
    if not extra_db or not os.path.exists(extra_db):
        return None
    con = sqlite3.connect(f"file:{extra_db}?mode=ro", uri=True)
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                       "AND name='prices'").fetchone():
        con.close()
        return None
    return con


def load_returns(db_path=DB_PATH, min_days=400, extra=None, exclude=(),
                 start=None, end=None, held=None, extra_db=None) -> dict:
    """Build a returns matrix from the SQLite prices table.

    Universe = currently-held positions with enough price history, plus the
    broad candidate ETFs. Holdings with short histories are EXCLUDED and
    reported rather than silently dropped, because excluding an asset changes
    what the optimizer is allowed to recommend and the reader deserves to know.

    `exclude` removes tickers by choice (reported separately from the
    short-history exclusions). `start` / `end` (inclusive, 'YYYY-MM-DD')
    restrict the date window; history is then counted inside the window, so
    `min_days` always means "at least this many prices in the data actually
    used". With the defaults the behaviour is unchanged.

    `held` replaces the held list derived from trades (positions entered by
    hand). `extra_db` is a second price source — the research price cache —
    used ONLY for tickers with no prices at all in `db_path`; a ticker is never
    stitched together from both. Those tickers are listed under "fetched".
    """
    con = sqlite3.connect(db_path)
    held = _held(con) if held is None else sorted(set(held))
    if start is None and end is None:
        counts = dict(con.execute(
            "SELECT ticker, COUNT(*) FROM prices GROUP BY ticker").fetchall())
    else:
        counts = dict(con.execute(
            "SELECT ticker, COUNT(*) FROM prices WHERE date >= ? AND date <= ? "
            "GROUP BY ticker",
            (start or "0000-00-00", end or "9999-99-99")).fetchall())
    in_db = _db_tickers(con)
    xcon = _open_extra(extra_db)
    if xcon is not None:
        x_counts = dict(xcon.execute(
            "SELECT ticker, COUNT(*) FROM prices WHERE date >= ? AND date <= ? "
            "GROUP BY ticker",
            (start or "0000-00-00", end or "9999-99-99")).fetchall())
        counts.update({t: n for t, n in x_counts.items() if t not in in_db})

    candidates = list(extra if extra is not None else CANDIDATE_ETFS)
    exclude = set(exclude)
    # A ticker can be both held and a candidate (QQQM, FDVV, ...). Count it once,
    # or one asset listed twice would pass the "at least two assets" check.
    everything = list(dict.fromkeys(held + candidates))
    user_excluded = [t for t in everything if t in exclude]
    pool = [t for t in everything if t not in exclude]
    universe = [t for t in pool if counts.get(t, 0) >= min_days]
    excluded = {t: counts.get(t, 0) for t in pool
                if counts.get(t, 0) < min_days}

    # Fail with an explanation rather than an IndexError twenty lines later.
    # The common way to reach this is running the capstone against the offline
    # demo database, which holds a handful of tickers and ~130 synthetic days —
    # far too little to estimate a covariance matrix from.
    if len(universe) < 2:
        con.close()
        if xcon is not None:
            xcon.close()
        raise InsufficientDataError(
            f"\nNot enough price history in {os.path.basename(db_path)} to run "
            f"the optimizer.\n"
            f"  Found {len(universe)} of {len(everything)} tickers "
            f"with at least {min_days} days of prices.\n"
            + (f"  Excluded: "
               + ", ".join(f"{t} ({n}d)" for t, n in sorted(excluded.items())[:8])
               + "\n" if excluded else "")
            + (f"  A date window ({start or 'start'} .. {end or 'end'}) is "
               f"active: history is counted inside it, so a shorter window or "
               f"a lower minimum may help.\n"
               if (start is not None or end is not None) else "")
            + (f"  Removed by choice: {', '.join(sorted(user_excluded))}\n"
               if user_excluded else "")
            + "\nThe capstone needs a real brokerage history. Build one with:\n"
              "  python projects/05-portfolio-database/build_db.py "
              "<your_export.csv>\n"
              "The --demo database is intentionally tiny and cannot support "
              "this step.\n")

    from_db = [t for t in universe if t in in_db]
    fetched = [t for t in universe if t not in in_db]
    rows = con.execute(
        f"SELECT ticker, date, close FROM prices WHERE ticker IN "
        f"({','.join('?' * len(from_db))}) ORDER BY date",
        from_db).fetchall() if from_db else []
    con.close()
    if fetched:
        # Non-empty only if xcon exists: a ticker outside db_path can only have
        # reached the universe through the cache's counts.
        rows += xcon.execute(
            f"SELECT ticker, date, close FROM prices WHERE ticker IN "
            f"({','.join('?' * len(fetched))}) ORDER BY date",
            fetched).fetchall()
    if xcon is not None:
        xcon.close()

    px = (pd.DataFrame(rows, columns=["ticker", "date", "close"])
          .pivot(index="date", columns="ticker", values="close")
          .sort_index())
    if start is not None:
        px = px[px.index >= start]
    if end is not None:
        px = px[px.index <= end]
    # Intersection of dates: every asset must have a price, or the covariance
    # is being estimated from different periods for different pairs.
    px = px.dropna(how="any")
    rets = np.log(px / px.shift(1)).dropna(how="any")

    # Every asset can pass the per-ticker history check and the intersection
    # still be too short (histories that barely overlap). Two returns is the
    # bare minimum for a covariance; anything near it is reported downstream
    # through obs_per_asset.
    if len(rets) < 2:
        raise InsufficientDataError(
            f"\nThe selected assets share only {len(rets)} day(s) of returns "
            f"in {os.path.basename(db_path)} — too few to estimate a "
            f"covariance matrix. Widen the date window or remove the asset "
            f"with the shortest history.\n")

    return {"prices": px, "returns": rets, "universe": list(rets.columns),
            "held": held, "candidates": candidates, "excluded": excluded,
            "user_excluded": user_excluded,
            "fetched": [t for t in rets.columns if t not in in_db],
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


_LATEST = """SELECT ticker, date, close FROM
               (SELECT ticker, date, close,
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) rn
                FROM prices WHERE ticker IN ({}))
             WHERE rn = 1"""


def position_table(db_path=DB_PATH, positions=None, extra_db=None) -> pd.DataFrame:
    """One row per position: ticker, shares, price, price_date, value, source.

    `positions=None` means the open positions in the trades table. Each ticker
    is priced at its latest close from the same source `load_returns` would
    use — the portfolio database if it has any prices for it, else the research
    price cache. A ticker with no price anywhere keeps NaN price and value, so
    the caller can say so rather than value it at zero.
    """
    pos = (held_positions(db_path) if positions is None
           else dict(normalize_positions(positions)))
    tickers = list(pos)
    latest = {}
    if tickers:
        con = sqlite3.connect(db_path)
        try:
            in_db = _db_tickers(con)
            mine = [t for t in tickers if t in in_db]
            if mine:
                for t, d, c in con.execute(
                        _LATEST.format(",".join("?" * len(mine))), mine):
                    latest[t] = (d, float(c), "database")
        finally:
            con.close()
        rest = [t for t in tickers if t not in in_db]
        xcon = _open_extra(extra_db) if rest else None
        if xcon is not None:
            try:
                for t, d, c in xcon.execute(
                        _LATEST.format(",".join("?" * len(rest))), rest):
                    latest[t] = (d, float(c), "fetched")
            finally:
                xcon.close()
    rows = []
    for t in tickers:
        d, c, src = latest.get(t, (None, np.nan, "no price"))
        rows.append({"ticker": t, "shares": float(pos[t]), "price": c,
                     "price_date": d, "value": float(pos[t]) * c, "source": src})
    return pd.DataFrame(rows, columns=["ticker", "shares", "price", "price_date",
                                       "value", "source"])


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
    fractions = fractions if fractions is not None else list(SWEEP_FRACTIONS)
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
@dataclass(frozen=True)
class PipelineConfig:
    """Every input the pipeline takes. The defaults reproduce the CLI exactly."""
    db_path: str = DB_PATH
    wealth: float | None = None        # dollars; None -> the portfolio's market value
    R: float | None = None             # dollars; None -> risk_fraction * wealth
    risk_fraction: float = 0.25
    seed: int = 7
    n_paths: int = 100_000
    min_days: int = 400
    max_weight: float | None = 0.25    # None -> no position cap
    estimates: str = "robust"          # "robust" (shrunk) or "naive" (raw sample)
    t_df: float | None = None          # None -> median fitted Student-t df
    candidates: tuple | None = None    # None -> CANDIDATE_ETFS
    exclude: tuple = ()
    start: str | None = None           # 'YYYY-MM-DD', inclusive
    end: str | None = None
    tail_study: bool = True
    positions: tuple | None = None     # ((ticker, shares), ...); None -> the trades table
    extra_db: str | None = None        # research price cache for tickers not in db_path

    def __post_init__(self):
        if self.positions is not None:
            # Frozen dataclass: normalise in place once, so the config that is
            # reported is the one that ran.
            object.__setattr__(self, "positions",
                               normalize_positions(self.positions))
        if self.estimates not in ESTIMATES:
            raise ValueError(f"estimates must be one of {ESTIMATES}, "
                             f"got {self.estimates!r}")
        if self.max_weight is not None and not 0 < self.max_weight <= 1:
            raise ValueError(f"max_weight must be in (0, 1], got {self.max_weight}")
        if not self.risk_fraction > 0:
            raise ValueError(f"risk_fraction must be positive, got {self.risk_fraction}")
        if self.R is not None and not self.R > 0:
            raise ValueError(f"R must be positive, got {self.R}")
        if self.wealth is not None and not self.wealth > 0:
            raise ValueError(f"wealth must be positive, got {self.wealth}")
        if self.t_df is not None and not self.t_df > 2:
            raise ValueError(f"t_df must exceed 2 for a finite variance, got {self.t_df}")
        if self.n_paths < 2:
            raise ValueError(f"n_paths must be at least 2, got {self.n_paths}")
        if self.min_days < 2:
            raise ValueError(f"min_days must be at least 2, got {self.min_days}")


def stage_data(db_path=DB_PATH, min_days=400, candidates=None, exclude=(),
               start=None, end=None, positions=None, extra_db=None) -> dict:
    """Layer 1: returns matrix, the current allocation, and how much of it the
    universe covers.

    `positions` (ticker -> shares) replaces the trades table as the definition
    of what is held, for when the database is behind the real account. The
    allocation is then each position's shares at its latest price. Without it
    the result is exactly what it always was.
    """
    held = None
    if positions is not None:
        positions = normalize_positions(positions)
        held = [t for t, _ in positions]
    d = load_returns(db_path, min_days=min_days, extra=candidates,
                     exclude=exclude, start=start, end=end, held=held,
                     extra_db=extra_db)
    # In trades mode the table is valued from the database alone, matching
    # current_allocation; the cache only prices positions entered by hand.
    table = position_table(db_path, positions,
                           extra_db if positions is not None else None)
    if positions is None:
        alloc = current_allocation(db_path)
        value = float(portfolio_value(db_path))
    else:
        priced = table[table["value"] > 0]       # NaN (unpriced) compares False
        value = float(priced["value"].sum())
        alloc = (priced.set_index("ticker")["value"] / value if value > 0
                 else pd.Series(dtype=float))
    covered = sum(alloc.get(t, 0.0) for t in d["universe"])
    return {"data": d, "allocation": alloc, "covered": covered,
            "portfolio_value": value, "positions": table}


def stage_statistics(rets: pd.DataFrame) -> dict:
    """Layer 2: naive and shrunk moments, plus the Week 1 normality fits."""
    m = estimate_moments(rets)
    diag = normality_diagnostics(rets)
    return {"moments": m, "diagnostics": diag,
            "median_t_df": float(diag["t_df"].median())}


def active_moments(moments: dict, estimates="robust"):
    """The (mu, cov) pair the recommendation is built on."""
    if estimates == "robust":
        return moments["mu"], moments["cov"]
    if estimates == "naive":
        return moments["mu_naive"], moments["cov_naive"]
    raise ValueError(f"estimates must be one of {ESTIMATES}, got {estimates!r}")


def stage_optimize(moments: dict, max_weight=0.25, estimates="robust") -> dict:
    """Layer 3: the frontier the decision chooses from, the uncapped naive
    frontier (always computed, as the reference that shows why shrinkage
    matters), and the minimum-variance benchmark."""
    from robust import min_variance_weights
    tickers = moments["tickers"]
    mu, cov = active_moments(moments, estimates)
    # With a cap, sum(w) = 1 is only reachable if n * cap >= 1. Saying so beats
    # an empty frontier and a KeyError three functions later.
    if max_weight is not None and max_weight * len(tickers) < 1 - 1e-9:
        raise ValueError(
            f"A {max_weight:.0%} position cap cannot be met with "
            f"{len(tickers)} assets: fully invested needs at least "
            f"{int(np.ceil(1 / max_weight - 1e-9))}. Raise the cap or "
            f"include more assets.")

    # The naive frontier is computed only to be shown failing. Markowitz on raw
    # sample means is an error maximizer: it cannot distinguish a high expected
    # return from a lucky one, so it concentrates on the noisiest estimates.
    fr_naive = efficient_frontier(moments["mu_naive"], moments["cov_naive"])
    fr = efficient_frontier(mu, cov, max_weight=max_weight)
    if fr.empty:
        raise RuntimeError("The optimizer found no feasible portfolio on any "
                           "point of the frontier.")

    # A benchmark that uses NO expected-return estimates at all. If a mean-driven
    # portfolio cannot beat this, the means were not carrying information.
    w_mv = min_variance_weights(cov)
    mv = describe(w_mv, mu, cov, tickers)
    return {"frontier": fr, "frontier_naive": fr_naive,
            "min_variance": {"weights": w_mv, **mv},
            "mu": mu, "cov": cov, "estimates": estimates,
            "max_weight": max_weight}


def stage_decide(opt: dict, tickers, wealth, R, t_df, seed, alloc,
                 sweep_fractions=None) -> dict:
    """Layer 4: the certainty-equivalent choice, the risk-tolerance sweep, and
    the current portfolio scored on the same scale."""
    fr, mu, cov = opt["frontier"], opt["mu"], opt["cov"]
    ch = choose_portfolio(fr, mu, cov, wealth, R, t_df=t_df, seed=seed)
    w_rec = ch["weights"]
    rec = describe(w_rec, mu, cov, tickers)
    sweep = risk_tolerance_sweep(
        fr, mu, cov, tickers, wealth, t_df=t_df, seed=seed,
        fractions=list(sweep_fractions) if sweep_fractions is not None else None)
    w_cur = align_weights(alloc, tickers)
    cur = describe(w_cur, mu, cov, tickers)
    ce_cur = portfolio_certainty_equivalent(w_cur, mu, cov, wealth, R,
                                            seed=seed, t_df=t_df)
    return {"frontier": ch["frontier"],
            "recommended": {"weights": w_rec, "gamma": ch["gamma"],
                            "ce": ch["ce"], **rec},
            "current": {"weights": w_cur, "ce": ce_cur, **cur},
            "sweep": sweep}


def stage_simulate(w_rec, w_cur, mu, cov, t_df, n_paths, seed,
                   tail_study=True) -> dict:
    """Layer 5: one year forward for the recommendation (normal and fat-tailed)
    and the current portfolio (fat-tailed), plus the horizon tail study."""
    mc_n = simulate_forward(w_rec, mu, cov, n_paths=n_paths, seed=seed)
    mc_t = simulate_forward(w_rec, mu, cov, n_paths=n_paths, seed=seed, t_df=t_df)
    mc_cur = simulate_forward(w_cur, mu, cov, n_paths=n_paths, seed=seed, t_df=t_df)
    tail = (horizon_tail_study(w_rec, mu, cov, t_df,
                               n_paths=min(n_paths, 100_000), seed=seed)
            if tail_study else None)
    return {"mc_normal": mc_n, "mc_t": mc_t, "mc_current": mc_cur,
            "tail_study": tail}


def pipeline(cfg: PipelineConfig | None = None) -> dict:
    """All five layers, no printing. Returns everything `run()` always has, plus
    `t_df` (the df actually used), `estimates`, `allocation` and `config`."""
    cfg = cfg if cfg is not None else PipelineConfig()
    s1 = stage_data(cfg.db_path, cfg.min_days, cfg.candidates, cfg.exclude,
                    cfg.start, cfg.end, cfg.positions, cfg.extra_db)
    d, alloc, covered = s1["data"], s1["allocation"], s1["covered"]
    tickers = d["universe"]

    s2 = stage_statistics(d["returns"])
    m, med_df = s2["moments"], s2["median_t_df"]
    t_df = cfg.t_df if cfg.t_df is not None else med_df

    s3 = stage_optimize(m, cfg.max_weight, cfg.estimates)

    # Default wealth is the portfolio's own market value, so the utility scale
    # is anchored to the real money at stake rather than a round number.
    wealth = cfg.wealth if cfg.wealth is not None else s1["portfolio_value"]
    if not wealth > 0:
        source = ("The database shows" if cfg.positions is None
                  else "The positions given include")
        raise ValueError(f"{source} no open positions with a price, "
                         "so there is no wealth to anchor the utility scale. "
                         "Pass wealth explicitly.")
    # Default risk tolerance is a quarter of wealth. R is measured in dollars:
    # setting R equal to wealth means being willing to stake essentially the
    # whole portfolio on a coin flip, which is not what most people mean by
    # "moderately aggressive".
    R = cfg.R if cfg.R is not None else cfg.risk_fraction * wealth

    s4 = stage_decide(s3, tickers, wealth, R, t_df, cfg.seed, alloc)
    s5 = stage_simulate(s4["recommended"]["weights"], s4["current"]["weights"],
                        s3["mu"], s3["cov"], t_df, cfg.n_paths, cfg.seed,
                        tail_study=cfg.tail_study)

    cur = s4["current"]
    return {
        "data": d, "moments": m, "diagnostics": s2["diagnostics"],
        "frontier": s4["frontier"], "frontier_naive": s3["frontier_naive"],
        "max_weight": cfg.max_weight,
        "min_variance": s3["min_variance"],
        "recommended": s4["recommended"],
        "current": {"weights": cur["weights"], "ce": cur["ce"],
                    "covered": covered,
                    **{k: v for k, v in cur.items() if k not in ("weights", "ce")}},
        "mc_normal": s5["mc_normal"], "mc_t": s5["mc_t"],
        "mc_current": s5["mc_current"], "sweep": s4["sweep"],
        "tail_study": s5["tail_study"],
        "tickers": tickers, "wealth": wealth, "R": R, "median_t_df": med_df,
        "t_df": t_df, "estimates": cfg.estimates, "allocation": alloc,
        "positions": s1["positions"], "config": asdict(cfg),
    }


def print_report(out: dict, file=None) -> None:
    """The CLI report, written from a finished `pipeline()` result."""
    def say(*a):
        print(*a, file=file)

    cfg = out["config"]
    d, m, diag = out["data"], out["moments"], out["diagnostics"]
    tickers, min_days = out["tickers"], cfg["min_days"]
    covered = out["current"]["covered"]
    med_df, t_df = out["median_t_df"], out["t_df"]
    fr_naive, fr, max_w = out["frontier_naive"], out["frontier"], out["max_weight"]
    rec, cur = out["recommended"], out["current"]
    wealth, R = out["wealth"], out["R"]
    mc_n, mc_t, mc_cur = out["mc_normal"], out["mc_t"], out["mc_current"]

    say("=" * 78)
    say("CAPSTONE — Utility-Based Portfolio Optimizer")
    say("=" * 78)

    # ---- Layer 1 --------------------------------------------------------
    say(f"\nLAYER 1 — DATA (from SQLite, no live API calls)")
    say(f"  window            {d['start']} .. {d['end']}  ({d['n_days']} days)")
    say(f"  universe          {len(tickers)} assets "
        f"({len([t for t in d['held'] if t in tickers])} held, "
        f"{len([t for t in d['candidates'] if t in tickers])} candidates)")
    if d["excluded"]:
        say(f"  excluded          {len(d['excluded'])} with < {min_days} days: "
            + ", ".join(f"{t}({n})" for t, n in sorted(d["excluded"].items())))
    if d.get("user_excluded"):
        say(f"  removed by choice {', '.join(sorted(d['user_excluded']))}")
    if d.get("fetched"):
        say(f"  fetched prices    {', '.join(d['fetched'])}  (research price "
            f"cache, not the portfolio database)")
    say(f"  current portfolio {len(out['allocation'])} positions; "
        f"{covered:.1%} of its value is modellable"
        + ("  (positions as entered, not from trades)"
           if cfg.get("positions") is not None else ""))

    # ---- Layer 2 --------------------------------------------------------
    say(f"\nLAYER 2 — STATISTICS")
    say(f"  observations/asset  {m['obs_per_asset']:.1f}")
    say(f"  mean shrinkage      {m['mean_shrinkage']:.1%} toward "
        f"{m['mean_target']:.2%}  (Jorion Bayes-Stein)")
    say(f"  covariance shrinkage {m['cov_shrinkage']:.1%} toward constant "
        f"correlation {m['avg_corr']:.2f}  (Ledoit-Wolf)")
    say(f"  condition number    {m['cond_number']:,.0f} -> {m['cond_robust']:,.0f}")
    n_fat = int((diag["best_fit"] != "Normal").sum())
    say(f"  normality check     {n_fat}/{len(diag)} assets reject the Normal "
        f"(median excess kurtosis {diag['excess_kurtosis'].median():.1f})")
    say(f"  median fitted t df  {med_df:.1f}  -> drives the fat-tailed VaR below")
    if cfg["t_df"] is not None:
        say(f"  t df used instead   {t_df:.1f}  (set explicitly)")

    # ---- Layer 3 --------------------------------------------------------
    say(f"\nLAYER 3 — OPTIMIZATION (CVXPY, long-only, fully invested)")
    say(f"  naive (raw sample estimates):")
    say(f"    return range      {fr_naive['ret'].min():.2%} .. {fr_naive['ret'].max():.2%}")
    say(f"    holdings at the aggressive end: "
        f"{int(fr_naive.iloc[-1]['n_holdings'])}")
    label = ("robust (shrunk estimates" if out["estimates"] == "robust"
             else "recommendation frontier (raw sample estimates")
    cap = f"max weight {max_w:.0%}" if max_w is not None else "no position cap"
    say(f"  {label}, {cap}):")
    say(f"    return range      {fr['ret'].min():.2%} .. {fr['ret'].max():.2%}")
    say(f"    volatility range  {fr['vol'].min():.2%} .. {fr['vol'].max():.2%}")
    say(f"    holdings at the aggressive end: {int(fr.iloc[-1]['n_holdings'])}")
    best_sharpe = fr.loc[fr["sharpe"].idxmax()]
    say(f"    max Sharpe        {best_sharpe['sharpe']:.3f} at "
        f"ret {best_sharpe['ret']:.2%}, vol {best_sharpe['vol']:.2%}")
    mv = out["min_variance"]
    say(f"  minimum-variance benchmark (uses no return estimates): "
        f"ret {mv['ret']:.2%}, vol {mv['vol']:.2%}, Sharpe {mv['sharpe']:.3f}")

    # ---- Layer 4 --------------------------------------------------------
    say(f"\nLAYER 4 — DECISION (certainty equivalent, R=${R:,.0f} = "
        f"{R/wealth:.0%} of wealth ${wealth:,.0f})")
    say(f"  chosen gamma       {rec['gamma']:.3f}")
    say(f"  certainty equiv    ${rec['ce']:,.0f}  (vs ${wealth:,.0f} held in cash)")
    say(f"  recommended        ret {rec['ret']:.2%}, vol {rec['vol']:.2%}, "
        f"Sharpe {rec['sharpe']:.3f}, {rec['n_holdings']} holdings")
    for t, wt in rec["top"]:
        say(f"      {t:<6} {wt:6.2%}")

    say(f"\n  How the recommendation moves with risk tolerance:")
    say(f"    {'R/wealth':>9}{'ret':>9}{'vol':>9}{'Sharpe':>9}{'held':>6}  top holdings")
    for r in out["sweep"].itertuples():
        mark = " <-" if abs(r.R - R) < 1e-6 else ""
        say(f"    {r.R_fraction:>8.0%}{r.ret:>9.1%}{r.vol:>9.1%}"
            f"{r.sharpe:>9.2f}{r.n_holdings:>6}  {r.top}{mark}")

    # ---- Layer 5 --------------------------------------------------------
    say(f"\nLAYER 5 — MONTE CARLO (1 year forward, {cfg['n_paths']:,} paths)")
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
    tail = out["tail_study"]
    if tail is not None:
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
    say(f"\nRECOMMENDED vs ACTUAL "
        f"(actual covers {covered:.0%} of portfolio value)")
    say(f"  {'':24}{'actual':>14}{'recommended':>14}")
    say(f"  {'expected return':<24}{cur['ret']:>13.2%}{rec['ret']:>14.2%}")
    say(f"  {'volatility':<24}{cur['vol']:>13.2%}{rec['vol']:>14.2%}")
    say(f"  {'Sharpe':<24}{cur['sharpe']:>13.3f}{rec['sharpe']:>14.3f}")
    say(f"  {'holdings':<24}{cur['n_holdings']:>13}{rec['n_holdings']:>14}")
    say(f"  {'certainty equivalent':<24}${cur['ce']:>12,.0f}${rec['ce']:>13,.0f}")
    say(f"  {'P(loss > 10%)':<24}{mc_cur['p_loss_10']:>13.1%}{mc_t['p_loss_10']:>14.1%}")
    say(f"  {'5% VaR':<24}{mc_cur['var_5']:>13.2%}{mc_t['var_5']:>14.2%}")


def run(db_path=DB_PATH, wealth=None, R=None, seed=7, n_paths=100_000,
        min_days=400, quiet=False):
    """The CLI entry point: `pipeline()` with the default configuration, then
    the report. Signature and return value are unchanged from before the
    refactor; `export_results.py` and the tests depend on both."""
    out = pipeline(PipelineConfig(db_path=db_path, wealth=wealth, R=R,
                                  seed=seed, n_paths=n_paths, min_days=min_days))
    if not quiet:
        print_report(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--risk", type=float, default=None,
                    help="risk tolerance R in dollars")
    ap.add_argument("--wealth", type=float, default=None)
    ap.add_argument("--paths", type=int, default=100_000)
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--add", default="",
                    help="extra candidate tickers, e.g. 'AAPL,MSFT'. Tickers not "
                         "in the database are read from the research price "
                         "cache (fetch them first with market_data.py)")
    ap.add_argument("--positions", default=None,
                    help="CSV of ticker,shares to use instead of the trades "
                         "table as what you hold (the app saves one as "
                         "data/portfolio_positions.csv)")
    a = ap.parse_args()

    if a.add or a.positions:
        from market_data import CACHE_DB, parse_tickers
        added, bad = parse_tickers(a.add)
        if bad:
            ap.error(f"not ticker symbols: {', '.join(bad)}")
        cands = CANDIDATE_ETFS + [t for t in added if t not in CANDIDATE_ETFS]
        out = pipeline(PipelineConfig(
            db_path=a.db, wealth=a.wealth, R=a.risk, n_paths=a.paths,
            candidates=tuple(cands) if added else None,
            positions=read_positions(a.positions) if a.positions else None,
            extra_db=CACHE_DB))
        print_report(out)
    else:
        out = run(a.db, wealth=a.wealth, R=a.risk, n_paths=a.paths)
    if not a.no_charts:
        from charts import make_all_charts
        make_all_charts(out, RESULTS)
        print(f"\nCharts written to {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
