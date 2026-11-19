"""
Week 12 — Test suite for the research app
=========================================
Drives `app.py` headlessly with Streamlit's AppTest: sets the sidebar controls
the way a user would, reruns the script, and checks what it rendered.

Three kinds of check:
  * Agreement — with the controls at the published configuration, the app
    shows the numbers in site/capstone.json, and its Layer 1-4 figures equal
    a direct call to the capstone stages. The app adds no maths of its own, so
    any disagreement is a wiring bug.
  * Every control does something — each one changes what it should, and
    leaves alone what it should not.
  * Failure paths are messages, not crashes — too little data, an infeasible
    position cap, a database the optimizer cannot use.

Needs the real portfolio database (data/portfolio.db); skipped without it.
Never touches your own saved positions or price cache, and never goes online:
both live in a temporary folder for the run, and Yahoo Finance is replaced by
an offline stub.

Run:
    python test_app.py
"""
from __future__ import annotations
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Before market_data is imported anywhere: point the price cache and the saved
# positions at a scratch folder, so a saved data/portfolio_positions.csv cannot
# change what the default view shows, and the tests cannot overwrite it.
SCRATCH = tempfile.mkdtemp(prefix="test_app_")
os.environ["RESEARCH_PRICES_DB"] = os.path.join(SCRATCH, "research_prices.db")
os.environ["RESEARCH_POSITIONS_DIR"] = SCRATCH

import numpy as np                                       # noqa: E402
import capstone as cs                                    # noqa: E402
import market_data as md                                 # noqa: E402

PASS, FAIL = [], []
APP = os.path.join(HERE, "app.py")
SITE_JSON = os.path.join(cs.REPO, "site", "capstone.json")
DEMO_DB = os.path.join(cs.REPO, "data", "portfolio_demo.db")


def check(name, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {got!r}, want {want!r}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return cond


# ---------------------------------------------------------------------------
# AppTest helpers
# ---------------------------------------------------------------------------
def fresh():
    from streamlit.testing.v1 import AppTest
    return AppTest.from_file(APP, default_timeout=600).run()


def widget(at, kind, label):
    for w in getattr(at, kind):
        if w.label == label:
            return w
    raise LookupError(f"no {kind} labelled {label!r}")


def metric(at, label):
    for m in at.metric:
        if m.label == label:
            return m
    raise LookupError(f"no metric labelled {label!r}")


def frame_with(at, column):
    """The first rendered dataframe that has `column`."""
    for df in at.dataframe:
        v = df.value
        if column in v.columns:
            return v
    raise LookupError(f"no dataframe with column {column!r}")


def editor_key(at):
    """Session-state key of the positions editor (it embeds a hash of the
    table it was opened on)."""
    keys = [k for k in at.session_state.filtered_state if str(k).startswith("positions_")]
    if len(keys) != 1:
        raise LookupError(f"expected one positions editor, found {keys}")
    return keys[0]


def edit_positions(at, edited_rows=None, added_rows=None, deleted_rows=None,
                   run=True):
    """Make the edits a user would make in the positions table, and rerun.

    A browser re-sends the editor's edits on every rerun. AppTest does not
    model the data editor, so it keeps them for one run only: any later run
    that should still see them calls this again (run=False to combine with
    another widget change or a button click in the same run).
    """
    at.session_state[editor_key(at)] = {
        "edited_rows": edited_rows or {}, "added_rows": added_rows or [],
        "deleted_rows": deleted_rows or []}
    return at.run() if run else at


def button(at, prefix):
    for b in at.button:
        if b.label.startswith(prefix):
            return b
    raise LookupError(f"no button starting {prefix!r}")


def stub_closes(ticker):
    """Offline stand-in for Yahoo: a reproducible random walk on the
    database's trading days, or nothing for an unknown symbol."""
    if ticker.startswith("NOPE"):
        return []
    days = [r[0] for r in sqlite3.connect(cs.DB_PATH).execute(
        "SELECT DISTINCT date FROM prices WHERE ticker = 'VOO' ORDER BY date")]
    rng = np.random.default_rng(sum(map(ord, ticker)))
    px = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, len(days))))
    return list(zip(days, px))


def clean(at):
    """No uncaught exception and no error box."""
    return not at.exception and not at.error


def texts(elements):
    return " ".join(e.value for e in elements)


# ---------------------------------------------------------------------------
def test_default_matches_pipeline():
    print("\n--- Default view agrees with the capstone stages " + "-" * 27)
    at = fresh()
    check_true("default run renders without exceptions or errors", clean(at),
               f"{[e.value for e in at.exception]} {[e.value for e in at.error]}")

    # The same stages, called directly with the CLI defaults.
    s1 = cs.stage_data()
    s2 = cs.stage_statistics(s1["data"]["returns"])
    opt = cs.stage_optimize(s2["moments"])
    wealth = s1["portfolio_value"]
    dec = cs.stage_decide(opt, s1["data"]["universe"], wealth, 0.25 * wealth,
                          s2["median_t_df"], 7, s1["allocation"])
    rec, cur = dec["recommended"], dec["current"]

    check("expected return metric", metric(at, "Expected return").value,
          f"{rec['ret']:.1%}")
    check("volatility metric", metric(at, "Volatility").value, f"{rec['vol']:.1%}")
    check("Sharpe metric", metric(at, "Sharpe ratio").value, f"{rec['sharpe']:.2f}")
    check("volatility delta is recommended minus current",
          metric(at, "Volatility").delta,
          f"{(rec['vol'] - cur['vol']) * 100:+.1f} pts vs current")
    check("condition-number metric",
          metric(at, "Condition number").value,
          f"{s2['moments']['cond_number']:,.0f} → {s2['moments']['cond_robust']:,.0f}")

    weights = frame_with(at, "Recommended %")
    shown = dict(zip(weights["Ticker"], weights["Recommended %"]))
    want = {t: w * 100 for t, w in zip(s1["data"]["universe"], rec["weights"])
            if w > 1e-4}
    check_true("allocation table lists exactly the recommended holdings",
               set(shown) >= set(want) and
               all(abs(shown[t] - want[t]) < 1e-9 for t in want),
               f"{sorted(want)}")
    check_true("the uncovered-value notice names the excluded holdings",
               all(t in texts(at.info) for t in s1["data"]["excluded"]
                   if t in s1["allocation"].index))
    check_true("values are indexed by default, not dollars",
               "$" not in frame_with(at, "Recommended").loc["Certainty equivalent",
                                                            "Recommended"])
    return at


def test_published_configuration():
    print("\n--- Published configuration reproduces site/capstone.json " + "-" * 17)
    if not os.path.exists(SITE_JSON):
        print("  (skipped — no site/capstone.json)")
        return
    pub = json.load(open(SITE_JSON))
    at = fresh()
    widget(at, "select_slider", "Monte Carlo paths").set_value(100_000).run()
    check_true("100,000 paths renders cleanly", clean(at))
    check_true("the caption recognises the published configuration",
               "the published configuration" in at.caption[0].value)

    sim = frame_with(at, "Recommended · Student-t")
    t, n = pub["monte_carlo"]["recommended_t"], pub["monte_carlo"]["recommended_normal"]
    check("P(loss > 10%), Student-t", sim.loc["P(loss > 10%)", "Recommended · Student-t"],
          f"{t['p_loss_10']:.1%}")
    check("1% VaR, Student-t", sim.loc["1% VaR", "Recommended · Student-t"],
          f"{t['var_1']:.2%}")
    check("5% VaR, normal", sim.loc["5% VaR", "Recommended · normal"],
          f"{n['var_5']:.2%}")
    check("1% CVaR, normal", sim.loc["1% CVaR", "Recommended · normal"],
          f"{n['cvar_1']:.2%}")
    check("current portfolio P(loss > 10%)",
          sim.loc["P(loss > 10%)", "Current · Student-t"],
          f"{pub['monte_carlo']['current_t']['p_loss_10']:.1%}")

    widget(at, "toggle", "Compare normal and fat-tailed 1% VaR across horizons").set_value(True).run()
    tail = frame_with(at, "Ratio (t ÷ normal)")
    want = [f"{r['ratio']:.2f}×" for r in pub["monte_carlo"]["horizon_tails"]]
    check("horizon tail study matches the published ratios",
          list(tail["Ratio (t ÷ normal)"]), want)


def test_controls():
    print("\n--- Each control changes what it should " + "-" * 36)
    at = fresh()
    base_vol = metric(at, "Volatility").value

    widget(at, "select_slider", "Risk tolerance (R as a share of wealth)").set_value(1.0).run()
    check_true("higher risk tolerance renders cleanly", clean(at))
    check_true("higher risk tolerance raises volatility",
               float(metric(at, "Volatility").value.rstrip("%")) >
               float(base_vol.rstrip("%")),
               f"{base_vol} -> {metric(at, 'Volatility').value}")
    sweep = frame_with(at, "Largest holdings")
    marked = [r for r in sweep["R / wealth"] if "selected" in r]
    check("the sweep marks exactly the selected risk tolerance", marked,
          ["100%  ◀ selected"])

    at = fresh()
    widget(at, "select_slider", "Largest single position").set_value(None).run()
    check_true("no position cap renders cleanly", clean(at))
    w = frame_with(at, "Recommended %")["Recommended %"]
    check_true("without a cap the weights still sum to 100%",
               abs(w.sum() - 100) < 1e-6, f"{w.sum():.6f}")

    at = fresh()
    widget(at, "checkbox", "Also show the uncapped raw-estimate frontier").check().run()
    check_true("overlaying the raw-estimate frontier renders cleanly", clean(at))

    at = fresh()
    widget(at, "radio", "Expected returns and covariance").set_value("naive").run()
    check_true("raw sample estimates render cleanly", clean(at))
    check_true("raw sample estimates carry a warning",
               "Raw sample estimates" in texts(at.warning))

    at = fresh()
    widget(at, "multiselect", "Remove from the universe").set_value(["GLD"]).run()
    check_true("removing a ticker renders cleanly", clean(at))
    check_true("the caption counts one asset fewer",
               "· 19 assets ·" in at.caption[0].value, at.caption[0].value)
    check_true("the removed ticker is listed on the Data tab",
               "GLD" in texts(at.markdown), "Removed by choice")

    at = fresh()
    widget(at, "radio", "Fat-tail model (Student-t degrees of freedom)").set_value("custom").run()
    widget(at, "number_input", "Degrees of freedom").set_value(6.0).run()
    check_true("a custom t df renders cleanly and is used",
               clean(at) and "t df 6.0" in at.caption[0].value,
               at.caption[0].value)

    at = fresh()
    widget(at, "radio", "Values").set_value("Dollars").run()
    ce = frame_with(at, "Recommended").loc["Certainty equivalent", "Recommended"]
    check_true("the dollar view shows dollars", ce.startswith("$"), ce)

    at = fresh()
    seed_box = widget(at, "number_input", "Random seed")
    p7 = frame_with(at, "Recommended · Student-t").loc["5% VaR", "Recommended · Student-t"]
    seed_box.set_value(8).run()
    p8 = frame_with(at, "Recommended · Student-t").loc["5% VaR", "Recommended · Student-t"]
    check_true("changing the seed changes the simulation", p7 != p8, f"{p7} vs {p8}")


def test_failure_paths():
    print("\n--- Failure paths show a message, never a crash " + "-" * 28)
    at = fresh()
    widget(at, "checkbox", "Limit the date window").check().run()
    from datetime import date
    widget(at, "date_input", "Start").set_value(date(2026, 1, 2)).run()
    check_true("a window shorter than the history minimum is an error message",
               not at.exception and at.error and
               "date window" in at.error[0].value, texts(at.error)[:120])
    widget(at, "number_input", "Minimum price history (days)").set_value(100).run()
    check_true("lowering the minimum inside that window recovers", clean(at),
               texts(at.error)[:120])
    # The data may start later than the window: the intersection of dates
    # begins when the youngest admitted asset starts trading.
    first_return = at.caption[0].value.split(" → ")[0]
    check_true("the window is honoured (no return before the chosen start)",
               first_return >= "2026-01-02", at.caption[0].value)
    check_true("a lower minimum admits the short-history holdings",
               "· 25 assets ·" in at.caption[0].value, at.caption[0].value)

    at = fresh()
    widget(at, "checkbox", "Limit the date window").check().run()
    widget(at, "date_input", "End").set_value(
        widget(at, "date_input", "Start").value).run()
    check_true("start not before end is an error message",
               not at.exception and "Start must be before end" in texts(at.error))

    at = fresh()
    pool = widget(at, "multiselect", "Remove from the universe").options
    s1 = cs.stage_data()
    keep = s1["data"]["universe"][:3]
    widget(at, "multiselect", "Remove from the universe").set_value(
        [t for t in pool if t not in keep]).run()
    check_true("an unreachable position cap is an error message",
               not at.exception and "cannot be met" in texts(at.error),
               texts(at.error)[:120])

    if os.path.exists(DEMO_DB):
        at = fresh()
        widget(at, "selectbox", "Database").set_value(DEMO_DB).run()
        check_true("the demo database explains why it cannot be used",
                   not at.exception and "Not enough price history" in texts(at.error),
                   texts(at.error)[:120])
    else:
        print("  (demo-database check skipped — no data/portfolio_demo.db)")


def test_tickers_and_positions():
    print("\n--- Your tickers and your positions " + "-" * 40)
    md.yahoo_closes = stub_closes          # the app calls md.fetch -> this stub
    db_pos = cs.normalize_positions(cs.held_positions())
    pos_file = os.path.join(SCRATCH, "portfolio_positions.csv")

    at = fresh()
    check_true("the default view uses the database's positions",
               f"Using the {len(db_pos)} open positions" in texts(at.sidebar.caption)
               and "positions as entered" not in at.caption[0].value)

    # ---- adding tickers --------------------------------------------------
    widget(at, "text_input", "Add tickers").set_value("aapl, NOPE1, bad$$, VOO").run()
    check_true("adding tickers renders cleanly", clean(at))
    warn = texts(at.sidebar.warning)
    check_true("a malformed symbol is named and ignored", "BAD$$" in warn, warn)
    check_true("tickers without prices are named before fetching",
               "No prices yet for AAPL, NOPE1" in warn, warn)
    check_true("a ticker already in the universe is said to be",
               "Already in the universe: VOO" in texts(at.sidebar.caption))
    check_true("nothing is fetched until asked",
               not os.path.exists(md.CACHE_DB))
    button(at, "Fetch prices").click().run()
    check_true("fetching renders cleanly", clean(at),
               f"{[e.value[:200] for e in at.exception]}")
    check_true("the fetch reports what it stored",
               "Fetched AAPL" in texts(at.sidebar.success))
    check_true("an unknown symbol is reported, not fatal",
               "No prices found for NOPE1" in texts(at.sidebar.warning))
    check_true("the caption counts only added tickers that made it in",
               "· 21 assets ·" in at.caption[0].value
               and "· +1 added" in at.caption[0].value, at.caption[0].value)
    uni = frame_with(at, "Prices from").set_index("Ticker")
    check("the added ticker's role and price source",
          (uni.loc["AAPL", "Role"], uni.loc["AAPL", "Prices from"]),
          ("added", "research cache"))
    check_true("an added ticker is never the published configuration",
               "the published configuration" not in at.caption[0].value)
    code = texts(at.code)
    check_true("the reproduce snippet carries the added ticker and the cache",
               "candidates=(*cs.CANDIDATE_ETFS, 'AAPL', 'NOPE1')" in code
               and "extra_db=" in code, code[:200])
    s1 = cs.stage_data(candidates=cs.CANDIDATE_ETFS + ["AAPL"], extra_db=md.CACHE_DB)
    check("the app's universe equals the stage called directly",
          list(frame_with(at, "Prices from")["Ticker"]), s1["data"]["universe"])
    check_true("the portfolio database was not written to",
               "AAPL" not in cs.held_tickers() and sqlite3.connect(cs.DB_PATH).execute(
                   "SELECT COUNT(*) FROM prices WHERE ticker='AAPL'").fetchone()[0] == 0)

    # ---- editing positions -------------------------------------------------
    at = fresh()
    base_ret = metric(at, "Expected return").value
    base_vol_delta = metric(at, "Volatility").delta
    big = max(range(len(db_pos)), key=lambda i: db_pos[i][1])
    tripled = {big: {"Shares": db_pos[big][1] * 3}}
    edit_positions(at, edited_rows=tripled)
    check_true("an edited share count renders cleanly", clean(at))
    check_true("the caption says positions are as entered",
               "positions as entered" in at.caption[0].value)
    check_true("the sidebar says the edits are not saved",
               "edited, not saved" in texts(at.sidebar.caption))
    check("the recommendation does not depend on what you hold",
          metric(at, "Expected return").value, base_ret)
    check_true("the current-portfolio comparison does",
               metric(at, "Volatility").delta != base_vol_delta,
               f"{base_vol_delta} -> {metric(at, 'Volatility').delta}")
    want = dict(db_pos)
    want[db_pos[big][0]] *= 3
    s1 = cs.stage_data(positions=want)
    shown = frame_with(at, "Weight %").set_index("Ticker")["Weight %"]
    check_true("current weights equal shares x price, computed independently",
               all(abs(shown[t] - w * 100) < 1e-9 for t, w in s1["allocation"].items()))
    check_true("the indexed view hides share counts and prices",
               "Shares" not in frame_with(at, "Weight %").columns
               and "Price" not in frame_with(at, "Weight %").columns)
    check("indexed values add up to 100",
          round(float(frame_with(at, "Weight %")["Value"].sum()), 9), 100.0)
    edit_positions(at, edited_rows=tripled, run=False)
    widget(at, "radio", "Values").set_value("Dollars").run()
    table = frame_with(at, "Weight %").set_index("Ticker")
    # Pass/fail only: these are real share counts, kept out of the test log.
    check_true("the dollar view shows the edited share count",
               float(table.loc[db_pos[big][0], "Shares"]) == db_pos[big][1] * 3)

    # ---- save, reload, revert ----------------------------------------------
    edit_positions(at, edited_rows=tripled, run=False)
    button(at, "Save").click().run()
    check_true("Save writes the positions file", os.path.exists(pos_file))
    check_true("the saved file holds exactly the edited positions",
               cs.read_positions(pos_file) == cs.normalize_positions(want))
    at = fresh()
    check_true("saved positions are used on the next visit",
               "positions as entered" in at.caption[0].value
               and "(saved file)" in texts(at.sidebar.caption),
               texts(at.sidebar.caption)[-160:])
    check_true("the reproduce snippet reads the saved file",
               "positions=cs.read_positions(" in texts(at.code))
    button(at, "Use database").click().run()
    check_true("Use database deletes the file and goes back to the trades",
               not os.path.exists(pos_file)
               and "positions as entered" not in at.caption[0].value)

    # ---- a position the database does not know -----------------------------
    at = fresh()
    edit_positions(at, added_rows=[{"Ticker": "nope2", "Shares": 5.0}])
    check_true("an unpriced new position renders cleanly", clean(at))
    check_true("it is named as unpriced and not valued",
               "No price for NOPE2" in texts(at.warning))
    check_true("its price can be fetched from the sidebar",
               "No prices yet for NOPE2" in texts(at.sidebar.warning)
               and button(at, "Fetch prices") is not None)
    edit_positions(at, added_rows=[{"Ticker": "aapl", "Shares": 5.0}])
    check_true("a cached new position joins the current portfolio",
               clean(at) and "AAPL" in list(frame_with(at, "Weight %")["Ticker"])
               and frame_with(at, "Prices from").set_index("Ticker")
               .loc["AAPL", "Role"] == "held")
    edit_positions(at, added_rows=[{"Ticker": "AAPL", "Shares": -1.0},
                                   {"Ticker": "two words", "Shares": 1.0}])
    w = texts(at.sidebar.warning)
    check_true("bad rows are named, and left out rather than guessed",
               clean(at) and "negative shares" in w and "'two words'" in w, w)
    edit_positions(at, deleted_rows=list(range(len(db_pos))))
    check_true("deleting every position leaves a working recommendation",
               clean(at) and "Recommended %" in frame_with(at, "Recommended %").columns
               and "current-vs-recommended comparisons are omitted"
               in texts(at.warning))


def main():
    print("=" * 78)
    print("Week 12 research app test suite")
    print("=" * 78)
    if not os.path.exists(cs.DB_PATH):
        print("  (skipped — no database)")
    else:
        try:
            import streamlit  # noqa: F401
        except ImportError:
            FAIL.append("streamlit is installed")
            print("  [FAIL] streamlit is not installed: pip install -r requirements.txt")
        else:
            test_default_matches_pipeline()
            test_published_configuration()
            test_controls()
            test_failure_paths()
            test_tickers_and_positions()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    shutil.rmtree(SCRATCH, ignore_errors=True)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
