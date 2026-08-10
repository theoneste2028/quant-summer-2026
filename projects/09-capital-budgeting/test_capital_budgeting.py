"""
Week 9 — Test suite for the capital budgeting module
====================================================
Nearly every case here is checked against a value worked out on paper, because
a discounting bug produces plausible-looking numbers rather than a crash. Where
a closed form exists the test states it, so the expected value is verifiable
without trusting the code that produced it.

Run:
    python test_capital_budgeting.py
"""
from __future__ import annotations
import os, sys, math
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from capital_budgeting import (                      # noqa: E402
    npv, irr, all_irrs, sign_changes, multiple_irr_warning,
    discounted_payback, profitability_index, summarize,
    incremental_analysis, SolarProject, tornado, breakeven, scenario_analysis)

PASS, FAIL = [], []


def check(name, got, want, tol=1e-6):
    if want is None or got is None:
        ok = got is want or got == want
    elif isinstance(want, (int, float)) and isinstance(got, (int, float)):
        ok = abs(got - want) <= tol
    else:
        ok = got == want
    (PASS if ok else FAIL).append(name)
    g = f"{got:.6f}" if isinstance(got, float) else repr(got)
    w = f"{want:.6f}" if isinstance(want, float) else repr(want)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {g}, want {w}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


# ---------------------------------------------------------------------------
def test_npv():
    print("\n--- NPV " + "-" * 68)
    # -1000 + 600/1.1 + 600/1.21 = -1000 + 545.454545 + 495.867769
    check("npv([-1000,600,600] @ 10%)", npv(0.10, [-1000, 600, 600]),
          -1000 + 600 / 1.1 + 600 / 1.21)
    check("npv at 0% equals the plain sum", npv(0.0, [-1000, 600, 600]), 200.0)
    check("t=0 flow is never discounted", npv(0.25, [-500]), -500.0)
    check("npv of all zeros", npv(0.1, [0, 0, 0]), 0.0)
    # A perpetuity-free check: a single flow one period out.
    check("single future flow", npv(0.05, [0, 105.0]), 100.0)
    # Higher discount rate must lower NPV for a conventional project.
    check_true("NPV decreases as the rate rises",
               npv(0.05, [-1000, 600, 600]) > npv(0.15, [-1000, 600, 600]))


def test_irr():
    print("\n--- IRR " + "-" * 68)
    check("irr([-1000,1100]) = 10%", irr([-1000, 1100]), 0.10, tol=1e-6)
    # -100 + 60x + 60x^2 = 0 with x = 1/(1+r)  =>  3x^2 + 3x - 5 = 0
    #   x = (-3 + sqrt(69)) / 6 ;  r = 1/x - 1
    x = (-3 + math.sqrt(69)) / 6
    check("irr([-100,60,60]) matches the quadratic root",
          irr([-100, 60, 60]), 1 / x - 1, tol=1e-6)
    check("NPV at the IRR is zero",
          npv(irr([-1000, 400, 400, 400]), [-1000, 400, 400, 400]), 0.0, tol=1e-6)
    check("no IRR when every flow is negative", irr([-100, -50]), None)
    check("no IRR when every flow is positive", irr([100, 50]), None)


def test_multiple_irr():
    print("\n--- Multiple IRRs (non-conventional flows) " + "-" * 33)
    # The textbook case: -4000, +25000, -25000.
    #   25000x^2 - 25000x + 4000 = 0  =>  25x^2 - 25x + 4 = 0
    #   x = (25 +/- 15)/50 = 0.8 or 0.2  =>  r = 25% or 400%
    cf = [-4000, 25000, -25000]
    roots = all_irrs(cf)
    check("two sign changes detected", sign_changes(cf), 2)
    check("exactly two IRRs found", len(roots), 2)
    check("first IRR = 25%", roots[0], 0.25, tol=1e-5)
    check("second IRR = 400%", roots[1], 4.00, tol=1e-5)
    check_true("both roots really zero the NPV",
               all(abs(npv(r, cf)) < 1e-4 for r in roots),
               str([npv(r, cf) for r in roots]))
    w = multiple_irr_warning(cf)
    check_true("warning raised for ambiguous IRR", w is not None and "IRR" in w)

    # A conventional project must NOT be flagged.
    check("conventional series has one sign change", sign_changes([-1000, 500, 500, 500]), 1)
    check("no warning for a conventional series",
          multiple_irr_warning([-1000, 500, 500, 500]), None)
    check("sign changes ignore zeros", sign_changes([-100, 0, 0, 50]), 1)
    check("alternating series", sign_changes([-1, 1, -1, 1]), 3)


def test_payback_and_pi():
    print("\n--- Discounted payback & profitability index " + "-" * 31)
    # At 0% the discounting vanishes: -1000, -500, 0 -> pays back exactly at t=2.
    check("payback at 0% is exact", discounted_payback(0.0, [-1000, 500, 500, 500]), 2.0)
    check("never pays back -> None", discounted_payback(0.10, [-1000, 100, 100]), None)
    check("pays back immediately at t=0", discounted_payback(0.1, [0, 100]), 0.0)

    # Interpolation: at 10%, cum = -1000, -454.55, +38.02 -> crossing inside yr 2.
    p = discounted_payback(0.10, [-1000, 600, 600])
    check_true("fractional payback lies in (1, 2)", 1.0 < p < 2.0, f"{p:.4f}")
    # Verify the interpolation arithmetic explicitly.
    c1 = -1000 + 600 / 1.1
    c2 = c1 + 600 / 1.21
    check("payback interpolation matches the hand calc", p, 1 + (-c1 / (c2 - c1)))

    # PI = PV(inflows) / initial outlay
    pi = profitability_index(0.10, [-1000, 600, 600])
    check("profitability index", pi, (600 / 1.1 + 600 / 1.21) / 1000)
    check_true("PI > 1 exactly when NPV > 0",
               (pi > 1) == (npv(0.10, [-1000, 600, 600]) > 0))
    raised = False
    try:
        profitability_index(0.1, [1000, 600])
    except ValueError:
        raised = True
    check_true("PI rejects a non-negative t=0 flow", raised)


def test_incremental():
    print("\n--- Incremental analysis " + "-" * 51)
    # Small project: high rate, small scale. Large: lower rate, more value.
    small = [-1000, 1300]          # IRR 30%
    large = [-10000, 12000]        # IRR 20%
    inc = incremental_analysis(0.10, small, large, names=("S", "L"))
    check("small IRR", inc["irr_S"], 0.30, tol=1e-6)
    check("large IRR", inc["irr_L"], 0.20, tol=1e-6)
    check_true("NPV prefers the large project", inc["npv_L"] > inc["npv_S"])
    check("IRR ranks the small one first", inc["irr_ranking"], "S")
    check("NPV ranks the large one first", inc["npv_ranking"], "L")
    check_true("the conflict is detected", inc["conflict"])
    # Incremental flows: (-10000+1000, 12000-1300) = (-9000, 10700) -> IRR 18.89%
    check("incremental IRR", inc["incremental_irr"], 10700 / 9000 - 1, tol=1e-6)
    check("choose the large project", inc["choice"], "L")

    # With a hurdle above the incremental IRR, the extra outlay is not worth it.
    inc2 = incremental_analysis(0.25, small, large, names=("S", "L"))
    check("high hurdle flips the choice to small", inc2["choice"], "S")


def test_solar_model():
    print("\n--- Solar project cash-flow model " + "-" * 42)
    p = SolarProject()
    cf = p.cashflows()
    check("one t=0 flow plus one per year", len(cf), p.life_years + 1)
    check("t=0 is the negative install cost", cf[0], -24_000.0)
    # Year 1: 11000 kWh x $0.17 - $200 maintenance + 30% x 24000 tax credit
    check("year 1 cash flow", cf[1], 11_000 * 0.17 - 200 + 24_000 * 0.30)
    # Year 2: degraded output, escalated price, no credit
    check("year 2 cash flow", cf[2], 11_000 * 0.995 * (0.17 * 1.025) - 200)
    check_true("output degrades year over year",
               all(cf[i] >= 0 for i in range(2, len(cf))))
    check("summarize reports one sign change", summarize(0.06, cf)["sign_changes"], 1)

    # Zero production must make the project a pure loss net of the credit.
    dead = replace(p, annual_kwh=0.0)
    check_true("a zero-output system has negative NPV", dead.npv() < 0,
               f"{dead.npv():,.0f}")


def test_tornado():
    print("\n--- Tornado sensitivity " + "-" * 52)
    p = SolarProject()
    t = tornado(p, ["annual_kwh", "price_per_kwh", "initial_cost",
                    "annual_maintenance", "discount_rate"], pct=0.30)
    check("base NPV matches the project", t["base_npv"], p.npv())
    check("one row per input", len(t["rows"]), 5)
    check_true("rows are sorted by swing, descending",
               all(t["rows"][i]["swing"] >= t["rows"][i + 1]["swing"]
                   for i in range(len(t["rows"]) - 1)))

    # kWh and price enter the model as a product, so a +/-30% move in either
    # must produce exactly the same swing. A mismatch means one of them is being
    # applied in the wrong place.
    sw = {r["input"]: r["swing"] for r in t["rows"]}
    check("output and price have identical influence",
          sw["annual_kwh"], sw["price_per_kwh"], tol=1e-6)
    check_true("cost has a smaller swing than output",
               sw["initial_cost"] < sw["annual_kwh"])

    # Directions: more output raises NPV, more cost lowers it.
    d = {r["input"]: r["direction"] for r in t["rows"]}
    check("higher output raises NPV", d["annual_kwh"], "+")
    check("higher install cost lowers NPV", d["initial_cost"], "-")
    check("higher discount rate lowers NPV", d["discount_rate"], "-")
    check("higher maintenance lowers NPV", d["annual_maintenance"], "-")

    # The low/high endpoints must equal the model re-evaluated at those inputs.
    row = next(r for r in t["rows"] if r["input"] == "initial_cost")
    check("tornado endpoint matches a direct re-evaluation",
          row["npv_low"], replace(p, initial_cost=24_000 * 0.7).npv())


def test_breakeven():
    print("\n--- Break-even " + "-" * 61)
    p = SolarProject()
    be = breakeven(p, "price_per_kwh")
    check_true("a break-even price exists", be is not None)
    check("NPV is zero at the break-even price",
          replace(p, price_per_kwh=be).npv(), 0.0, tol=1.0)
    check_true("break-even price is below the base case", be < p.price_per_kwh,
               f"{be:.4f} vs {p.price_per_kwh}")
    # kWh and price are interchangeable in the model, so their break-even
    # percentage moves must agree.
    be_k = breakeven(p, "annual_kwh")
    check("break-even % is the same for output and price",
          be_k / p.annual_kwh, be / p.price_per_kwh, tol=1e-3)


def test_scenarios():
    print("\n--- Scenario analysis " + "-" * 54)
    p = SolarProject()
    scen = {"worst": (0.25, {"annual_kwh": 9_000.0}),
            "base":  (0.50, {}),
            "best":  (0.25, {"annual_kwh": 12_500.0})}
    s = scenario_analysis(p, scen)
    vals = {r["scenario"]: r["npv"] for r in s["rows"]}
    exp = 0.25 * vals["worst"] + 0.50 * vals["base"] + 0.25 * vals["best"]
    check("expected NPV is the probability-weighted mean", s["expected_npv"], exp)
    var = (0.25 * (vals["worst"] - exp) ** 2 + 0.50 * (vals["base"] - exp) ** 2
           + 0.25 * (vals["best"] - exp) ** 2)
    check("variance matches the hand calc", s["variance"], var, tol=1e-4)
    check("std dev is the square root of variance", s["std_dev"], var ** 0.5, tol=1e-6)
    check("base scenario equals the unmodified project", vals["base"], p.npv())
    check_true("worst < base < best", vals["worst"] < vals["base"] < vals["best"])

    raised = False
    try:
        scenario_analysis(p, {"a": (0.5, {}), "b": (0.2, {})})
    except ValueError:
        raised = True
    check_true("probabilities that do not sum to 1 are rejected", raised)

    # A degenerate single scenario has zero spread.
    s1 = scenario_analysis(p, {"only": (1.0, {})})
    check("single scenario has zero variance", s1["variance"], 0.0, tol=1e-9)
    check("single scenario expectation equals its NPV", s1["expected_npv"], p.npv())

    # Downside probability counts only the negative-NPV scenarios.
    s2 = scenario_analysis(p, {"bad": (0.4, {"annual_kwh": 1_000.0}),
                               "good": (0.6, {})})
    check("P(NPV < 0) picks up the losing scenario", s2["p_negative_npv"], 0.4)


def main():
    print("=" * 78)
    print("Week 9 capital budgeting test suite")
    print("=" * 78)
    test_npv()
    test_irr()
    test_multiple_irr()
    test_payback_and_pi()
    test_incremental()
    test_solar_model()
    test_tornado()
    test_breakeven()
    test_scenarios()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
