# Expected value is the wrong rule

**Phase 3 · CivEnv 205 · Weeks 9–10**

Phases 1 and 2 were about measurement: what is the distribution, what is in the
database. This phase is about the harder question that comes after — given
uncertainty you have measured, what should you actually *do*?

The textbook answer is to maximise expected value. Two weeks of building tools
convinced me that is wrong for most decisions a person actually faces, and I can
now say precisely why.

## Discounting, and the number that hides

Week 9 built a capital budgeting module: net present value, internal rate of
return, discounted payback, profitability index. I tested it on a real decision
— an 11 kW rooftop solar installation, modelled from its drivers rather than
from a fixed list of cash flows, so that sensitivity analysis would have real
assumptions to vary.

The base case: $24,000 installed, a 30% federal tax credit, 11,000 kWh in the
first year, $0.17/kWh avoided at 2.5% escalation, 0.5% annual panel degradation,
25-year life, 6% discount rate. That produces an NPV of $9,079.71, an IRR of
10.35%, and a profitability index of 1.378. Accept, comfortably.

Discounted payback came out at 13.61 years. Undiscounted, the system pays back
around year 10. That three-and-a-half-year gap *is* the time value of money made
visible — plain payback treats a 2036 dollar as a 2026 dollar, which flatters
long-lived projects systematically.

## Two ways IRR lies

IRR is the measure everyone quotes and the one that breaks most easily. I built
detection for both failure modes because both are invisible unless you look.

**Multiple roots.** Add a roof replacement in year 12 — an outflow *after* the
inflows have started — and the cash-flow series has three sign changes.
Descartes' rule of signs then permits up to three IRRs. The canonical case is
`[-4000, +25000, -25000]`, which genuinely has two: 25% and 400%, both verified
against the closed-form quadratic. A tool that returns one of them and stays
quiet, as `numpy_financial.irr` does, is how IRR produces a confidently wrong
ranking. My module scans for every root and warns when the shape is
non-conventional.

**Scale blindness.** IRR is a rate, so it systematically favours small projects.
Comparing the 11 kW system against a smaller, more efficient 4 kW array:

| | NPV | IRR |
|:--|--:|--:|
| 4 kW | $2,581 | **10.76%** |
| 11 kW | **$9,080** | 10.35% |

The two rules disagree, and you can only build one. Incremental analysis
resolves it by asking the right question — not "which rate is higher?" but "does
the *extra* $18,000 earn its keep?" The incremental cash flows return 10.21%
against a 6% hurdle, so the larger system wins. Raise the hurdle above 10.21%
and the answer correctly flips.

## Which assumption actually matters

A single NPV is dangerously overconfident. It hides the fact that the answer
rests on numbers somebody guessed. So I varied each input ±30% and sorted by
influence.

Production and price dominate, at $17,306 of NPV swing each. Maintenance moves
the answer by $1,534, and panel degradation by $872. Production and price come
out *identical* — necessarily so, because they enter the model only as a product
(kWh × $/kWh). My test suite asserts that equality, since a mismatch would mean
one of them was being applied in the wrong place.

The practical reading: time spent refining the maintenance budget is wasted.
Time spent on a production estimate is the whole game.

Break-even analysis sharpens it further. Production would have to come in
**31.5% below estimate** before the project destroys value. That is the honest
headline — not "NPV is $9,080" but "the decision survives a fairly bad forecast."

Scenario analysis then moves several inputs together, because the world does not
vary one at a time: a bad year is low output *and* a soft utility rate *and* an
install that ran over. Expected NPV $9,183, standard deviation $9,592,
P(NPV < 0) = 25%. The standard deviation exceeds the mean. A one-in-four chance
of losing money is a materially different proposition from "NPV is $9,080", and
only the scenario analysis says so.

## Pricing information before you buy it

Week 10 turned to decision trees, and to a question I had never seen posed
formally: how much is it worth paying for research?

The setup is a wildcat drilling lease. Drill and the outcome depends on the
geology — dry, wet, or soaking — with an expected value of $185,000 against
$90,000 for selling the lease outright. Expected value says drill, while
accepting a 45% chance of losing $700,000.

**EVPI** — the expected value of perfect information — is what a crystal ball
would be worth. Solve the problem knowing the state before choosing, and the
value rises to $540,500. The difference, **$355,500**, is a hard ceiling: no
study, however good, is worth more than that.

The whole idea reduces to the order of two operators. Expected value is
`max_a Σ_s p(s)·V(a,s)`. With perfect information it becomes
`Σ_s p(s)·max_a V(a,s)`. Swapping the max and the sum is exactly what
information buys, and by Jensen's inequality the difference can never be
negative — you can always ignore a report.

Real tests are imperfect, which is where Bayes' Rule from Phase 1 does actual
work. A seismic survey reads "closed" or "open" structure with known
reliability. Bayes converts a reading into revised beliefs — a "closed" reading
lifts P(soaking) from 0.25 to 0.43 and drops P(dry) from 0.45 to 0.17 — and
re-solving under each posterior gives **EVSI of $214,750**, or 60.4% of what
perfect information would deliver.

That is a number to negotiate against, derived before spending anything. And the
mechanism is worth stating plainly: the survey earns its value only because it
sometimes *changes the decision*. After an "open" reading you sell, which you
would not otherwise have done. A test that never changes what you do is worth
exactly zero regardless of its accuracy — my test suite verifies this directly
with an uninformative likelihood, and gets zero.

## Why insurance is not a bad bet

The last piece is the one that reframed something I thought I understood.

Exponential utility, `U(x) = 1 − e^(−x/R)`, encodes risk aversion with a single
parameter: R, the risk tolerance in dollars. Applied to the drilling problem,
the same cash flows produce different decisions. A wildcatter with $5M of risk
tolerance drills. One with $2M sells the identical lease. **The dollars never
change; the decision does.** The certainty equivalent of drilling falls from
$185,000 to −$501,772 as tolerance shrinks, while the certain $90,000 is
unmoved.

Then insurance. A household with $250,000 of wealth faces a 2% chance of a
$200,000 loss. The actuarially fair premium — the expected loss — is $4,000. The
most a buyer would pay solves `U(wealth − premium) = E[U(wealth − loss)]`:

| Risk tolerance | Max premium | Markup |
|:--|--:|--:|
| infinite (risk neutral) | $4,000 | $0 |
| $200,000 | $6,758 | $2,758 |
| $100,000 | $12,025 | $8,025 |

A risk-neutral buyer pays exactly the fair premium and not a cent more, so no
trade is possible with a break-even insurer. Every risk-averse buyer values the
contract *above* its fair price. The insurer, holding thousands of independent
policies, is effectively risk neutral by the law of large numbers and values it
*at* fair. That gap is the entire reason the market exists.

Insurance is not a bet the customer loses on average. It is a trade between two
parties who value the same risk differently, and both of them gain.

## The decision I actually faced

I modelled one of my own: accept an early internship offer, or decline and wait
for other interviews. Expected value says decline — waiting is worth $14,200
against $12,000 certain. But below a risk tolerance of about $30,000, the
certainty equivalent of waiting drops below $12,000 and accepting becomes
correct.

A student whose entire summer income is at stake has a risk tolerance in exactly
that range. So accepting the "suboptimal" early offer is not a failure of nerve.
It is the right answer for that person, and expected value simply cannot express
why.

That is the lesson of the phase. Expected value is the correct rule for a
decision you will face a thousand times. Almost none of the decisions that
matter are like that.
