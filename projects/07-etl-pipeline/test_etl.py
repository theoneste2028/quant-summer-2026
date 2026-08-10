"""
Week 7 — Test suite for the ETL pipeline and the SQL/NoSQL comparison
=====================================================================
Everything here runs offline against scratch databases, so the pipeline's
guarantees can be checked without hitting the network or depending on what
Yahoo happens to be publishing today.

Covered:
  * every validation rule, each with a row that must be rejected for exactly
    that reason (and a neighbouring row that must survive)
  * the transaction actually rolling back a whole batch on failure
  * idempotency, both at the extract level and the row level
  * news flattening into news + news_tickers, and the enrichment step
  * SQL and MongoDB returning identical answers to the same seven questions

Run:
    python test_etl.py
"""
from __future__ import annotations
import os, sys, sqlite3, tempfile
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import etl                                            # noqa: E402
import news_pipeline as np_                           # noqa: E402

SCHEMA = os.path.join(REPO, "projects", "05-portfolio-database", "sql", "schema.sql")
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


def scratch_db():
    path = os.path.join(tempfile.mkdtemp(prefix="wk7_"), "t.db")
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA) as fh:
        con.executescript(fh.read())
    for tk in ("AAA", "BBB"):
        con.execute("INSERT INTO securities (ticker,name,sector,asset_type) "
                    "VALUES (?,?,?,?)", (tk, tk + " Inc", "Tech", "STOCK"))
    con.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                "VALUES ('AAA','2026-01-02','BUY',10,10.0,0,'r1')")
    con.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                "VALUES ('BBB','2026-01-02','BUY',10,10.0,0,'r2')")
    con.commit()
    return con, path


def bar(ticker="AAA", date="2026-06-01", o=10.0, h=11.0, l=9.0, c=10.5, v=1000):
    return {"ticker": ticker, "date": date, "open": o, "high": h,
            "low": l, "close": c, "volume": v}


# ---------------------------------------------------------------------------
def test_validation():
    print("\n--- Validation rules " + "-" * 55)
    known = {"AAA", "BBB"}
    seen = {"AAA": {"2026-05-01"}, "BBB": set()}
    today = "2026-06-15"

    cases = [
        ("clean row accepted",            bar(),                                    True,  None),
        ("unknown ticker",                bar(ticker="ZZZ"),                        False, "unknown ticker"),
        ("missing date",                  {**bar(), "date": None},                  False, "missing ticker or date"),
        ("unparseable date",              {**bar(), "date": "06/01/2026"},          False, "unparseable date"),
        ("future date",                   {**bar(), "date": "2026-12-31"},          False, "is in the future"),
        ("null close",                    {**bar(), "close": None},                 False, "null price field"),
        ("zero price",                    {**bar(), "low": 0.0, "open": 0.0,
                                           "close": 0.0},                           False, "non-positive price"),
        ("negative price",                {**bar(), "low": -1.0},                   False, "non-positive price"),
        ("high < low",                    {**bar(), "high": 8.0, "low": 9.0,
                                           "open": 8.5, "close": 8.5},              False, "high < low"),
        ("open outside band",             {**bar(), "open": 99.0},                  False, "open outside"),
        ("close outside band",            {**bar(), "close": 99.0},                 False, "close outside"),
        ("negative volume",               {**bar(), "volume": -5},                  False, "negative volume"),
        ("already in database",           bar(date="2026-05-01"),                   False, "already present"),
    ]
    for name, row, should_pass, reason in cases:
        ok, bad = etl.validate([row], known, seen, today=today)
        if should_pass:
            check(name, (len(ok), len(bad)), (1, 0))
        else:
            got_reason = bad[0][1] if bad else ""
            check_true(f"{name} rejected", len(bad) == 1 and reason in got_reason,
                       f"reason={got_reason!r}")

    # Duplicate inside one batch: first survives, second is rejected.
    ok, bad = etl.validate([bar(), bar()], known, seen, today=today)
    check("duplicate within batch", (len(ok), len(bad)), (1, 1))
    check_true("batch-duplicate reason", "duplicate within this batch" in bad[0][1])

    # A bad row must not take a good row down with it during validation.
    ok, bad = etl.validate([bar(), bar(date="2026-06-02", o=99.0)], known, seen, today=today)
    check("good row survives alongside bad", (len(ok), len(bad)), (1, 1))


def test_load_and_transaction():
    print("\n--- Load & transaction " + "-" * 53)
    con, path = scratch_db()

    n = etl.load(con, [bar(date="2026-06-01"), bar(date="2026-06-02")])
    check("inserts accepted rows", n, 2)
    check("rows visible after commit",
          con.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 2)

    # Whole-batch rollback: a constraint violation anywhere kills the batch.
    before = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    bad_batch = [bar(date="2026-06-03"),
                 bar(date="2026-06-04", c=-5.0),     # violates CHECK(close > 0)
                 bar(date="2026-06-05")]
    raised = False
    try:
        etl.load(con, bad_batch)
    except sqlite3.IntegrityError:
        raised = True
    check_true("bad batch raises", raised)
    check("no partial write survived",
          con.execute("SELECT COUNT(*) FROM prices").fetchone()[0], before)

    # load() is strict by design: a duplicate that reached it means validation
    # was bypassed, so it must fail loudly rather than silently skip. Dropping
    # already-present rows is validate()'s job (covered above and below).
    dup_raised = False
    try:
        etl.load(con, [bar(date="2026-06-01")])
    except sqlite3.IntegrityError:
        dup_raised = True
    check_true("duplicate reaching load() raises rather than skipping", dup_raised)
    check("still no partial write after duplicate",
          con.execute("SELECT COUNT(*) FROM prices").fetchone()[0], before)

    check("empty batch is a no-op", etl.load(con, []), 0)
    con.close()


def test_run_idempotency():
    print("\n--- End-to-end run & idempotency " + "-" * 43)
    con, path = scratch_db()
    con.close()
    rows = [bar(date="2026-06-01"), bar(date="2026-06-02"),
            bar(ticker="BBB", date="2026-06-01")]

    s1 = etl.run(path, date="2026-06-01", rows=rows)
    check("first run inserts all valid rows", s1["inserted"], 3)

    s2 = etl.run(path, date="2026-06-01", rows=rows)
    check("second run inserts nothing", s2["inserted"], 0)
    check("second run rejects them as already present", s2["accepted"], 0)
    check_true("rejection reason recorded",
               any("already present" in k for k in s2["reasons"]),
               str(s2["reasons"]))

    s3 = etl.run(path, date="2026-06-01", rows=rows, dry_run=True)
    check("dry run writes nothing", s3["inserted"], 0)

    con = sqlite3.connect(path)
    check("total rows unchanged after re-runs",
          con.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 3)
    con.close()


def test_logging():
    print("\n--- Logging " + "-" * 64)
    d = tempfile.mkdtemp(prefix="wk7_log_")
    log_path = os.path.join(d, "etl.log")
    etl.setup_logging(verbose=False, log_path=log_path)
    con, path = scratch_db(); con.close()
    etl.run(path, date="2026-06-01", rows=[bar(date="2026-06-01"),
                                           bar(ticker="ZZZ", date="2026-06-01")])
    for h in etl.log.handlers:
        h.flush()
    text = open(log_path).read()
    check_true("log file written", os.path.exists(log_path) and len(text) > 0)
    check_true("log records run boundaries", "ETL run start" in text and "ETL run end" in text)
    check_true("log records the counts", "inserted=1" in text, text[-200:])
    check_true("log records rejections", "rejected" in text)
    check_true("log records runtime", "elapsed=" in text)
    etl.setup_logging(verbose=False)   # restore default


# ---------------------------------------------------------------------------
def sample_docs():
    return [
        {"_id": "a1", "tickers": ["AAA"], "title": "AAA soars on AI demand",
         "summary": "AAA Inc rose after strong guidance.", "content_type": "STORY",
         "pub_date": "2026-06-10T10:00:00Z",
         "provider": {"displayName": "Zacks"},
         "canonical_url": {"url": "http://x/1"},
         "thumbnail": {"resolutions": [{"w": 1}, {"w": 2}]}},
        {"_id": "a2", "tickers": ["BBB"], "title": "BBB earnings beat",
         "summary": "BBB Corp beat estimates.", "content_type": "STORY",
         "pub_date": "2026-06-11T10:00:00Z",
         "provider": {"displayName": "Reuters"},
         "canonical_url": {"url": "http://x/2"},
         "thumbnail": {"resolutions": [{"w": 1}]}},
        {"_id": "a3", "tickers": ["AAA"], "title": "Sector roundup",
         "summary": "Both AAA and BBB gained today.", "content_type": "VIDEO",
         "pub_date": "2026-06-12T10:00:00Z",
         "provider": {"displayName": "Zacks"},
         "canonical_url": {"url": "http://x/3"},
         "thumbnail": {}},
    ]


def test_news_pipeline():
    print("\n--- News: flattening, enrichment, idempotency " + "-" * 31)
    con, path = scratch_db()
    docs = sample_docs()

    added = np_.enrich_mentions(docs, ["AAA", "BBB"])
    check("enrichment tags cross-mentions", added, 1)          # a3 mentions BBB
    check("a3 now references both tickers", sorted(docs[2]["tickers"]), ["AAA", "BBB"])
    check_true("a1 not falsely tagged with BBB", "BBB" not in docs[0]["tickers"])

    n_news, n_links = np_.load_sqlite(con, docs)
    check("articles flattened into news", n_news, 3)
    check("links written to junction table", n_links, 4)       # 1 + 1 + 2

    again_n, again_l = np_.load_sqlite(con, docs)
    check("re-loading news is idempotent", (again_n, again_l), (0, 0))

    db, backend = np_.mongo_db()
    db["news"].delete_many({})
    check("mongo insert count", np_.load_mongo(db, docs), 3)
    check("mongo re-load is idempotent", np_.load_mongo(db, docs), 0)

    row = con.execute("SELECT publisher, link FROM news WHERE id='a1'").fetchone()
    check("nested provider flattened to a column", row[0], "Zacks")
    check("nested canonicalUrl flattened to a column", row[1], "http://x/1")
    con.close()


def test_sql_mongo_equivalence():
    print("\n--- SQL vs MongoDB give the same answers " + "-" * 35)
    con, path = scratch_db()
    docs = sample_docs()
    np_.enrich_mentions(docs, ["AAA", "BBB"])
    np_.load_sqlite(con, docs)
    db, backend = np_.mongo_db()
    db["news"].delete_many({})
    np_.load_mongo(db, docs)

    rows = np_.comparisons(con, db, ticker="AAA", keyword="AI")
    for title, sql, mongo, a, b in rows:
        if a is None:
            check_true(f"{title} — SQL correctly cannot answer", b is not None)
            continue
        check_true(f"{title} — stores agree", a == b, f"sql={a} mongo={b}")

    # Spot-check the values themselves, not just that the two agree.
    n_multi = con.execute("SELECT COUNT(*) FROM (SELECT news_id FROM news_tickers "
                          "GROUP BY news_id HAVING COUNT(*) > 1)").fetchone()[0]
    check("exactly one multi-ticker article", n_multi, 1)
    check("AAA article count",
          con.execute("SELECT COUNT(*) FROM news_tickers WHERE ticker='AAA'").fetchone()[0], 2)
    check("thumbnail resolutions answerable in mongo only",
          db["news"].count_documents(
              {"$expr": {"$gt": [{"$size": {"$ifNull": ["$thumbnail.resolutions", []]}}, 1]}}), 1)
    con.close()


def main():
    print("=" * 78)
    print("Week 7 ETL test suite")
    print("=" * 78)
    etl.setup_logging(verbose=False)
    test_validation()
    test_load_and_transaction()
    test_run_idempotency()
    test_logging()
    test_news_pipeline()
    test_sql_mongo_equivalence()
    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
