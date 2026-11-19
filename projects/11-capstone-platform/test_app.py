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

Run:
    python test_app.py
"""
from __future__ import annotations
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import capstone as cs                                    # noqa: E402

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
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
