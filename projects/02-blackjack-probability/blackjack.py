"""
Week 2 — Combinatorics & Simulation: Blackjack Probability Engine
================================================================
IEMS 302 consolidation project.

The idea
--------
Answer the same probability questions TWO ways and check they agree:
  1. Analytically  — exact answers from counting (combinatorics) and from
     conditional-probability recursion.
  2. By simulation — deal millions of random hands and just count.
When the exact math and the experiment land on the same number, each one
validates the other. This is the dress rehearsal for Week 3, where the math
gets too hard and we must trust simulation alone.

Quantities computed
--------------------
  - P(blackjack on first two cards)           [combinatorics, finite deck]
  - P(player is dealt a pair)                 [combinatorics, finite deck]
  - P(dealer busts | upcard)                  [conditional prob, infinite deck]
  - EV of standing vs hitting (bonus)         [decision under uncertainty]

Outputs (in ./results/)
-----------------------
  - convergence.png      : estimates settling onto the truth (Law of Large Numbers)
  - dealer_bust.png      : analytical vs simulated bust probability per upcard
  - results_table.md     : analytical-vs-simulated comparison table

Run it:
    python blackjack.py
"""

from __future__ import annotations
import math
from functools import lru_cache
import numpy as np
import matplotlib.pyplot as plt
import os

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# ============================================================================
# PART A — ANALYTICAL (exact) probabilities
# ============================================================================

# ---- A1. First-two-card probabilities via combinatorics (finite 52-card deck)
#
# A standard deck: 13 ranks x 4 suits = 52 cards.
# Total number of distinct 2-card hands = C(52, 2) = 1326.

TOTAL_2CARD_HANDS = math.comb(52, 2)          # 1326

def p_blackjack_exact() -> float:
    """P(blackjack) = P(one Ace AND one ten-value card) on the first two cards.

    Ten-value cards = {10, J, Q, K} -> 4 ranks x 4 suits = 16 cards.
    Aces = 4 cards.
    Favourable hands = (choose 1 of 4 aces) x (choose 1 of 16 tens) = 4*16 = 64.
    """
    favourable = math.comb(4, 1) * math.comb(16, 1)    # 64
    return favourable / TOTAL_2CARD_HANDS              # 64/1326 = 0.04827...

def p_pair_exact() -> float:
    """P(pair) = P(both cards share the same rank).

    For each of the 13 ranks there are C(4,2)=6 ways to pick 2 of its 4 suits.
    Favourable hands = 13 * 6 = 78.
    """
    favourable = 13 * math.comb(4, 2)                  # 78
    return favourable / TOTAL_2CARD_HANDS              # 78/1326 = 0.05882...


# ---- A2. P(dealer busts | upcard) via conditional-probability recursion
#
# Simplifying model (standard): INFINITE deck, so each drawn card is independent
# with P(rank) = 1/13, and ten-value cards {10,J,Q,K} have P = 4/13. Dealer hits
# until reaching 17 or more, and stands on 17 (including soft 17 -> "S17").
#
# Hand state = (hard_total, ace_available):
#   hard_total    = sum of all cards counting every Ace as 1
#   ace_available = True if at least one Ace is held (so one Ace MAY count as 11)
#   value         = hard_total + 10 if an Ace can be 11 without busting, else hard_total
# At most one Ace is ever worth 11 (two would be 22 = bust), so this is exact.

# Draw distribution: (card_value_as_1_or_pip, probability). 'A' handled specially.
_DRAW = [("A", 1/13)] + [(v, 1/13) for v in range(2, 10)] + [(10, 4/13)]

def _value(hard: int, ace_avail: bool) -> int:
    """Best (highest non-busting) total for the hand."""
    if ace_avail and hard + 10 <= 21:
        return hard + 10
    return hard

@lru_cache(maxsize=None)
def p_bust(hard: int, ace_avail: bool) -> float:
    """P(dealer eventually busts) from the current hand, drawing under S17."""
    if hard > 21:
        return 1.0
    if _value(hard, ace_avail) >= 17:     # dealer stands (S17 stands on soft 17)
        return 0.0
    p = 0.0
    for card, prob in _DRAW:
        if card == "A":
            p += prob * p_bust(hard + 1, True)
        else:
            new_hard = hard + card
            p += prob * (1.0 if new_hard > 21 else p_bust(new_hard, ace_avail))
    return p

def p_dealer_bust_exact(upcard: int) -> float:
    """upcard: 2..10 for pip/ten cards, 11 for an Ace."""
    if upcard == 11:                       # Ace upcard: hard=1, an ace is available
        return p_bust(1, True)
    return p_bust(upcard, False)

@lru_cache(maxsize=None)
def dealer_final_dist(hard: int, ace_avail: bool) -> tuple:
    """Distribution of the dealer's final standing value.

    Returns a tuple of (outcome, probability) where outcome is 17,18,19,20,21
    or the string 'bust'. Used by the EV (decision) analysis below.
    """
    if hard > 21:
        return (("bust", 1.0),)
    v = _value(hard, ace_avail)
    if v >= 17:
        return ((v, 1.0),)
    acc = {}
    for card, prob in _DRAW:
        if card == "A":
            sub = dealer_final_dist(hard + 1, True)
        else:
            nh = hard + card
            sub = (("bust", 1.0),) if nh > 21 else dealer_final_dist(nh, ace_avail)
        for outcome, p in sub:
            acc[outcome] = acc.get(outcome, 0.0) + prob * p
    return tuple(acc.items())

def _dist_from_upcard(upcard: int) -> dict:
    start = (1, True) if upcard == 11 else (upcard, False)
    return dict(dealer_final_dist(*start))


# ============================================================================
# PART B — BONUS: decision analysis (EV of standing vs hitting)
# ============================================================================
# A first taste of Weeks 9-10: use probability to MAKE a decision. We compare,
# for a player hard total against a dealer upcard, the expected value of:
#   - standing now, vs
#   - taking exactly one more card and then standing.
# Payoff convention: win = +1, lose = -1, push = 0 (blackjack 3:2 ignored).

def ev_stand(player_total: int, upcard: int) -> float:
    """Expected value of standing on `player_total` against `upcard`."""
    ev = 0.0
    for outcome, p in _dist_from_upcard(upcard).items():
        if outcome == "bust":
            ev += p * 1.0                              # dealer busts -> we win
        elif player_total > outcome:
            ev += p * 1.0
        elif player_total < outcome:
            ev += p * -1.0
        # equal -> push -> +0
    return ev

def ev_hit_then_stand(player_total: int, upcard: int) -> float:
    """EV of taking one card (as a hard hand) then standing."""
    ev = 0.0
    for card, prob in _DRAW:
        add = 11 if card == "A" else card             # treat a drawn ace as 11...
        new_total = player_total + add
        if card == "A" and new_total > 21:            # ...or 1 if 11 would bust
            new_total = player_total + 1
        if new_total > 21:
            ev += prob * -1.0                          # we bust -> lose
        else:
            ev += prob * ev_stand(new_total, upcard)
    return ev

def best_action(player_total: int, upcard: int) -> str:
    return "HIT" if ev_hit_then_stand(player_total, upcard) > ev_stand(player_total, upcard) else "STAND"


# ============================================================================
# PART C — SIMULATION (Monte Carlo)
# ============================================================================

def simulate_two_card(n: int, rng) -> dict:
    """Deal `n` two-card hands from a real finite 52-card deck (vectorised).

    Cards are 0..51; rank = card // 4 with 0=Ace, 9..12 = {10,J,Q,K} (ten-value).
    Returns cumulative-mean arrays so we can plot convergence (Law of Large Nums).
    """
    c1 = rng.integers(0, 52, size=n)
    c2 = rng.integers(0, 51, size=n)
    c2 = c2 + (c2 >= c1)                                # make the 2nd card distinct
    r1, r2 = c1 // 4, c2 // 4
    ace1, ace2 = (r1 == 0), (r2 == 0)
    ten1, ten2 = (r1 >= 9), (r2 >= 9)
    blackjack = (ace1 & ten2) | (ace2 & ten1)
    pair = (r1 == r2)
    trials = np.arange(1, n + 1)
    return {
        "p_blackjack": blackjack.mean(),
        "p_pair": pair.mean(),
        "bj_running": np.cumsum(blackjack) / trials,
        "pair_running": np.cumsum(pair) / trials,
    }

def simulate_dealer_bust(upcard: int, n: int, rng) -> float:
    """Simulate `n` dealer hands from `upcard` (infinite deck, S17), vectorised."""
    hard = np.full(n, 1 if upcard == 11 else upcard, dtype=np.int64)
    ace_avail = np.zeros(n, dtype=bool)
    if upcard == 11:
        ace_avail[:] = True
    for _ in range(25):                                # safety cap on draws
        value = hard + np.where(ace_avail & (hard + 10 <= 21), 10, 0)
        drawing = (value < 17) & (hard <= 21)
        if not drawing.any():
            break
        m = int(drawing.sum())
        draw = rng.integers(0, 13, size=m)             # 0=Ace,1..8=2..9,9..12=ten
        pip = np.where(draw == 0, 1, np.where(draw >= 9, 10, draw + 1))
        idx = np.where(drawing)[0]
        hard[idx] += pip
        ace_avail[idx] |= (draw == 0)
    return float((hard > 21).mean())


# ============================================================================
# PART D — Orchestration: compare, tabulate, plot
# ============================================================================

def _save_convergence(sim: dict, outdir: str):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, key, exact, label in [
        (axes[0], "bj_running", p_blackjack_exact(), "P(blackjack)"),
        (axes[1], "pair_running", p_pair_exact(), "P(pair)"),
    ]:
        run = sim[key]
        ax.plot(np.arange(1, len(run) + 1), run, color="0.5", lw=0.8,
                label="Simulated estimate")
        ax.axhline(exact, color="red", lw=1.5, ls="--",
                   label=f"Exact = {exact:.4f}")
        ax.set_xscale("log")
        ax.set_xlabel("Number of trials (log scale)")
        ax.set_ylabel(label)
        ax.set_title(f"{label}: estimate converging to the truth")
        ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "convergence.png"), dpi=130)
    plt.close(fig)

def _save_dealer_bust(analytical: dict, simulated: dict, outdir: str):
    ups = list(analytical.keys())
    labels = ["A" if u == 11 else str(u) for u in ups]
    x = np.arange(len(ups))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x - 0.2, [analytical[u] for u in ups], 0.4, label="Analytical", color="0.4")
    ax.bar(x + 0.2, [simulated[u] for u in ups], 0.4, label="Simulated", color="0.7")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_xlabel("Dealer upcard"); ax.set_ylabel("P(dealer busts)")
    ax.set_title("Dealer bust probability: analytical vs simulated (S17, infinite deck)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(outdir, "dealer_bust.png"), dpi=130)
    plt.close(fig)

def _write_table(rows, path):
    header = "| Quantity | Analytical | Simulated | Abs. diff |\n|:--|--:|--:|--:|\n"
    body = "\n".join(
        f"| {name} | {a:.4f} | {s:.4f} | {abs(a-s):.4f} |" for name, a, s in rows
    )
    with open(path, "w") as fh:
        fh.write(header + body + "\n")


def main(n_two_card=1_000_000, n_dealer=300_000, seed=7):
    os.makedirs(RESULTS_DIR, exist_ok=True)
    rng = np.random.default_rng(seed)

    # --- First-two-card quantities
    sim = simulate_two_card(n_two_card, rng)
    bj_a, bj_s = p_blackjack_exact(), sim["p_blackjack"]
    pr_a, pr_s = p_pair_exact(), sim["p_pair"]
    _save_convergence(sim, RESULTS_DIR)

    # --- Dealer bust by upcard
    upcards = list(range(2, 11)) + [11]                # 2..10, Ace
    analytical = {u: p_dealer_bust_exact(u) for u in upcards}
    simulated = {u: simulate_dealer_bust(u, n_dealer, rng) for u in upcards}
    _save_dealer_bust(analytical, simulated, RESULTS_DIR)

    # --- Comparison table
    rows = [("P(blackjack)", bj_a, bj_s), ("P(pair)", pr_a, pr_s)]
    for u in upcards:
        name = f"P(dealer bust | {'A' if u==11 else u})"
        rows.append((name, analytical[u], simulated[u]))
    _write_table(rows, os.path.join(RESULTS_DIR, "results_table.md"))

    # --- Print everything
    print(f"P(blackjack):  exact {bj_a:.4f} ({math.comb(4,1)*math.comb(16,1)}/{TOTAL_2CARD_HANDS})"
          f"  |  simulated {bj_s:.4f}")
    print(f"P(pair):       exact {pr_a:.4f} ({13*math.comb(4,2)}/{TOTAL_2CARD_HANDS})"
          f"  |  simulated {pr_s:.4f}")
    print("\nDealer bust probability (S17, infinite deck):")
    print(f"  {'upcard':>7} {'analytic':>9} {'sim':>8}")
    for u in upcards:
        print(f"  {'A' if u==11 else u:>7} {analytical[u]:>9.4f} {simulated[u]:>8.4f}")

    # --- Decision-analysis demo (bonus)
    print("\nDecision analysis — EV of standing vs hitting (win=+1, lose=-1):")
    for total, up in [(16, 10), (12, 4), (13, 6), (15, 7)]:
        es, eh = ev_stand(total, up), ev_hit_then_stand(total, up)
        print(f"  player {total} vs dealer {('A' if up==11 else up)}:  "
              f"stand {es:+.3f}  hit {eh:+.3f}  ->  {best_action(total, up)}")

    print(f"\nPlots + table written to: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
