# The database found bugs I could not see

**Phase 2 · CS 217 · Weeks 5–8**

My portfolio data lived where most people's does: brokerage exports, a
spreadsheet, and whatever `yfinance` returned when I happened to run a script.
Scattered, duplicated, and impossible to query reliably. The plan for this phase
was to normalise it into SQLite and then ask it interesting questions.

What actually happened is that the questions found three bugs in the data — and
one of them had been silently corrupting my prices for weeks.

## Constraints as a design tool

The schema is four tables in third normal form: `securities`, `trades`,
`prices`, `dividends`. Every table carries constraints that make bad data
structurally impossible rather than merely discouraged — `CHECK(quantity > 0)`,
`CHECK(side IN ('BUY','SELL'))`, foreign keys to `securities`, and a composite
primary key on `(ticker, date)` so a duplicate price day cannot exist.

The design rule I committed to was: **store only what was observed, derive
everything else.** No position totals, no cost basis, no P&L columns. Those are
queries. A stored total goes stale the moment a trade lands and nobody notices;
a query cannot.

That decision is what surfaced the bugs.

## Three defects, found by asking for impossible states

When I wrote the position query in Week 6, three tickers came back with
*negative* share counts. IREN at −100, TQQQ at −1.5, FXAIX at −0.006. A
long-only cash account cannot hold negative shares. Any query returning one is
reporting a fact about the world that is not true.

Tracing each:

**Seven duplicated trades.** The sample CSV I had used to test the loader was
also a subset of my real export, and I had loaded both. The loader had no notion
of whether a row was already present, so it cheerfully inserted everything
twice.

**655 fabricated price rows.** This was the bad one. The offline demo mode
generated synthetic random-walk prices so the project could run without
internet — and it wrote them into the production database. Because the price
insert used `INSERT OR IGNORE`, and because the synthetic rows landed first,
the *real* yfinance prices for those five tickers were silently skipped for 131
trading days. Every valuation I had computed in that window was wrong, and
nothing had complained. I caught it by querying for the demo's signature:
synthetic rows had `open` exactly equal to `close × 0.99`.

**Two lost share lots.** The parser kept only rows whose action contained
`BOUGHT` or `SOLD`, which discarded `REINVESTMENT` rows. Dividend reinvestments
are genuine share purchases, so fractional shares were vanishing.

Two schema changes make the first two impossible to repeat. `trades` gained a
`source_ref` column — a fingerprint of the source CSV row including its line
number — with a `UNIQUE` constraint, so re-running any export inserts nothing.
The line number matters: two identical fills on the same day at the same price
are real, and hashing content alone would silently merge them. And `--demo` now
writes to its own database file, so synthetic and observed data never share a
table again.

## FIFO in pure SQL

The hardest query was realised profit and loss, which requires matching each
sale to the specific shares it disposed of. FIFO is a sequential rule, which is
why it is usually written as a Python loop over a queue of lots. The brief
suggested exactly that.

It can be done in one query instead, and the trick is worth knowing.

Picture every share of a ticker as occupying a point on a number line: the first
share ever bought sits at position 0, the next at 1. A purchase of *q* shares
then covers the interval `[bought_before, bought_before + q)`, and a sale of *q*
shares consumes `[sold_before, sold_before + q)`. Under FIFO a sale always
consumes the lowest unsold positions — which means **a buy lot and a sale are
matched exactly where their intervals overlap**, and the matched quantity is the
length of that overlap.

Two cumulative-sum window functions produce the intervals; an inequality join
finds the overlaps. No cursor, no loop. The same arithmetic answers the other
half: a lot's shares are still held when its interval lies above everything sold
so far, which gives the FIFO cost basis for open positions. Realised and
unrealised P&L end up on one consistent basis instead of two that quietly
disagree.

## What the analytics actually showed

Once the data was trustworthy: 14 open positions, and — indexing to market
value = 100 — a cost basis of 120.8, realised P&L of +8.7 across 57 tickers with
closed round trips, against −20.8 unrealised.

The sector query surfaced something no brokerage screen had shown me: **41.5% of
the portfolio sat in leveraged 2× ETFs**, spread across seven separate
positions. Individually each looked like a modest holding. Aggregated, it was
the single largest exposure in the book — and those same instruments held the
four largest unrealised losses, at −72%, −69%, −57% and −45%. That is the
volatility-decay behaviour daily-rebalanced leveraged funds exhibit over
multi-week holds, and it was invisible until the data was in one place and I
could ask a question nobody had built a screen for.

## Automating it, and the trap in the obvious solution

Week 7's ETL pipeline ingests daily prices under four guarantees: twelve
validation rules, one transaction per batch, idempotency, and structured
logging.

The brief suggested `INSERT OR IGNORE` for idempotency. My tests found that this
is a mistake. I fed the loader a batch containing one row with a negative price
and asserted the entire batch should roll back. It did not: **`OR IGNORE`
suppresses every constraint violation, not just duplicate keys.** The bad row
was silently dropped and the remaining rows committed — the exact
silent-partial-success the pipeline exists to prevent.

The fix separates the two concerns that `OR IGNORE` conflates. Idempotency
belongs to validation, which drops rows whose `(ticker, date)` is already
stored. Integrity belongs to the transaction, which uses a plain `INSERT` so
anything violating a constraint takes the whole batch down loudly. The primary
key changed role from mechanism to backstop.

## What indexes actually buy

Week 8 loaded 2.96 million NYC taxi trips and timed five query shapes with and
without indexes. Speed-ups ranged from 10.0× on a filtered sort down to 1.4× on
a group-by aggregation.

The 1.4× case is the instructive one. Its query plan still says `SCAN`, not
`SEARCH`. With roughly five distinct payment types across three million rows
there is nothing to narrow — every row contributes to a group — so the index did
not eliminate a single row. What it removed was the *sort*, because the index
was already in the right order. An index helps in proportion to how much of the
table it lets you avoid looking at, and when the answer needs every row, the
best it can do is change how you read them.

The cost side is rarely quoted: the database grew from 268 MB to 503 MB, an 88%
increase, and inserts became 3.77× slower.

The sharpest finding came from a failing test. I had asserted that every query
must return identical results with and without indexes — an index changes
timing, never answers. Two queries failed. Both had an `ORDER BY` with ties and
no tie-breaker, so the output order depended on the access path, and **adding an
index changed which rows the report returned.** On real data the counts happened
to differ and it looked stable. Synthetic test data made the ties explicit.

A query whose result depends on the plan is a latent bug that surfaces the day
someone indexes the table for unrelated reasons. I would not have found it by
reading the SQL.
