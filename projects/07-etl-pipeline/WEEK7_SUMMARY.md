# Week 7 Summary — ETL Pipeline + SQL vs. NoSQL
**Course:** CS 217 · **Author:** Tteddy

> All numbers are real output from `etl.py` and `news_pipeline.py` against the
> live portfolio database (28,791 price rows through 2026-08-10; 71 news
> articles across 12 held tickers).

## Question
A manual refresh fails silently: you skip a day, a bad row slips in, and weeks
later the analysis is quietly wrong. What separates a pipeline from a script
that happens to insert rows? And where does the relational model stop being the
right tool?

## Part 1 — The pipeline

`etl.py` pulls daily OHLCV for every traded ticker and loads it under four
guarantees.

**Validated.** Twelve rejection rules, each corresponding to a way the feed has
actually been wrong: null price fields, non-positive prices, `high < low`, an
open or close outside the day's own `[low, high]` band, negative volume,
unparseable or future dates, unknown tickers, and dates already stored. Bad rows
are rejected *with a reason* and counted in the log, never coerced.

The band checks matter more than they look. Each number in `open=99, high=11,
low=9, close=10.5` is individually plausible; only the relationship between them
reveals the bar is corrupt.

**Transactional.** One `BEGIN … COMMIT` for the whole batch. If row 400 of 500
violates a constraint, the first 399 do not survive — a partial day is worse
than no day, because it looks complete.

**Idempotent.** Re-running any date inserts nothing:

```
RUN 1:  extracted=658  accepted=658  rejected=0   inserted=658  elapsed=1.26s
RUN 2:  nothing to do: database is current through 2026-08-10
RUN 3 (forced --date 2026-08-07):
        extracted=60   accepted=0    rejected=60  inserted=0
        rejected 60 row(s): already present in database
```

**Logged.** Rows extracted, accepted, rejected (grouped by reason), inserted,
and elapsed runtime go to `logs/etl.log`.

### The bug the tests found

The first version used `INSERT OR IGNORE`, which the brief suggests for
idempotency. The test that fed it a batch containing one row with `close = -5`
expected the whole batch to roll back. It didn't: **`OR IGNORE` suppresses every
constraint violation, not just duplicate keys.** The bad row was silently
dropped and the rest committed — the exact silent-partial-success the pipeline
exists to prevent.

The fix separates the two concerns that `OR IGNORE` conflates:

- **Idempotency** belongs to `validate()`, which drops rows whose `(ticker,
  date)` is already stored, and to the catch-up window, which starts from the
  last stored date so settled days are never re-fetched.
- **Integrity** belongs to `load()`, which uses a plain `INSERT`, so anything
  that reaches it and violates a constraint takes the whole batch down loudly.

The primary key changed role from mechanism to backstop. That is the more
useful design: a duplicate reaching `load()` now means validation was bypassed,
which is a bug worth a stack trace rather than a silent no-op.

## Part 2 — SQL vs. MongoDB, on the same data

To compare honestly, the *same* 71 articles go into both stores, each modelled
the way that store wants:

| | SQLite | MongoDB |
|:--|:--|:--|
| Shape | `news` (flattened columns) + `news_tickers` (junction) | one document per article, near-verbatim |
| Ticker links | second table, 82 rows | one array field |
| Nested provider/URL/thumbnail | flattened to columns, sub-objects dropped | kept whole |

An article can mention several tickers, so the relationship is many-to-many:
in SQL that costs a junction table and a join; in Mongo it is `tickers: [...]`.

Yahoo's per-ticker feeds turn out to be completely disjoint — 71 articles across
12 tickers with zero overlap — so an **enrichment step** tags each article with
every portfolio ticker its text mentions (symbols plus company-name aliases,
skipping symbols under three characters because `PL`, `MU` and `T` collide with
ordinary words). That found 11 extra mentions and produced 9 genuinely
multi-ticker articles. Without it the array-vs-junction comparison would have
been vacuous, which is itself a lesson: the interesting structure in this data
had to be *created* by the pipeline, not just carried through it.

### The seven questions

Queries 1–6 return **identical results from both stores**:

| # | Question | Answer |
|--:|:--|--:|
| 1 | Latest 5 articles for GOOGL | same 5, same order |
| 2 | Article count per ticker | same top 5 |
| 3 | Articles published since a date | 26 |
| 4 | Top publishers | Zacks 27, Simply Wall St. 17, … |
| 5 | Titles mentioning "AI" | 21 |
| 6 | Articles mentioning >1 ticker | 9 |

Query 7 is the one that separates them: *how many articles carry a thumbnail
with more than one stored resolution?* Mongo answers immediately — **55** — with
`{"$gt": [{"$size": "$thumbnail.resolutions"}, 1]}`. SQL cannot answer at all,
because `thumbnail.resolutions` was discarded when the document was flattened.
Getting it would require a schema migration and a re-load of source data that
may no longer be available.

### Schema-on-write vs. schema-on-read

The distinction is **when** you are forced to decide what the data means.

*Schema-on-write* (SQL) decides at insert time. The cost is that you must know
the shape up front, and anything not modelled is lost at the door — question 7
is unanswerable not because SQLite is weak but because a decision made during
loading threw the field away. The benefit is that everything which did get in is
guaranteed conformant: the Week 6 P&L queries can assume every trade has a
positive quantity and a valid side, because the engine refused everything else.

*Schema-on-read* (MongoDB) defers the decision. Store the document, work out
what it means when you query. The benefit is that unanticipated questions stay
answerable, and a feed that adds a field next month does not break ingestion.
The cost is that nothing guarantees a field exists or has a consistent type, so
every query carries the burden — hence `$ifNull` guarding the array size above,
which exists because some articles have no thumbnail at all.

**Transactions differ in scope, not existence.** SQLite gives ACID across any
number of rows and tables: the Week 6 demo rolls back a security, a trade and a
price together. MongoDB guarantees atomicity for a single document for free —
which covers more than it sounds, since an article and its ticker array are one
document, where the relational version needs two tables kept in step. Beyond one
document, Mongo needs explicit multi-document transactions and a replica set.

**When I'd choose each.** Prices, trades, positions — SQL, without hesitation.
The shape is stable, the invariants are the point, and the questions are
aggregations across many rows. News, filings, earnings-call text — documents.
The shape drifts, most fields are read rarely, and the useful queries are
"find me the ones that mention X". This project needs both, which is why it has
both, and the interesting engineering is the boundary: the enrichment step is
where the document world hands the relational world a clean, typed fact.

## Scheduling

```bash
crontab -e
# Weekdays at 18:30, after the US close has settled:
30 18 * * 1-5 cd ~/Desktop/projects/quant-summer-2026 && \
  .venv/bin/python projects/07-etl-pipeline/etl.py --quiet >> \
  projects/07-etl-pipeline/logs/cron.log 2>&1
```

`--quiet` suppresses console output but keeps the file log. Because the job is
idempotent, a missed day self-heals: the next run's catch-up window starts from
the last stored date and backfills everything since.

## Testing
`test_etl.py` runs **54 checks**, all offline against scratch databases: every
validation rule with a row that must be rejected for exactly that reason, whole-
batch rollback, both layers of idempotency, log contents, news flattening and
enrichment, and SQL/Mongo agreement on all seven questions. The `OR IGNORE` bug
above was caught by these tests, not by inspection.

MongoDB runs against a real server when one is reachable and falls back to
`mongomock` in-process otherwise; the pymongo calls are identical either way.
Note that mongomock starts empty each run, so its totals reflect one batch,
unlike the persistent SQLite file.

## So what?
Week 8 asks what indexes actually buy on millions of rows — and this pipeline is
what keeps the table it will measure honest. Week 11 reads returns from these
tables rather than making fresh yfinance calls, which is only safe because
ingestion now validates before it writes and fails loudly when it cannot.
