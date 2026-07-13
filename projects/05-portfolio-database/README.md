# Portfolio Database & SQL Analytics

> **Course:** CS 217 · **Weeks:** 5-6 · **Status:** ✅ Week 5 complete, Week 6 pending

## Problem
Portfolio data scattered across brokerage exports is unqueryable and error-prone.
A normalized SQLite schema with constraints becomes the single source of truth.

## Approach (Week 5)
- 3NF schema: securities, trades, prices, dividends (see `sql/schema.sql`).
- Constraints as data quality: CHECKs, FKs, composite PKs.
- Fidelity CSV parser handling junk headers, signed/fractional quantities.
- Transactional loading with rollback; yfinance price backfill.

## How to run
```bash
cd projects/05-portfolio-database
python build_db.py --demo                    # offline demo (sample CSV + synthetic prices)
python build_db.py ~/Downloads/activity.csv  # real: your Fidelity export + live backfill
```
DB lands at `data/portfolio.db` (gitignored). Browse with the SQLite Viewer extension.

## Files
- `sql/schema.sql` — schema with constraints
- `sql/er_diagram.mermaid` — ER diagram (render at mermaid.live or recreate in Lucidchart)
- `build_db.py` — parser + loader + backfill + constraint verification
- `sample_fidelity.csv` — sample in the real Fidelity format
- `WEEK5_SUMMARY.md` — writeup
