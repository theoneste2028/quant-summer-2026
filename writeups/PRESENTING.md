# Presenting this work

Everything here is drafted from measured results in the repo. Numbers are as of
the final run; regenerate with `python run_all_tests.py` and
`python projects/11-capstone-platform/capstone.py` if you extend the project.

---

## Résumé bullets

Pick three or four. Each leads with the artifact, not the coursework.

**Capstone / optimization**
> Built a five-layer portfolio optimizer (SQLite → distribution fitting → CVXPY
> Markowitz → utility-based selection → Monte Carlo VaR) that cut portfolio
> volatility 62% and raised the Sharpe ratio from 0.64 to 1.00 on a real
> brokerage history of 555 trades.

> Diagnosed and corrected Markowitz "error maximization" by implementing Jorion
> Bayes-Stein mean shrinkage and Ledoit-Wolf covariance shrinkage from the
> papers, improving covariance conditioning 23× (condition number 64,049 → 2,744)
> and replacing a 4-asset concentrated recommendation with a 7-asset portfolio.

**Data engineering**
> Designed a 3NF SQLite schema and ETL pipeline for a real brokerage history;
> discovered and fixed three silent data-corruption defects, including 655
> fabricated price rows that had shadowed real market data for 131 trading days.

> Implemented FIFO tax-lot matching in pure SQL using cumulative-sum window
> functions and an interval-overlap join, eliminating the row-by-row Python loop
> the problem normally requires.

**Performance**
> Benchmarked five query patterns over 2.96M rows, measuring 10× speed-ups from
> B-tree indexes while quantifying their cost (88% storage growth, 3.77× slower
> inserts) and identifying a query where indexing bought nothing.

**Probability / simulation**
> Built a Monte Carlo option pricer validated against Black-Scholes across 12
> strike/maturity pairs (all within the 95% CI), confirming O(1/√n) convergence
> to a fitted slope of −0.500; cut Greek estimation noise 74× using common
> random numbers.

**Testing**
> Wrote 603 assertion-based tests across 11 suites, catching four defects that
> code review had missed — including an index that silently changed which rows a
> report returned.

---

## LinkedIn "Projects" entry

**Quant Research Platform — Summer 2026**

> Twelve-week build consolidating probability, data management, and engineering
> economics into one system that runs on my own brokerage history.
>
> A SQLite data layer ingests trades and prices through a validated, idempotent
> ETL pipeline. A statistics layer fits return distributions and measures how far
> they are from normal (all 20 assets reject it, median 3.8 degrees of freedom).
> An optimization layer traces the efficient frontier with CVXPY using shrunk
> estimates. A decision layer applies exponential utility to pick one allocation.
> A Monte Carlo layer reports Value-at-Risk under both normal and fat-tailed
> models.
>
> The result cuts volatility 62% and raises the Sharpe ratio from 0.64 to 1.00
> against my actual allocation.
>
> The most interesting findings were the failures: Markowitz on raw sample means
> is an error maximizer that recommended a 124% expected return; and fat tails,
> which I had spent a month measuring, turn out to barely affect one-year risk
> because the Central Limit Theorem washes them out. Both are written up.
>
> Python · SQL · CVXPY · Monte Carlo · 603 tests

---

## Walkthrough script (3–5 minutes)

Aim for one screen per beat. Don't read the code — narrate the decisions.

**0:00 — What and why** *(≈25s)*
> "Three courses this summer covered probability, databases, and engineering
> economics. Rather than three disconnected assignments, I built one system that
> uses all of them, running on my actual brokerage account."

Show the README architecture diagram.

**0:25 — The database, and what it found** *(≈50s)*
> "Everything starts here — a normalized schema for my real trade history. The
> rule I committed to was: store only what was observed, derive everything else.
> No stored P&L columns, because those go stale."
>
> "That decision is what found the bugs. When I wrote the position query, three
> tickers came back with negative share counts. A long-only account can't hold
> negative shares, so the query was reporting something impossible."

Run `python dashboard.py positions`.

> "Tracing it found duplicated trades, dropped dividend reinvestments, and —
> the bad one — 655 synthetic prices from a demo mode that had leaked into
> production and silently shadowed real market data for 131 days."

**1:15 — FIFO in SQL** *(≈35s)*
> "The hardest query was realized P&L, which needs each sale matched to the
> specific shares it disposed of. That's normally a Python loop."
>
> "Instead: picture every share as a point on a number line. A buy covers an
> interval, a sale consumes one, and under FIFO they match exactly where the
> intervals overlap. Two window functions and an inequality join."

Show `queries.sql`, the `fifo_matches` block.

**1:50 — The capstone, and the failure** *(≈70s)*
> "The capstone is five layers, one per phase. Here's the thing: the first time
> I ran it, it recommended putting everything into four stocks at a projected
> 124% annual return."

Show the naive-vs-robust frontier chart.

> "That's Markowitz error maximization. The optimizer treats expected returns as
> known, but they're the noisiest estimates in the procedure — so it loads onto
> whichever one is most favourably wrong. Those four names happened to return
> 116 to 131 percent in my estimation window."
>
> "Two shrinkage estimators from the literature and a position cap fixed it.
> Covariance conditioning improved 23-fold, and the recommendation went from
> four holdings to seven."

**3:00 — The result** *(≈40s)*

Show the frontier chart with both portfolios.

> "Against my actual allocation: 62% less volatility, Sharpe from 0.64 to 1.00,
> and a double-digit loss goes from a 32% chance to under 10% — for 17 points
> less expected return. It adds gold and a dividend fund, neither of which I
> held, and neither of which is there for its return. They're there for low
> correlation, which is the thing you can't eyeball."

**3:40 — The result I didn't expect** *(≈45s)*
> "I'd spent a month measuring fat tails, so I expected the fat-tailed
> simulation to give a much worse VaR. It barely moved — about 4% worse over a
> day, and nothing over a year."
>
> "That's the Central Limit Theorem. An annual return is a sum of 252 daily
> draws, and heavy tails wash out under summation. So fat tails dominate
> short-horizon risk and stop mattering at long horizons. The real long-horizon
> danger is dependence — volatility clustering — which my model doesn't capture
> and therefore understates. I'd rather end on a limitation I can name than a
> confident number."

**4:25 — Close** *(≈20s)*
> "603 tests across eleven suites. Four real defects came from tests rather than
> review, including an index that changed which rows a report returned. Building
> it was the easy half — establishing it tells the truth was the work."

---

## GitHub profile README

Drop into a repo named after your username.

```markdown
### Theoneste Ndahimana

Engineering student at Northwestern, building quantitative systems.

**[Quant Summer 2026](https://github.com/theoneste2028/quant-summer-2026)** — a
12-week platform consolidating probability, data management, and engineering
economics into a portfolio optimizer that runs on a real brokerage history.
SQLite data layer, CVXPY optimization, utility-based selection, Monte Carlo
risk. 603 tests.

Recent things I learned the hard way:
- `INSERT OR IGNORE` is error suppression, not idempotency
- An index can change *which rows* a report returns, if the sort has ties
- Markowitz optimization is an error maximizer without shrinkage
- Fat tails dominate daily risk and wash out over a year — the CLT does not care
  how heavy your tails are once you sum 252 of them

Python · SQL · CVXPY · pandas · Monte Carlo
```

---

## Before you publish

- [ ] `python run_all_tests.py` — expect 603 passed, 0 failed
- [ ] Regenerate the site export if the model changed
- [ ] Decide on `WEEK6_SUMMARY.md`, which contains aggregate dollar figures.
      The site page is already indexed to 100; the summary is not.
- [ ] Confirm `data/` is still gitignored (it holds real trades)
- [ ] Push: `git push --force-with-lease origin main`
