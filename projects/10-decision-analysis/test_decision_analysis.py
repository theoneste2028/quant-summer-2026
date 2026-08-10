"""
Week 10 — Test suite for the decision analysis engine
=====================================================
Decision analysis is unusually easy to get subtly wrong: swap a max and a sum
and EVPI comes out plausible but incorrect; apply utility after averaging
instead of before and risk aversion silently vanishes. So the tests here lean on
two things a bug cannot fake — values worked out on paper, and structural
theorems that must hold for *any* problem (EVPI >= 0, EVSI <= EVPI, a perfect
test being worth exactly EVPI, an uninformative one worth nothing).

Run:
    python test_decision_analysis.py
"""
from __future__ import annotations
import os, sys, math

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decision_analysis import (                        # noqa: E402
    exponential_utility, inverse_exponential_utility, certainty_equivalent,
    risk_premium, Terminal, Chance, Decision, solve, DecisionProblem,
    actuarially_fair_premium, max_premium)

PASS, FAIL = [], []


def check(name, got, want, tol=1e-6):
    if isinstance(want, (int, float)) and isinstance(got, (int, float)):
        ok = abs(got - want) <= tol
    else:
        ok = got == want
    (PASS if ok else FAIL).append(name)
    g = f"{got:,.4f}" if isinstance(got, float) else repr(got)
    w = f"{want:,.4f}" if isinstance(want, float) else repr(want)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {g}, want {w}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


def drilling():
    return DecisionProblem(
        actions=["drill", "sell lease"],
        states=["dry", "wet", "soaking"],
        payoffs={"drill": {"dry": -700_000, "wet": 500_000, "soaking": 1_400_000},
                 "sell lease": {"dry": 90_000, "wet": 90_000, "soaking": 90_000}},
        prior={"dry": 0.45, "wet": 0.30, "soaking": 0.25})


SEISMIC = {"dry":     {"closed": 0.20, "open": 0.80},
           "wet":     {"closed": 0.70, "open": 0.30},
           "soaking": {"closed": 0.90, "open": 0.10}}


# ---------------------------------------------------------------------------
def test_utility():
    print("\n--- Exponential utility " + "-" * 52)
    R = 100_000.0
    check("U(0) = 0", float(exponential_utility(0.0, R)), 0.0)
    check("U(x) = 1 - exp(-x/R)", float(exponential_utility(50_000.0, R)),
          1 - math.exp(-0.5))
    check("risk neutral returns x unchanged",
          float(exponential_utility(1234.0, None)), 1234.0)
    check("U is invertible",
          float(inverse_exponential_utility(exponential_utility(37_000.0, R), R)),
          37_000.0, tol=1e-6)
    check_true("U is strictly increasing",
               exponential_utility(10.0, R) < exponential_utility(20.0, R))
    check_true("U is concave (risk aversion)",
               exponential_utility(20_000.0, R) - exponential_utility(10_000.0, R)
               > exponential_utility(30_000.0, R) - exponential_utility(20_000.0, R))

    raised = False
    try:
        inverse_exponential_utility(1.5, R)
    except ValueError:
        raised = True
    check_true("inverse rejects utility >= 1", raised)


def test_certainty_equivalent():
    print("\n--- Certainty equivalents & risk premium " + "-" * 35)
    pay, pr = [0.0, 100_000.0], [0.5, 0.5]
    check("risk-neutral CE equals the expected value",
          certainty_equivalent(pay, pr, None), 50_000.0)
    check_true("risk-averse CE is below the expected value",
               certainty_equivalent(pay, pr, 100_000.0) < 50_000.0,
               f"{certainty_equivalent(pay, pr, 100_000.0):,.0f}")
    check_true("more risk aversion lowers the CE further",
               certainty_equivalent(pay, pr, 50_000.0)
               < certainty_equivalent(pay, pr, 200_000.0))
    check("a certain payoff is its own CE",
          certainty_equivalent([777.0], [1.0], 50_000.0), 777.0, tol=1e-6)
    check("risk premium is zero when risk neutral",
          risk_premium(pay, pr, None), 0.0)
    check_true("risk premium is positive when risk averse",
               risk_premium(pay, pr, 100_000.0) > 0)
    # CE -> EV as R -> infinity.
    check("CE approaches EV for very large R",
          certainty_equivalent(pay, pr, 1e12), 50_000.0, tol=1.0)

    raised = False
    try:
        certainty_equivalent([1, 2], [0.5, 0.4], None)
    except ValueError:
        raised = True
    check_true("probabilities must sum to 1", raised)


def test_backward_induction():
    print("\n--- Backward induction " + "-" * 53)
    # A hand-solvable tree:
    #   decide A -> chance: 0.5 -> 100, 0.5 -> 0        => EV 50
    #   decide B -> certain 60                          => EV 60   (B wins)
    tree = Decision(label="root", alternatives=[
        ("A", Chance(label="coin", branches=[("h", 0.5, Terminal(100.0)),
                                             ("t", 0.5, Terminal(0.0))])),
        ("B", Terminal(60.0, "certain")),
    ])
    s = solve(tree)
    check("root value is the better alternative", s.money, 60.0)
    check("the better alternative is chosen", s.choice, "B")

    # Flip the certain amount below the gamble's EV and the choice must flip.
    tree2 = Decision(alternatives=[
        ("A", Chance(branches=[("h", 0.5, Terminal(100.0)), ("t", 0.5, Terminal(0.0))])),
        ("B", Terminal(40.0)),
    ])
    check("choice flips when the certain amount drops", solve(tree2).choice, "A")
    check("value is the gamble's EV", solve(tree2).money, 50.0)

    # Under enough risk aversion, the certain 40 beats the 50/50 gamble.
    s3 = solve(tree2, R=50.0)
    check("risk aversion flips the tree's choice", s3.choice, "B")

    # Nested chance nodes must compose.
    nested = Chance(branches=[
        ("x", 0.5, Chance(branches=[("a", 0.5, Terminal(100.0)),
                                    ("b", 0.5, Terminal(0.0))])),
        ("y", 0.5, Terminal(20.0))])
    check("nested chance nodes compose", solve(nested).money, 0.5 * 50 + 0.5 * 20)

    raised = False
    try:
        Chance(branches=[("a", 0.5, Terminal(1.0)), ("b", 0.4, Terminal(2.0))])
    except ValueError:
        raised = True
    check_true("chance probabilities must sum to 1", raised)


def test_emv_and_evpi():
    print("\n--- EMV and EVPI " + "-" * 59)
    p = drilling()
    # EMV(drill) = .45(-700k) + .30(500k) + .25(1400k) = -315k + 150k + 350k
    check("EMV of drilling", p.action_value("drill"), 185_000.0)
    check("EMV of selling", p.action_value("sell lease"), 90_000.0)
    check("problem EMV takes the better action", p.emv(), 185_000.0)
    check("best action is drill", p.best_action()[0], "drill")

    # EVwPI = .45 x max(-700k,90k) + .30 x max(500k,90k) + .25 x max(1400k,90k)
    #       = .45(90k) + .30(500k) + .25(1400k) = 40.5k + 150k + 350k
    check("EV with perfect information", p.ev_with_perfect_information(), 540_500.0)
    check("EVPI = EVwPI - EMV", p.evpi(), 355_500.0)
    check_true("EVPI is never negative", p.evpi() >= 0)

    # A dominated problem: one action is best in every state, so knowing the
    # state cannot change what you do, and information is worthless.
    dom = DecisionProblem(
        actions=["good", "bad"], states=["s1", "s2"],
        payoffs={"good": {"s1": 100, "s2": 200}, "bad": {"s1": 10, "s2": 20}},
        prior={"s1": 0.5, "s2": 0.5})
    check("EVPI is zero when one action dominates", dom.evpi(), 0.0)

    raised = False
    try:
        DecisionProblem(actions=["a"], states=["s"], payoffs={"a": {"s": 1}},
                        prior={"s": 0.9})
    except ValueError:
        raised = True
    check_true("prior must sum to 1", raised)

    raised = False
    try:
        DecisionProblem(actions=["a"], states=["s1", "s2"],
                        payoffs={"a": {"s1": 1}}, prior={"s1": 0.5, "s2": 0.5})
    except ValueError:
        raised = True
    check_true("missing payoffs are rejected", raised)


def test_bayes_and_evsi():
    print("\n--- Bayes' Rule and EVSI " + "-" * 51)
    p = drilling()
    # P(closed) = .45(.20) + .30(.70) + .25(.90) = .09 + .21 + .225 = .525
    check("P(closed)", p.signal_probability(SEISMIC, "closed"), 0.525)
    post = p.posterior(SEISMIC, "closed")
    check("P(dry | closed) = .09/.525", post["dry"], 0.09 / 0.525)
    check("P(wet | closed) = .21/.525", post["wet"], 0.21 / 0.525)
    check("P(soaking | closed) = .225/.525", post["soaking"], 0.225 / 0.525)
    check("posterior sums to 1", sum(post.values()), 1.0)
    check_true("a 'closed' reading raises P(soaking) above the prior",
               post["soaking"] > p.prior["soaking"])
    check_true("a 'closed' reading lowers P(dry) below the prior",
               post["dry"] < p.prior["dry"])

    # Signal probabilities must themselves form a distribution.
    check("signal probabilities sum to 1",
          sum(p.signal_probability(SEISMIC, z) for z in ("closed", "open")), 1.0)

    evsi, parts = p.evsi(SEISMIC, ["closed", "open"])
    check_true("EVSI is positive for an informative test", evsi > 0, f"{evsi:,.0f}")
    check_true("EVSI never exceeds EVPI", evsi <= p.evpi() + 1e-9,
               f"EVSI={evsi:,.0f} EVPI={p.evpi():,.0f}")
    check_true("efficiency lies in [0, 1]",
               0 <= p.efficiency(SEISMIC, ["closed", "open"]) <= 1)

    # A PERFECT test must be worth exactly EVPI.
    perfect = {s: {z: (1.0 if z == s else 0.0) for z in p.states} for s in p.states}
    evsi_perfect, _ = p.evsi(perfect, p.states)
    check("a perfect test is worth exactly EVPI", evsi_perfect, p.evpi(), tol=1e-6)

    # An UNINFORMATIVE test (same likelihood in every state) is worth nothing,
    # because the posterior equals the prior.
    useless = {s: {"a": 0.5, "b": 0.5} for s in p.states}
    evsi_useless, _ = p.evsi(useless, ["a", "b"])
    check("an uninformative test is worth zero", evsi_useless, 0.0, tol=1e-6)
    post_useless = p.posterior(useless, "a")
    check_true("uninformative posterior equals the prior",
               all(abs(post_useless[s] - p.prior[s]) < 1e-12 for s in p.states))

    raised = False
    try:
        p.posterior({s: {"z": 0.0} for s in p.states}, "z")
    except ValueError:
        raised = True
    check_true("an impossible signal is rejected", raised)


def test_utility_changes_decision():
    print("\n--- Risk aversion changes the chosen action " + "-" * 32)
    p = drilling()
    check("risk-neutral agent drills", p.best_action(R=None)[0], "drill")
    check_true("a sufficiently risk-averse agent sells",
               p.best_action(R=1_000_000)[0] == "sell lease")
    # The certain action's CE must be exactly its payoff at any R.
    check("a certain action's CE is risk-independent",
          p.action_value("sell lease", R=50_000), 90_000.0, tol=1e-6)
    # Drilling's CE must fall monotonically as risk tolerance falls.
    ces = [p.action_value("drill", R=r) for r in
           [1e12, 5_000_000, 2_000_000, 1_000_000, 500_000]]
    check_true("CE of the risky action falls as R falls",
               all(ces[i] > ces[i + 1] for i in range(len(ces) - 1)),
               str([f"{c:,.0f}" for c in ces]))
    check("CE at huge R matches the EMV", ces[0], 185_000.0, tol=100.0)


def test_insurance():
    print("\n--- Insurance pricing " + "-" * 54)
    wealth, losses, probs = 250_000.0, [0.0, 200_000.0], [0.98, 0.02]
    fair = actuarially_fair_premium(losses, probs)
    check("fair premium equals the expected loss", fair, 4_000.0)
    check("risk-neutral buyer pays exactly the fair premium",
          max_premium(wealth, losses, probs, None), 4_000.0, tol=1e-6)

    mp = max_premium(wealth, losses, probs, 100_000.0)
    check_true("risk-averse buyer pays above fair", mp > fair, f"{mp:,.2f}")

    # The markup must grow as risk tolerance falls.
    prem = [max_premium(wealth, losses, probs, r)
            for r in [2_000_000, 1_000_000, 500_000, 200_000, 100_000]]
    check_true("premium rises monotonically as R falls",
               all(prem[i] < prem[i + 1] for i in range(len(prem) - 1)),
               str([f"{x:,.0f}" for x in prem]))
    check_true("the premium never exceeds the maximum possible loss",
               all(x <= 200_000 for x in prem))

    # Cross-check against the definition: U(wealth - premium) == E[U(wealth-loss)]
    R = 100_000.0
    lhs = float(exponential_utility(wealth - mp, R))
    rhs = sum(pr * float(exponential_utility(wealth - L, R))
              for L, pr in zip(losses, probs))
    check("premium satisfies the indifference equation", lhs, rhs, tol=1e-9)

    # No loss possible -> nobody pays anything.
    check("zero risk means zero premium",
          max_premium(wealth, [0.0], [1.0], 100_000.0), 0.0, tol=1e-6)


def test_tree_matches_table():
    print("\n--- The explicit tree agrees with the payoff table " + "-" * 25)
    p = drilling()
    s = solve(p.to_tree())
    check("tree rollback reproduces the EMV", s.money, p.emv(), tol=1e-6)
    check("tree picks the same action", s.choice, p.best_action()[0])
    for R in [2_000_000, 1_000_000, 250_000]:
        sr = solve(p.to_tree(), R=R)
        check(f"tree and table agree at R={R:,}", sr.money, p.emv(R=R), tol=1e-3)
        check(f"tree and table choose alike at R={R:,}", sr.choice, p.best_action(R=R)[0])


def main():
    print("=" * 78)
    print("Week 10 decision analysis test suite")
    print("=" * 78)
    test_utility()
    test_certainty_equivalent()
    test_backward_induction()
    test_emv_and_evpi()
    test_bayes_and_evsi()
    test_utility_changes_decision()
    test_insurance()
    test_tree_matches_table()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
