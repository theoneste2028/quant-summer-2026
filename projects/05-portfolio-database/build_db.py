"""
Week 5 — Build the Portfolio Database
=====================================
Creates the schema, loads a Fidelity activity CSV into `trades`, and backfills
`prices` from yfinance.

Fidelity CSV mapping (matches the real export format):
  Symbol -> ticker | Price ($) -> price | Quantity sign -> side (+ = BUY,
  - = SELL), abs() -> quantity | Fees ($) -> fees (blank -> 0)
  Settlement Date -> trade_date

Run:
    python build_db.py path/to/fidelity_activity.csv
    python build_db.py --demo          # offline demo with sample data
"""
from __future__ import annotations
import os, sys, sqlite3
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB_PATH = os.path.join(REPO, "data", "portfolio.db")
SCHEMA = os.path.join(HERE, "sql", "schema.sql")


def connect(db_path=DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def create_schema(con):
    with open(SCHEMA) as fh:
        con.executescript(fh.read())
    con.commit()


def parse_fidelity_csv(path: str) -> pd.DataFrame:
    """Parse a Fidelity activity export into tidy trades.

    Fidelity files sometimes have junk rows before the header. We locate the
    header by finding any line that contains 'Symbol' as a column name.
    Real exports may also start directly with the header row.
    """
    with open(path) as fh:
        lines = fh.readlines()
    hdr = next(i for i, ln in enumerate(lines) if "Symbol" in ln)
    df = pd.read_csv(path, skiprows=hdr)
    df.columns = [c.strip() for c in df.columns]

    # Keep only actual buy/sell executions — filter out dividends, reinvestments,
    # interest, etc. that appear in the full account history export.
    if "Action" in df.columns:
        action = df["Action"].str.upper().fillna("")
        df = df[action.str.contains("BOUGHT|SOLD")]

    df = df.dropna(subset=["Symbol", "Quantity", "Price ($)"])
    df = df[df["Symbol"].str.strip().str.len() > 0]

    qty = pd.to_numeric(df["Quantity"], errors="coerce")
    out = pd.DataFrame({
        "ticker": df["Symbol"].str.strip().str.upper(),
        "name": df.get("Description", df["Symbol"]).str.strip(),
        "trade_date": pd.to_datetime(df["Settlement Date"]).dt.strftime("%Y-%m-%d"),
        "side": qty.apply(lambda q: "BUY" if q > 0 else "SELL"),
        "quantity": qty.abs(),
        "price": pd.to_numeric(df["Price ($)"], errors="coerce"),
        "fees": pd.to_numeric(df.get("Fees ($)"), errors="coerce").fillna(0.0),
    }).dropna(subset=["quantity", "price"])
    return out


def load_trades(con, trades: pd.DataFrame):
    """Insert securities first (FK target), then trades — one transaction."""
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        for _, r in trades.drop_duplicates("ticker").iterrows():
            cur.execute(
                "INSERT OR IGNORE INTO securities (ticker, name) VALUES (?, ?)",
                (r["ticker"], r["name"]),
            )
        cur.executemany(
            """INSERT INTO trades (ticker, trade_date, side, quantity, price, fees)
               VALUES (?, ?, ?, ?, ?, ?)""",
            trades[["ticker", "trade_date", "side", "quantity", "price", "fees"]]
            .itertuples(index=False, name=None),
        )
        con.commit()
        print(f"Loaded {len(trades)} trades, {trades['ticker'].nunique()} securities.")
    except Exception:
        con.rollback()
        raise


def backfill_prices(con, years=2):
    """Fill `prices` for every ticker in `securities` via yfinance."""
    import yfinance as yf
    tickers = [r[0] for r in con.execute("SELECT ticker FROM securities")]
    data = yf.download(tickers, period=f"{years}y", auto_adjust=True,
                       progress=False, group_by="ticker")
    rows = []
    for t in tickers:
        try:
            d = data[t].dropna()
        except KeyError:
            print(f"  ! no data for {t}, skipping"); continue
        for date, r in d.iterrows():
            rows.append((t, date.strftime("%Y-%m-%d"), r["Open"], r["High"],
                         r["Low"], r["Close"], int(r["Volume"])))
    con.executemany(
        "INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"Backfilled {len(rows)} price rows for {len(tickers)} tickers.")


def demo_data(con):
    """Offline demo: sample trades + synthetic prices, so everything runs
    without internet. Replace with your real CSV + backfill_prices later."""
    import numpy as np
    sample = os.path.join(HERE, "sample_fidelity.csv")
    trades = parse_fidelity_csv(sample)
    load_trades(con, trades)
    rng = np.random.default_rng(7)
    rows = []
    for t in trades["ticker"].unique():
        price = float(trades.loc[trades.ticker == t, "price"].iloc[0])
        for d in pd.bdate_range("2026-01-02", "2026-07-03"):
            price *= float(np.exp(rng.normal(0.0004, 0.02)))
            rows.append((t, d.strftime("%Y-%m-%d"), price*0.99, price*1.01,
                         price*0.98, price, int(rng.integers(1e5, 5e6))))
    con.executemany("INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"Demo: {len(rows)} synthetic price rows inserted.")


def verify(con):
    """Prove the constraints reject bad data."""
    bad = [
        ("negative qty", "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
                         "VALUES ('IREN','2026-01-01','BUY',-5,10)"),
        ("bad side",     "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
                         "VALUES ('IREN','2026-01-01','HOLD',5,10)"),
        ("unknown FK",   "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
                         "VALUES ('ZZZZ','2026-01-01','BUY',5,10)"),
        ("dup price day","INSERT INTO prices SELECT * FROM prices LIMIT 1"),
    ]
    print("\nConstraint checks (all should be REJECTED):")
    for name, sql in bad:
        try:
            con.execute(sql); con.rollback()
            print(f"  ✗ {name}: WAS ACCEPTED — constraint missing!")
        except sqlite3.Error as e:
            print(f"  ✓ {name}: rejected ({type(e).__name__})")
    for t in ("securities", "trades", "prices", "dividends"):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} rows")


if __name__ == "__main__":
    con = connect()
    create_schema(con)
    if "--demo" in sys.argv:
        demo_data(con)
    elif len(sys.argv) > 1:
        load_trades(con, parse_fidelity_csv(sys.argv[1]))
        backfill_prices(con)
    else:
        print("usage: python build_db.py <fidelity.csv>  |  python build_db.py --demo")
        sys.exit(1)
    verify(con)
    print(f"\nDatabase at: {DB_PATH}")
