"""
Week 8 — Query Optimization Study
=================================
CS 217. Five realistic queries against ~2.96M NYC taxi trips, timed with no
indexes and again with indexes, with the query plan recorded both times.

The interesting result is not "indexes make things faster". It is *which*
queries they help, by how much, and the one where adding an index changes
nothing at all — because that is the case that separates understanding B-trees
from cargo-culting `CREATE INDEX`.

Run:
    python benchmark.py                 # full study, writes results/ + charts
    python benchmark.py --repeat 3      # fewer timing runs (default 5)
"""
from __future__ import annotations
import os, sys, time, json, sqlite3, argparse

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB_PATH = os.path.join(REPO, "data", "taxi", "taxi.db")
RESULTS = os.path.join(HERE, "results")

# ---------------------------------------------------------------------------
# The five queries
# ---------------------------------------------------------------------------
# Each is a shape you actually write against trip data, chosen so the set spans
# the range from "an index is transformative" to "an index is irrelevant".
QUERIES = {
    "Q1 point lookup": {
        "sql": """SELECT COUNT(*) AS trips, ROUND(AVG(fare_amount),2) AS avg_fare
                  FROM trips WHERE pu_location_id = 132""",
        "note": "All trips from one zone (JFK). Highly selective — the classic "
                "case an index is built for.",
    },
    "Q2 date range scan": {
        "sql": """SELECT COUNT(*) AS trips, ROUND(SUM(total_amount),2) AS revenue
                  FROM trips
                  WHERE pickup_ts >= '2024-01-15' AND pickup_ts < '2024-01-16'""",
        "note": "One day out of 31. Contiguous in index order, so the B-tree "
                "can seek once and walk.",
    },
    "Q3 group-by aggregation": {
        # ORDER BY trips DESC alone is NOT deterministic: when two payment types
        # have equal counts the tie is broken by whatever order rows arrived in,
        # which the access path decides. Adding an index then silently changes
        # the output. `payment_type` is unique per group, so it settles ties.
        "sql": """SELECT payment_type, COUNT(*) AS trips,
                         ROUND(AVG(fare_amount),2) AS avg_fare
                  FROM trips GROUP BY payment_type
                  ORDER BY trips DESC, payment_type""",
        "note": "Every row contributes to the answer. Predicted: the index "
                "cannot help, because there is nothing to narrow.",
    },
    "Q4 join to zone lookup": {
        # z.zone breaks count ties, for the same reason as Q3 and Q5.
        "sql": """SELECT z.zone, COUNT(*) AS trips
                  FROM trips t JOIN zones z ON z.location_id = t.do_location_id
                  WHERE t.pu_location_id = 132
                  GROUP BY z.zone ORDER BY trips DESC, z.zone LIMIT 10""",
        "note": "Selective filter on the big table, then a 265-row lookup "
                "probed by primary key.",
    },
    "Q5 filtered sort": {
        # Same trap, sharper: a LIMIT over a tied sort returns an arbitrary
        # subset, so an index can change *which rows the report shows* rather
        # than merely their order. trip_id is the primary key, so it makes the
        # ordering total.
        "sql": """SELECT pickup_ts, fare_amount, trip_distance
                  FROM trips
                  WHERE pu_location_id = 138
                    AND pickup_ts >= '2024-01-10' AND pickup_ts < '2024-01-17'
                  ORDER BY fare_amount DESC, trip_id LIMIT 20""",
        "note": "Two predicates on the same table — the case a COMPOSITE index "
                "is for.",
    },
}

INDEXES = [
    ("idx_trips_pu",        "CREATE INDEX idx_trips_pu ON trips(pu_location_id)"),
    ("idx_trips_pickup",    "CREATE INDEX idx_trips_pickup ON trips(pickup_ts)"),
    ("idx_trips_pu_pickup", "CREATE INDEX idx_trips_pu_pickup "
                            "ON trips(pu_location_id, pickup_ts)"),
    # Added deliberately to demonstrate an index that earns nothing: payment_type
    # has ~5 distinct values across 3M rows, so it cannot narrow anything.
    ("idx_trips_payment",   "CREATE INDEX idx_trips_payment ON trips(payment_type)"),
]


# ---------------------------------------------------------------------------
def connect(db=DB_PATH):
    con = sqlite3.connect(db)
    return con


def drop_indexes(con):
    for name, _ in INDEXES:
        con.execute(f"DROP INDEX IF EXISTS {name}")
    con.execute("ANALYZE")          # refresh planner stats for the no-index state
    con.commit()


def build_indexes(con) -> dict:
    """Create every index, timing each. Returns {name: seconds}."""
    times = {}
    for name, ddl in INDEXES:
        t0 = time.perf_counter()
        con.execute(ddl)
        con.commit()
        times[name] = time.perf_counter() - t0
        print(f"    built {name:22} in {times[name]:6.2f}s")
    # Without ANALYZE, SQLite's planner works from heuristics rather than
    # measured selectivity, and can pick a worse index than the one available.
    con.execute("ANALYZE")
    con.commit()
    return times


def time_query(con, sql, repeat=5) -> dict:
    """Run once to warm the cache, then `repeat` timed runs. Returns ms stats."""
    cur = con.cursor()
    cur.execute(sql).fetchall()                     # warmup
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        rows = cur.execute(sql).fetchall()
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    return {"mean_ms": sum(times) / len(times), "min_ms": times[0],
            "max_ms": times[-1], "rows": len(rows), "result": rows[:3]}


def plan(con, sql) -> str:
    rows = con.execute("EXPLAIN QUERY PLAN " + sql).fetchall()
    return " | ".join(r[-1].strip() for r in rows)


def driving_step(plan_text: str) -> str:
    """The outermost loop of the plan — the step whose cost dominates.

    A join plan concatenates several steps, and the inner ones are almost always
    indexed seeks (here, a 265-row lookup by primary key). Classifying the whole
    string would call a query 'indexed' on the strength of its cheapest step
    while the driving table is being scanned end to end.
    """
    for step in plan_text.split(" | "):
        s = step.upper()
        if s.startswith("SCAN") or s.startswith("SEARCH"):
            return step
    return plan_text


def scan_kind(plan_text: str) -> str:
    """Condense a query plan into the one fact that matters.

    The distinction that counts is SEARCH vs SCAN, not indexed vs not:
      SEARCH ... USING INDEX  -> a seek: descend the B-tree, touch matching rows
      SCAN ... USING INDEX    -> still every row, just read from the narrower
                                 index instead of the table (or to get free
                                 ordering). No selectivity gained.
      SCAN <table>            -> full table scan
    Collapsing those two index cases into one label is exactly how you end up
    believing an index helped when it only removed a sort.
    """
    p = plan_text.upper()
    seek = "SEARCH" in p
    if "ANY(" in p and seek:
        return "INDEX SKIP-SCAN"
    if "USING COVERING INDEX" in p:
        return "COVERING SEEK" if seek else "COVERING SCAN"
    if "USING INDEX" in p or "USING INTEGER PRIMARY KEY" in p:
        return "INDEX SEEK" if seek else "INDEX SCAN"
    if "SCAN" in p:
        return "FULL SCAN"
    return "?"


# ---------------------------------------------------------------------------
def run_study(db=DB_PATH, repeat=5):
    os.makedirs(RESULTS, exist_ok=True)
    con = connect(db)
    n = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    print(f"Dataset: {n:,} trips, {os.path.getsize(db)/1e6:.0f} MB\n")

    print("Phase 1 — no indexes")
    drop_indexes(con)
    # VACUUM before measuring: DROP INDEX releases pages to SQLite's free list
    # but does not shrink the file, so an unvacuumed "before" still carries the
    # previous run's index pages and the comparison comes out negative.
    con.execute("VACUUM")
    size_before = os.path.getsize(db)
    before = {}
    for name, q in QUERIES.items():
        p = plan(con, q["sql"])
        t = time_query(con, q["sql"], repeat)
        before[name] = {**t, "plan": p, "scan": scan_kind(driving_step(p))}
        print(f"  {name:26} {t['mean_ms']:9.1f} ms   [{scan_kind(driving_step(p))}]")

    print("\nPhase 2 — building indexes")
    build_times = build_indexes(con)
    con.execute("VACUUM")           # so the size delta reflects index pages only
    size_after = os.path.getsize(db)

    print("\nPhase 3 — with indexes")
    after = {}
    for name, q in QUERIES.items():
        p = plan(con, q["sql"])
        t = time_query(con, q["sql"], repeat)
        after[name] = {**t, "plan": p, "scan": scan_kind(driving_step(p))}
        speed = before[name]["mean_ms"] / t["mean_ms"] if t["mean_ms"] else float("inf")
        print(f"  {name:26} {t['mean_ms']:9.1f} ms   [{scan_kind(driving_step(p))}]  "
              f"{speed:6.1f}x")

    write_cost = measure_write_cost(con)
    composite = composite_order_experiment(con, repeat)

    con.close()
    return {"n_rows": n, "before": before, "after": after,
            "build_times": build_times, "repeat": repeat,
            "size_before_mb": size_before / 1e6, "size_after_mb": size_after / 1e6,
            "write_cost": write_cost, "composite": composite}


def measure_write_cost(con, n_rows=20_000):
    """Indexes are not free: every INSERT must also update every index.

    Measured by inserting the same rows twice — once with the indexes in place,
    once without — into a scratch table shaped like `trips`.
    """
    print("\nPhase 4 — write cost of indexes")
    rows = [(1, f"2024-02-{(i % 28) + 1:02d} 12:00:00", None, 1, 1.5,
             (i % 260) + 1, (i % 260) + 1, (i % 4) + 1, 10.0, 2.0, 12.0)
            for i in range(n_rows)]
    ins = """INSERT INTO bench_w (vendor_id,pickup_ts,dropoff_ts,passenger_count,
             trip_distance,pu_location_id,do_location_id,payment_type,
             fare_amount,tip_amount,total_amount) VALUES (?,?,?,?,?,?,?,?,?,?,?)"""
    ddl = """CREATE TABLE bench_w (
                trip_id INTEGER PRIMARY KEY, vendor_id INTEGER, pickup_ts TEXT,
                dropoff_ts TEXT, passenger_count INTEGER, trip_distance REAL,
                pu_location_id INTEGER, do_location_id INTEGER,
                payment_type INTEGER, fare_amount REAL, tip_amount REAL,
                total_amount REAL)"""

    con.execute("DROP TABLE IF EXISTS bench_w"); con.execute(ddl)
    t0 = time.perf_counter(); con.executemany(ins, rows); con.commit()
    plain = time.perf_counter() - t0

    con.execute("DROP TABLE IF EXISTS bench_w"); con.execute(ddl)
    con.execute("CREATE INDEX ix_w1 ON bench_w(pu_location_id)")
    con.execute("CREATE INDEX ix_w2 ON bench_w(pickup_ts)")
    con.execute("CREATE INDEX ix_w3 ON bench_w(pu_location_id, pickup_ts)")
    con.execute("CREATE INDEX ix_w4 ON bench_w(payment_type)")
    t0 = time.perf_counter(); con.executemany(ins, rows); con.commit()
    indexed = time.perf_counter() - t0
    con.execute("DROP TABLE IF EXISTS bench_w"); con.commit()

    print(f"  {n_rows:,} inserts, no indexes : {plain*1000:8.1f} ms")
    print(f"  {n_rows:,} inserts, 4 indexes  : {indexed*1000:8.1f} ms  "
          f"({indexed/plain:.2f}x slower)")
    return {"rows": n_rows, "plain_ms": plain * 1000,
            "indexed_ms": indexed * 1000, "ratio": indexed / plain}


def composite_order_experiment(con, repeat=5):
    """Does the column ORDER of a composite index matter? Measure it.

    A composite index on (a, b) is a B-tree sorted by a, then by b within equal
    a. It serves a lookup on `a` alone, because the a-values are contiguous. A
    lookup on `b` alone has no such run to seek to — b-values are scattered
    across every a block.

    BUT that textbook rule has an exception SQLite actually implements: if the
    leading column has few distinct values, the planner can loop over each of
    them and seek within it — a SKIP-SCAN. So the honest answer is "order
    matters, unless the leading column's cardinality is low enough to skip over".
    Both cases are measured below, on the same data.
    """
    print("\nPhase 5 — does composite column order matter?")
    con.execute("DROP INDEX IF EXISTS idx_trips_pickup")
    con.execute("DROP INDEX IF EXISTS idx_trips_pu_pickup")
    con.execute("DROP INDEX IF EXISTS idx_trips_pu")

    card = {r[0]: r[1] for r in con.execute(
        "SELECT 'pu', COUNT(DISTINCT pu_location_id) FROM trips "
        "UNION ALL SELECT 'ts', COUNT(DISTINCT pickup_ts) FROM trips")}
    print(f"  distinct pu_location_id: {card['pu']:,}   "
          f"distinct pickup_ts: {card['ts']:,}")

    experiments = [
        # Filter on a LOW-cardinality column. Wrong order is partly rescued by
        # skip-scan, because there are only a few hundred leading values.
        ("filter pu_location_id (low cardinality, ~%d values)" % card["pu"],
         "SELECT COUNT(*), SUM(total_amount) FROM trips WHERE pu_location_id = 132",
         [("(pu_location_id, pickup_ts)  leading matches",
           "CREATE INDEX ix_c ON trips(pu_location_id, pickup_ts)"),
          ("(pickup_ts, pu_location_id)  leading does NOT match",
           "CREATE INDEX ix_c ON trips(pickup_ts, pu_location_id)")]),
        # Filter on a HIGH-cardinality column. Skip-scan is not viable over
        # millions of leading values, so the wrong order collapses to a scan.
        ("filter pickup_ts (high cardinality, ~%d values)" % card["ts"],
         "SELECT COUNT(*), SUM(total_amount) FROM trips "
         "WHERE pickup_ts >= '2024-01-15' AND pickup_ts < '2024-01-16'",
         [("(pickup_ts, pu_location_id)  leading matches",
           "CREATE INDEX ix_c ON trips(pickup_ts, pu_location_id)"),
          ("(pu_location_id, pickup_ts)  leading does NOT match",
           "CREATE INDEX ix_c ON trips(pu_location_id, pickup_ts)")]),
    ]

    out = {}
    for header, q, variants in experiments:
        print(f"  {header}")
        for label, ddl in variants:
            con.execute("DROP INDEX IF EXISTS ix_c")
            con.execute(ddl); con.execute("ANALYZE"); con.commit()
            t = time_query(con, q, repeat)
            p = plan(con, q)
            key = f"{header} | {label}"
            out[key] = {"mean_ms": t["mean_ms"], "scan": scan_kind(driving_step(p)), "plan": p}
            print(f"    {label:44} {t['mean_ms']:8.1f} ms  [{scan_kind(driving_step(p))}]")

    con.execute("DROP INDEX IF EXISTS ix_c")
    # Restore the study's index set.
    for name, ddl in INDEXES:
        con.execute(ddl.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS"))
    con.execute("ANALYZE"); con.commit()
    return out


# ---------------------------------------------------------------------------
def write_outputs(study):
    os.makedirs(RESULTS, exist_ok=True)
    with open(os.path.join(RESULTS, "benchmark.json"), "w") as fh:
        json.dump(study, fh, indent=1, default=str)

    lines = ["# Week 8 — Index Benchmark Results\n",
             f"Dataset: **{study['n_rows']:,} rows**, "
             f"mean of {study['repeat']} runs after a warm-up run.\n",
             "| Query | Before (ms) | Plan | After (ms) | Plan | Speed-up |",
             "|:--|--:|:--|--:|:--|--:|"]
    for name in QUERIES:
        b, a = study["before"][name], study["after"][name]
        sp = b["mean_ms"] / a["mean_ms"] if a["mean_ms"] else float("inf")
        lines.append(f"| {name} | {b['mean_ms']:.1f} | {b['scan']} | "
                     f"{a['mean_ms']:.1f} | {a['scan']} | {sp:.1f}x |")
    lines += ["",
              f"Database grew from {study['size_before_mb']:.0f} MB to "
              f"{study['size_after_mb']:.0f} MB "
              f"(+{study['size_after_mb']-study['size_before_mb']:.0f} MB of index pages).",
              "",
              "## Write cost",
              f"- {study['write_cost']['rows']:,} inserts without indexes: "
              f"{study['write_cost']['plain_ms']:.0f} ms",
              f"- same inserts with 4 indexes: {study['write_cost']['indexed_ms']:.0f} ms "
              f"(**{study['write_cost']['ratio']:.2f}x slower**)",
              "", "## Composite column order"]
    for label, v in study["composite"].items():
        lines.append(f"- `{label}` → {v['mean_ms']:.1f} ms [{v['scan']}]")
    with open(os.path.join(RESULTS, "results_table.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")

    # Chart
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    names = list(QUERIES)
    b = [study["before"][n]["mean_ms"] for n in names]
    a = [study["after"][n]["mean_ms"] for n in names]
    x = np.arange(len(names)); w = 0.38
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(x - w/2, b, w, label="No indexes", color="0.35")
    ax.bar(x + w/2, a, w, label="With indexes", color="0.72")
    ax.set_yscale("log")
    ax.set_ylabel("Mean query time (ms, log scale)")
    ax.set_title(f"Index impact on {study['n_rows']:,} NYC taxi trips")
    ax.set_xticks(x)
    ax.set_xticklabels([n.replace(" ", "\n", 1) for n in names], fontsize=9)
    ax.legend(loc="upper right")
    ax.grid(axis="y", alpha=0.3, which="both")
    # Headroom above the tallest bar so the annotations cannot reach the title.
    ax.set_ylim(min(a + b) * 0.55, max(a + b) * 4.0)
    for i, (bb, aa) in enumerate(zip(b, a)):
        sp = bb / aa if aa else 0
        weak = sp < 1.5
        ax.text(i, max(bb, aa) * 1.25,
                f"{sp:.1f}x" + ("\n(no real gain)" if weak else ""),
                ha="center", va="bottom", fontsize=9,
                fontweight="bold" if weak else "normal")
    fig.tight_layout()
    fig.savefig(os.path.join(RESULTS, "index_speedup.png"), dpi=130)
    plt.close(fig)
    print(f"\nResults written to {RESULTS}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--repeat", type=int, default=5)
    a = ap.parse_args()
    if not os.path.exists(a.db):
        print(f"No database at {a.db}. Run: python load_taxi.py")
        return 1
    study = run_study(a.db, a.repeat)
    write_outputs(study)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
