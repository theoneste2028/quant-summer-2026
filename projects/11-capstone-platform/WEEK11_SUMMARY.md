# Week 11 Summary — Capstone: Utility-Based Portfolio Optimizer
**Courses:** IEMS 302 + CS 217 + CivEnv 205 · **Author:** Tteddy

> All numbers are real output from `capstone.py` against the live portfolio
> database: 20 assets, 450 trading days (2024-10-22 to 2026-08-10), 100,000
> Monte Carlo paths.

## Question
Three phases produced three sets of tools. Do they compose into something that
answers a question about real money — what should this portfolio actually hold,
and how much risk is that?

## The five layers

| Layer | Does | From |
|:--|:--|:--|
| 1. Data | SQLite → returns matrix, no live API calls | CS 217, weeks 5–8 |
| 2. Statistics | mean vector, covariance, shrinkage, normality fits | IEMS 302, weeks 1–4 |
| 3. Optimization | CVXPY Markowitz across risk aversion γ | CivEnv 205 |
| 4. Decision | certainty equivalents select one portfolio | week 10 |
| 5. Simulation | 1-year forward paths, VaR, normal vs fat-tailed | week 3 |

The imports are the integration test: `capstone.py` imports `fit_all` from Week
1 and `certainty_equivalent` from Week 10. If those break, the capstone is no
longer integrating anything.

## Layer 1 — Data

Universe is 20 assets: 9 currently-held positions with sufficient history, plus
11 broad candidate ETFs added to the database through the Week 5 loader. Five
holdings were **excluded** for having under 400 days of price history (ASTX 272,
NVTX 231, IREX 199, NBIG 197, LUNL 144) — the newest leveraged ETFs.

That exclusion means **22.3% of current portfolio value is not modelled**, which
is reported rather than buried: it bounds what the recommended-vs-actual
comparison can claim.

Returns use the date intersection across all assets. Using each asset's own full
history would estimate different covariance pairs from different periods.

## Layer 2 — Statistics, and the reason for shrinkage

Only **22.5 observations per asset**. The sample covariance at that ratio is
badly conditioned, and the sample means are far worse than badly conditioned —
they are the estimates the optimizer is most sensitive to and the ones estimated
least precisely.

The first run made the consequence vivid. Over this window PL, ONDS, NBIS and MU
realised 131%, 129%, 125% and 116% annualised. The naive optimizer put **100% of
the recommendation into exactly those four**, and reported a 124% expected
return. That is Markowitz's well-documented *error maximization*: it cannot
distinguish a genuinely high expected return from a lucky one, so it
concentrates on whichever estimate is most favourably wrong.

Two corrections, implemented from the papers since scikit-learn is not a
dependency here:

| | Intensity | Effect |
|:--|--:|:--|
| Jorion Bayes-Stein (mean) | 58.9% | PL's estimate 131% → 57% |
| Ledoit-Wolf (covariance) | 8.3% | condition number 64,049 → **2,744** |

Plus a non-statistical third: a **25% cap** on any single position, encoding the
judgement that no estimate justifies betting a quarter of the portfolio on one
name.

The normality check reruns Week 1 on this universe: **all 20 assets reject the
Normal**, median excess kurtosis 7.2, median fitted 3.8 degrees of freedom. The
optimizer uses only a mean and a covariance, which is a complete description of
risk *only* under normality — so that median 3.8 is carried into Layer 5 rather
than being noted and forgotten.

## Layer 3 — Optimization

| | Return range | Holdings at the aggressive end |
|:--|:--|--:|
| Naive | 4.3% – 130.7% | 5 |
| Robust + 25% cap | 8.8% – 54.7% | 7 |

The **minimum-variance portfolio** (4.6% return, 4.4% volatility) is reported as
a benchmark that uses no expected-return estimates at all. It is what a return
forecast must beat to justify its own existence.

## Layer 4 — Decision

Wealth defaults to the portfolio's own market value, so the utility scale is
anchored to the real money at stake. Risk tolerance defaults to 25% of wealth —
setting R equal to wealth means being willing to stake essentially everything on
a coin flip, which is not what "moderately aggressive" means.

**Recommended:** 25.19% return, 25.28% volatility, Sharpe 0.997, 7 holdings —
GLD 25%, GOOGL 24.7%, SCHD 23.3%, MU 14.6%, PL 8.8%, ONDS 2.2%, NBIS 1.4%.

Since R is not observable, the pipeline reports the whole map rather than
defending one guess:

| R / wealth | Return | Volatility | Sharpe | Largest positions |
|--:|--:|--:|--:|:--|
| 2% | 8.8% | 9.6% | 0.92 | BND, FDVV, SCHD |
| 10% | 9.4% | 9.7% | 0.97 | BND, FDVV, SCHD |
| **25%** | **25.2%** | **25.3%** | **1.00** | **GLD, GOOGL, SCHD** |
| 50% | 44.8% | 52.8% | 0.85 | MU, GOOGL, PL |
| 100% | 54.7% | 73.0% | 0.75 | ONDS, MU, NBIS |

## Layer 5 — Monte Carlo, and a surprise

|  | Normal | Student-t |
|:--|--:|--:|
| Expected return | 28.4% | 29.1% |
| P(loss > 10%) | 10.0% | 9.8% |
| 5% VaR | 18.0% | 17.7% |
| 1% VaR | 31.0% | 30.8% |

Having spent Week 1 establishing fat tails, I expected the t model to give a
markedly worse VaR. It did not.

**Two reasons, both worth knowing.** First, rescaled to equal variance a t(3.8)
sits *nearer its centre* than a normal — its extra far-tail mass is paid for by
a narrower middle — so it is actually *less* extreme at the 5th percentile. The
crossover is between the 2nd and 5th. Quoting a 5% VaR alone would make heavy
tails look harmless.

Second, and larger: the Central Limit Theorem. Varying the horizon:

| Horizon | 1% VaR normal | 1% VaR t | Ratio |
|:--|--:|--:|--:|
| 1 day | 3.51% | 3.65% | **1.04×** |
| 1 week | 7.54% | 7.64% | 1.01× |
| 1 month | 14.05% | 14.12% | 1.00× |
| 1 year | 31.00% | 30.76% | 0.99× |

A one-year return is a sum of 252 daily draws, and sums of independent
heavy-tailed variables with finite variance converge toward normality. **Fat
tails dominate short-horizon risk and wash out at long horizons.** The real
long-horizon danger is dependence — volatility clustering, correlations rising
together in a crash — which an i.i.d. simulation does not model and therefore
understates.

## Recommended vs actual

| | Current | Recommended |
|:--|--:|--:|
| Expected return | 42.25% | 25.19% |
| Volatility | 65.91% | **25.28%** |
| Sharpe | 0.641 | **0.997** |
| P(loss > 10%) | 32.0% | **9.8%** |
| 1% VaR | 73.7% | **30.8%** |
| Certainty equivalent (base 100) | 95.5 | **115.1** |

The recommendation gives up 17 points of expected return to cut volatility 62%,
raise return-per-risk 55%, and make a double-digit loss roughly a third as
likely.

What it *adds* is the interesting part: **gold and a broad dividend fund**,
neither previously held, and neither near the top of the universe on expected
return. They earn their place through low correlation — which is what an
optimizer is for, and what eyeballing a portfolio cannot do.

## Testing
`test_capstone.py` runs **108 checks**. Estimators are scored against a synthetic
market with a *known* covariance, so shrinkage can be shown to actually improve
the estimate rather than merely change it. Structural invariants: weights sum to
1 and respect the cap; higher risk aversion lowers both return and volatility; a
riskless portfolio's certainty equivalent equals its certain value; 1% VaR is
always worse than 5%; the same seed reproduces the same result. Then the real
pipeline end to end.

The pipeline's interface is tested too: configuration defaults and
validation, ticker exclusion, date windows, the infeasible-cap error, and that
the decision is unchanged when wealth is rescaled — the property that lets the
research app show values indexed to 100. `test_app.py` adds 38 checks that drive
the app headlessly, including that it reproduces `site/capstone.json` at the
published settings.

All pass, and the repo-wide suite is at **671 passed, 0 failed**.

## Honest limitations
- **The window is short and flattering.** 450 days covering a strong market.
  Shrinkage reduces the damage without eliminating it.
- **22.3% of portfolio value is unmodelled** for want of price history.
- **Returns are assumed i.i.d.** No volatility clustering, no correlations that
  rise in a crash — precisely when they do.
- **No transaction costs or taxes.** Rebalancing to the recommendation is not
  free, and the comparison ignores that.
- **This is coursework, not advice.**

## So what?
Week 12 turns this into something a person can look at: results precomputed to
JSON, rendered as a self-contained static page with hand-drawn SVG charts, plus
a drop-in React component for a Next.js site. Portfolio values are indexed to
100 by default — the method is fully demonstrable without publishing the
amounts.
