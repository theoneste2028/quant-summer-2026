# Week 8 — Index Benchmark Results

Dataset: **2,964,624 rows**, mean of 5 runs after a warm-up run.

| Query | Before (ms) | Plan | After (ms) | Plan | Speed-up |
|:--|--:|:--|--:|:--|--:|
| Q1 point lookup | 93.7 | FULL SCAN | 43.5 | INDEX SEEK | 2.2x |
| Q2 date range scan | 105.5 | FULL SCAN | 13.3 | INDEX SEEK | 7.9x |
| Q3 group-by aggregation | 422.1 | FULL SCAN | 295.8 | INDEX SCAN | 1.4x |
| Q4 join to zone lookup | 130.9 | FULL SCAN | 76.7 | INDEX SEEK | 1.7x |
| Q5 filtered sort | 96.5 | FULL SCAN | 9.6 | INDEX SEEK | 10.0x |

Database grew from 268 MB to 503 MB (+235 MB of index pages).

## Write cost
- 20,000 inserts without indexes: 10 ms
- same inserts with 4 indexes: 36 ms (**3.77x slower**)

## Composite column order
- `filter pu_location_id (low cardinality, ~260 values) | (pu_location_id, pickup_ts)  leading matches` → 51.1 ms [INDEX SEEK]
- `filter pu_location_id (low cardinality, ~260 values) | (pickup_ts, pu_location_id)  leading does NOT match` → 94.9 ms [FULL SCAN]
- `filter pickup_ts (high cardinality, ~1575706 values) | (pickup_ts, pu_location_id)  leading matches` → 13.8 ms [INDEX SEEK]
- `filter pickup_ts (high cardinality, ~1575706 values) | (pu_location_id, pickup_ts)  leading does NOT match` → 30.5 ms [INDEX SKIP-SCAN]
