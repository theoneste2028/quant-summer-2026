# The optimizer told me exactly what I wanted to hear

**Phase 4 · Capstone · Weeks 11–12**

The capstone was supposed to be the easy part. Three phases of tools already
existed: a database that could produce clean returns, distribution fits that
knew how non-normal those returns were, and utility machinery that could turn a
menu of options into a choice. Week 11 was assembly.

Then I ran it, and it recommended putting 100% of my portfolio into four stocks
at a projected 124% annual return.

## The pipeline

Five layers, each drawing on a different part of the summer:

1. **Data** reads returns out of SQLite. Never a live API call — the database
   built in Phase 2 is the single source of truth, which is the entire point of
   having built it.
2. **Statistics** estimates the mean vector and covariance, and re-runs the
   Week 1 fits so the normality assumption is stated rather than assumed.
3. **Optimization** solves the Markowitz problem across a grid of risk-aversion
   values with CVXPY, tracing the efficient frontier.
4. **Decision** applies Week 10's certainty equivalents to pick one portfolio.
5. **Simulation** projects that portfolio forward a year using Week 3's Monte
   Carlo, under both normal and fat-tailed innovations.

The universe is 20 assets: nine current holdings with enough price history, plus
eleven broad candidate ETFs. Five holdings were excluded for having under 400
days of history — the newest leveraged ETFs — which means 22% of current
portfolio value is not modelled. That exclusion is reported rather than
buried, because it bounds what the comparison can claim.

## Error maximization, in the wild

The first run's recommendation was PL, ONDS, NBIS and MU, at 25% each. Those are
precisely the four assets with the highest realised returns over the estimation
window: 131%, 129%, 125% and 116% annualised.

This is the failure mode Michaud named in 1989. Markowitz optimization takes
expected returns as *inputs* and treats them as known. They are not known — they
are estimates, and the noisiest estimates in the whole procedure. The optimizer
cannot distinguish a genuinely high expected return from a lucky one, so it
loads onto whichever estimate happens to be most favourably wrong. It is an
error maximizer.

The window made it worse. 450 trading days covering a strong market for
small-cap AI and space names. Any mean estimated from it is momentum
extrapolation wearing the costume of optimization.

Two standard corrections, implemented directly since scikit-learn is not a
dependency here:

**Jorion Bayes-Stein** shrinks the mean vector toward the return of the
minimum-variance portfolio. The intensity is computed from the data and came out
at 58.9%, pulling PL's estimate from 131% down to 57%. Means are what the
optimizer is most sensitive to and what is estimated least precisely, so pulling
them together removes most of the damage.

**Ledoit-Wolf** shrinks the sample covariance toward a constant-correlation
target with an analytically optimal intensity. That cut the covariance condition
number from 64,049 to 2,744 — a 23× improvement in conditioning, which matters
because with 450 observations across 20 assets there are only 22.5 observations
per asset.

A third correction is not statistical at all: a 25% cap on any single position.
It encodes the judgement that no estimate is good enough to justify betting a
quarter of the portfolio on one name, let alone all of it.

With all three, the recommendation became seven holdings — GLD, GOOGL, SCHD, MU,
PL, ONDS, NBIS — at 25.2% expected return and 25.3% volatility.

I also compute the **minimum-variance portfolio**, which uses no expected-return
estimates whatsoever. It is the benchmark a return forecast has to beat to
justify its own existence. Reporting it keeps the rest of the pipeline honest.

## What the recommendation actually says

| | Current | Recommended |
|:--|--:|--:|
| Expected return | 42.3% | 25.2% |
| Volatility | 65.9% | 25.3% |
| Sharpe ratio | 0.64 | 1.00 |
| P(loss > 10%) | 32.0% | 9.8% |
| 1% VaR | 73.7% | 30.8% |

The recommendation gives up 17 points of expected return. In exchange it cuts
volatility by 62%, raises return per unit of risk by 55%, and makes a
double-digit loss roughly a third as likely.

What it adds is instructive: gold and a broad dividend fund, neither of which
the portfolio held any of. Neither is there for its expected return — both are
near the bottom of the universe on that measure. They are there for low
correlation, which is exactly the thing an optimizer is for and the thing
intuition reliably misses. You cannot eyeball a covariance matrix.

## The number nobody knows

The decision layer needs a risk tolerance, R, and R is not observable. Nobody
knows their own to two significant figures.

Rather than defend one guess, the pipeline reports the whole map. At 2% of
wealth the optimizer holds bonds and dividend funds at 9.6% volatility; at 100%
it concentrates into the highest-return names it is allowed, at 73%. The
recommendation above sits at 25%, a moderate setting for someone whose portfolio
is a meaningful fraction of their savings.

That table is more useful than any single recommendation, because a reader can
locate themselves on it instead of trusting my guess about them.

## The result I did not expect

All 20 assets reject the normal distribution, with a median fitted 3.8 degrees
of freedom. So I expected the fat-tailed simulation to produce a substantially
worse Value-at-Risk than the normal one.

It barely moved. At the 5% level the fat-tailed model looked *no worse at all* —
in some runs slightly better.

That is not a bug, and chasing it produced the most interesting finding of the
project. Rescaled to the same variance, a Student-t with 3.8 degrees of freedom
sits *nearer its centre* than a normal; its extra mass in the far tail is paid
for by a narrower middle. The crossover is between the 2nd and 5th percentile.
**A 5% VaR is not deep enough into the tail for fat tails to bite.** Quoting one
alone would make heavy tails look harmless — precisely the error Phase 1 warned
about.

Even at 1%, the effect was small. So I varied the horizon:

| Horizon | 1% VaR, normal | 1% VaR, t | Ratio |
|:--|--:|--:|--:|
| 1 day | 3.51% | 3.65% | 1.04× |
| 1 week | 7.54% | 7.64% | 1.01× |
| 1 month | 14.05% | 14.12% | 1.00× |
| 1 year | 31.00% | 30.76% | 0.99× |

The Central Limit Theorem. A one-year return is a sum of 252 daily draws, and
sums of independent heavy-tailed variables with finite variance converge toward
normality. Daily fat tails dominate short-horizon risk and wash out at long
ones.

Which reframes the risk entirely. The danger over a year is not tail *shape* but
tail *dependence* — volatility clustering, correlations rising together in a
crash — and an independent-draw simulation models none of it. My model
understates long-horizon risk, and it understates it for a reason I can name.
That is a more useful place to end than a confident VaR number.

## Shipping it

Week 12 turned the results into something a person can look at: results
precomputed in Python, exported as a 21 KB JSON file, and rendered as a
self-contained static page with hand-drawn SVG charts. No build step, no CDN, no
Python at request time.

One deliberate choice: absolute dollar amounts are withheld by default and
everything is indexed to 100. The analysis is entirely demonstrable in
percentages, and a reader wants to see whether the pipeline works, not what my
net worth is.

## What twelve weeks taught me

The technical answer is that the constraint is never the solver. CVXPY solved
every problem I gave it in milliseconds. The binding constraint was always the
quality of the inputs and my willingness to admit they were estimates —
shrinkage, position caps, reported exclusions, and a risk-tolerance sweep
instead of a single confident number.

The broader answer is about where bugs actually live. The duplicated trades, the
fabricated prices, the `INSERT OR IGNORE` that swallowed a negative-price row,
the two queries whose results changed when I added an index, the test that
demanded the Normal beat the Student-t on a statistic that does not penalise
parameters — not one of those was found by reading code. Every one surfaced from
asking a system for something that should have been impossible, and noticing
that it answered.

Building the thing is the easy half. Establishing that it is telling the truth
is the work.
