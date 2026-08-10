"""
Week 9 — Capital Budgeting & Sensitivity Analysis
=================================================
CivEnv 205. Every capital decision — a firm buying equipment, a household
choosing solar panels, a bank pricing a loan — reduces to comparing cash flows
that arrive at different times. NPV and IRR do that comparison. But a single
NPV is dangerously overconfident: it hides the fact that the answer rests on
assumptions you guessed. Sensitivity analysis finds *which* guess the decision
actually depends on.

What this module provides
-------------------------
  Core measures     npv, irr, discounted_payback, profitability_index
  Edge cases        multiple-IRR detection (non-conventional cash flows),
                    incremental analysis for mutually exclusive projects
  Sensitivity       one-at-a-time tornado analysis
  Uncertainty       scenario analysis -> expected NPV and its standard deviation

Sign convention: cash flows are listed from t=0, outflows negative. So a project
costing 1000 today and returning 600 for two years is [-1000, 600, 600].

Run:
    python capital_budgeting.py          # worked solar-panel case study
"""
from __future__ import annotations
import os
from dataclasses import dataclass, replace, fields

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


# ===========================================================================
# PART A — Core measures
# ===========================================================================
def npv(rate: float, cashflows) -> float:
    """Net present value: sum of CF_t / (1+r)^t, with t starting at 0.

    A dollar in 2030 is not a dollar today, and the discount rate is the price
    of that difference. NPV > 0 means the project beats the return you could
    have had elsewhere at the same risk.
    """
    cf = np.asarray(cashflows, dtype=float)
    t = np.arange(len(cf))
    return float(np.sum(cf / (1.0 + rate) ** t))


def npv_derivative(rate: float, cashflows) -> float:
    """d(NPV)/d(rate). Used by the Newton step inside irr()."""
    cf = np.asarray(cashflows, dtype=float)
    t = np.arange(len(cf))
    return float(np.sum(-t * cf / (1.0 + rate) ** (t + 1)))


def sign_changes(cashflows) -> int:
    """Number of sign changes in the cash-flow series (zeros ignored).

    Descartes' rule of signs bounds the number of positive real roots of the NPV
    polynomial by this count. One sign change (the conventional
    spend-then-earn shape) guarantees at most one IRR; more than one means the
    IRR may not be unique, which is when IRR stops being a safe decision rule.
    """
    s = [np.sign(c) for c in cashflows if c != 0]
    return sum(1 for a, b in zip(s, s[1:]) if a != b)


def irr(cashflows, guess=0.1) -> float | None:
    """Internal rate of return: the discount rate where NPV = 0.

    Returns None when no rate in a plausible range zeroes the NPV — which is a
    real outcome, not a failure. A project that never pays back has no IRR, and
    reporting one would be worse than reporting nothing.
    """
    roots = all_irrs(cashflows)
    if not roots:
        return None
    # With a conventional series there is exactly one root; with several, return
    # the one nearest the caller's guess and let multiple_irr_warning() flag it.
    return min(roots, key=lambda r: abs(r - guess))


def all_irrs(cashflows, lo=-0.9999, hi=10.0, steps=2000) -> list[float]:
    """Find every IRR by scanning for sign changes in NPV, then bisecting.

    numpy_financial.irr returns a single root and gives no hint that others
    exist. For non-conventional cash flows (an outflow after inflows have
    begun — a mine that must be remediated, equipment needing a mid-life
    overhaul) there genuinely can be several, and picking one arbitrarily is how
    IRR produces a confidently wrong ranking.
    """
    cf = np.asarray(cashflows, dtype=float)
    if len(cf) < 2 or np.all(cf >= 0) or np.all(cf <= 0):
        return []
    grid = np.linspace(lo, hi, steps)
    vals = np.array([npv(r, cf) for r in grid])
    roots = []
    for i in range(len(grid) - 1):
        a, b = vals[i], vals[i + 1]
        if a == 0.0:
            roots.append(float(grid[i]))
        elif a * b < 0:                      # sign change brackets a root
            lo_r, hi_r = grid[i], grid[i + 1]
            for _ in range(200):             # bisection: robust, no derivative
                mid = (lo_r + hi_r) / 2
                if npv(lo_r, cf) * npv(mid, cf) <= 0:
                    hi_r = mid
                else:
                    lo_r = mid
            roots.append((lo_r + hi_r) / 2)
    # De-duplicate roots that the grid found twice.
    out = []
    for r in sorted(roots):
        if not out or abs(r - out[-1]) > 1e-6:
            out.append(r)
    return out


def multiple_irr_warning(cashflows) -> str | None:
    """Return a warning if IRR is unreliable for this cash-flow shape."""
    n_sign = sign_changes(cashflows)
    roots = all_irrs(cashflows)
    if n_sign > 1 and len(roots) > 1:
        return (f"NON-CONVENTIONAL CASH FLOWS: {n_sign} sign changes and "
                f"{len(roots)} IRRs found ({', '.join(f'{r:.2%}' for r in roots)}). "
                "IRR is ambiguous here — decide on NPV.")
    if n_sign > 1:
        return (f"NON-CONVENTIONAL CASH FLOWS: {n_sign} sign changes, so IRR is "
                "not guaranteed unique. Only one root was found, but prefer NPV.")
    return None


def discounted_payback(rate: float, cashflows) -> float | None:
    """Years until cumulative DISCOUNTED cash flow first turns non-negative.

    Fractional, by linear interpolation within the year it crosses. Discounting
    matters: plain payback treats a dollar in year 5 as a dollar today, which
    flatters long projects. Returns None if it never pays back.
    """
    cf = np.asarray(cashflows, dtype=float)
    disc = cf / (1.0 + rate) ** np.arange(len(cf))
    cum = np.cumsum(disc)
    if cum[-1] < 0:
        return None
    for i, c in enumerate(cum):
        if c >= 0:
            if i == 0:
                return 0.0
            prev = cum[i - 1]
            # prev < 0 <= c, so the crossing sits between i-1 and i.
            return (i - 1) + (-prev / (c - prev))
    return None


def profitability_index(rate: float, cashflows) -> float:
    """PV of future inflows divided by the initial outlay.

    PI > 1 is equivalent to NPV > 0, but it expresses value *per dollar
    invested*, which is what you want when capital is rationed and the projects
    are different sizes.
    """
    cf = np.asarray(cashflows, dtype=float)
    initial = -cf[0]
    if initial <= 0:
        raise ValueError("profitability_index expects a negative cash flow at t=0")
    pv_future = npv(rate, np.concatenate([[0.0], cf[1:]]))
    return pv_future / initial


def summarize(rate: float, cashflows) -> dict:
    """All four measures plus any IRR caveat, in one call."""
    return {
        "npv": npv(rate, cashflows),
        "irr": irr(cashflows),
        "all_irrs": all_irrs(cashflows),
        "discounted_payback": discounted_payback(rate, cashflows),
        "profitability_index": (profitability_index(rate, cashflows)
                                if cashflows[0] < 0 else float("nan")),
        "sign_changes": sign_changes(cashflows),
        "warning": multiple_irr_warning(cashflows),
    }


# ===========================================================================
# PART B — Mutually exclusive projects: incremental analysis
# ===========================================================================
def incremental_analysis(rate: float, small, large, names=("A", "B")) -> dict:
    """Choose between two mutually exclusive projects of different scale.

    The trap: IRR is a *rate*, so it favours small projects. A 60% return on
    $1,000 beats a 25% return on $100,000 by IRR and loses badly by NPV, and you
    can only do one. The resolution is to ask whether the EXTRA money in the
    bigger project earns its keep — i.e. compute the IRR of the difference
    (large - small). If that incremental IRR clears the hurdle rate, the extra
    outlay is worth making.
    """
    n = max(len(small), len(large))
    a = np.pad(np.asarray(small, float), (0, n - len(small)))
    b = np.pad(np.asarray(large, float), (0, n - len(large)))
    delta = b - a

    out = {
        "names": names,
        f"npv_{names[0]}": npv(rate, a), f"npv_{names[1]}": npv(rate, b),
        f"irr_{names[0]}": irr(a), f"irr_{names[1]}": irr(b),
        "incremental_cashflows": delta.tolist(),
        "incremental_irr": irr(delta),
        "incremental_npv": npv(rate, delta),
    }
    inc_irr = out["incremental_irr"]
    out["irr_ranking"] = (names[0] if (out[f"irr_{names[0]}"] or -9)
                          > (out[f"irr_{names[1]}"] or -9) else names[1])
    out["npv_ranking"] = (names[0] if out[f"npv_{names[0]}"]
                          > out[f"npv_{names[1]}"] else names[1])
    out["conflict"] = out["irr_ranking"] != out["npv_ranking"]
    out["choice"] = names[1] if (inc_irr is not None and inc_irr > rate) else names[0]
    out["reason"] = (
        f"incremental IRR {inc_irr:.2%} {'>' if inc_irr and inc_irr > rate else '<='} "
        f"hurdle {rate:.2%}" if inc_irr is not None
        else "incremental cash flows have no IRR; decide on NPV")
    return out


# ===========================================================================
# PART C — A concrete project model (so sensitivity has inputs to vary)
# ===========================================================================
@dataclass
class SolarProject:
    """A rooftop solar installation, modelled from its actual drivers.

    Sensitivity analysis needs a model, not a fixed list of cash flows: you vary
    an *assumption* and watch the cash flows move. Every field here is a number
    somebody guessed, which is exactly what makes it a candidate for the tornado.
    """
    initial_cost: float = 24_000.0      # installed, before incentives
    tax_credit_rate: float = 0.30       # federal ITC, refunded in year 1
    annual_kwh: float = 11_000.0        # first-year production
    price_per_kwh: float = 0.17         # utility rate avoided
    price_escalation: float = 0.025     # utility inflation per year
    degradation: float = 0.005          # panel output lost per year
    annual_maintenance: float = 200.0   # cleaning, inverter reserve
    life_years: int = 25
    salvage_value: float = 0.0
    discount_rate: float = 0.06         # opportunity cost of the capital

    def cashflows(self) -> list[float]:
        cf = [-self.initial_cost]
        for year in range(1, self.life_years + 1):
            kwh = self.annual_kwh * (1 - self.degradation) ** (year - 1)
            price = self.price_per_kwh * (1 + self.price_escalation) ** (year - 1)
            savings = kwh * price - self.annual_maintenance
            if year == 1:
                savings += self.initial_cost * self.tax_credit_rate
            if year == self.life_years:
                savings += self.salvage_value
            cf.append(savings)
        return cf

    def npv(self) -> float:
        return npv(self.discount_rate, self.cashflows())


# ===========================================================================
# PART D — Sensitivity: one-at-a-time tornado
# ===========================================================================
def tornado(project, inputs, pct=0.30, metric=None) -> list[dict]:
    """Vary each input by ±pct, holding all others at base. Sort by influence.

    One-at-a-time is the right first cut precisely because it is simple: it
    answers "which single assumption, if I got it wrong, moves the answer most?"
    It does NOT capture interactions — two inputs that are individually harmless
    can be damaging together — which is what the scenario analysis below starts
    to address.
    """
    metric = metric or (lambda p: p.npv())
    base = metric(project)
    rows = []
    for name in inputs:
        base_val = getattr(project, name)
        lo_p = replace(project, **{name: base_val * (1 - pct)})
        hi_p = replace(project, **{name: base_val * (1 + pct)})
        lo, hi = metric(lo_p), metric(hi_p)
        rows.append({
            "input": name,
            "base_value": base_val,
            "low_value": base_val * (1 - pct),
            "high_value": base_val * (1 + pct),
            "npv_low": lo, "npv_high": hi,
            "swing": abs(hi - lo),
            # Which direction the NPV moves when the input goes UP.
            "direction": "+" if hi >= lo else "-",
        })
    rows.sort(key=lambda r: -r["swing"])
    return {"base_npv": base, "pct": pct, "rows": rows}


def breakeven(project, name, lo=1e-6, hi=10.0, steps=400) -> float | None:
    """The value of `name` at which NPV crosses zero, others held at base.

    A tornado says which assumption matters; this says how wrong it has to be
    before the decision flips, which is the more actionable number.
    """
    base_val = getattr(project, name)
    grid = np.linspace(base_val * lo, base_val * hi, steps) if base_val > 0 \
        else np.linspace(-abs(base_val) * hi, abs(base_val) * hi, steps)
    prev_v, prev_n = None, None
    for v in grid:
        n = replace(project, **{name: float(v)}).npv()
        if prev_n is not None and prev_n * n < 0:
            a, b = prev_v, v
            for _ in range(120):
                mid = (a + b) / 2
                if replace(project, **{name: float(a)}).npv() * \
                   replace(project, **{name: float(mid)}).npv() <= 0:
                    b = mid
                else:
                    a = mid
            return (a + b) / 2
        prev_v, prev_n = v, n
    return None


# ===========================================================================
# PART E — Scenario analysis
# ===========================================================================
def scenario_analysis(project, scenarios: dict) -> dict:
    """Best/base/worst (or any set) with probabilities -> E[NPV] and SD[NPV].

    `scenarios` maps a name to (probability, {field: value, ...}). Unlike the
    tornado, several inputs move together here, which is how the world actually
    behaves: a bad year for solar is low output AND a soft utility rate.
    """
    total_p = sum(p for p, _ in scenarios.values())
    if abs(total_p - 1.0) > 1e-9:
        raise ValueError(f"scenario probabilities must sum to 1, got {total_p}")

    rows = []
    for name, (p, overrides) in scenarios.items():
        variant = replace(project, **overrides)
        v = variant.npv()
        rows.append({"scenario": name, "probability": p, "npv": v,
                     "irr": irr(variant.cashflows()),
                     "overrides": overrides})
    exp = sum(r["probability"] * r["npv"] for r in rows)
    var = sum(r["probability"] * (r["npv"] - exp) ** 2 for r in rows)
    sd = var ** 0.5
    return {
        "rows": rows, "expected_npv": exp, "variance": var, "std_dev": sd,
        # Downside probability is the number people actually ask for.
        "p_negative_npv": sum(r["probability"] for r in rows if r["npv"] < 0),
        "coefficient_of_variation": (sd / exp) if exp else float("inf"),
    }


# ===========================================================================
# PART F — Plots
# ===========================================================================
def plot_tornado(t, outdir=RESULTS, fname="tornado.png", title=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)

    rows = list(reversed(t["rows"]))
    base = t["base_npv"]
    labels = [r["input"].replace("_", " ") for r in rows]
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(10, 0.6 * len(rows) + 2.5))
    for i, r in enumerate(rows):
        lo, hi = sorted((r["npv_low"], r["npv_high"]))
        ax.barh(i, lo - base, left=base, height=0.6, color="0.35")
        ax.barh(i, hi - base, left=base, height=0.6, color="0.72")
    ax.axvline(base, color="black", lw=1.5)
    ax.set_yticks(y); ax.set_yticklabels(labels)
    ax.set_xlabel("NPV ($)")
    ax.set_title(title or f"Tornado: NPV sensitivity to ±{t['pct']:.0%} in each input"
                          f"\n(base NPV = ${base:,.0f}, vertical line)")
    ax.grid(axis="x", alpha=0.3)
    for i, r in enumerate(rows):
        ax.text(max(r["npv_low"], r["npv_high"]), i, f"  ${r['swing']:,.0f}",
                va="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, fname), dpi=130)
    plt.close(fig)


def plot_scenarios(s, outdir=RESULTS, fname="scenarios.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    rows = s["rows"]
    fig, ax = plt.subplots(figsize=(8, 5))
    names = [r["scenario"] for r in rows]
    vals = [r["npv"] for r in rows]
    cols = ["0.35" if v < 0 else "0.65" for v in vals]
    ax.bar(names, vals, color=cols)
    ax.axhline(0, color="black", lw=1)
    ax.axhline(s["expected_npv"], color="red", ls="--", lw=1.5,
               label=f"E[NPV] = ${s['expected_npv']:,.0f}")
    for i, r in enumerate(rows):
        ax.text(i, r["npv"], f"${r['npv']:,.0f}\np={r['probability']:.0%}",
                ha="center", va="bottom" if r["npv"] >= 0 else "top", fontsize=9)
    ax.set_ylabel("NPV ($)")
    ax.set_title(f"Scenario analysis (SD = ${s['std_dev']:,.0f})")
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, fname), dpi=130)
    plt.close(fig)


def plot_npv_profile(cashflows, outdir=RESULTS, fname="npv_profile.png",
                     label="Project", rates=None):
    """NPV as a function of discount rate — where the IRR(s) actually are."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    rates = rates if rates is not None else np.linspace(-0.5, 1.0, 400)
    vals = [npv(r, cashflows) for r in rates]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(rates * 100, vals, color="0.3", lw=1.6)
    ax.axhline(0, color="black", lw=1)
    for r in all_irrs(cashflows):
        if rates[0] <= r <= rates[-1]:
            ax.plot(r * 100, 0, "o", color="red", ms=7)
            ax.annotate(f"IRR = {r:.2%}", (r * 100, 0),
                        textcoords="offset points", xytext=(6, 12), fontsize=9)
    ax.set_xlabel("Discount rate (%)"); ax.set_ylabel("NPV ($)")
    ax.set_title(f"NPV profile — {label}")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, fname), dpi=130)
    plt.close(fig)


# ===========================================================================
# PART G — Worked case study
# ===========================================================================
def case_study():
    os.makedirs(RESULTS, exist_ok=True)
    p = SolarProject()
    cf = p.cashflows()
    s = summarize(p.discount_rate, cf)

    print("=" * 78)
    print("CASE STUDY — 11 kW rooftop solar installation")
    print("=" * 78)
    print(f"  Installed cost           ${p.initial_cost:>12,.0f}")
    print(f"  Federal tax credit        {p.tax_credit_rate:>12.0%}  "
          f"(${p.initial_cost*p.tax_credit_rate:,.0f}, received in year 1)")
    print(f"  First-year production    {p.annual_kwh:>12,.0f} kWh")
    print(f"  Avoided utility rate     ${p.price_per_kwh:>12.3f} /kWh, "
          f"escalating {p.price_escalation:.1%}/yr")
    print(f"  Panel degradation         {p.degradation:>12.1%} /yr")
    print(f"  Maintenance              ${p.annual_maintenance:>12,.0f} /yr")
    print(f"  Life / discount rate     {p.life_years:>12} yr  @ {p.discount_rate:.1%}")

    print("\n--- Core measures " + "-" * 59)
    print(f"  NPV                      ${s['npv']:>12,.2f}")
    print(f"  IRR                       {s['irr']:>12.2%}")
    print(f"  Discounted payback        {s['discounted_payback']:>12.2f} years")
    print(f"  Profitability index       {s['profitability_index']:>12.3f}")
    print(f"  Sign changes              {s['sign_changes']:>12}   "
          f"(1 => IRR is unique)")
    print(f"  Decision: {'ACCEPT' if s['npv'] > 0 else 'REJECT'} "
          f"(NPV {'>' if s['npv'] > 0 else '<'} 0)")

    # --- Non-conventional cash flows: the multiple-IRR trap ----------------
    print("\n--- Edge case: non-conventional cash flows " + "-" * 34)
    # Same panels, but the roof must be replaced in year 12, costing more than
    # that year's savings — an outflow after inflows have started.
    cf_nc = list(cf)
    cf_nc[12] -= 30_000
    w = multiple_irr_warning(cf_nc)
    print(f"  Roof replacement in year 12 (-$30,000):")
    print(f"    sign changes: {sign_changes(cf_nc)}")
    print(f"    IRRs found  : {', '.join(f'{r:.2%}' for r in all_irrs(cf_nc)) or 'none'}")
    print(f"    NPV @ {p.discount_rate:.0%}   : ${npv(p.discount_rate, cf_nc):,.2f}")
    if w:
        print(f"    ! {w}")
    plot_npv_profile(cf_nc, fname="npv_profile_nonconventional.png",
                     label="solar + year-12 roof replacement")

    # --- Mutually exclusive comparison -------------------------------------
    print("\n--- Mutually exclusive: small vs large system " + "-" * 31)
    # A smaller but more efficient array: $1.67 per first-year kWh against the
    # big system's $2.18. That efficiency gives it the higher IRR while its
    # smaller scale gives it the lower NPV — the exact configuration where the
    # two rules disagree, and the reason incremental analysis exists.
    small = replace(p, initial_cost=6_000.0, annual_kwh=3_600.0)
    inc = incremental_analysis(p.discount_rate, small.cashflows(), p.cashflows(),
                               names=("4kW", "11kW"))
    print(f"  4kW : NPV ${inc['npv_4kW']:>10,.0f}   IRR {inc['irr_4kW']:.2%}")
    print(f"  11kW: NPV ${inc['npv_11kW']:>10,.0f}   IRR {inc['irr_11kW']:.2%}")
    print(f"  IRR ranks {inc['irr_ranking']} first; NPV ranks {inc['npv_ranking']} first"
          f"  ->  {'CONFLICT' if inc['conflict'] else 'agreement'}")
    print(f"  Incremental IRR on the extra outlay: {inc['incremental_irr']:.2%}")
    print(f"  Choose {inc['choice']} — {inc['reason']}")

    # --- Tornado ------------------------------------------------------------
    print("\n--- Sensitivity: which assumption matters? " + "-" * 34)
    t = tornado(p, ["initial_cost", "annual_kwh", "price_per_kwh",
                    "price_escalation", "degradation", "annual_maintenance",
                    "discount_rate", "tax_credit_rate"], pct=0.30)
    print(f"  base NPV = ${t['base_npv']:,.0f};  each input varied ±30%")
    print(f"  {'input':<22}{'NPV low':>13}{'NPV high':>13}{'swing':>13}")
    for r in t["rows"]:
        print(f"  {r['input']:<22}{r['npv_low']:>13,.0f}{r['npv_high']:>13,.0f}"
              f"{r['swing']:>13,.0f}")
    plot_tornado(t)

    print("\n  Break-even values (others held at base):")
    for name in ["price_per_kwh", "annual_kwh", "initial_cost"]:
        be = breakeven(p, name)
        base_val = getattr(p, name)
        if be is not None:
            print(f"    {name:<20} NPV = 0 at {be:>10,.3f}  "
                  f"(base {base_val:,.3f}, {be/base_val - 1:+.1%})")
        else:
            print(f"    {name:<20} no break-even in the searched range")

    # --- Scenarios ----------------------------------------------------------
    print("\n--- Scenario analysis " + "-" * 55)
    scen = {
        "worst": (0.25, {"annual_kwh": 9_000.0, "price_escalation": 0.005,
                         "initial_cost": 27_000.0, "annual_maintenance": 350.0}),
        "base":  (0.50, {}),
        "best":  (0.25, {"annual_kwh": 12_500.0, "price_escalation": 0.045,
                         "initial_cost": 22_000.0, "annual_maintenance": 120.0}),
    }
    s2 = scenario_analysis(p, scen)
    for r in s2["rows"]:
        print(f"  {r['scenario']:<7} p={r['probability']:.0%}  "
              f"NPV ${r['npv']:>11,.0f}   IRR {r['irr']:>7.2%}")
    print(f"  {'-'*54}")
    print(f"  Expected NPV            ${s2['expected_npv']:>12,.0f}")
    print(f"  Standard deviation      ${s2['std_dev']:>12,.0f}")
    print(f"  Coefficient of variation {s2['coefficient_of_variation']:>12.3f}")
    print(f"  P(NPV < 0)               {s2['p_negative_npv']:>12.0%}")
    plot_scenarios(s2)
    plot_npv_profile(cf, label="11 kW solar (conventional)")

    print(f"\nCharts written to {RESULTS}")
    return {"summary": s, "incremental": inc, "tornado": t, "scenarios": s2}


if __name__ == "__main__":
    case_study()
