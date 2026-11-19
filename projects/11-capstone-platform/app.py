"""
Week 12 — Portfolio research app
================================
An interactive front end to the capstone pipeline. Every number comes from the
same functions the CLI uses (`capstone.stage_*`); this file only chooses inputs,
caches results, and draws them. Nothing here re-implements the model.

Why it is staged and cached: optimisation and the decision layer take about a
second, but a 100,000-path simulation takes several. Each stage is cached on
exactly the inputs it depends on, so moving the risk-tolerance slider re-runs
the decision and simulation, and never reloads data or re-fits distributions.

"Live" means the database, not a market feed: cache keys include the
database file's modification time, so after the Week 7 ETL appends prices the
next interaction recomputes on the new data.

Your own tickers and positions: "Add tickers" puts names you are considering
into the optimizer's universe, and the positions table lets you set the share
counts you actually hold when the database is behind your account. Prices for
tickers the database lacks come from a separate cache (market_data.py), filled
only when you press "Fetch prices"; the portfolio database is never written.
Edited positions can be saved to data/<database>_positions.csv (gitignored).

Privacy: values are indexed to 100 by default, the convention the published
results page uses. Dollar amounts and share counts are one toggle away and
never leave the machine. The only network call is the "Fetch prices" button,
and it sends ticker symbols alone — never share counts or values.

Run (from the repo root):
    streamlit run projects/11-capstone-platform/app.py
"""
from __future__ import annotations
import glob
import os
import sqlite3
import sys
from datetime import date, datetime

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import capstone as cs                                    # noqa: E402
import market_data as md                                 # noqa: E402
from charts import simulate_wealth_paths                 # noqa: E402

# Entity colours, validated with the dataviz palette checker on BOTH the light
# (#fcfcfb) and dark (#1a1a19) chart surfaces, all pairs: lightness band,
# chroma, colour-blind separation (worst ΔE 9.4) and contrast all pass. Every
# chart that shows these three portfolios uses the same colour for the same
# portfolio, and pairs it with a distinct point shape.
C_REC = "#3987e5"   # recommended
C_CUR = "#d95926"   # current
C_MV = "#199e70"    # minimum variance
C_NEUTRAL = "#8c8b86"  # frontier lines: structure, not an entity

PATH_CHOICES = [10_000, 25_000, 50_000, 100_000]
CAP_CHOICES = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75, None]
RISK_CHOICES = [0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50, 0.75,
                1.00, 2.00, 4.00]
FAN_PATHS = 4_000     # export_results.py's fan_paths for the published page
FAN_SEED = 21          # ... and its seed, so this fan matches that one
INDEX_BASE = 100.0

st.set_page_config(page_title="Portfolio Research", page_icon="📈",
                   layout="wide")


# ===========================================================================
# Database discovery
# ===========================================================================
def find_databases() -> list[str]:
    """SQLite files under data/ that have the tables the pipeline reads."""
    found = []
    for path in sorted(glob.glob(os.path.join(cs.REPO, "data", "*.db"))):
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                names = {r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                con.close()
        except sqlite3.Error:
            continue
        if {"trades", "prices"} <= names:
            found.append(path)
    return found


@st.cache_data(show_spinner=False, max_entries=8)
def db_summary(db_path: str, mtime: float) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        lo, hi, n_rows, n_tickers = con.execute(
            "SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT ticker) "
            "FROM prices").fetchone()
        counts = dict(con.execute(
            "SELECT ticker, COUNT(*) FROM prices GROUP BY ticker").fetchall())
    finally:
        con.close()
    return {"first": lo, "last": hi, "rows": n_rows, "tickers": n_tickers,
            "counts": counts, "held": cs.held_tickers(db_path),
            "positions": cs.normalize_positions(cs.held_positions(db_path))}


def positions_file(db_path: str) -> str:
    """Where edited positions for this database are saved: next to it as
    <name>_positions.csv (data/ is gitignored). Overridable for the tests."""
    folder = os.environ.get("RESEARCH_POSITIONS_DIR", os.path.dirname(db_path))
    stem = os.path.splitext(os.path.basename(db_path))[0]
    return os.path.join(folder, f"{stem}_positions.csv")


def editor_positions(df: pd.DataFrame) -> tuple[tuple, list[str]]:
    """The positions table as entered -> (normalised positions, problems).

    Blank rows are ignored. A row that cannot be used is left out and named in
    `problems` rather than guessed at, so nothing is silently misread.
    """
    pairs, problems, seen = [], [], set()
    for _, r in df.iterrows():
        t, q = r.get("Ticker"), r.get("Shares")
        t = "" if t is None or (isinstance(t, float) and np.isnan(t)) else str(t).strip()
        q_missing = q is None or pd.isna(q)
        if not t and q_missing:
            continue
        if not t:
            problems.append("a row has shares but no ticker")
            continue
        syms, bad = md.parse_tickers(t)
        if bad or len(syms) != 1:
            problems.append(f"{t!r} is not a ticker symbol")
            continue
        t = syms[0]
        if q_missing:
            problems.append(f"{t} has no share count")
            continue
        if float(q) < 0:
            problems.append(f"{t} has negative shares (long-only)")
            continue
        if t in seen:
            problems.append(f"{t} is listed twice — the share counts are added")
        seen.add(t)
        pairs.append((t, float(q)))
    return cs.normalize_positions(pairs), problems


# ===========================================================================
# Cached pipeline stages
# ===========================================================================
# DataKey = (db_path, mtime, min_days, exclude, start, end, candidates,
# positions, cache_mtime). All primitives or tuples of them, so Streamlit
# hashes them cheaply and exactly. `candidates` and `positions` are None when
# unchanged, which keeps the default path identical to the CLI's.

@st.cache_data(show_spinner=False, max_entries=16)
def get_data(key: tuple) -> dict:
    (db_path, _mtime, min_days, exclude, start, end, candidates, positions,
     _cache_mtime) = key
    return cs.stage_data(db_path, min_days,
                         list(candidates) if candidates is not None else None,
                         exclude, start, end, positions, md.CACHE_DB)


@st.cache_data(show_spinner=False, max_entries=16)
def get_stats(key: tuple) -> dict:
    return cs.stage_statistics(get_data(key)["data"]["returns"])


@st.cache_data(show_spinner=False, max_entries=32)
def get_opt(key: tuple, max_weight, estimates: str) -> dict:
    return cs.stage_optimize(get_stats(key)["moments"], max_weight, estimates)


def wealth_for(s1: dict) -> float:
    """The CLI's wealth: the portfolio's market value. A database with no open
    positions has none, so fall back to 100 — the recommendation depends only
    on R as a fraction of wealth, so the choice of base cannot change it."""
    v = s1["portfolio_value"]
    return v if v > 0 else INDEX_BASE


@st.cache_data(show_spinner=False, max_entries=32)
def get_decision(key: tuple, max_weight, estimates: str, risk_fraction: float,
                 t_df: float, seed: int) -> dict:
    s1 = get_data(key)
    opt = get_opt(key, max_weight, estimates)
    wealth = wealth_for(s1)
    R = risk_fraction * wealth
    fractions = tuple(sorted(set(cs.SWEEP_FRACTIONS) | {risk_fraction}))
    dec = cs.stage_decide(opt, s1["data"]["universe"], wealth, R, t_df, seed,
                          s1["allocation"], sweep_fractions=fractions)
    return {**dec, "wealth": wealth, "R": R}


@st.cache_data(show_spinner=False, max_entries=16)
def get_simulation(key: tuple, max_weight, estimates: str, risk_fraction: float,
                   t_df: float, seed: int, n_paths: int) -> dict:
    opt = get_opt(key, max_weight, estimates)
    dec = get_decision(key, max_weight, estimates, risk_fraction, t_df, seed)
    return cs.stage_simulate(dec["recommended"]["weights"],
                             dec["current"]["weights"], opt["mu"], opt["cov"],
                             t_df, n_paths, seed, tail_study=False)


@st.cache_data(show_spinner=False, max_entries=16)
def get_tail_study(key: tuple, max_weight, estimates: str, risk_fraction: float,
                   t_df: float, seed: int, n_paths: int) -> pd.DataFrame:
    opt = get_opt(key, max_weight, estimates)
    dec = get_decision(key, max_weight, estimates, risk_fraction, t_df, seed)
    # Same call the CLI makes: paths capped at 100k, the pipeline's seed.
    return cs.horizon_tail_study(dec["recommended"]["weights"], opt["mu"],
                                 opt["cov"], t_df,
                                 n_paths=min(n_paths, 100_000), seed=seed)


@st.cache_data(show_spinner=False, max_entries=16)
def get_fan(key: tuple, max_weight, estimates: str, risk_fraction: float,
            t_df: float, seed: int) -> dict:
    """Percentiles of 1-year wealth paths per unit of starting wealth, sampled
    exactly as export_results.py samples the published fan (~60 points)."""
    opt = get_opt(key, max_weight, estimates)
    dec = get_decision(key, max_weight, estimates, risk_fraction, t_df, seed)
    paths = simulate_wealth_paths(dec["recommended"]["weights"], opt["mu"],
                                  opt["cov"], 1.0, n_paths=FAN_PATHS,
                                  t_df=t_df, seed=FAN_SEED)
    step = max(1, paths.shape[1] // 60)
    cols = list(range(0, paths.shape[1], step))
    if cols[-1] != paths.shape[1] - 1:
        cols.append(paths.shape[1] - 1)
    out = {"month": [c / (paths.shape[1] - 1) * 12 for c in cols]}
    for q in (5, 25, 50, 75, 95):
        out[f"p{q}"] = np.percentile(paths[:, cols], q, axis=0)
    return out


# ===========================================================================
# Formatting helpers
# ===========================================================================
def pct(x, nd=1) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:.{nd}%}"


def num(x, nd=2) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:.{nd}f}"


def money(x, scale: float, dollars: bool) -> str:
    v = x * scale
    return f"${v:,.0f}" if dollars else f"{v:,.1f}"


def chart(c: alt.Chart) -> None:
    st.altair_chart(c, use_container_width=True)


ENTITY_COLOR = {"Recommended": C_REC, "Current": C_CUR, "Minimum variance": C_MV}
ENTITY_SHAPE = {"Recommended": "diamond", "Current": "cross",
                "Minimum variance": "circle"}


def entity_color(names) -> alt.Scale:
    """Colour scale over only the entities on this chart, so a legend never
    lists something that is not drawn — and each keeps its fixed colour."""
    names = [n for n in ENTITY_COLOR if n in set(names)]
    return alt.Scale(domain=names, range=[ENTITY_COLOR[n] for n in names])


def entity_shape(names) -> alt.Scale:
    names = [n for n in ENTITY_SHAPE if n in set(names)]
    return alt.Scale(domain=names, range=[ENTITY_SHAPE[n] for n in names])


# ===========================================================================
# Sidebar — inputs
# ===========================================================================
st.sidebar.title("Inputs")

databases = find_databases()
if not databases:
    st.title("Portfolio research")
    st.error("No usable database found in `data/`. Build one first:\n\n"
             "`python projects/05-portfolio-database/build_db.py "
             "<your_export.csv>`")
    st.stop()

default_db = cs.DB_PATH if cs.DB_PATH in databases else databases[0]
db_path = st.sidebar.selectbox(
    "Database", databases, index=databases.index(default_db),
    format_func=os.path.basename,
    help="SQLite files in data/ that contain `trades` and `prices` tables.")
mtime = os.path.getmtime(db_path)
info = db_summary(db_path, mtime)

st.sidebar.caption(
    f"Prices {info['first']} → {info['last']} · {info['rows']:,} rows · "
    f"{info['tickers']} tickers · file updated "
    f"{datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}")

# ---- Holdings: what you actually own --------------------------------------
st.sidebar.subheader("Holdings")
db_positions = info["positions"]
pos_path = positions_file(db_path)
saved_positions, saved_error = None, None
if os.path.exists(pos_path):
    try:
        saved_positions = cs.read_positions(pos_path)
    except (OSError, ValueError, KeyError) as e:
        saved_error = f"Could not read {os.path.basename(pos_path)}: {e}"
base_positions = saved_positions if saved_positions is not None else db_positions

with st.sidebar.expander("Positions (shares you hold)", expanded=False):
    st.caption("Starts from your trades in the database. Edit share counts, "
               "add rows for positions the database does not have yet, or "
               "delete rows you have sold.")
    # The key carries the base it was opened on: after Save or Revert the base
    # changes, and the editor starts again from it rather than replaying edits
    # made against a different table.
    edited = st.data_editor(
        pd.DataFrame({"Ticker": [t for t, _ in base_positions],
                      "Shares": [q for _, q in base_positions]},
                     ).astype({"Ticker": "object", "Shares": "float64"}),
        key=f"positions_{abs(hash(base_positions))}",
        num_rows="dynamic", hide_index=True, use_container_width=True,
        column_config={
            "Ticker": st.column_config.TextColumn(max_chars=15),
            "Shares": st.column_config.NumberColumn(min_value=0.0,
                                                    format="%.4f"),
        })
    positions_now, position_problems = editor_positions(edited)
    for p in position_problems:
        st.warning(p)
    if saved_error:
        st.error(saved_error)
    unsaved = positions_now != base_positions
    b1, b2 = st.columns(2)
    if b1.button("Save", disabled=not unsaved, use_container_width=True,
                 help=f"Write these positions to "
                      f"{os.path.relpath(pos_path, cs.REPO)} so they are used "
                      f"next time. The file stays on this machine (gitignored)."):
        cs.write_positions(pos_path, positions_now)
        st.rerun()
    if b2.button("Use database", use_container_width=True,
                 disabled=saved_positions is None and not unsaved,
                 help="Discard edits and delete the saved positions file, "
                      "going back to the positions in the trades table."):
        if os.path.exists(pos_path):
            os.remove(pos_path)
        st.session_state.pop(f"positions_{abs(hash(base_positions))}", None)
        st.rerun()

# None = the trades table, so an untouched table runs the CLI's exact path.
positions = None if positions_now == db_positions else positions_now
held_now = ([t for t, _ in positions] if positions is not None
            else list(info["held"]))
if positions is None:
    st.sidebar.caption(f"Using the {len(db_positions)} open positions in the "
                       f"database's trades.")
else:
    where = ("saved file" if not unsaved
             else "edited, not saved — Save to keep them")
    st.sidebar.caption(f"Using {len(positions)} positions as entered "
                       f"({where}), not the trades table.")

# ---- Universe: what the optimizer may use ---------------------------------
st.sidebar.subheader("Universe")
added_text = st.sidebar.text_input(
    "Add tickers", placeholder="e.g. AAPL, MSFT, VNQ",
    help="Tickers to consider buying. They join the candidates the optimizer "
         "may use. Separate with commas or spaces. Tickers you hold belong in "
         "the positions table instead.")
added, added_bad = md.parse_tickers(added_text)
if added_bad:
    st.sidebar.warning("Not ticker symbols, ignored: " + ", ".join(added_bad))
new_candidates = [t for t in added
                  if t not in held_now and t not in cs.CANDIDATE_ETFS]
already = [t for t in added if t not in new_candidates]
if already:
    st.sidebar.caption("Already in the universe: " + ", ".join(already))
candidates = (tuple(cs.CANDIDATE_ETFS) + tuple(new_candidates)
              if new_candidates else None)

# Prices: the database first; anything it has never priced comes from the
# research cache, which only fills when asked.
cache_info = md.cached_tickers()
cache_mtime = (os.path.getmtime(md.CACHE_DB) if os.path.exists(md.CACHE_DB)
               else 0.0)
needs_price = [t for t in dict.fromkeys(held_now + new_candidates)
               if t not in info["counts"]]
unpriced = [t for t in needs_price if t not in cache_info]
from_cache = [t for t in needs_price if t in cache_info]
fetch_result = st.session_state.pop("fetch_result", None)
if fetch_result:
    if fetch_result["stored"]:
        st.sidebar.success("Fetched " + ", ".join(
            f"{t} ({n:,} days)" for t, n in fetch_result["stored"].items()))
    if fetch_result["missing"]:
        st.sidebar.warning("No prices found for " + ", ".join(
            fetch_result["missing"]) + " — check the symbol (Yahoo format, "
            "e.g. BRK-B).")
    for t, err in fetch_result["errors"].items():
        st.sidebar.error(f"{t}: fetch failed — {err}")
if unpriced:
    st.sidebar.warning(f"No prices yet for {', '.join(unpriced)}. Until they "
                       f"are fetched they are left out of the analysis.")
to_fetch = unpriced or from_cache
if to_fetch:
    label = ("Fetch prices" if unpriced
             else f"Update fetched prices ({len(from_cache)})")
    if st.sidebar.button(
            label, help="Downloads about five years of adjusted daily closes "
                        "from Yahoo Finance for: " + ", ".join(to_fetch) +
                        ". Only the ticker symbols are sent. Stored in "
                        f"{os.path.relpath(md.CACHE_DB, cs.REPO)}, never in "
                        "the portfolio database."):
        with st.spinner(f"Fetching {', '.join(to_fetch)}…"):
            st.session_state["fetch_result"] = md.fetch(to_fetch)
        st.rerun()

pool = list(dict.fromkeys(held_now + cs.CANDIDATE_ETFS + new_candidates))
# Keep earlier removals that are still in the pool when the pool changes.
if "exclude" in st.session_state:
    st.session_state["exclude"] = [t for t in st.session_state["exclude"]
                                   if t in pool]
exclude = st.sidebar.multiselect(
    "Remove from the universe", pool, key="exclude",
    help="Held positions and candidate ETFs the optimizer may use. Removing a "
         "held position also removes it from the current-portfolio comparison.")
min_days = int(st.sidebar.number_input(
    "Minimum price history (days)", min_value=30, max_value=2000, value=400,
    step=10,
    help="Tickers with fewer prices than this (inside the date window, if one "
         "is set) are excluded and listed on the Data tab. 400 is the CLI "
         "default."))

use_window = st.sidebar.checkbox("Limit the date window", value=False)
start = end = None
if use_window:
    first = date.fromisoformat(info["first"])
    last = date.fromisoformat(info["last"])
    c1, c2 = st.sidebar.columns(2)
    d_start = c1.date_input("Start", value=first, min_value=first, max_value=last)
    d_end = c2.date_input("End", value=last, min_value=first, max_value=last)
    if d_start >= d_end:
        st.sidebar.error("Start must be before end.")
        st.stop()
    start, end = d_start.isoformat(), d_end.isoformat()

st.sidebar.subheader("Model")
estimates = st.sidebar.radio(
    "Expected returns and covariance",
    cs.ESTIMATES,
    format_func=lambda e: {"robust": "Shrunk (Bayes-Stein + Ledoit-Wolf)",
                           "naive": "Raw sample (naive Markowitz)"}[e],
    help="Shrunk is the published configuration. Raw sample estimates are the "
         "version the project shows failing — use it to see why.")
max_weight = st.sidebar.select_slider(
    "Largest single position", CAP_CHOICES, value=0.25,
    format_func=lambda c: "No cap" if c is None else f"{c:.0%}")
risk_fraction = st.sidebar.select_slider(
    "Risk tolerance (R as a share of wealth)", RISK_CHOICES, value=0.25,
    format_func=lambda f: f"{f:.0%}",
    help="R is roughly the largest amount you would stake on a 50/50 coin "
         "flip. Lower is more cautious. 25% is the CLI default.")
# Filled in after Layer 2 has run, because it shows the fitted df.
tail_slot = st.sidebar.container()

st.sidebar.subheader("Simulation")
n_paths = st.sidebar.select_slider(
    "Monte Carlo paths", PATH_CHOICES, value=10_000,
    format_func=lambda n: f"{n:,}",
    help="10,000 is quick for exploring. 100,000 with seed 7 reproduces the "
         "published numbers exactly.")
seed = int(st.sidebar.number_input("Random seed", min_value=0,
                                   max_value=2**31 - 1, value=7, step=1))

st.sidebar.subheader("Display")
dollars = st.sidebar.radio(
    "Values", ["Indexed (start = 100)", "Dollars"],
    help="Indexed hides the portfolio's size; every ratio is unchanged.") == "Dollars"


# ===========================================================================
# Run the stages
# ===========================================================================
key = (db_path, mtime, min_days, tuple(sorted(exclude)), start, end,
       candidates, positions, cache_mtime)

st.title("Portfolio research")

try:
    with st.spinner("Loading prices and fitting distributions…"):
        s1 = get_data(key)
        s2 = get_stats(key)
except cs.InsufficientDataError as e:
    st.error(str(e).strip())
    st.stop()

d, alloc, covered = s1["data"], s1["allocation"], s1["covered"]
tickers = d["universe"]
m, diag, med_df = s2["moments"], s2["diagnostics"], s2["median_t_df"]

# The tail model needs the fitted df, so this control comes after Layer 2.
tail_choice = tail_slot.radio(
    "Fat-tail model (Student-t degrees of freedom)",
    ["fitted", "custom"],
    format_func=lambda c: (f"Fitted median ({med_df:.1f})" if c == "fitted"
                           else "Custom"),
    help="Lower degrees of freedom mean fatter tails. The fitted value is the "
         "median across the universe, as in the CLI.")
if tail_choice == "custom":
    t_df = float(tail_slot.number_input("Degrees of freedom", min_value=2.1,
                                         max_value=100.0, value=4.0, step=0.1,
                                         format="%.1f"))
else:
    t_df = med_df

args = (key, max_weight, estimates)
try:
    with st.spinner("Optimizing…"):
        opt = get_opt(*args)
        dec = get_decision(*args, risk_fraction, t_df, seed)
    with st.spinner(f"Simulating {n_paths:,} paths…"):
        sim = get_simulation(*args, risk_fraction, t_df, seed, n_paths)
except (ValueError, RuntimeError) as e:
    st.error(str(e))
    st.stop()

mu, cov = opt["mu"], opt["cov"]
rec, cur, mv = dec["recommended"], dec["current"], opt["min_variance"]
wealth, R = dec["wealth"], dec["R"]
mc_n, mc_t, mc_cur = sim["mc_normal"], sim["mc_t"], sim["mc_current"]
scale = 1.0 if dollars else INDEX_BASE / wealth
has_current = covered > 0 and np.asarray(cur["weights"]).sum() > 0
is_published = (estimates == "robust" and max_weight == 0.25
                and risk_fraction == 0.25 and tail_choice == "fitted"
                and seed == 7 and n_paths == 100_000 and not exclude
                and start is None and end is None and min_days == 400
                and db_path == cs.DB_PATH and candidates is None
                and positions is None)

st.caption(
    f"{d['start']} → {d['end']} · {d['n_days']} trading days · "
    f"{len(tickers)} assets · "
    + ("shrunk estimates" if estimates == "robust" else "raw sample estimates")
    + f" · cap {'none' if max_weight is None else f'{max_weight:.0%}'}"
    + f" · R = {risk_fraction:.0%} of wealth · t df {t_df:.1f}"
    + f" · {n_paths:,} paths, seed {seed}"
    + (f" · +{n_added} added" if (n_added := sum(t in tickers
                                                  for t in new_candidates))
       else "")
    + (" · positions as entered" if positions is not None else "")
    + (" · **the published configuration**" if is_published else ""))

# ---- Caveats that change how to read everything below ---------------------
if estimates == "naive":
    st.warning("**Raw sample estimates.** This is the configuration the project "
               "shows failing: Markowitz on raw means concentrates in the assets "
               "whose favourable estimates are noisiest. Compare with shrunk.")
if m["obs_per_asset"] < 10:
    st.warning(f"Only {m['obs_per_asset']:.1f} observations per asset. Below "
               f"about 10 the covariance estimate is noisy and the optimizer "
               f"leans on that noise — treat results as indicative.")
if not has_current:
    st.warning("None of the current portfolio is in the universe, so the "
               "current-vs-recommended comparisons are omitted.")
elif covered < 0.999:
    missing = sorted(t for t in alloc.index if t not in tickers)
    st.info(f"{1 - covered:.1%} of current portfolio value is not modelled "
            f"({', '.join(missing)}), because those positions are outside the "
            f"universe. The current portfolio below is the remaining "
            f"{covered:.1%}, rescaled to 100%.")
pos_table = s1["positions"]
no_price = list(pos_table.loc[pos_table["price"].isna(), "ticker"])
if no_price:
    st.warning(f"No price for {', '.join(no_price)}, so "
               f"{'it is' if len(no_price) == 1 else 'they are'} not counted in "
               f"the current portfolio. Fetch prices in the sidebar.")
dated = pos_table["price_date"].dropna()
if len(dated) and (date.fromisoformat(dated.max())
                   - date.fromisoformat(dated.min())).days > 5:
    st.warning(f"Positions are valued at prices from different dates "
               f"({dated.min()} to {dated.max()}), so the current weights mix "
               f"old and new prices. Bring the database up to date with the "
               f"ETL (projects/07-etl-pipeline/etl.py) to line them up.")
if s1["portfolio_value"] <= 0:
    st.info(("This database has no open positions with prices"
             if positions is None else
             "None of the positions entered has a price yet")
            + ", so values are indexed to 100 regardless of the display "
              "setting.")
    dollars, scale = False, 1.0

(tab_rec, tab_front, tab_risk, tab_sim, tab_stats, tab_data) = st.tabs(
    ["Recommendation", "Frontier", "Risk tolerance", "Simulation",
     "Statistics", "Data"])


# ===========================================================================
# Recommendation
# ===========================================================================
with tab_rec:
    cols = st.columns(4)
    cols[0].metric("Expected return", pct(rec["ret"]),
                   delta=(f"{(rec['ret'] - cur['ret']) * 100:+.1f} pts vs current"
                          if has_current else None),
                   delta_color="off")
    cols[1].metric("Volatility", pct(rec["vol"]),
                   delta=(f"{(rec['vol'] - cur['vol']) * 100:+.1f} pts vs current"
                          if has_current else None),
                   delta_color="inverse")
    cols[2].metric("Sharpe ratio", num(rec["sharpe"]),
                   delta=(f"{rec['sharpe'] - cur['sharpe']:+.2f} vs current"
                          if has_current else None))
    cols[3].metric("P(loss > 10%), 1 year", pct(mc_t["p_loss_10"]),
                   delta=(f"{(mc_t['p_loss_10'] - mc_cur['p_loss_10']) * 100:+.1f} "
                          f"pts vs current" if has_current else None),
                   delta_color="inverse")
    st.caption("Sharpe is return ÷ volatility (no risk-free rate). Loss "
               "probability and VaR use the fat-tailed simulation.")

    rows = [
        ("Expected return", pct(cur["ret"]), pct(rec["ret"])),
        ("Volatility", pct(cur["vol"]), pct(rec["vol"])),
        ("Sharpe ratio", num(cur["sharpe"]), num(rec["sharpe"])),
        ("Holdings", f"{cur['n_holdings']}", f"{rec['n_holdings']}"),
        ("Certainty equivalent", money(cur["ce"], scale, dollars),
         money(rec["ce"], scale, dollars)),
        ("P(loss > 10%)", pct(mc_cur["p_loss_10"]), pct(mc_t["p_loss_10"])),
        ("5% VaR", pct(mc_cur["var_5"]), pct(mc_t["var_5"])),
        ("1% VaR", pct(mc_cur["var_1"]), pct(mc_t["var_1"])),
    ]
    table = pd.DataFrame(rows, columns=["", "Current", "Recommended"]).set_index("")
    if not has_current:
        table = table[["Recommended"]]

    left, right = st.columns([2, 3])
    with left:
        st.subheader("Current vs recommended")
        st.dataframe(table, use_container_width=True)
        st.caption(
            f"Certainty equivalent: the certain amount worth the same as the "
            f"one-year gamble at R = {money(R, scale, dollars)} "
            f"(starting value {money(wealth, scale, dollars)}).")

    with right:
        st.subheader("Allocation")
        w_rec = np.asarray(rec["weights"])
        w_cur = np.asarray(cur["weights"])
        keep = [i for i in range(len(tickers))
                if w_rec[i] > 1e-4 or (has_current and w_cur[i] > 1e-4)]
        order = sorted(keep, key=lambda i: (-w_rec[i], -w_cur[i], tickers[i]))
        alloc_rows = []
        for i in order:
            alloc_rows.append({"Ticker": tickers[i], "Portfolio": "Recommended",
                               "Weight": w_rec[i]})
            if has_current:
                alloc_rows.append({"Ticker": tickers[i], "Portfolio": "Current",
                                   "Weight": w_cur[i]})
        adf = pd.DataFrame(alloc_rows)
        sort = [tickers[i] for i in order]
        bars = alt.Chart(adf).mark_bar(cornerRadiusEnd=4).encode(
            y=alt.Y("Ticker:N", sort=sort, title=None),
            yOffset=alt.YOffset("Portfolio:N", sort=["Recommended", "Current"]),
            x=alt.X("Weight:Q", title="Weight", axis=alt.Axis(format="%")),
            color=alt.Color("Portfolio:N", scale=entity_color(adf["Portfolio"]),
                            legend=alt.Legend(orient="top", title=None)),
            tooltip=["Ticker", "Portfolio", alt.Tooltip("Weight:Q", format=".1%")],
        ).properties(height=max(240, (48 if has_current else 30) * len(order)))
        chart(bars)

    with st.expander("Weights table"):
        wt = pd.DataFrame({
            "Ticker": [tickers[i] for i in order],
            "Current %": [w_cur[i] * 100 for i in order],
            "Recommended %": [w_rec[i] * 100 for i in order],
        })
        wt["Change (pts)"] = wt["Recommended %"] - wt["Current %"]
        if not has_current:
            wt = wt.drop(columns=["Current %", "Change (pts)"])
        st.dataframe(wt, hide_index=True, use_container_width=True,
                     column_config={c: st.column_config.NumberColumn(format="%.1f")
                                    for c in wt.columns if c != "Ticker"})


# ===========================================================================
# Frontier
# ===========================================================================
with tab_front:
    fr = dec["frontier"]
    frontier_label = ("Frontier (shrunk estimates)" if estimates == "robust"
                      else "Frontier (raw estimates)")
    show_naive = st.checkbox(
        "Also show the uncapped raw-estimate frontier", value=False,
        help="Off by default: its projected returns reach "
             f"{opt['frontier_naive']['ret'].max():.0%}, which flattens the "
             "chart. That projection is the failure shrinkage exists to fix.")

    fdf = pd.DataFrame({
        "vol": fr["vol"], "ret": fr["ret"], "sharpe": fr["sharpe"],
        "holdings": fr["n_holdings"], "gamma": fr["gamma"],
        "Line": frontier_label})
    lines = [fdf]
    if show_naive:
        frn = opt["frontier_naive"]
        lines.append(pd.DataFrame({
            "vol": frn["vol"], "ret": frn["ret"], "sharpe": frn["sharpe"],
            "holdings": frn["n_holdings"], "gamma": frn["gamma"],
            "Line": "Raw estimates, no cap"}))
    ldf = pd.concat(lines, ignore_index=True)
    line_domain = [frontier_label] + (["Raw estimates, no cap"] if show_naive else [])

    tip = [alt.Tooltip("Line:N", title="Frontier"),
           alt.Tooltip("ret:Q", title="Expected return", format=".1%"),
           alt.Tooltip("vol:Q", title="Volatility", format=".1%"),
           alt.Tooltip("sharpe:Q", title="Sharpe", format=".2f"),
           alt.Tooltip("holdings:Q", title="Holdings"),
           alt.Tooltip("gamma:Q", title="Risk aversion γ", format=".3g")]
    base_x = alt.X("vol:Q", title="Volatility (annual)", axis=alt.Axis(format="%"))
    base_y = alt.Y("ret:Q", title="Expected return (annual)", axis=alt.Axis(format="%"))
    dash = alt.StrokeDash("Line:N", scale=alt.Scale(domain=line_domain,
                                                     range=[[1, 0], [6, 4]][:len(line_domain)]),
                          legend=alt.Legend(orient="top", title=None))
    frontier_line = alt.Chart(ldf).mark_line(color=C_NEUTRAL, strokeWidth=2).encode(
        x=base_x, y=base_y, strokeDash=dash, order="vol:Q")
    frontier_pts = alt.Chart(ldf).mark_circle(color=C_NEUTRAL, size=36).encode(
        x=base_x, y=base_y, tooltip=tip)

    pts = [{"Portfolio": "Recommended", "vol": rec["vol"], "ret": rec["ret"],
            "sharpe": rec["sharpe"], "holdings": rec["n_holdings"]},
           {"Portfolio": "Minimum variance", "vol": mv["vol"], "ret": mv["ret"],
            "sharpe": mv["sharpe"], "holdings": mv["n_holdings"]}]
    if has_current:
        pts.append({"Portfolio": "Current", "vol": cur["vol"], "ret": cur["ret"],
                    "sharpe": cur["sharpe"], "holdings": cur["n_holdings"]})
    pdf = pd.DataFrame(pts)
    markers = alt.Chart(pdf).mark_point(size=220, filled=True, opacity=1,
                                        strokeWidth=2).encode(
        x=base_x, y=base_y,
        color=alt.Color("Portfolio:N", scale=entity_color(pdf["Portfolio"]),
                        legend=alt.Legend(orient="top", title=None)),
        shape=alt.Shape("Portfolio:N", scale=entity_shape(pdf["Portfolio"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("Portfolio:N"),
                 alt.Tooltip("ret:Q", title="Expected return", format=".1%"),
                 alt.Tooltip("vol:Q", title="Volatility", format=".1%"),
                 alt.Tooltip("sharpe:Q", title="Sharpe", format=".2f"),
                 alt.Tooltip("holdings:Q", title="Holdings")])
    chart(alt.layer(frontier_line, frontier_pts, markers)
          .properties(height=460).interactive())
    best = fr.loc[fr["sharpe"].idxmax()]
    st.caption(
        f"{len(fr)} frontier portfolios, one per risk-aversion value γ. Highest "
        f"Sharpe on this frontier: {best['sharpe']:.2f} at "
        f"{best['ret']:.1%} return, {best['vol']:.1%} volatility. The "
        f"minimum-variance portfolio uses no return estimates at all — it is "
        f"what a return forecast has to beat. Scroll to zoom, drag to pan.")


# ===========================================================================
# Risk tolerance
# ===========================================================================
with tab_risk:
    sw = dec["sweep"].copy()
    sw["selected"] = np.isclose(sw["R_fraction"], risk_fraction)
    st.markdown("Nobody knows their risk tolerance precisely, so this is the map "
                "from R to the portfolio it implies. Find the row that sounds "
                "like you.")
    c1, c2 = st.columns(2)
    for col, field, title in [(c1, "ret", "Expected return"),
                              (c2, "vol", "Volatility")]:
        base = alt.Chart(sw).encode(
            x=alt.X("R_fraction:Q", title="Risk tolerance (share of wealth)",
                    scale=alt.Scale(type="log"),
                    axis=alt.Axis(format="%", values=list(cs.SWEEP_FRACTIONS))),
            y=alt.Y(f"{field}:Q", title=f"{title} (recommended)",
                    axis=alt.Axis(format="%")),
            tooltip=[alt.Tooltip("R_fraction:Q", title="R / wealth", format=".0%"),
                     alt.Tooltip("ret:Q", title="Expected return", format=".1%"),
                     alt.Tooltip("vol:Q", title="Volatility", format=".1%"),
                     alt.Tooltip("sharpe:Q", title="Sharpe", format=".2f"),
                     alt.Tooltip("top:N", title="Largest holdings")])
        layer = (base.mark_line(color=C_REC, strokeWidth=2)
                 + base.mark_circle(color=C_REC, size=70)
                 + base.transform_filter("datum.selected").mark_point(
                     color=C_REC, size=320, strokeWidth=2.5, filled=False))
        with col:
            chart(layer.properties(height=280))
    st.caption("The ringed point is your selected risk tolerance.")

    show = pd.DataFrame({
        "R / wealth": [f"{f:.0%}" + ("  ◀ selected" if s else "")
                       for f, s in zip(sw["R_fraction"], sw["selected"])],
        "Expected return": [pct(v) for v in sw["ret"]],
        "Volatility": [pct(v) for v in sw["vol"]],
        "Sharpe": [num(v) for v in sw["sharpe"]],
        "Holdings": sw["n_holdings"].astype(int),
        "Largest holdings": sw["top"],
        "Certainty equivalent": [money(v, scale, dollars) for v in sw["ce"]],
    })
    st.dataframe(show, hide_index=True, use_container_width=True)


# ===========================================================================
# Simulation
# ===========================================================================
with tab_sim:
    st.markdown(
        f"One year forward, {n_paths:,} paths, daily steps, rebalanced daily. "
        f"Run twice for the recommendation: once with normal shocks, once with "
        f"Student-t shocks (df {t_df:.1f}) scaled to the same variance.")
    metrics = [("Expected return", "mean", 2), ("Median return", "median", 2),
               ("P(loss)", "p_loss_any", 1), ("P(loss > 10%)", "p_loss_10", 1),
               ("5% VaR", "var_5", 2), ("1% VaR", "var_1", 2),
               ("1% CVaR", "cvar_1", 2)]
    sim_table = {"": [label for label, _, _ in metrics],
                 "Recommended · normal": [pct(mc_n[k], nd) for _, k, nd in metrics],
                 "Recommended · Student-t": [pct(mc_t[k], nd) for _, k, nd in metrics]}
    if has_current:
        sim_table["Current · Student-t"] = [pct(mc_cur[k], nd) for _, k, nd in metrics]
    st.dataframe(pd.DataFrame(sim_table).set_index(""), use_container_width=True)
    st.caption(
        f"Expected return 95% CI (normal model): [{mc_n['ci_low']:.2%}, "
        f"{mc_n['ci_high']:.2%}]. VaR and CVaR are losses, so higher is worse. "
        f"At the 5% level the fat-tailed model can look no worse, or even "
        f"better, than the normal one — its extra mass sits in the far tail, "
        f"which is why the 1% numbers are shown too.")

    st.subheader("Distribution of one-year returns (Student-t model)")
    series = [("Recommended", mc_t["returns"])]
    if has_current:
        series.append(("Current", mc_cur["returns"]))
    allr = np.concatenate([r for _, r in series])
    lo, hi = np.percentile(allr, [0.5, 99.5])
    edges = np.linspace(lo, hi, 81)
    hist = []
    for name, r in series:
        counts, _ = np.histogram(r, bins=edges)
        share = counts / len(r)
        for a, b, s in zip(edges[:-1], edges[1:], share):
            hist.append({"Portfolio": name, "ret": (a + b) / 2, "share": s,
                         "lo": a, "hi": b})
    hdf = pd.DataFrame(hist)
    dist = alt.Chart(hdf).mark_line(interpolate="step", strokeWidth=2).encode(
        x=alt.X("ret:Q", title="One-year return", axis=alt.Axis(format="%")),
        y=alt.Y("share:Q", title="Share of paths", axis=alt.Axis(format="%")),
        color=alt.Color("Portfolio:N", scale=entity_color(hdf["Portfolio"]),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=[alt.Tooltip("Portfolio:N"),
                 alt.Tooltip("lo:Q", title="From", format=".1%"),
                 alt.Tooltip("hi:Q", title="To", format=".1%"),
                 alt.Tooltip("share:Q", title="Share of paths", format=".2%")])
    loss_rule = alt.Chart(pd.DataFrame({"x": [-0.10]})).mark_rule(
        color=C_NEUTRAL, strokeWidth=1.5).encode(x="x:Q")
    chart((dist + loss_rule).properties(height=300))
    st.caption(f"The grey rule marks a 10% loss. The axis spans the 0.5th to "
               f"99.5th percentile of all paths drawn, so the extreme tails run "
               f"off the edge; {n_paths:,} paths per portfolio.")

    st.subheader("A year of possible paths for the recommendation")
    fan = get_fan(*args, risk_fraction, t_df, seed)
    unit = wealth * scale
    fdf2 = pd.DataFrame({k: (np.asarray(v) * unit if k != "month" else v)
                         for k, v in fan.items()})
    y_fmt = "$,.0f" if dollars else ",.0f"
    y_title = "Portfolio value ($)" if dollars else "Portfolio value (start = 100)"
    xb = alt.X("month:Q", title="Months ahead", scale=alt.Scale(domain=[0, 12]),
               axis=alt.Axis(values=list(range(13))))
    band90 = alt.Chart(fdf2).mark_area(color=C_REC, opacity=0.18).encode(
        x=xb, y=alt.Y("p5:Q", title=y_title, axis=alt.Axis(format=y_fmt),
                      scale=alt.Scale(zero=False)),
        y2="p95:Q")
    band50 = alt.Chart(fdf2).mark_area(color=C_REC, opacity=0.32).encode(
        x=xb, y="p25:Q", y2="p75:Q")
    median = alt.Chart(fdf2).mark_line(color=C_REC, strokeWidth=2).encode(
        x=xb, y="p50:Q")
    ref = alt.Chart(pd.DataFrame({"y": [unit, unit * 0.9]})).mark_rule(
        color=C_NEUTRAL, strokeWidth=1.2).encode(y="y:Q")
    # Crosshair: an invisible point per sample catches the pointer, a rule and
    # a dot mark the nearest month, and the tooltip carries all five bands.
    hover = alt.selection_point(fields=["month"], nearest=True, on="mouseover",
                                empty=False, clear="mouseout")
    catcher = alt.Chart(fdf2).mark_point(opacity=0, size=400).encode(
        x=xb, y="p50:Q",
        tooltip=[alt.Tooltip("month:Q", title="Months ahead", format=".1f"),
                 alt.Tooltip("p95:Q", title="95th percentile", format=y_fmt),
                 alt.Tooltip("p75:Q", title="75th percentile", format=y_fmt),
                 alt.Tooltip("p50:Q", title="Median", format=y_fmt),
                 alt.Tooltip("p25:Q", title="25th percentile", format=y_fmt),
                 alt.Tooltip("p5:Q", title="5th percentile", format=y_fmt)]
    ).add_params(hover)
    cross = alt.Chart(fdf2).mark_rule(color=C_NEUTRAL, strokeWidth=1).encode(
        x=xb).transform_filter(hover)
    dot = alt.Chart(fdf2).mark_circle(color=C_REC, size=80).encode(
        x=xb, y="p50:Q").transform_filter(hover)
    chart((band90 + band50 + ref + median + cross + dot + catcher)
          .properties(height=320))
    st.caption(f"Light band: 90% of paths. Dark band: 50%. Line: median. Grey "
               f"rules: the starting value and a 10% loss. Student-t model, "
               f"{FAN_PATHS:,} paths (seed {FAN_SEED}, as on the published page).")

    st.subheader("Where fat tails matter")
    run_tail = st.toggle(
        "Compare normal and fat-tailed 1% VaR across horizons",
        value=False,
        help="Eight more simulations (1 day, 1 week, 1 month, 1 year × two "
             "models). Off by default because the 1-year pair is slow at "
             "high path counts.")
    if run_tail:
        with st.spinner("Simulating four horizons under both models…"):
            tail = get_tail_study(*args, risk_fraction, t_df, seed, n_paths)
        st.dataframe(pd.DataFrame({
            "Horizon": tail["horizon"],
            "1% VaR · normal": [pct(v, 2) for v in tail["var1_normal"]],
            "1% VaR · Student-t": [pct(v, 2) for v in tail["var1_t"]],
            "Ratio (t ÷ normal)": [f"{v:.2f}×" for v in tail["ratio"]],
        }), hide_index=True, use_container_width=True)
        st.caption("Fat tails dominate short horizons. Over a year the return "
                   "is a sum of 252 daily draws and the Central Limit Theorem "
                   "pulls it back toward normal. The danger the model misses at "
                   "long horizons is dependence — volatility clustering and "
                   "correlations rising together in a crash.")


# ===========================================================================
# Statistics
# ===========================================================================
with tab_stats:
    c = st.columns(4)
    c[0].metric("Observations per asset", f"{m['obs_per_asset']:.1f}")
    c[1].metric("Mean shrinkage (Bayes-Stein)", pct(m["mean_shrinkage"]),
                help=f"Every mean pulled this far toward {m['mean_target']:.2%}.")
    c[2].metric("Covariance shrinkage (Ledoit-Wolf)", pct(m["cov_shrinkage"]),
                help=f"Toward constant correlation {m['avg_corr']:.2f}.")
    c[3].metric("Condition number", f"{m['cond_number']:,.0f} → {m['cond_robust']:,.0f}",
                help="Raw sample covariance → shrunk. Lower is better conditioned.")
    n_fat = int((diag["best_fit"] != "Normal").sum())
    st.markdown(f"**{n_fat} of {len(diag)}** assets reject the normal "
                f"distribution. Median fitted Student-t degrees of freedom: "
                f"**{med_df:.1f}**.")

    by_t = {t: i for i, t in enumerate(m["tickers"])}
    per = diag.copy()
    per["Expected return · shrunk %"] = [m["mu"][by_t[t]] * 100 for t in per["ticker"]]
    per["Expected return · raw %"] = [m["mu_naive"][by_t[t]] * 100 for t in per["ticker"]]
    per["Volatility %"] = per["ann_vol"] * 100
    per = per.rename(columns={"ticker": "Ticker", "skew": "Skew",
                              "excess_kurtosis": "Excess kurtosis",
                              "t_df": "t df", "best_fit": "Best fit (AIC)"})
    per = per[["Ticker", "Expected return · shrunk %", "Expected return · raw %",
               "Volatility %", "Skew", "Excess kurtosis", "t df", "Best fit (AIC)"]]
    st.dataframe(per, hide_index=True, use_container_width=True,
                 column_config={
                     "Expected return · shrunk %": st.column_config.NumberColumn(format="%.1f"),
                     "Expected return · raw %": st.column_config.NumberColumn(format="%.1f"),
                     "Volatility %": st.column_config.NumberColumn(format="%.1f"),
                     "Skew": st.column_config.NumberColumn(format="%.2f"),
                     "Excess kurtosis": st.column_config.NumberColumn(format="%.1f"),
                     "t df": st.column_config.NumberColumn(format="%.1f"),
                 })
    st.caption("Sorted by excess kurtosis (0 for a normal distribution). The "
               "gap between the shrunk and raw expected returns is how much the "
               "estimator distrusts each asset's history.")


# ===========================================================================
# Data
# ===========================================================================
with tab_data:
    st.markdown(f"**Database:** `{os.path.relpath(db_path, cs.REPO)}` · prices "
                f"through **{info['last']}** · file updated "
                f"{datetime.fromtimestamp(mtime):%Y-%m-%d %H:%M}. "
                f"The app recomputes automatically when the file changes "
                f"(for example after the daily ETL run).")
    held_set, added_set = set(d["held"]), set(new_candidates)
    fetched_set = set(d.get("fetched", []))
    uni = pd.DataFrame({
        "Ticker": tickers,
        "Role": ["held" if t in held_set else
                 "added" if t in added_set else "candidate" for t in tickers],
        "Prices from": ["research cache" if t in fetched_set else "database"
                        for t in tickers],
        "Current weight %": [float(alloc.get(t, 0.0)) * 100 for t in tickers],
    })
    st.subheader(f"Universe — {len(tickers)} assets")
    st.dataframe(uni, hide_index=True, use_container_width=True,
                 column_config={"Current weight %": st.column_config.NumberColumn(
                     format="%.1f", help="Share of the whole current portfolio, "
                                         "before rescaling to the modelled part.")})

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Excluded for short history")
        if d["excluded"]:
            st.dataframe(pd.DataFrame(
                sorted(d["excluded"].items()),
                columns=["Ticker", f"Days of prices (need {min_days})"]),
                hide_index=True, use_container_width=True)
        else:
            st.write("None.")
    with c2:
        st.subheader("Removed by choice")
        st.write(", ".join(sorted(d["user_excluded"])) or "None.")

    st.subheader("Current portfolio")
    pt = pos_table
    cp = pd.DataFrame({
        "Ticker": pt["ticker"],
        "Shares": pt["shares"],
        "Price": pt["price"],
        "Price date": pt["price_date"].fillna("—"),
        "Value": pt["value"] * scale,
        "Weight %": [float(alloc.get(t, 0.0)) * 100 for t in pt["ticker"]],
        "Modelled": ["yes" if t in tickers else
                     "no price" if t in no_price else "no" for t in pt["ticker"]],
    }).sort_values(["Weight %", "Ticker"], ascending=[False, True])
    if not dollars:
        # Shares × price is the account size, which the indexed view hides.
        cp = cp.drop(columns=["Shares", "Price"])
    st.dataframe(cp, hide_index=True, use_container_width=True,
                 column_config={
                     "Shares": st.column_config.NumberColumn(format="%.4f"),
                     "Price": st.column_config.NumberColumn(format="$%.2f"),
                     "Value": st.column_config.NumberColumn(
                         format="$%.0f" if dollars else "%.1f",
                         help="Market value in dollars" if dollars else
                              "Market value, indexed so the whole portfolio "
                              "is 100"),
                     "Weight %": st.column_config.NumberColumn(format="%.1f")})
    st.caption(f"{covered:.1%} of current value is modelled. Each position is "
               f"valued at its latest close"
               + (" from the trades table's FIFO open lots." if positions is None
                  else ", using the share counts entered in the sidebar.")
               + ("" if dollars else " Switch Values to Dollars to see share "
                                     "counts and prices."))

    st.subheader("Reproduce from the command line")
    if is_published:
        st.code("python projects/11-capstone-platform/capstone.py", language="bash")
        st.caption("This is the published configuration; the CLI prints the "
                   "same numbers.")
    else:
        extras = ""
        if candidates is not None:
            extras += (f"candidates=(*cs.CANDIDATE_ETFS, "
                       f"{', '.join(repr(t) for t in new_candidates)}), ")
        if positions is not None:
            extras += (f"positions=cs.read_positions("
                       f"{os.path.relpath(pos_path, cs.REPO)!r}), ")
        if d.get("fetched") or positions is not None:
            extras += f"extra_db={os.path.relpath(md.CACHE_DB, cs.REPO)!r}, "
        cfg = (f"cs.PipelineConfig(db_path={os.path.relpath(db_path, cs.REPO)!r}, "
               f"{extras}"
               f"min_days={min_days}, exclude={tuple(sorted(exclude))!r}, "
               f"start={start!r}, end={end!r}, estimates={estimates!r}, "
               f"max_weight={max_weight!r}, risk_fraction={risk_fraction!r}, "
               f"t_df={(None if tail_choice == 'fitted' else t_df)!r}, "
               f"seed={seed}, n_paths={n_paths})")
        st.code("import sys; sys.path.insert(0, 'projects/11-capstone-platform')\n"
                "import capstone as cs\n"
                f"out = cs.pipeline({cfg})\n"
                "cs.print_report(out)", language="python")
        st.caption("Run from the repo root. Differences from the defaults are "
                   "spelled out so the result is reproducible."
                   + (" Your edited positions are not saved yet — press Save "
                      "in the sidebar so the file matches what you see here."
                      if positions is not None and unsaved else ""))
