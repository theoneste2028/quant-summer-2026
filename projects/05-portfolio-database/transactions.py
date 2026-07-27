"""
Week 6 — Transactions and ACID, demonstrated
============================================
CS 217. Every scenario below runs against a scratch database and *prints what
actually happened*, so the guarantees are observed rather than asserted.

The operation under test is the realistic one: recording a trade is not a single
INSERT. Booking a sale means inserting the trade AND making sure the security
exists AND recording the day's closing price — several writes that must all
land or none of them. That "all or nothing" requirement is what transactions
are for, and it is why the loader in `build_db.py` wraps its inserts the way it
does.

Run:
    python transactions.py
"""
from __future__ import annotations
import os, sqlite3, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA = os.path.join(HERE, "sql", "schema.sql")


def fresh_db(path):
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA) as fh:
        con.executescript(fh.read())
    con.execute("INSERT INTO securities (ticker,name,sector,asset_type) "
                "VALUES ('GOOGL','Alphabet Inc','Communication Services','STOCK')")
    con.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                "VALUES ('GOOGL','2026-01-05','BUY',10,150.0,0,'seed1')")
    # A seed price row: the duplicate-ticker-day check below needs an existing
    # row to duplicate, and an INSERT ... SELECT from an empty table silently
    # inserts nothing rather than raising.
    con.execute("INSERT INTO prices (ticker,date,open,high,low,close,volume) "
                "VALUES ('GOOGL','2026-01-05',149.0,152.0,148.0,150.0,1000000)")
    con.commit()
    return con


def counts(con):
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("securities", "trades", "prices")}


def banner(title, prop, why):
    print(f"\n{'='*78}\n{title}\n{'='*78}")
    print(f"ACID property: {prop}")
    print(f"Why this operation needs it: {why}\n")


# ---------------------------------------------------------------------------
# 1. ATOMICITY — a multi-statement booking either fully lands or fully unwinds
# ---------------------------------------------------------------------------
def demo_atomicity(con):
    banner("1. ATOMICITY — booking a trade is several writes, not one",
           "Atomicity",
           "Recording a sale inserts the security (if new), the trade, and the\n"
           "  day's price. A crash between them would leave a trade referencing\n"
           "  a security that does not exist, or a position with no price.")

    before = counts(con)
    print(f"  before:            {before}")
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute("INSERT INTO securities (ticker,name,sector,asset_type) "
                    "VALUES ('NVDA','NVIDIA Corp','Technology','STOCK')")
        cur.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                    "VALUES ('NVDA','2026-02-01','BUY',5,900.0,0,'tx-atom-1')")
        print(f"  mid-transaction:   {counts(con)}   <- our own connection sees the writes")
        # This one violates CHECK(close > 0). It is the third of three writes,
        # so the two successful ones are already sitting in the transaction.
        cur.execute("INSERT INTO prices (ticker,date,open,high,low,close,volume) "
                    "VALUES ('NVDA','2026-02-01',900,910,890,-1,1000)")
        con.commit()
        print("  committed (unexpected!)")
    except sqlite3.IntegrityError as e:
        con.rollback()
        print(f"  third write failed: {e}")
        print("  -> ROLLBACK issued")

    after = counts(con)
    print(f"  after rollback:    {after}")
    ok = after == before
    print(f"  RESULT: {'all three writes unwound together' if ok else 'PARTIAL WRITE LEAKED'}")
    return ok


# ---------------------------------------------------------------------------
# 2. CONSISTENCY — constraints hold at every commit boundary
# ---------------------------------------------------------------------------
def demo_consistency(con):
    banner("2. CONSISTENCY — the database refuses to enter an invalid state",
           "Consistency",
           "A trade for an unknown ticker, a negative quantity, or a side other\n"
           "  than BUY/SELL is not a bug to be caught by careful application\n"
           "  code — the engine itself rejects it, on every path in.")

    attempts = [
        ("trade for a ticker that does not exist (FK)",
         "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
         "VALUES ('FAKE','2026-02-01','BUY',1,10)"),
        ("negative quantity (CHECK quantity > 0)",
         "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
         "VALUES ('GOOGL','2026-02-01','BUY',-1,10)"),
        ("side outside BUY/SELL (CHECK)",
         "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
         "VALUES ('GOOGL','2026-02-01','SHORT',1,10)"),
        ("second price row for the same ticker-day (composite PK)",
         "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
         "SELECT ticker,date,open,high,low,close,volume FROM prices LIMIT 1"),
        ("re-inserting a trade already loaded (UNIQUE source_ref)",
         "INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
         "VALUES ('GOOGL','2026-01-05','BUY',10,150.0,0,'seed1')"),
    ]
    all_ok = True
    for label, sql in attempts:
        try:
            con.execute(sql)
            con.rollback()
            print(f"  ACCEPTED (bad!) : {label}")
            all_ok = False
        except sqlite3.IntegrityError as e:
            print(f"  rejected        : {label}\n                    ({e})")
    print(f"  RESULT: {'every invalid write refused' if all_ok else 'A CONSTRAINT IS MISSING'}")
    return all_ok


# ---------------------------------------------------------------------------
# 3. ISOLATION — uncommitted work is invisible to other connections
# ---------------------------------------------------------------------------
def demo_isolation(path):
    banner("3. ISOLATION — a half-finished booking is invisible to readers",
           "Isolation",
           "The dashboard may run its portfolio-value query at the exact moment\n"
           "  a trade is being booked. It must see the portfolio either before\n"
           "  or after that trade — never halfway through it.")

    writer = sqlite3.connect(path)
    reader = sqlite3.connect(path)
    writer.execute("PRAGMA foreign_keys = ON")

    def n_trades(con):
        return con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

    print(f"  reader sees {n_trades(reader)} trades (start)")
    cur = writer.cursor()
    cur.execute("BEGIN")
    cur.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                "VALUES ('GOOGL','2026-03-01','BUY',3,160.0,0,'tx-iso-1')")
    inside = n_trades(writer)
    outside = n_trades(reader)
    print(f"  writer mid-transaction sees {inside} trades")
    print(f"  reader concurrently sees    {outside} trades   <- unchanged")
    hidden = outside < inside

    writer.commit()
    after = n_trades(reader)
    print(f"  reader after writer commits: {after} trades")
    ok = hidden and after == inside
    print(f"  RESULT: {'uncommitted work stayed private until commit' if ok else 'DIRTY READ'}")
    writer.close(); reader.close()
    return ok


# ---------------------------------------------------------------------------
# 4. DURABILITY — a committed trade survives losing the connection
# ---------------------------------------------------------------------------
def demo_durability(path):
    banner("4. DURABILITY — once committed, a trade outlives the process",
           "Durability",
           "A booked trade is a financial record. If the laptop dies one second\n"
           "  after the commit returns, the trade must still be there when the\n"
           "  database is reopened.")

    con = sqlite3.connect(path)
    con.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                "VALUES ('GOOGL','2026-04-01','SELL',2,170.0,0,'tx-dur-1')")
    con.commit()
    print("  committed a SELL of 2 GOOGL, then closed the connection abruptly")
    con.close()

    reopened = sqlite3.connect(path)
    row = reopened.execute(
        "SELECT trade_date, side, quantity, price FROM trades "
        "WHERE source_ref = 'tx-dur-1'").fetchone()
    print(f"  after reopening the file: {row}")
    ok = row is not None
    print(f"  RESULT: {'committed trade survived' if ok else 'COMMITTED DATA LOST'}")
    reopened.close()
    return ok


# ---------------------------------------------------------------------------
# 5. The realistic failure: a trade that would oversell a position
# ---------------------------------------------------------------------------
def demo_business_rule_rollback(con):
    banner("5. ROLLBACK ON A BUSINESS RULE — selling more than you hold",
           "Atomicity + Consistency together",
           "Some invariants cannot be a column CHECK, because they depend on\n"
           "  other rows: 'do not sell more shares than the position holds' is a\n"
           "  fact about the whole trade history. The application enforces it\n"
           "  INSIDE the transaction, so a violation unwinds like any other.")

    def position(t):
        r = con.execute(
            "SELECT COALESCE(SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END),0) "
            "FROM trades WHERE ticker = ?", (t,)).fetchone()
        return float(r[0])

    print(f"  GOOGL position before: {position('GOOGL')}")
    before = position("GOOGL")
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        cur.execute("INSERT INTO trades (ticker,trade_date,side,quantity,price,fees,source_ref) "
                    "VALUES ('GOOGL','2026-05-01','SELL',999,180.0,0,'tx-over-1')")
        # Check the invariant while still inside the transaction.
        if position("GOOGL") < -1e-9:
            raise ValueError(f"would oversell: position becomes {position('GOOGL')}")
        con.commit()
        print("  committed (unexpected!)")
    except ValueError as e:
        con.rollback()
        print(f"  rejected by business rule: {e}")
        print("  -> ROLLBACK issued")

    after = position("GOOGL")
    print(f"  GOOGL position after:  {after}")
    ok = abs(after - before) < 1e-9
    print(f"  RESULT: {'oversell prevented, position intact' if ok else 'POSITION CORRUPTED'}")
    return ok


def main():
    tmp = tempfile.mkdtemp(prefix="wk6_tx_")
    path = os.path.join(tmp, "tx_demo.db")
    con = fresh_db(path)

    print("Week 6 — Transactions & ACID, demonstrated against a scratch database")
    print(f"(scratch db: {path})")

    results = {
        "Atomicity":   demo_atomicity(con),
        "Consistency": demo_consistency(con),
    }
    con.commit(); con.close()
    results["Isolation"] = demo_isolation(path)
    results["Durability"] = demo_durability(path)

    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    results["Business-rule rollback"] = demo_business_rule_rollback(con)
    con.close()

    print(f"\n{'='*78}\nSUMMARY\n{'='*78}")
    for k, v in results.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    failed = [k for k, v in results.items() if not v]
    print(f"\n{len(results)-len(failed)}/{len(results)} demonstrations behaved as specified.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
