# Week 5 Summary — Portfolio Database: Schema Design & Build
**Course:** CS 217 · **Author:** Tteddy

## Question
Turn scattered brokerage exports into one queryable source of truth where bad data is structurally impossible to insert.

## Schema (3NF)
Four tables: `securities` (1 row per instrument), `trades` (1 per execution), `prices` (1 per ticker-day), `dividends` (1 per ticker-ex-date). ER diagram: `sql/er_diagram.mermaid` (render in Lucidchart or mermaid.live).

**Normalization reasoning:**
- Security attributes (name, sector) live only in `securities` — repeating them per trade would be a transitive dependency (trade → ticker → name). 1 update point, no inconsistency.
- `prices` uses composite PK (ticker, date): the close depends on the *whole* key, no partial dependencies — duplicate days are rejected by the PK itself.
- No derived values stored (no position totals, no P&L) — those are queries (Week 6), so they can never go stale.

**Constraints as data quality:** `CHECK(quantity > 0)`, `CHECK(side IN ('BUY','SELL'))`, `CHECK(close > 0)`, FKs with `PRAGMA foreign_keys = ON`. Verified: negative quantities, invalid sides, unknown tickers, and duplicate price days are all rejected with `IntegrityError`.

## Fidelity loader
`build_db.py` parses the real Fidelity activity export: locates the header row (skipping junk lines), infers side from quantity sign, stores `abs(quantity)` as REAL (fractional shares like −0.5 TQQQ load correctly), fills blank fees with 0, and loads securities+trades in a single transaction with rollback on failure.

## Results (demo run)
7 trades / 5 securities loaded from a sample CSV in the real Fidelity format; 655 price rows backfilled; all 4 constraint checks rejected bad inserts.

## What I learned
Constraints move data validation from "hope the loader is careful" to "the database physically refuses" — the same validate-before-trust habit as Phase 1, enforced by the engine.

## So what?
Week 6 turns this storage into analytics: positions, FIFO P&L, sector exposure — all as SQL against these four tables.
