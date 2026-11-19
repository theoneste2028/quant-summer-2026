# The distribution nobody checks

**Phase 1 · IEMS 302 · Weeks 1–4**

Every model I was about to build for the summer rested on the same assumption:
that daily stock returns are normally distributed. Black-Scholes assumes it.
Markowitz assumes it. The Value-at-Risk number your brokerage shows you assumes
it. It is the load-bearing wall of introductory quantitative finance, and almost
nobody checks whether it holds.

So I started by checking.

## Measuring how wrong the bell curve is

I pulled five years of daily prices for nine tickers I actually own, converted
them to log returns, and fitted three candidate distributions to each: the
Normal, the Student-t, and the Laplace. Then I scored the fits three ways — the
Kolmogorov–Smirnov statistic, the log-likelihood, and AIC, which penalises the
Student-t for having an extra parameter so it cannot win on flexibility alone.

The Normal lost every time. Not narrowly — the Student-t fitted best on all
nine tickers, even after the AIC penalty. The KS statistic for the t was
typically about three times smaller than for the Normal, and up to five times
smaller.

The number that says why is **excess kurtosis**, which measures how much
probability lives in the tails relative to a bell curve. A Normal has excess
kurtosis of zero by construction. My holdings ranged from 3.0 to 19.1. VRT, the
worst offender, had a skew of −1.49 and excess kurtosis of 19.1, meaning its
crash days are both more frequent and more violent than any normal model would
ever generate.

The most useful surprise was SPY. I expected the diversified index to be close
to normal — that is the standard intuition, and diversification is supposed to
average away extremes. Its excess kurtosis was 7.9, higher than seven of the
other eight tickers, with fitted degrees of freedom of 3.9. Diversification
crushed the day-to-day volatility (1.08% daily standard deviation against 2–7%
for single names) and did essentially nothing to the *shape* of the tail. Those
are two different kinds of risk, and only one of them responds to holding more
things.

## Learning to trust simulation

Week 2 was a detour that turned out to be the foundation for everything after
it. I computed blackjack probabilities two independent ways: exactly, using
combinatorics and a conditional-probability recursion, and approximately, by
simulating a million hands.

The point was not blackjack. The point was calibration. When your analytical
answer and your simulated answer agree to three decimal places across twelve
different quantities, you have learned something about your simulator that you
cannot learn any other way — and you need that confidence later, when you reach
problems where no analytical answer exists to check against.

The dealer-bust probabilities came out at 35.4% on a 2, rising to 42.3% on a 6,
then dropping sharply to 26.2% on a 7. That discontinuity is the structural fact
basic strategy is built on, and it fell out of a recursion I wrote in about
twenty lines.

## Pricing something with no formula

Week 3 built a Monte Carlo option pricer and validated it against Black-Scholes
across twelve combinations of strike and maturity. All twelve landed inside the
simulation's 95% confidence interval. Better, the standard error fell with a
fitted log-log slope of −0.500 against a theoretical −0.5 — the Central Limit
Theorem showing up as a measured number rather than a claim in a textbook.

That slope has a practical meaning that took me a while to internalise: halving
your error costs four times the computation. Monte Carlo is not slow because
computers are slow. It is slow because √n is a punishing function.

Which is what made Week 4 worth doing. Antithetic variates — for every random
draw Z, also use −Z — gave a stable 1.66× variance reduction for the same number
of paths. Free accuracy, from noticing that a symmetric payoff has correlated
mirror images.

The technique I keep coming back to, though, is **common random numbers**. To
compute an option's Delta by finite differences you price it at two nearby spot
prices and take the slope. If you use fresh random draws for each, the
simulation noise swamps the signal entirely. Reuse the *same* draws for both and
the noise cancels in the subtraction. My tests measured the difference: the
standard deviation of the estimate fell from 0.094 to 0.0013, a factor of 74.
Same number of paths, same math, one decision about where the randomness comes
from.

## What broke, and what it taught me

When I went back and wrote proper assertion-based tests for this phase — the
original "tests" were demo scripts that printed tables a human was supposed to
eyeball — one of them failed in a way I initially thought was a bug.

I had asserted that on genuinely normal data, the Normal distribution should
achieve the smallest KS statistic. It did not. The Student-t matched it or beat
it slightly, every time.

That is not a bug. The KS statistic measures goodness of fit and *does not
penalise complexity*. A three-parameter model can always fit a finite sample at
least as well as a two-parameter one nested inside it, because it can spend the
extra freedom on sampling noise. When the t is fitted to normal data it simply
drives its degrees of freedom toward infinity — I measured values above 21
million — at which point it *is* the Normal, numerically identical to ten
decimal places.

AIC is what separates them, and it does so entirely through the parameter
penalty. The AIC gap I measured was 2.0000: exactly `2k` for one extra
parameter, with the log-likelihoods identical. My test had contradicted the very
argument the project makes for using AIC in the first place.

The corrected test asserts what is actually true: that the Normal and t are
indistinguishable on KS, that Laplace is clearly worse, and that AIC does the
discriminating. It is a better test than the one I meant to write.

## Why this phase comes first

The honest conclusion is that any model I build on a normality assumption will
understate tail risk for these holdings. Black-Scholes will misprice deep
out-of-the-money options. A Normal-based VaR will report a rosier worst case
than reality — which is precisely the failure that surprised risk managers in
2008.

I still use the Normal later. The Week 11 optimizer works with a mean vector and
a covariance matrix, which is a complete description of risk *only* if returns
are normal. The difference is that it is now a documented caveat with a measured
magnitude attached, rather than an assumption I inherited without noticing.

There is a coda to this, and it surprised me. When I finally simulated the
capstone portfolio forward under fat-tailed innovations, expecting a much worse
tail, the one-year Value-at-Risk barely moved — about 4% worse at a one-day
horizon, and no worse at all over a year. That is the Central Limit Theorem
again: an annual return is a sum of 252 daily draws, and sums of independent
heavy-tailed variables with finite variance drift back toward normality.

So the fat tails I spent Week 1 measuring dominate short-horizon risk and wash
out at long ones. The real long-horizon danger is not tail *shape* but tail
*dependence* — volatility clustering, correlations that rise together in a
crash — which an independent-draw model does not capture at all.

Knowing which of your assumptions is wrong is useful. Knowing *where* it is
wrong, and by how much, is what makes it actionable.
