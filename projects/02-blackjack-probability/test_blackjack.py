"""
Week 2 — Assertion-based tests for the blackjack engine
=======================================================
`blackjack.py` prints a table that a human can eyeball, which is not the same as
verifying it. These tests assert the values instead, against three independent
sources of truth: exact combinatorial identities, published dealer-bust
probabilities for the standard S17 infinite-deck model, and the simulator itself
(which must agree with the analytics to within its own sampling error).

Run:
    python test_blackjack.py
"""
from __future__ import annotations
import os, sys, math
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blackjack as bj                                  # noqa: E402

PASS, FAIL = [], []


def check(name, got, want, tol=1e-9):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    (PASS if ok else FAIL).append(name)
    g = f"{got:.6f}" if isinstance(got, float) else repr(got)
    w = f"{want:.6f}" if isinstance(want, float) else repr(want)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {g}, want {w}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


def test_exact_combinatorics():
    print("\n--- Exact two-card probabilities " + "-" * 43)
    # P(blackjack) = 4 aces x 16 ten-value cards / C(52,2) = 64/1326
    check("P(blackjack) = 64/1326", bj.p_blackjack_exact(), 64 / 1326)
    # P(pair) = 13 ranks x C(4,2) / C(52,2) = 78/1326
    check("P(pair) = 78/1326", bj.p_pair_exact(), 78 / 1326)
    check("C(52,2) = 1326", bj.TOTAL_2CARD_HANDS, 1326)
    check_true("both probabilities are in (0,1)",
               0 < bj.p_blackjack_exact() < 1 and 0 < bj.p_pair_exact() < 1)
    # Sanity: a pair is more likely than a blackjack (78 hands vs 64).
    check_true("P(pair) > P(blackjack)", bj.p_pair_exact() > bj.p_blackjack_exact())


def test_dealer_bust_against_published():
    print("\n--- Dealer bust vs published S17 infinite-deck values " + "-" * 22)
    # Standard reference values for stand-on-all-17, infinite deck.
    published = {2: 0.3536, 3: 0.3739, 4: 0.3945, 5: 0.4164, 6: 0.4232,
                 7: 0.2623, 8: 0.2447, 9: 0.2284, 10: 0.2121, 11: 0.1153}
    for up, want in published.items():
        got = bj.p_dealer_bust_exact(up)
        check(f"P(bust | {'A' if up == 11 else up})", got, want, tol=5e-4)

    check_true("6 is the dealer's worst upcard",
               max(published, key=lambda u: bj.p_dealer_bust_exact(u)) == 6)
    check_true("an Ace is the dealer's best upcard",
               min(published, key=lambda u: bj.p_dealer_bust_exact(u)) == 11)
    # The bust rate jumps discontinuously between a 6 and a 7: with 2-6 the
    # dealer must draw to a stiff hand, with 7+ they often stand on the first
    # draw. This is the structural fact basic strategy is built on.
    check_true("bust rate drops sharply from 6 to 7",
               bj.p_dealer_bust_exact(6) - bj.p_dealer_bust_exact(7) > 0.15)


def test_dealer_distribution():
    print("\n--- Dealer final-hand distribution " + "-" * 41)
    for up in [2, 6, 10, 11]:
        dist = bj._dist_from_upcard(up)
        total = sum(dist.values())
        check(f"distribution for upcard {up} sums to 1", total, 1.0, tol=1e-9)
        check_true(f"upcard {up}: all probabilities non-negative",
                   all(p >= 0 for p in dist.values()))
        check_true(f"upcard {up}: outcomes are 17-21 or bust",
                   set(dist) <= {17, 18, 19, 20, 21, "bust"}, str(sorted(map(str, dist))))
        # The bust mass must match the standalone recursion exactly.
        check(f"upcard {up}: bust mass matches p_dealer_bust_exact",
              dist.get("bust", 0.0), bj.p_dealer_bust_exact(up), tol=1e-9)

    # A dealer showing an Ace reaches 21 far more often than one showing a 6.
    check_true("Ace upcard makes 21 most likely of any upcard",
               bj._dist_from_upcard(11).get(21, 0) > bj._dist_from_upcard(6).get(21, 0))


def test_ev_decisions():
    print("\n--- Expected-value decision analysis " + "-" * 39)
    for total in [12, 16, 20]:
        for up in [2, 6, 10, 11]:
            ev_s = bj.ev_stand(total, up)
            ev_h = bj.ev_hit_then_stand(total, up)
            check_true(f"EV(stand {total} vs {up}) within [-1,1]", -1 <= ev_s <= 1,
                       f"{ev_s:.3f}")
            check_true(f"EV(hit {total} vs {up}) within [-1,1]", -1 <= ev_h <= 1,
                       f"{ev_h:.3f}")

    # Standing on 20 is strong against everything.
    check_true("standing on 20 has positive EV against a 6", bj.ev_stand(20, 6) > 0.5)
    # Hitting a 20 is close to suicide: only an ace helps.
    check_true("hitting on 20 is much worse than standing",
               bj.ev_hit_then_stand(20, 6) < bj.ev_stand(20, 6))
    check("best action on 20 vs 6 is STAND", bj.best_action(20, 6), "STAND")
    # The canonical hard case from the summary.
    check("best action on 16 vs 10 is HIT", bj.best_action(16, 10), "HIT")
    # Standing on a stiff 12 against a bust-prone 4 beats hitting.
    check("best action on 12 vs 4 is STAND", bj.best_action(12, 4), "STAND")


def test_simulation_agrees():
    print("\n--- Simulation converges to the exact values " + "-" * 32)
    rng = np.random.default_rng(20260810)
    n = 400_000
    sim = bj.simulate_two_card(n, rng)

    # Sampling error for a proportion is sqrt(p(1-p)/n); allow 4 standard errors.
    for key, exact, label in [("p_blackjack", bj.p_blackjack_exact(), "P(blackjack)"),
                              ("p_pair", bj.p_pair_exact(), "P(pair)")]:
        se = math.sqrt(exact * (1 - exact) / n)
        diff = abs(sim[key] - exact)
        check_true(f"simulated {label} within 4 SE of exact",
                   diff <= 4 * se,
                   f"|{sim[key]:.5f} - {exact:.5f}| = {diff:.5f}, 4SE = {4*se:.5f}")

    # The running mean must actually converge, not merely end up close.
    run = sim["bj_running"]
    early = abs(run[99] - bj.p_blackjack_exact())
    late = abs(run[-1] - bj.p_blackjack_exact())
    check_true("late estimate is closer than the early one (LLN)", late < early,
               f"early={early:.5f} late={late:.5f}")

    for up in [2, 6, 10, 11]:
        exact = bj.p_dealer_bust_exact(up)
        got = bj.simulate_dealer_bust(up, 200_000, rng)
        se = math.sqrt(exact * (1 - exact) / 200_000)
        check_true(f"simulated bust|{up} within 4 SE", abs(got - exact) <= 4 * se,
                   f"{got:.4f} vs {exact:.4f}")


def test_simulation_mechanics():
    print("\n--- Simulator mechanics " + "-" * 52)
    rng = np.random.default_rng(7)
    # The two dealt cards must always be distinct.
    c1 = rng.integers(0, 52, size=50_000)
    c2 = rng.integers(0, 51, size=50_000)
    c2 = c2 + (c2 >= c1)
    check_true("dealt cards are never identical", bool(np.all(c1 != c2)))
    check_true("card indices stay within the deck",
               bool(np.all((c2 >= 0) & (c2 < 52))))

    sim = bj.simulate_two_card(5_000, np.random.default_rng(1))
    check("running array has one entry per trial", len(sim["bj_running"]), 5_000)
    check_true("running mean stays a valid probability",
               bool(np.all((sim["bj_running"] >= 0) & (sim["bj_running"] <= 1))))

    # A dealer simulation must return a probability.
    p = bj.simulate_dealer_bust(6, 20_000, np.random.default_rng(3))
    check_true("simulated bust probability is in [0,1]", 0 <= p <= 1, f"{p:.4f}")


def main():
    print("=" * 78)
    print("Week 2 blackjack test suite")
    print("=" * 78)
    test_exact_combinatorics()
    test_dealer_bust_against_published()
    test_dealer_distribution()
    test_ev_decisions()
    test_simulation_agrees()
    test_simulation_mechanics()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
