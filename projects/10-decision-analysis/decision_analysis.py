"""
Week 10 — Decision Trees, Value of Information & Utility
========================================================
CivEnv 205, reusing Bayes' Rule from IEMS 302.

Three ideas, each fixing a limitation of the one before:

  1. DECISION TREES + BACKWARD INDUCTION solve sequences of choices under
     uncertainty by folding the future back into the present.

  2. VALUE OF INFORMATION prices research *before* you buy it. EVPI is the most
     a perfect crystal ball could be worth; EVSI is what an imperfect test is
     worth, which needs Bayes' Rule to turn test results into revised beliefs.

  3. UTILITY fixes expected value itself. Maximising EMV says you should be
     indifferent to a coin flip between +$1M and -$1M. Nobody is. Exponential
     utility encodes risk aversion explicitly, which is what explains insurance:
     a risk-averse agent rationally pays MORE than the actuarially fair premium.

Run:
    python decision_analysis.py        # all worked examples
"""
from __future__ import annotations
import os, math
from dataclasses import dataclass, field

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")


# ===========================================================================
# PART A — Utility
# ===========================================================================
def exponential_utility(x, R: float | None):
    """U(x) = 1 - exp(-x/R). R is the RISK TOLERANCE, in dollars.

    Smaller R = more risk averse. R -> infinity is risk neutrality, where the
    utility ranking and the plain money ranking coincide; `R=None` means exactly
    that and returns x unchanged.

    Rule of thumb from the course: R is roughly the largest amount you would
    accept in a 50/50 gamble to win R against losing R/2.
    """
    if R is None or R == float("inf"):
        return x
    return 1.0 - np.exp(-np.asarray(x, dtype=float) / R)


def inverse_exponential_utility(u, R: float | None):
    """U^-1(u) = -R ln(1 - u). Maps a utility back to its dollar equivalent."""
    if R is None or R == float("inf"):
        return u
    u = np.asarray(u, dtype=float)
    if np.any(u >= 1.0):
        raise ValueError("utility must be < 1 for the exponential form")
    return -R * np.log(1.0 - u)


def certainty_equivalent(payoffs, probs, R: float | None) -> float:
    """The guaranteed amount that feels exactly as good as the gamble.

    CE = U^-1(E[U]). For a risk-averse agent (finite R) the CE is always BELOW
    the expected value; the gap is the risk premium — what you would pay to
    swap the gamble for its certain equivalent.
    """
    payoffs = np.asarray(payoffs, dtype=float)
    probs = np.asarray(probs, dtype=float)
    if abs(probs.sum() - 1.0) > 1e-9:
        raise ValueError(f"probabilities must sum to 1, got {probs.sum()}")
    if R is None or R == float("inf"):
        return float(payoffs @ probs)
    eu = float(exponential_utility(payoffs, R) @ probs)
    return float(inverse_exponential_utility(eu, R))


def risk_premium(payoffs, probs, R: float | None) -> float:
    """Expected value minus certainty equivalent: the cost of bearing the risk."""
    ev = float(np.asarray(payoffs, float) @ np.asarray(probs, float))
    return ev - certainty_equivalent(payoffs, probs, R)


# ===========================================================================
# PART B — Decision tree + backward induction
# ===========================================================================
@dataclass
class Terminal:
    """A leaf: the payoff you end up with."""
    payoff: float
    label: str = ""


@dataclass
class Chance:
    """A node where nature moves. branches = [(label, probability, child), ...]"""
    branches: list
    label: str = ""

    def __post_init__(self):
        total = sum(p for _, p, _ in self.branches)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"chance node {self.label!r} probabilities sum to "
                             f"{total}, not 1")


@dataclass
class Decision:
    """A node where YOU move. alternatives = [(label, child), ...]"""
    alternatives: list
    label: str = ""


@dataclass
class Solved:
    """Result of rolling back a node."""
    value: float                 # in utility space if R is finite, else dollars
    money: float                 # certainty equivalent in dollars
    choice: str | None = None    # chosen alternative at a decision node
    label: str = ""
    children: list = field(default_factory=list)


def solve(node, R: float | None = None) -> Solved:
    """Backward induction (rollback).

    Terminal -> its utility.
    Chance   -> the EXPECTATION of its children's utilities (nature averages).
    Decision -> the MAXIMUM over alternatives (you choose).

    Everything is computed in utility space and converted back to dollars via
    the certainty equivalent, so a decision node maximises the CE rather than
    the raw expected payoff. Those differ exactly when the agent is risk averse,
    which is the whole point of running the tree under a utility function.
    """
    if isinstance(node, Terminal):
        u = float(exponential_utility(node.payoff, R))
        return Solved(value=u, money=node.payoff, label=node.label)

    if isinstance(node, Chance):
        kids = [(lbl, p, solve(child, R)) for lbl, p, child in node.branches]
        u = sum(p * k.value for _, p, k in kids)
        money = float(inverse_exponential_utility(u, R)) if R not in (None, float("inf")) else u
        return Solved(value=u, money=money, label=node.label,
                      children=[(lbl, p, k) for lbl, p, k in kids])

    if isinstance(node, Decision):
        kids = [(lbl, solve(child, R)) for lbl, child in node.alternatives]
        best_lbl, best = max(kids, key=lambda kv: kv[1].value)
        return Solved(value=best.value, money=best.money, choice=best_lbl,
                      label=node.label, children=[(lbl, None, k) for lbl, k in kids])

    raise TypeError(f"unknown node type: {type(node)}")


def print_tree(s: Solved, indent=0, prob=None, money_fmt="{:,.2f}"):
    pad = "  " * indent
    p = f" p={prob:.3f}" if prob is not None else ""
    mark = ""
    if s.choice:
        mark = f"  -> CHOOSE {s.choice}"
    print(f"{pad}{s.label or '(node)'}{p}  CE=${money_fmt.format(s.money)}{mark}")
    for item in s.children:
        lbl, pr, kid = item
        kid_label = kid.label or lbl
        kid2 = Solved(kid.value, kid.money, kid.choice, kid_label, kid.children)
        print_tree(kid2, indent + 1, pr, money_fmt)


# ===========================================================================
# PART C — Payoff-table problems, EVPI and EVSI
# ===========================================================================
@dataclass
class DecisionProblem:
    """A decision under uncertainty, as a payoff table plus a prior.

    payoffs[action][state] = money.  prior[state] = P(state).
    This is the form value-of-information questions are naturally posed in, and
    it can be expanded into an explicit tree via `to_tree()`.
    """
    actions: list
    states: list
    payoffs: dict          # {action: {state: payoff}}
    prior: dict            # {state: probability}

    def __post_init__(self):
        tot = sum(self.prior.values())
        if abs(tot - 1.0) > 1e-9:
            raise ValueError(f"prior sums to {tot}, not 1")
        for a in self.actions:
            missing = [s for s in self.states if s not in self.payoffs.get(a, {})]
            if missing:
                raise ValueError(f"action {a!r} missing payoffs for {missing}")

    # ---- no information -------------------------------------------------
    def action_value(self, action, beliefs=None, R=None) -> float:
        """Certainty equivalent of an action under the given beliefs."""
        b = beliefs or self.prior
        pay = [self.payoffs[action][s] for s in self.states]
        pr = [b[s] for s in self.states]
        return certainty_equivalent(pay, pr, R)

    def best_action(self, beliefs=None, R=None):
        vals = {a: self.action_value(a, beliefs, R) for a in self.actions}
        best = max(vals, key=vals.get)
        return best, vals[best], vals

    def emv(self, R=None) -> float:
        """Value of the problem with no extra information."""
        return self.best_action(R=R)[1]

    # ---- perfect information --------------------------------------------
    def ev_with_perfect_information(self, R=None) -> float:
        """Learn the true state BEFORE choosing, then pick the best action.

        Note the order of max and sum: here it is sum_s p(s) * max_a V(a,s),
        whereas EMV is max_a sum_s p(s) * V(a,s). Swapping them is precisely
        what information buys, and the difference can never be negative.
        """
        if R in (None, float("inf")):
            return sum(self.prior[s] * max(self.payoffs[a][s] for a in self.actions)
                       for s in self.states)
        # Under a utility function, average the utilities of the best outcome in
        # each state, then convert back.
        best_pay = [max(self.payoffs[a][s] for a in self.actions) for s in self.states]
        return certainty_equivalent(best_pay, [self.prior[s] for s in self.states], R)

    def evpi(self, R=None) -> float:
        """Expected Value of Perfect Information — the ceiling on any study."""
        return self.ev_with_perfect_information(R) - self.emv(R)

    # ---- imperfect information ------------------------------------------
    def posterior(self, likelihood: dict, signal) -> dict:
        """Bayes' Rule: P(state | signal) from P(signal | state) and the prior.

            P(s | z) = P(z | s) P(s) / sum_s' P(z | s') P(s')

        This is the IEMS 302 machinery doing real work: a test result is not an
        answer, it is evidence that shifts a belief by an amount that depends on
        both the test's accuracy and how likely the state was to begin with.
        """
        num = {s: likelihood[s][signal] * self.prior[s] for s in self.states}
        denom = sum(num.values())
        if denom <= 0:
            raise ValueError(f"signal {signal!r} has probability 0 under the prior")
        return {s: num[s] / denom for s in self.states}

    def signal_probability(self, likelihood: dict, signal) -> float:
        return sum(likelihood[s][signal] * self.prior[s] for s in self.states)

    def ev_with_sample_information(self, likelihood: dict, signals, R=None) -> float:
        """Run the test, update beliefs, then choose — averaged over results."""
        total_u, parts = 0.0, []
        for z in signals:
            pz = self.signal_probability(likelihood, z)
            if pz <= 0:
                continue
            post = self.posterior(likelihood, z)
            a, v, _ = self.best_action(beliefs=post, R=R)
            parts.append((z, pz, a, v))
            total_u += pz * float(exponential_utility(v, R))
        val = (float(inverse_exponential_utility(total_u, R))
               if R not in (None, float("inf")) else total_u)
        return val, parts

    def evsi(self, likelihood: dict, signals, R=None):
        """Expected Value of Sample Information for an imperfect test."""
        evwsi, parts = self.ev_with_sample_information(likelihood, signals, R)
        return evwsi - self.emv(R), parts

    def efficiency(self, likelihood: dict, signals, R=None) -> float:
        """EVSI / EVPI — how much of a perfect test's value this one delivers."""
        e_pi = self.evpi(R)
        if e_pi <= 0:
            return float("nan")
        return self.evsi(likelihood, signals, R)[0] / e_pi

    # ---- expansion into an explicit tree --------------------------------
    def to_tree(self) -> Decision:
        return Decision(
            label="choose action",
            alternatives=[
                (a, Chance(label=f"state | {a}",
                           branches=[(s, self.prior[s],
                                      Terminal(self.payoffs[a][s], f"{a} & {s}"))
                                     for s in self.states]))
                for a in self.actions])


# ===========================================================================
# PART D — Insurance pricing
# ===========================================================================
def actuarially_fair_premium(losses, probs) -> float:
    """The expected loss. An insurer charging exactly this breaks even."""
    return float(np.asarray(losses, float) @ np.asarray(probs, float))


def max_premium(wealth: float, losses, probs, R: float | None) -> float:
    """The most a risk-averse agent would pay to insure the loss away.

    Solve  U(wealth - premium) = E[U(wealth - loss)]  for the premium. Since the
    right-hand side is the expected utility of going uninsured, the premium that
    makes the agent indifferent is

        premium = wealth - CE(uninsured wealth)

    For a risk-averse agent this EXCEEDS the fair premium, and the excess is the
    risk premium. That gap is why insurance markets exist: the insurer, holding
    many independent risks, is effectively risk neutral and values the same
    contract at the fair premium.
    """
    final_wealth = [wealth - L for L in losses]
    ce = certainty_equivalent(final_wealth, probs, R)
    return wealth - ce


# ===========================================================================
# PART E — Worked examples
# ===========================================================================
def example_drilling():
    """The canonical value-of-information problem, with a seismic test."""
    print("=" * 78)
    print("EXAMPLE 1 — Wildcat drilling, with and without a seismic survey")
    print("=" * 78)

    prob = DecisionProblem(
        actions=["drill", "sell lease"],
        states=["dry", "wet", "soaking"],
        payoffs={
            "drill":      {"dry": -700_000, "wet": 500_000, "soaking": 1_400_000},
            "sell lease": {"dry": 90_000, "wet": 90_000, "soaking": 90_000},
        },
        # Chosen so drilling wins on expected value (EMV $185k vs $90k) while
        # still carrying a 45% chance of losing $700k. That combination is what
        # makes the utility analysis in Example 2 interesting: risk aversion has
        # to overturn a genuine EMV advantage, not merely confirm a decision
        # expected value had already made.
        prior={"dry": 0.45, "wet": 0.30, "soaking": 0.25},
    )

    best, val, vals = prob.best_action()
    print("  Payoffs by action and state:")
    for a in prob.actions:
        print(f"    {a:<11} " + "  ".join(
            f"{s}: ${prob.payoffs[a][s]:>10,.0f}" for s in prob.states))
    print(f"  Prior: " + ", ".join(f"P({s})={prob.prior[s]:.2f}" for s in prob.states))
    print("\n  Expected value of each action (no information):")
    for a, v in vals.items():
        print(f"    {a:<11} ${v:>12,.0f}")
    print(f"  EMV-optimal: {best}  (${val:,.0f})")

    print("\n  --- Backward induction on the explicit tree ---")
    print_tree(solve(prob.to_tree()))

    evwpi = prob.ev_with_perfect_information()
    print(f"\n  With PERFECT information: ${evwpi:,.0f}")
    print("    (know the state first, then choose: "
          + ", ".join(f"{s} -> {max(prob.actions, key=lambda a: prob.payoffs[a][s])}"
                      for s in prob.states) + ")")
    print(f"  EVPI = ${prob.evpi():,.0f}"
          f"   <- the most any study could possibly be worth")

    # An imperfect seismic test: 'closed' structure suggests oil, 'open' does not.
    likelihood = {
        "dry":     {"closed": 0.20, "open": 0.80},
        "wet":     {"closed": 0.70, "open": 0.30},
        "soaking": {"closed": 0.90, "open": 0.10},
    }
    signals = ["closed", "open"]
    print("\n  Seismic test reliability  P(reading | state):")
    for s in prob.states:
        print(f"    {s:<8} " + "  ".join(f"P({z}|{s})={likelihood[s][z]:.2f}"
                                         for z in signals))

    evsi, parts = prob.evsi(likelihood, signals)
    print("\n  Posterior beliefs and the resulting choice:")
    for z, pz, a, v in parts:
        post = prob.posterior(likelihood, z)
        print(f"    reading '{z}' (p={pz:.3f}) -> "
              + ", ".join(f"P({s})={post[s]:.3f}" for s in prob.states)
              + f"  => {a} (${v:,.0f})")
    print(f"\n  EVSI = ${evsi:,.0f}")
    print(f"  Efficiency = EVSI/EVPI = {prob.efficiency(likelihood, signals):.1%}")
    print(f"  -> pay at most ${evsi:,.0f} for this survey; "
          f"${prob.evpi():,.0f} for a perfect one.")
    return prob, likelihood, signals


def example_utility(prob):
    """The same problem, seen by agents with different risk tolerance."""
    print("\n" + "=" * 78)
    print("EXAMPLE 2 — Risk aversion changes the decision")
    print("=" * 78)
    print("  U(x) = 1 - exp(-x/R);  smaller R = more risk averse\n")
    print(f"  {'R (risk tolerance)':>22} {'CE drill':>14} {'CE sell':>12} {'choice':>10}")
    rows = []
    for R in [None, 5_000_000, 2_000_000, 1_000_000, 500_000, 250_000]:
        v_drill = prob.action_value("drill", R=R)
        v_sell = prob.action_value("sell lease", R=R)
        best, _, _ = prob.best_action(R=R)
        label = "infinite (risk neutral)" if R is None else f"${R:,.0f}"
        print(f"  {label:>22} ${v_drill:>13,.0f} ${v_sell:>11,.0f} {best:>10}")
        rows.append((R, v_drill, v_sell, best))

    print("\n  The switch point is where the certainty equivalent of drilling")
    print("  falls below the $90,000 the lease is worth for sure. A risk-neutral")
    print("  agent drills; a sufficiently risk-averse one sells, even though the")
    print("  expected DOLLARS never change.")

    pay = [prob.payoffs["drill"][s] for s in prob.states]
    pr = [prob.prior[s] for s in prob.states]
    for R in [None, 1_000_000, 250_000]:
        ce = certainty_equivalent(pay, pr, R)
        rp = risk_premium(pay, pr, R)
        label = "risk neutral" if R is None else f"R=${R:,.0f}"
        print(f"    {label:<16} CE=${ce:>10,.0f}   risk premium=${rp:>10,.0f}")
    return rows


def example_insurance():
    """Why a rational agent pays more than the fair premium."""
    print("\n" + "=" * 78)
    print("EXAMPLE 3 — Pricing insurance against a rare, large loss")
    print("=" * 78)
    wealth = 250_000.0
    losses = [0.0, 200_000.0]
    probs = [0.98, 0.02]

    fair = actuarially_fair_premium(losses, probs)
    print(f"  Wealth ${wealth:,.0f}; 2% chance of a ${losses[1]:,.0f} loss")
    print(f"  Actuarially fair premium (= expected loss): ${fair:,.2f}\n")
    print(f"  {'risk tolerance R':>20} {'max premium':>14} {'markup over fair':>18}")
    rows = []
    for R in [None, 2_000_000, 1_000_000, 500_000, 200_000, 100_000, 50_000]:
        mp = max_premium(wealth, losses, probs, R)
        label = "infinite" if R is None else f"${R:,.0f}"
        print(f"  {label:>20} ${mp:>13,.2f} {mp - fair:>17,.2f}")
        rows.append((R, mp))
    print("\n  A risk-neutral agent pays exactly the fair premium and not a cent")
    print("  more. Every risk-averse agent pays a markup, and the markup grows as")
    print("  risk tolerance falls. The insurer, holding thousands of independent")
    print("  policies, is effectively risk neutral — it values the contract at the")
    print("  fair premium. That gap between the two valuations is the entire")
    print("  reason the trade happens, and both sides gain from it.")
    return fair, rows


def example_internship():
    """A real decision: take the early offer, or wait for the other interviews?"""
    print("\n" + "=" * 78)
    print("EXAMPLE 4 — Accept the early internship offer, or wait?")
    print("=" * 78)

    # Payoffs are a subjective value score for the summer, in "$ equivalent"
    # terms: what the outcome is worth relative to having no internship.
    prob = DecisionProblem(
        actions=["accept early offer", "decline and interview"],
        states=["top offer arrives", "comparable offer", "nothing arrives"],
        payoffs={
            "accept early offer":    {"top offer arrives": 12_000,
                                      "comparable offer": 12_000,
                                      "nothing arrives": 12_000},
            "decline and interview": {"top offer arrives": 30_000,
                                      "comparable offer": 13_000,
                                      "nothing arrives": 0},
        },
        # Declining is worth more in expectation ($14,200 vs $12,000) but carries
        # a 30% chance of no internship at all. That is the real shape of the
        # decision, and the reason expected value alone gives students advice
        # most of them correctly refuse to take.
        prior={"top offer arrives": 0.30, "comparable offer": 0.40,
               "nothing arrives": 0.30},
    )
    best, val, vals = prob.best_action()
    print("  The early offer is worth 12,000 whatever happens (it is certain).")
    print("  Declining exposes you to the market:")
    for s in prob.states:
        print(f"    {s:<20} p={prob.prior[s]:.2f}  "
              f"-> ${prob.payoffs['decline and interview'][s]:,.0f}")
    print("\n  Risk-neutral expected values:")
    for a, v in vals.items():
        print(f"    {a:<24} ${v:>10,.0f}")
    print(f"  EMV-optimal: {best}")

    print(f"\n  EVPI = ${prob.evpi():,.0f}  <- what it would be worth to know the")
    print("         outcome of the other interviews before deciding.")

    print("\n  Under risk aversion:")
    print(f"  {'R':>16} {'CE accept':>12} {'CE decline':>12} {'choice':>26}")
    for R in [None, 100_000, 50_000, 25_000, 15_000, 10_000]:
        va = prob.action_value("accept early offer", R=R)
        vd = prob.action_value("decline and interview", R=R)
        b, _, _ = prob.best_action(R=R)
        label = "risk neutral" if R is None else f"${R:,.0f}"
        print(f"  {label:>16} ${va:>11,.0f} ${vd:>11,.0f} {b:>26}")
    print("\n  Expected value says decline. Every risk-averse agent below the")
    print("  switch point says accept — and they are not being irrational. A")
    print("  student with no fallback is exactly the agent whose risk tolerance")
    print("  is small relative to the stake, which is precisely when the certain")
    print("  offer dominates. EMV is the wrong rule for a decision you make once.")
    return prob


def plot_all(prob, outdir=RESULTS):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)

    # 1. Certainty equivalent vs risk tolerance
    Rs = np.logspace(np.log10(100_000), np.log10(20_000_000), 60)
    ce_drill = [prob.action_value("drill", R=float(R)) for R in Rs]
    ce_sell = [prob.action_value("sell lease", R=float(R)) for R in Rs]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.semilogx(Rs, ce_drill, color="0.25", lw=2, label="drill")
    ax.semilogx(Rs, ce_sell, color="0.6", lw=2, ls="--", label="sell lease")
    ev = sum(prob.prior[s] * prob.payoffs["drill"][s] for s in prob.states)
    ax.axhline(ev, color="red", lw=1, ls=":", label=f"EMV of drilling = ${ev:,.0f}")
    cross = None
    for i in range(len(Rs) - 1):
        if (ce_drill[i] - ce_sell[i]) * (ce_drill[i + 1] - ce_sell[i + 1]) < 0:
            cross = Rs[i]
    if cross:
        ax.axvline(cross, color="black", lw=1, alpha=0.5)
        ax.annotate(f"switch at R≈${cross:,.0f}", (cross, ev * 0.2),
                    fontsize=9, rotation=90, va="bottom")
    ax.set_xlabel("Risk tolerance R ($, log scale)")
    ax.set_ylabel("Certainty equivalent ($)")
    ax.set_title("Risk aversion flips the decision, though the dollars never change")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "risk_tolerance.png"), dpi=130)
    plt.close(fig)

    # 2. Insurance premium vs risk tolerance
    wealth, losses, probs_ = 250_000.0, [0.0, 200_000.0], [0.98, 0.02]
    fair = actuarially_fair_premium(losses, probs_)
    Rs2 = np.logspace(np.log10(30_000), np.log10(10_000_000), 60)
    prem = [max_premium(wealth, losses, probs_, float(R)) for R in Rs2]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.semilogx(Rs2, prem, color="0.25", lw=2, label="max premium a buyer would pay")
    ax.axhline(fair, color="red", ls="--", lw=1.5,
               label=f"actuarially fair = ${fair:,.0f}")
    ax.fill_between(Rs2, fair, prem, color="0.8", alpha=0.6,
                    label="risk premium (the zone where trade happens)")
    ax.set_xlabel("Risk tolerance R ($, log scale)")
    ax.set_ylabel("Premium ($)")
    ax.set_title("Why insurance exists: buyers value the contract above its fair price")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "insurance.png"), dpi=130)
    plt.close(fig)

    # 3. EVPI / EVSI comparison
    likelihood = {
        "dry":     {"closed": 0.20, "open": 0.80},
        "wet":     {"closed": 0.70, "open": 0.30},
        "soaking": {"closed": 0.90, "open": 0.10},
    }
    evsi, _ = prob.evsi(likelihood, ["closed", "open"])
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ["No information\n(EMV)", "Imperfect test\n(EVSI)", "Perfect info\n(EVPI)"]
    base = prob.emv()
    vals = [base, base + evsi, base + prob.evpi()]
    ax.bar(bars, vals, color=["0.6", "0.42", "0.25"])
    ax.axhline(base, color="red", ls=":", lw=1)
    for i, v in enumerate(vals):
        ax.text(i, v, f"${v:,.0f}" + ("" if i == 0 else f"\n(+${v-base:,.0f})"),
                ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Expected value ($)")
    ax.set_ylim(0, max(vals) * 1.25)
    ax.set_title("What information is worth")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "value_of_information.png"), dpi=130)
    plt.close(fig)


def main():
    os.makedirs(RESULTS, exist_ok=True)
    prob, likelihood, signals = example_drilling()
    example_utility(prob)
    example_insurance()
    example_internship()
    plot_all(prob)
    print(f"\nCharts written to {RESULTS}")


if __name__ == "__main__":
    main()
