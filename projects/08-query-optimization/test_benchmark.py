"""
Week 8 — Test suite for the index benchmark
===========================================
A benchmark that measures the wrong thing is worse than none, so the tests here
check the *methodology* as much as the code:

  * plan classification distinguishes a seek from a full index scan, and reads
    the driving loop of a join rather than its cheapest step
  * every query returns byte-identical results with and without indexes — an
    index must never change an answer, only the time taken to reach it
  * the queries are actually selective enough to be worth indexing (a "point
    lookup" that matches half the table is not testing what it claims)
  * timing helpers behave (warm-up excluded, repeat count honoured)

The heavy queries run against a small synthetic table so the suite finishes in
seconds; a final pass checks the real 2.9M-row database if it has been built.

Run:
    python test_benchmark.py
"""
from __future__ import annotations
import os, sys, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import benchmark as bm                                # noqa: E402

PASS, FAIL = [], []


def check(name, got, want):
    ok = got == want
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: got {got!r}, want {want!r}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


# ---------------------------------------------------------------------------
def test_plan_classification():
    print("\n--- Query-plan classification " + "-" * 46)
    cases = [
        ("SCAN trips", "FULL SCAN"),
        ("SEARCH trips USING INDEX idx_trips_pu (pu_location_id=?)", "INDEX SEEK"),
        ("SCAN trips USING INDEX idx_trips_payment", "INDEX SCAN"),
        ("SCAN trips USING COVERING INDEX ix_c", "COVERING SCAN"),
        ("SEARCH trips USING COVERING INDEX ix_c (pickup_ts>?)", "COVERING SEEK"),
        ("SEARCH trips USING COVERING INDEX ix_c (ANY(pu_location_id) AND pickup_ts>?)",
         "INDEX SKIP-SCAN"),
    ]
    for text, want in cases:
        check(f"classify {want}", bm.scan_kind(text), want)

    # A join plan must be judged by its driving loop, not its cheapest step.
    join_plan = ("SCAN t | SEARCH z USING INTEGER PRIMARY KEY (rowid=?) | "
                 "USE TEMP B-TREE FOR GROUP BY")
    check("driving step of a join", bm.driving_step(join_plan), "SCAN t")
    check("join with scanned driver classified as FULL SCAN",
          bm.scan_kind(bm.driving_step(join_plan)), "FULL SCAN")

    indexed_join = ("SEARCH t USING INDEX idx_trips_pu (pu_location_id=?) | "
                    "SEARCH z USING INTEGER PRIMARY KEY (rowid=?)")
    check("join with seeking driver classified as INDEX SEEK",
          bm.scan_kind(bm.driving_step(indexed_join)), "INDEX SEEK")

    # Non-scan preamble lines must be skipped when finding the driver.
    check("driving step skips CO-ROUTINE preamble",
          bm.driving_step("CO-ROUTINE (subquery) | SCAN trips | SEARCH z USING INDEX x"),
          "SCAN trips")


# ---------------------------------------------------------------------------
def make_small_db(n=20_000):
    """A miniature `trips` table with the same shape and skew as the real one."""
    path = os.path.join(tempfile.mkdtemp(prefix="wk8_"), "small.db")
    con = sqlite3.connect(path)
    con.executescript(bm_ddl())
    rows = []
    for i in range(n):
        day = (i % 28) + 1
        rows.append((1, f"2024-01-{day:02d} {(i % 24):02d}:00:00",
                     f"2024-01-{day:02d} {(i % 24):02d}:30:00",
                     1, 1.0 + (i % 50) / 10,
                     (i % 260) + 1, (i % 137) + 1, (i % 4) + 1,
                     5.0 + (i % 100), 1.0, 8.0 + (i % 100)))
    con.executemany(
        """INSERT INTO trips (vendor_id,pickup_ts,dropoff_ts,passenger_count,
           trip_distance,pu_location_id,do_location_id,payment_type,
           fare_amount,tip_amount,total_amount) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        rows)
    con.executemany("INSERT INTO zones VALUES (?,?,?,?)",
                    [(i, f"Boro{i%5}", f"Zone {i}", "Yellow") for i in range(1, 266)])
    con.commit()
    return con, path


def bm_ddl():
    return """
    CREATE TABLE trips (
        trip_id INTEGER PRIMARY KEY, vendor_id INTEGER, pickup_ts TEXT NOT NULL,
        dropoff_ts TEXT, passenger_count INTEGER, trip_distance REAL,
        pu_location_id INTEGER, do_location_id INTEGER, payment_type INTEGER,
        fare_amount REAL, tip_amount REAL, total_amount REAL);
    CREATE TABLE zones (location_id INTEGER PRIMARY KEY, borough TEXT,
        zone TEXT, service_zone TEXT);
    """


def test_results_unchanged_by_indexes():
    print("\n--- An index must never change an answer " + "-" * 35)
    con, path = make_small_db()

    before = {}
    for name, q in bm.QUERIES.items():
        before[name] = con.execute(q["sql"]).fetchall()

    bm.build_indexes(con)

    for name, q in bm.QUERIES.items():
        after = con.execute(q["sql"]).fetchall()
        check_true(f"{name} identical with indexes", before[name] == after,
                   f"before={before[name][:2]} after={after[:2]}")

    check_true("queries actually returned rows",
               all(len(v) > 0 for v in before.values()),
               str({k: len(v) for k, v in before.items()}))
    con.close()


def test_index_changes_plan():
    print("\n--- Indexes change the plan in the expected direction " + "-" * 22)
    con, path = make_small_db()

    p_before = bm.scan_kind(bm.driving_step(bm.plan(con, bm.QUERIES["Q1 point lookup"]["sql"])))
    check("Q1 scans without an index", p_before, "FULL SCAN")

    bm.build_indexes(con)
    p_after = bm.scan_kind(bm.driving_step(bm.plan(con, bm.QUERIES["Q1 point lookup"]["sql"])))
    check_true("Q1 seeks with an index", "SEEK" in p_after, p_after)

    # The designated no-win query must not become a seek: there is nothing to
    # narrow, so at best the planner swaps one full traversal for another.
    p3 = bm.scan_kind(bm.driving_step(bm.plan(con, bm.QUERIES["Q3 group-by aggregation"]["sql"])))
    check_true("Q3 never becomes a seek", "SEEK" not in p3, p3)
    con.close()


def test_selectivity_assumptions():
    print("\n--- The queries test what they claim " + "-" * 39)
    con, path = make_small_db()
    total = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]

    n1 = con.execute("SELECT COUNT(*) FROM trips WHERE pu_location_id = 132").fetchone()[0]
    check_true("Q1 filter is selective (<5% of rows)", n1 / total < 0.05,
               f"{n1}/{total} = {n1/total:.2%}")

    n3 = con.execute("SELECT COUNT(DISTINCT payment_type) FROM trips").fetchone()[0]
    check_true("Q3 groups on a low-cardinality column (<10 values)", n3 < 10, str(n3))

    n_zones = con.execute("SELECT COUNT(*) FROM zones").fetchone()[0]
    check_true("zones really is a small lookup table (<1000 rows)", n_zones < 1000,
               str(n_zones))
    con.close()


def test_timing_helpers():
    print("\n--- Timing helpers " + "-" * 57)
    con, path = make_small_db()
    r = bm.time_query(con, "SELECT COUNT(*) FROM trips", repeat=3)
    check_true("timing returns mean/min/max", {"mean_ms", "min_ms", "max_ms"} <= set(r))
    check_true("min <= mean <= max", r["min_ms"] <= r["mean_ms"] <= r["max_ms"] + 1e-9,
               f"{r['min_ms']:.3f} {r['mean_ms']:.3f} {r['max_ms']:.3f}")
    check_true("timings are positive", r["min_ms"] > 0)
    check("row count reported", r["rows"], 1)

    w = bm.measure_write_cost(con, n_rows=2000)
    check_true("indexed writes are slower than unindexed", w["ratio"] > 1.0,
               f"ratio={w['ratio']:.2f}")
    con.close()


def test_real_database():
    print("\n--- Real 2.9M-row database " + "-" * 49)
    db = bm.DB_PATH
    if not os.path.exists(db):
        print("  (skipped — run load_taxi.py first)")
        return
    con = sqlite3.connect(db)
    n = con.execute("SELECT COUNT(*) FROM trips").fetchone()[0]
    check_true("dataset is the expected scale (>2M rows)", n > 2_000_000, f"{n:,}")
    check_true("zones loaded", con.execute("SELECT COUNT(*) FROM zones").fetchone()[0] > 200)
    check_true("pickup_ts is never null",
               con.execute("SELECT COUNT(*) FROM trips WHERE pickup_ts IS NULL").fetchone()[0] == 0)

    idx = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_trips%'")}
    check_true("study indexes present after a run",
               {"idx_trips_pu", "idx_trips_pickup", "idx_trips_pu_pickup"} <= idx,
               str(sorted(idx)))

    # Same correctness invariant, on the real data this time.
    q = bm.QUERIES["Q2 date range scan"]["sql"]
    with_idx = con.execute(q).fetchall()
    con.execute("DROP INDEX IF EXISTS idx_trips_pickup")
    without = con.execute(q).fetchall()
    con.execute("CREATE INDEX IF NOT EXISTS idx_trips_pickup ON trips(pickup_ts)")
    con.commit()
    check_true("real-data answer identical with and without index",
               with_idx == without, f"{with_idx} vs {without}")
    con.close()


def main():
    print("=" * 78)
    print("Week 8 benchmark test suite")
    print("=" * 78)
    test_plan_classification()
    test_results_unchanged_by_indexes()
    test_index_changes_plan()
    test_selectivity_assumptions()
    test_timing_helpers()
    test_real_database()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
