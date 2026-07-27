"""
Week 6 — Test suite for the analytical queries
==============================================
Two layers of testing:

  1. HAND-CHECKED CASES. A tiny in-memory database is built with trades whose
     FIFO answer can be worked out on paper, and the query must reproduce it.
     This is what actually proves the interval-overlap FIFO is right — real
     data can only ever show that nothing looks obviously wrong.

  2. INVARIANTS ON REAL DATA. Properties that must hold for any portfolio
     (shares closed can never exceed shares bought, weights must sum to 100%,
     realized P&L must agree whether summed per-match or per-ticker). These
     catch the errors that hand cases miss because they only appear at scale.

Run:
    python test_queries.py                    # against data/portfolio.db
    python test_queries.py --db path/to.db
"""
from __future__ import annotations
import os, sys, sqlite3
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
from dashboard import load_queries, run  # noqa: E402

QUERIES = load_queries()
SCHEMA = os.path.join(HERE, "sql", "schema.sql")

PASS, FAIL = [], []


def check(name, got, want, tol=1e-6):
    ok = abs(got - want) <= tol if isinstance(want, (int, float)) else got == want
    (PASS if ok else FAIL).append(name)
    flag = "PASS" if ok else "FAIL"
    print(f"  [{flag}] {name}: got {got!r}, want {want!r}")
    return ok


def check_true(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return cond


# ---------------------------------------------------------------------------
# Layer 1 — synthetic databases with hand-computed answers
# ---------------------------------------------------------------------------
def make_db(trades, prices=None, divs=None):
    """Build an in-memory DB. trades: (ticker, date, side, qty, price, fees)."""
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA) as fh:
        con.executescript(fh.read())
    tickers = {t[0] for t in trades} | {p[0] for p in (prices or [])}
    for tk in tickers:
        con.execute("INSERT INTO securities (ticker,name,sector,asset_type) VALUES (?,?,?,?)",
                    (tk, tk + " Inc", "TestSector", "STOCK"))
    for i, (tk, d, side, q, px, fee) in enumerate(trades):
        con.execute("""INSERT INTO trades
                       (ticker,trade_date,side,quantity,price,fees,source_ref)
                       VALUES (?,?,?,?,?,?,?)""", (tk, d, side, q, px, fee, f"ref{i}"))
    for tk, d, close in (prices or []):
        con.execute("INSERT INTO prices (ticker,date,open,high,low,close,volume) "
                    "VALUES (?,?,?,?,?,?,?)", (tk, d, close, close, close, close, 1000))
    for tk, d, amt in (divs or []):
        con.execute("INSERT INTO dividends VALUES (?,?,?)", (tk, d, amt))
    con.commit()
    return con


def test_fifo_hand_cases():
    print("\n--- FIFO: hand-computed cases " + "-" * 44)

    # Case 1: one lot in, one lot out. 10 shares bought at 10, sold at 12.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-02-01", "SELL", 10, 12.0, 0)])
    r = run(con, QUERIES["realized_pnl"])
    check("case1 realized P&L (10 x $2)", float(r["realized_pnl"].iloc[0]), 20.0)
    check("case1 shares closed", float(r["shares_closed"].iloc[0]), 10.0)

    # Case 2: partial sale. Buy 10 @ 10, sell 4 @ 12 -> +8 realized, 6 left @ 10.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-02-01", "SELL", 4, 12.0, 0)],
                  prices=[("AAA", "2026-03-01", 15.0)])
    r = run(con, QUERIES["realized_pnl"])
    cb = run(con, QUERIES["cost_basis"])
    check("case2 realized P&L (4 x $2)", float(r["realized_pnl"].iloc[0]), 8.0)
    check("case2 remaining quantity", float(cb["quantity"].iloc[0]), 6.0)
    check("case2 remaining cost basis (6 x $10)", float(cb["cost_basis"].iloc[0]), 60.0)
    check("case2 unrealized P&L (6 x $5)", float(cb["unrealized_pnl"].iloc[0]), 30.0)

    # Case 3: THE FIFO TEST. Two lots at different prices, one sale spanning
    # both. Buy 10 @ 10, buy 10 @ 20, sell 15 @ 30.
    #   FIFO consumes lot 1 entirely (10 x (30-10) = +200)
    #   then 5 shares of lot 2        ( 5 x (30-20) = +50)   => +250
    # Under LIFO this would be 10x10 + 5x20 = 200; under average cost, 15x15=225.
    # Only 250 is FIFO, so this case pins down the matching order.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-01-15", "BUY", 10, 20.0, 0),
                   ("AAA", "2026-02-01", "SELL", 15, 30.0, 0)],
                  prices=[("AAA", "2026-03-01", 25.0)])
    r = run(con, QUERIES["realized_pnl"])
    m = run(con, QUERIES["fifo_matches"])
    cb = run(con, QUERIES["cost_basis"])
    check("case3 realized P&L (FIFO = 250, not 200/225)",
          float(r["realized_pnl"].iloc[0]), 250.0)
    check("case3 number of matches", len(m), 2)
    check("case3 first match qty (whole lot 1)", float(m["matched_qty"].iloc[0]), 10.0)
    check("case3 second match qty (part of lot 2)", float(m["matched_qty"].iloc[1]), 5.0)
    check("case3 remaining quantity", float(cb["quantity"].iloc[0]), 5.0)
    check("case3 remaining cost (5 @ $20, the newer lot)",
          float(cb["cost_basis"].iloc[0]), 100.0)

    # Case 4: fees reduce realized P&L on both legs.
    # Buy 10 @ 10 (fee 1), sell 10 @ 12 (fee 1) -> 20 - 1 - 1 = 18.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 1.0),
                   ("AAA", "2026-02-01", "SELL", 10, 12.0, 1.0)])
    r = run(con, QUERIES["realized_pnl"])
    check("case4 realized P&L net of fees", float(r["realized_pnl"].iloc[0]), 18.0)

    # Case 5: fees apportion pro-rata when only part of a lot is sold.
    # Buy 10 @ 10 (fee 2), sell 5 @ 12 (fee 1) -> 5x2 - 2*(5/10) - 1 = 8.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 2.0),
                   ("AAA", "2026-02-01", "SELL", 5, 12.0, 1.0)])
    r = run(con, QUERIES["realized_pnl"])
    check("case5 pro-rata fee allocation", float(r["realized_pnl"].iloc[0]), 8.0)

    # Case 6: fractional shares (the reinvestment case) survive the arithmetic.
    con = make_db([("AAA", "2026-01-01", "BUY", 0.5, 100.0, 0),
                   ("AAA", "2026-01-02", "BUY", 0.25, 200.0, 0),
                   ("AAA", "2026-02-01", "SELL", 0.6, 300.0, 0)],
                  prices=[("AAA", "2026-03-01", 250.0)])
    r = run(con, QUERIES["realized_pnl"])
    cb = run(con, QUERIES["cost_basis"])
    # 0.5 @ (300-100) = 100 ; 0.1 @ (300-200) = 10  => 110
    check("case6 fractional FIFO P&L", float(r["realized_pnl"].iloc[0]), 110.0, tol=1e-9)
    check("case6 fractional remainder", float(cb["quantity"].iloc[0]), 0.15, tol=1e-9)

    # Case 7: a fully closed position must NOT appear as an open position, even
    # though float arithmetic leaves a residue instead of exact zero.
    con = make_db([("AAA", "2026-01-01", "BUY", 0.1, 10.0, 0),
                   ("AAA", "2026-01-02", "BUY", 0.2, 10.0, 0),
                   ("AAA", "2026-02-01", "SELL", 0.3, 12.0, 0)],
                  prices=[("AAA", "2026-03-01", 15.0)])
    pos = run(con, QUERIES["positions"])
    cb = run(con, QUERIES["cost_basis"])
    check("case7 closed position absent from positions", len(pos), 0)
    check("case7 closed position absent from cost basis", len(cb), 0)

    # Case 8: sell everything, then buy again. The second lot must not be
    # matched against the already-consumed first sale.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-02-01", "SELL", 10, 12.0, 0),
                   ("AAA", "2026-03-01", "BUY", 5, 20.0, 0)],
                  prices=[("AAA", "2026-04-01", 22.0)])
    r = run(con, QUERIES["realized_pnl"])
    cb = run(con, QUERIES["cost_basis"])
    check("case8 realized unchanged by later buy", float(r["realized_pnl"].iloc[0]), 20.0)
    check("case8 new lot open", float(cb["quantity"].iloc[0]), 5.0)
    check("case8 new lot cost basis", float(cb["cost_basis"].iloc[0]), 100.0)

    # Case 9: two identical fills on the same day are two lots, not one.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-02-01", "SELL", 20, 11.0, 0)])
    r = run(con, QUERIES["realized_pnl"])
    check("case9 duplicate same-day fills both counted",
          float(r["shares_closed"].iloc[0]), 20.0)


def test_other_queries_hand_cases():
    print("\n--- Other queries: hand-computed cases " + "-" * 33)

    # Sector exposure: two sectors, known weights.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("BBB", "2026-01-01", "BUY", 10, 10.0, 0)],
                  prices=[("AAA", "2026-02-01", 30.0), ("BBB", "2026-02-01", 10.0)])
    con.execute("UPDATE securities SET sector='Tech' WHERE ticker='AAA'")
    con.execute("UPDATE securities SET sector='Energy' WHERE ticker='BBB'")
    con.commit()
    se = run(con, QUERIES["sector_exposure"])
    # AAA = 300, BBB = 100, total 400 -> 75% / 25%
    check("sector weights sum to 100", float(se["pct_of_portfolio"].sum()), 100.0, tol=0.01)
    check("dominant sector weight", float(se["pct_of_portfolio"].iloc[0]), 75.0, tol=0.01)

    # An unclassified sector must be bucketed, not dropped (else weights lie).
    con.execute("UPDATE securities SET sector=NULL WHERE ticker='BBB'")
    con.commit()
    se = run(con, QUERIES["sector_exposure"])
    check("NULL sector bucketed as Unclassified",
          "Unclassified" in set(se["sector"]), True)
    check("weights still sum to 100 with NULL sector",
          float(se["pct_of_portfolio"].sum()), 100.0, tol=0.01)

    # Best/worst day: a known price path.  100 -> 110 (+10%) -> 99 (-10%).
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0)],
                  prices=[("AAA", "2026-01-01", 100.0), ("AAA", "2026-01-02", 110.0),
                          ("AAA", "2026-01-03", 99.0)])
    bw = run(con, QUERIES["best_worst_days"])
    check("best day return %", float(bw["best_ret_pct"].iloc[0]), 10.0, tol=0.01)
    check("worst day return %", float(bw["worst_ret_pct"].iloc[0]), -10.0, tol=0.01)
    check("best day date", str(bw["best_day"].iloc[0]), "2026-01-02")

    # Dividend quarter bucketing across all four quarters + a year boundary.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0)],
                  divs=[("AAA", "2026-01-15", 5.0), ("AAA", "2026-03-31", 5.0),
                        ("AAA", "2026-04-01", 7.0), ("AAA", "2026-07-01", 3.0),
                        ("AAA", "2026-10-01", 2.0), ("AAA", "2025-12-31", 1.0)])
    dq = run(con, QUERIES["dividends_by_quarter"])
    got = {f"{r.year} {r.quarter}": r.income for r in dq.itertuples()}
    check("2026 Q1 income (Jan + Mar)", got.get("2026 Q1"), 10.0)
    check("2026 Q2 income (Apr 1 -> Q2)", got.get("2026 Q2"), 7.0)
    check("2026 Q3 income (Jul 1 -> Q3)", got.get("2026 Q3"), 3.0)
    check("2026 Q4 income (Oct 1 -> Q4)", got.get("2026 Q4"), 2.0)
    check("2025 Q4 income (year boundary)", got.get("2025 Q4"), 1.0)

    # Portfolio value over time: position changes mid-window.
    con = make_db([("AAA", "2026-01-01", "BUY", 10, 10.0, 0),
                   ("AAA", "2026-01-03", "BUY", 10, 10.0, 0)],
                  prices=[("AAA", "2026-01-01", 10.0), ("AAA", "2026-01-02", 11.0),
                          ("AAA", "2026-01-03", 12.0)])
    pv = run(con, QUERIES["portfolio_value"])
    vals = dict(zip(pv["date"], pv["portfolio_value"]))
    check("portfolio value day 1 (10 sh x $10)", vals["2026-01-01"], 100.0)
    check("portfolio value day 2 (10 sh x $11)", vals["2026-01-02"], 110.0)
    check("portfolio value day 3 (20 sh x $12)", vals["2026-01-03"], 240.0)


# ---------------------------------------------------------------------------
# Layer 2 — invariants that must hold on the real portfolio
# ---------------------------------------------------------------------------
def test_real_invariants(db_path):
    print(f"\n--- Invariants on real data ({os.path.basename(db_path)}) " + "-" * 20)
    con = sqlite3.connect(db_path)
    pos = run(con, QUERIES["positions"])
    cb = run(con, QUERIES["cost_basis"])
    rp = run(con, QUERIES["realized_pnl"])
    fm = run(con, QUERIES["fifo_matches"])
    se = run(con, QUERIES["sector_exposure"])
    pv = run(con, QUERIES["portfolio_value"])
    raw = run(con, "SELECT ticker, side, SUM(quantity) q FROM trades GROUP BY ticker, side")

    bought = raw[raw.side == "BUY"].set_index("ticker")["q"]
    sold = raw[raw.side == "SELL"].set_index("ticker")["q"]

    # 1. FIFO must never close more shares than were ever bought.
    over = [t for t in rp.ticker
            if float(rp.set_index("ticker").loc[t, "shares_closed"])
            > float(bought.get(t, 0)) + 1e-6]
    check_true("shares closed never exceed shares bought", not over, str(over))

    # 2. Shares closed must equal shares sold (no sell left unmatched), for any
    #    ticker that was not oversold.
    mism = []
    for t in sold.index:
        closed = float(rp.set_index("ticker")["shares_closed"].get(t, 0))
        if abs(closed - float(sold[t])) > 1e-4 and float(sold[t]) <= float(bought.get(t, 0)) + 1e-6:
            mism.append((t, closed, float(sold[t])))
    check_true("every sold share is matched to a buy lot", not mism, str(mism[:4]))

    # 3. bought = closed + still held, per ticker.
    held = cb.set_index("ticker")["quantity"]
    bad = []
    for t in bought.index:
        closed = float(rp.set_index("ticker")["shares_closed"].get(t, 0))
        h = float(held.get(t, 0))
        if abs(float(bought[t]) - closed - h) > 1e-4:
            bad.append((t, float(bought[t]), closed, h))
    check_true("bought == closed + held (share conservation)", not bad, str(bad[:4]))

    # 4. Per-match and per-ticker realized P&L must agree.
    a = fm["realized_pnl"].sum()
    b = rp["realized_pnl"].sum()
    check_true("per-match and per-ticker realized P&L agree",
               abs(a - b) < 0.05, f"{a:.2f} vs {b:.2f}")

    # 5. Sector weights sum to 100%.
    tot = float(se["pct_of_portfolio"].sum())
    check_true("sector weights sum to 100%", abs(tot - 100.0) < 0.05, f"{tot:.3f}%")

    # 6. Market value in cost_basis matches the last row of portfolio_value,
    #    give or take tickers whose last price predates the final trading day.
    if not pv.empty:
        last_pv = float(pv["portfolio_value"].iloc[-1])
        mv = float(cb["market_value"].sum())
        rel = abs(last_pv - mv) / max(mv, 1)
        check_true("cost_basis market value ≈ latest portfolio value",
                   rel < 0.02, f"{mv:,.2f} vs {last_pv:,.2f} ({rel:.2%})")

    # 7. No open position may be negative.
    check_true("no negative open positions", (cb["quantity"] > 0).all())

    # 8. Positions and cost_basis must agree on which tickers are open.
    check_true("positions and cost_basis agree on open tickers",
               set(pos.ticker) == set(cb.ticker),
               str(set(pos.ticker) ^ set(cb.ticker)))

    # 9. Portfolio value must be positive and dated in order.
    if not pv.empty:
        check_true("portfolio value always positive", (pv["portfolio_value"] > 0).all())
        check_true("portfolio value dates ascending",
                   list(pv["date"]) == sorted(pv["date"]))

    # 10. No duplicate trades survived the idempotency guard.
    dup = run(con, """SELECT COUNT(*) n FROM (
                        SELECT source_ref FROM trades WHERE source_ref IS NOT NULL
                        GROUP BY source_ref HAVING COUNT(*) > 1)""")
    check_true("no duplicate source_refs", int(dup["n"].iloc[0]) == 0)

    # 11. No synthetic demo prices leaked into this database.
    syn = run(con, """SELECT COUNT(*) n FROM prices
                      WHERE ABS(open - close*0.99) < 1e-9
                        AND ABS(high - close*1.01) < 1e-9
                        AND ABS(low  - close*0.98) < 1e-9""")
    check_true("no synthetic demo prices present", int(syn["n"].iloc[0]) == 0,
               f"{int(syn['n'].iloc[0])} rows match the demo signature")
    con.close()


def main():
    argv = sys.argv[1:]
    db = os.path.join(REPO, "data", "portfolio.db")
    if "--db" in argv:
        db = argv[argv.index("--db") + 1]

    print("=" * 78)
    print("Week 6 query test suite")
    print("=" * 78)
    test_fifo_hand_cases()
    test_other_queries_hand_cases()
    if os.path.exists(db):
        test_real_invariants(db)
    else:
        print(f"\n(skipping real-data invariants — no database at {db})")

    print("\n" + "=" * 78)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
    print("=" * 78)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
