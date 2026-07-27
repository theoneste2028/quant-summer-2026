"""
Weeks 5-6 — Build the Portfolio Database
========================================
Creates the schema, loads a Fidelity activity CSV into `securities`, `trades`
and `dividends`, and backfills `prices` from yfinance.

What the export contains, and what we do with each action type:
  YOU BOUGHT / YOU SOLD  -> trades (side from the quantity sign)
  REINVESTMENT           -> trades as BUY (a dividend reinvestment really is a
                            share purchase; dropping it silently loses shares)
  DIVIDEND RECEIVED      -> dividends (total cash received, summed per ex-date)
  TRANSFER / CONTRIBUTION / INTEREST / JOURNAL -> ignored (cash movements, not
                            security positions)

Two things the loader guards against, both of which corrupted an earlier build:
  1. DOUBLE LOADING. Every trade carries a `source_ref` fingerprint of its
     source row with a UNIQUE constraint, so re-running any file is a no-op.
  2. SYNTHETIC DEMO PRICES leaking into the real database. `--demo` now writes
     to its own file and never touches the production DB.

Run:
    python build_db.py ~/Downloads/Accounts_History.csv   # real load + backfill
    python build_db.py --demo                             # offline, separate DB
    python build_db.py <csv> --skip-prices                # load, no network
"""
from __future__ import annotations
import os, sys, json, hashlib, sqlite3
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB_PATH = os.path.join(REPO, "data", "portfolio.db")
DEMO_DB_PATH = os.path.join(REPO, "data", "portfolio_demo.db")
SCHEMA = os.path.join(HERE, "sql", "schema.sql")
META_CACHE = os.path.join(HERE, "sql", "security_meta.json")

# The brokerage cash sweep fund. Its "shares" are dollars, and it has no SELL
# rows (cash leaves via TRANSFER), so treating its reinvestments as trades would
# produce a position that only ever grows. We keep it as a security so its
# interest income still lands in `dividends`, but exclude it from `trades`.
CASH_SWEEP = {"SPAXX", "FDRXX", "SPRXX"}


def connect(db_path=DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def create_schema(con):
    with open(SCHEMA) as fh:
        con.executescript(fh.read())
    con.commit()


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def _source_ref(row: pd.Series, line_no: int) -> str:
    """Stable fingerprint of one source row: content + line number.

    Content alone is not enough — two identical fills on the same day are a real
    thing, and hashing only content would collapse them into one. The line
    number keeps them distinct while staying stable across re-runs of the file.
    """
    payload = "|".join(str(row.get(c, "")) for c in
                       ("Run Date", "Action", "Symbol", "Price ($)",
                        "Quantity", "Amount ($)", "Settlement Date"))
    return hashlib.sha1(f"{line_no}|{payload}".encode()).hexdigest()[:16]


def _read_export(path: str) -> pd.DataFrame:
    """Read a Fidelity activity export, tolerating junk lines before the header."""
    with open(path) as fh:
        lines = fh.readlines()
    hdr = next(i for i, ln in enumerate(lines) if "Symbol" in ln)
    df = pd.read_csv(path, skiprows=hdr)
    df.columns = [c.strip() for c in df.columns]
    df["_line"] = range(len(df))
    for c in ("Symbol", "Action", "Description"):
        if c in df.columns:
            df[c] = df[c].astype("string").fillna("")
    return df


def parse_export(path: str) -> dict:
    """Split a Fidelity export into tidy `trades` and `dividends` frames.

    Handles both layouts seen in practice: the full account-history export
    (which has `Action` and `Run Date` columns describing the event type) and
    the trimmed per-account download (which has neither, and where every row is
    an execution whose direction is given by the sign of Quantity).
    """
    df = _read_export(path)
    has_action = "Action" in df.columns
    act = df["Action"].str.upper() if has_action else pd.Series("", index=df.index)

    # ---- Trades: outright buys/sells, plus reinvestments (real share buys) ---
    is_reinv = act.str.contains("REINVESTMENT") if has_action else pd.Series(False, index=df.index)
    keep = ((act.str.contains("YOU BOUGHT|YOU SOLD", regex=True) | is_reinv)
            if has_action else pd.Series(True, index=df.index))
    t = df[keep].copy()
    t = t[t["Symbol"].str.strip().str.len() > 0]
    t = t[~t["Symbol"].str.strip().str.upper().isin(CASH_SWEEP)]

    qty = pd.to_numeric(t["Quantity"], errors="coerce")
    # Reinvestments carry no Settlement Date; fall back to the Run Date when the
    # export has one at all.
    trade_date = pd.to_datetime(t.get("Settlement Date"), errors="coerce")
    if "Run Date" in t.columns:
        trade_date = trade_date.fillna(pd.to_datetime(t["Run Date"], errors="coerce"))
    reinv_t = is_reinv.reindex(t.index).fillna(False)

    trades = pd.DataFrame({
        "ticker": t["Symbol"].str.strip().str.upper(),
        "name": t.get("Description", t["Symbol"]).str.strip(),
        "trade_date": trade_date.dt.strftime("%Y-%m-%d"),
        # A reinvestment is always an acquisition, whatever the sign convention.
        "side": ["BUY" if r or q > 0 else "SELL"
                 for r, q in zip(reinv_t, qty)],
        "quantity": qty.abs(),
        "price": pd.to_numeric(t["Price ($)"], errors="coerce"),
        "fees": pd.to_numeric(t.get("Fees ($)"), errors="coerce").fillna(0.0),
        "source_ref": [_source_ref(r, int(r["_line"])) for _, r in t.iterrows()],
    }).dropna(subset=["quantity", "price", "trade_date"])
    trades = trades[trades["quantity"] > 0]

    # ---- Dividends: cash received, summed across accounts per ex-date --------
    # A trimmed export carries no Action column and therefore no dividend rows.
    d = (df[act.str.contains("DIVIDEND RECEIVED")].copy() if has_action
         else df.iloc[0:0].copy())
    if "Run Date" not in d.columns:
        d = d.assign(**{"Run Date": pd.Series(dtype="object")})
    d = d[d["Symbol"].str.strip().str.len() > 0]
    divs = pd.DataFrame({
        "ticker": d["Symbol"].str.strip().str.upper(),
        "name": d.get("Description", d["Symbol"]).str.strip(),
        "ex_date": pd.to_datetime(d["Run Date"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "amount": pd.to_numeric(d["Amount ($)"], errors="coerce"),
    }).dropna(subset=["ex_date", "amount"])
    divs = divs[divs["amount"] > 0]

    names = (pd.concat([trades[["ticker", "name"]], divs[["ticker", "name"]]])
             .drop_duplicates("ticker").set_index("ticker")["name"].to_dict())
    divs = divs.groupby(["ticker", "ex_date"], as_index=False)["amount"].sum()

    return {"trades": trades, "dividends": divs, "names": names}


# Backwards-compatible alias: Week 5 called this parse_fidelity_csv.
def parse_fidelity_csv(path: str) -> pd.DataFrame:
    return parse_export(path)["trades"]


# ---------------------------------------------------------------------------
# Security metadata (sector / asset_type)
# ---------------------------------------------------------------------------
def fetch_security_meta(tickers, use_cache=True) -> dict:
    """Look up sector and asset type per ticker, cached to JSON.

    ETFs and mutual funds have no single sector (they are baskets), so we store
    the fund category there instead — that is what makes the sector-exposure
    query meaningful rather than a wall of NULLs.
    """
    cache = {}
    if use_cache and os.path.exists(META_CACHE):
        with open(META_CACHE) as fh:
            cache = json.load(fh)
    missing = [t for t in tickers if t not in cache]
    if missing:
        try:
            import yfinance as yf
            for tk in missing:
                try:
                    info = yf.Ticker(tk).info or {}
                    qt = (info.get("quoteType") or "").upper()
                    asset = {"EQUITY": "STOCK", "ETF": "ETF",
                             "MUTUALFUND": "FUND"}.get(qt, "OTHER")
                    cache[tk] = {"sector": info.get("sector") or info.get("category"),
                                 "asset_type": asset,
                                 "name": info.get("shortName")}
                except Exception:
                    cache[tk] = {"sector": None, "asset_type": "OTHER", "name": None}
        except ImportError:
            for tk in missing:
                cache.setdefault(tk, {"sector": None, "asset_type": "OTHER", "name": None})
        with open(META_CACHE, "w") as fh:
            json.dump(cache, fh, indent=1, sort_keys=True)
    return cache


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_securities(con, names: dict, meta: dict):
    cur = con.cursor()
    for tk, nm in names.items():
        m = meta.get(tk, {})
        cur.execute(
            """INSERT INTO securities (ticker, name, sector, asset_type)
               VALUES (?,?,?,?)
               ON CONFLICT(ticker) DO UPDATE SET
                 sector     = COALESCE(excluded.sector, securities.sector),
                 asset_type = excluded.asset_type""",
            (tk, (nm or tk)[:120], m.get("sector"), m.get("asset_type") or "OTHER"))


def load_trades(con, trades: pd.DataFrame) -> int:
    """Insert trades inside one transaction. Idempotent via source_ref.

    Returns the number of rows actually inserted (0 on a repeat load).
    """
    before = con.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        cur.executemany(
            """INSERT OR IGNORE INTO trades
               (ticker, trade_date, side, quantity, price, fees, source_ref)
               VALUES (?,?,?,?,?,?,?)""",
            trades[["ticker", "trade_date", "side", "quantity", "price",
                    "fees", "source_ref"]].itertuples(index=False, name=None))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return con.execute("SELECT COUNT(*) FROM trades").fetchone()[0] - before


def load_dividends(con, divs: pd.DataFrame) -> int:
    before = con.execute("SELECT COUNT(*) FROM dividends").fetchone()[0]
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        cur.executemany(
            "INSERT OR IGNORE INTO dividends (ticker, ex_date, amount) VALUES (?,?,?)",
            divs[["ticker", "ex_date", "amount"]].itertuples(index=False, name=None))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return con.execute("SELECT COUNT(*) FROM dividends").fetchone()[0] - before


def backfill_prices(con, years=2, tickers=None):
    """Fill `prices` for the given tickers (default: all securities) via yfinance."""
    import yfinance as yf
    if tickers is None:
        tickers = [r[0] for r in con.execute("SELECT ticker FROM securities")]
    if not tickers:
        return
    data = yf.download(tickers, period=f"{years}y", auto_adjust=True,
                       progress=False, group_by="ticker")
    rows, missing = [], []
    for t in tickers:
        try:
            d = data[t].dropna() if len(tickers) > 1 else data.dropna()
        except KeyError:
            missing.append(t); continue
        if d.empty:
            missing.append(t); continue
        for date, r in d.iterrows():
            rows.append((t, date.strftime("%Y-%m-%d"), float(r["Open"]),
                         float(r["High"]), float(r["Low"]), float(r["Close"]),
                         int(r["Volume"])))
    con.executemany("INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"Backfilled {len(rows)} price rows for {len(tickers)-len(missing)} tickers.")
    if missing:
        print(f"  ! no price data for: {', '.join(sorted(missing))}")


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(con):
    """Prove the constraints reject bad data, then report table sizes."""
    row = con.execute("SELECT ticker FROM securities LIMIT 1").fetchone()
    tk = row[0] if row else "TEST"
    bad = [
        ("negative qty",  f"INSERT INTO trades (ticker,trade_date,side,quantity,price) "
                          f"VALUES ('{tk}','2026-01-01','BUY',-5,10)"),
        ("bad side",      f"INSERT INTO trades (ticker,trade_date,side,quantity,price) "
                          f"VALUES ('{tk}','2026-01-01','HOLD',5,10)"),
        ("unknown FK",     "INSERT INTO trades (ticker,trade_date,side,quantity,price) "
                           "VALUES ('ZZZZ','2026-01-01','BUY',5,10)"),
        ("dup price day",  "INSERT INTO prices SELECT * FROM prices LIMIT 1"),
        ("dup source_ref", "INSERT INTO trades (ticker,trade_date,side,quantity,price,source_ref) "
                           "SELECT ticker,trade_date,side,quantity,price,source_ref "
                           "FROM trades WHERE source_ref IS NOT NULL LIMIT 1"),
        ("negative dividend", f"INSERT INTO dividends VALUES ('{tk}','1999-01-01',-5)"),
    ]
    print("\nConstraint checks (all should be REJECTED):")
    ok = True
    for name, sql in bad:
        try:
            con.execute(sql); con.rollback()
            print(f"  x {name}: WAS ACCEPTED — constraint missing!"); ok = False
        except sqlite3.Error as e:
            print(f"  + {name}: rejected ({type(e).__name__})")
    for t in ("securities", "trades", "prices", "dividends"):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {n} rows")
    return ok


def demo_data(con):
    """Offline demo: sample trades + synthetic prices.

    Only ever called against the separate demo database — synthetic prices in
    the real one silently shadow the true ones, because the price insert is
    INSERT OR IGNORE and whichever lands first wins.
    """
    import numpy as np
    parsed = parse_export(os.path.join(HERE, "sample_fidelity.csv"))
    trades = parsed["trades"]
    load_securities(con, parsed["names"], {})
    con.commit()
    n = load_trades(con, trades)
    print(f"Demo: {n} trades loaded.")
    rng = np.random.default_rng(7)
    rows = []
    for t in trades["ticker"].unique():
        price = float(trades.loc[trades.ticker == t, "price"].iloc[0])
        for d in pd.bdate_range("2026-01-02", "2026-07-03"):
            price *= float(np.exp(rng.normal(0.0004, 0.02)))
            rows.append((t, d.strftime("%Y-%m-%d"), price * 0.99, price * 1.01,
                         price * 0.98, price, int(rng.integers(1e5, 5e6))))
    con.executemany("INSERT OR IGNORE INTO prices VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    print(f"Demo: {len(rows)} synthetic price rows inserted.")


def load_export(con, csv_path: str, skip_prices=False):
    parsed = parse_export(csv_path)
    meta = fetch_security_meta(sorted(set(parsed["trades"]["ticker"]) |
                                      set(parsed["dividends"]["ticker"])))
    load_securities(con, parsed["names"], meta)
    con.commit()
    nt = load_trades(con, parsed["trades"])
    nd = load_dividends(con, parsed["dividends"])
    print(f"Loaded {nt} new trades ({len(parsed['trades'])} in file), "
          f"{nd} new dividend rows ({len(parsed['dividends'])} in file).")
    if not skip_prices:
        backfill_prices(con)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--demo" in args:
        # Deliberately a different file: never mix synthetic prices with real.
        if os.path.exists(DEMO_DB_PATH):
            os.remove(DEMO_DB_PATH)
        con = connect(DEMO_DB_PATH)
        create_schema(con)
        demo_data(con)
        verify(con)
        print(f"\nDemo database at: {DEMO_DB_PATH}")
    elif args:
        con = connect()
        create_schema(con)
        load_export(con, args[0], skip_prices="--skip-prices" in args)
        verify(con)
        print(f"\nDatabase at: {DB_PATH}")
    else:
        print("usage: python build_db.py <fidelity.csv> [--skip-prices]"
              "  |  python build_db.py --demo")
        sys.exit(1)
