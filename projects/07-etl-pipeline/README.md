# Market Data ETL Pipeline (SQL + MongoDB)

> **Course:** CS 217 · **Week:** 7 · **Status:** ✅ Complete

## Problem
Manual data refreshes fail silently. An automated, idempotent, transaction-safe
pipeline ingests daily OHLCV into SQLite, plus unstructured news into MongoDB —
a working SQL vs. NoSQL comparison on identical data.

## Approach
- `etl.py` — 12 validation rules, one transaction per batch, two layers of
  idempotency, structured logging of counts/reasons/runtime.
- Plain `INSERT` rather than `INSERT OR IGNORE`: `OR IGNORE` suppresses *every*
  constraint violation, which silently commits partial batches. Idempotency
  moved up into validation instead.
- `news_pipeline.py` — the same 71 articles loaded into SQLite (flattened +
  junction table) and MongoDB (documents), then seven questions asked of both.
- Enrichment tags articles with every portfolio ticker their text mentions,
  because Yahoo's per-ticker feeds are disjoint.
- `test_etl.py` — 54 offline checks.

## Results
Queries 1–6 return identical answers from both stores. Query 7 —
"articles whose thumbnail has more than one resolution" — is answered by Mongo
(**55**) and is *unanswerable* in SQL, because flattening dropped the
sub-document. That asymmetry is the whole schema-on-write vs. schema-on-read
argument in one query.

```
RUN 1:  extracted=658  accepted=658  rejected=0   inserted=658  elapsed=1.26s
RUN 2:  nothing to do: database is current through 2026-08-10
RUN 3:  extracted=60   accepted=0    rejected=60  inserted=0    (already present)
```

## How to run
```bash
# from repo root, with venv active
python projects/07-etl-pipeline/etl.py --dry-run        # validate, write nothing
python projects/07-etl-pipeline/etl.py                  # catch up to today
python projects/07-etl-pipeline/etl.py --date 2026-08-07

python projects/07-etl-pipeline/news_pipeline.py            # live news
python projects/07-etl-pipeline/news_pipeline.py --offline  # replay cache

python projects/07-etl-pipeline/test_etl.py             # 54 checks
```
MongoDB is used if reachable at `$MONGO_URI` (default `localhost:27017`),
otherwise `mongomock` runs in-process. Same pymongo calls either way.

## What I learned
`INSERT OR IGNORE` looks like an idempotency tool and is really an
error-suppression tool — it hid a negative-price row and committed the rest of
the batch, which the tests caught and inspection had not. Separating idempotency
(validation's job) from integrity (the transaction's job) made both stronger.
The SQL/NoSQL choice turned out not to be about speed at all but about *when*
you are forced to commit to a shape, and what it costs when the question you
want to ask arrives after that decision.
