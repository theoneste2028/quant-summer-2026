# Portfolio Database & SQL Analytics

> **Course:** CS 217 · **Weeks:** 5-6 · **Status:** ✅ Week 5 complete, ✅ Week 6 complete

## Problem
Portfolio data scattered across brokerage exports is unqueryable and error-prone.
A normalized SQLite schema with constraints becomes the single source of truth
(Week 5); SQL over it answers questions no brokerage app will (Week 6).

## Approach

**Week 5 — storage**
- 3NF schema: securities, trades, prices, dividends (see `sql/schema.sql`).
- Constraints as data quality: CHECKs, FKs, composite PKs.
- Fidelity CSV parser handling junk headers, signed/fractional quantities,
  dividend reinvestments, and both export layouts.
- Transactional loading with rollback; yfinance price backfill.
- `source_ref UNIQUE` makes re-loading an export a no-op.

**Week 6 — analytics**
- Nine documented queries in `sql/queries.sql`, including FIFO lot matching
  done in pure SQL via interval-overlap window functions.
- ACID demonstrations that print observed behaviour rather than asserting it.
- 49-check test suite: hand-computed FIFO cases plus invariants on real data.

## How to run
```bash
cd projects/05-portfolio-database

python build_db.py ~/Downloads/Accounts_History.csv   # build from a real export
python build_db.py --demo                             # offline demo, separate DB

python dashboard.py                                   # all queries + charts
python dashboard.py positions                         # a single query
python dashboard.py --list                            # query names

python transactions.py                                # ACID demonstrations
python test_queries.py                                # test suite
```
DB lands at `data/portfolio.db` (gitignored — it holds real trades). Browse with
the SQLite Viewer extension.

## Files
- `sql/schema.sql` — schema with constraints and the idempotency key
- `sql/queries.sql` — the nine analytical queries, documented
- `sql/er_diagram.mermaid` — ER diagram (render at mermaid.live or in Lucidchart)
- `build_db.py` — parser + loader + backfill + constraint verification
- `dashboard.py` — query runner, charts, portfolio summary
- `transactions.py` — atomicity / consistency / isolation / durability demos
- `test_queries.py` — 49 checks across synthetic and real data
- `sample_fidelity.csv` — sample in the trimmed Fidelity format
- `WEEK5_SUMMARY.md`, `WEEK6_SUMMARY.md` — writeups

## Headline result
14 open positions. Indexed to market value = 100: cost basis 110.6, realized
P&L +7.9 (FIFO, net of fees) against −10.6 unrealized. The sector query
surfaced a 44.0% concentration in
leveraged 2x ETFs across seven positions — invisible when each is viewed on its
own, and the source of the four largest unrealized losses.
