"""
Week 12 — Price cache for tickers the portfolio database does not hold
======================================================================
The research app lets you add tickers you are only considering, and enter
positions the database does not know about yet. Their prices have to come from
somewhere, and that somewhere is deliberately NOT data/portfolio.db: that file
is built from brokerage exports and the daily ETL, and a research tool should
not be writing into it.

So fetched prices go into a separate SQLite file, data/research_prices.db,
which the pipeline reads only for tickers that have no prices in the portfolio
database at all. A ticker is never stitched together from both sources.

The pipeline itself still makes no network calls. Fetching is a separate,
explicit step: the app's "Fetch prices" button, or this script:

    python projects/11-capstone-platform/market_data.py AAPL MSFT

Only ticker symbols are sent to Yahoo Finance — never share counts or values.
Prices are dividend- and split-adjusted closes (auto_adjust=True), the same
series build_db.py and the ETL store, so returns from the two sources are
comparable.
"""
from __future__ import annotations
import argparse
import math
import os
import re
import sqlite3
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
# Overridable so the test suites can use a throwaway file.
CACHE_DB = os.environ.get("RESEARCH_PRICES_DB",
                          os.path.join(REPO, "data", "research_prices.db"))

# Five years is more than the portfolio database holds, so a fetched ticker is
# never the one that shortens the shared window.
PERIOD = "5y"

# Yahoo symbols: letters, digits, and . - ^ = (BRK-B, ^GSPC, EURUSD=X).
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=]{0,14}$|^\^[A-Z0-9.\-=]{1,14}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prices (
    ticker TEXT NOT NULL,
    date   TEXT NOT NULL,
    close  REAL NOT NULL CHECK (close > 0),
    PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS fetches (
    ticker     TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    n_rows     INTEGER NOT NULL,
    first_date TEXT NOT NULL,
    last_date  TEXT NOT NULL
);
"""


def parse_tickers(text: str) -> tuple[list[str], list[str]]:
    """Split free text into (valid symbols, rejected tokens).

    Commas, semicolons and whitespace all separate; case is normalised;
    duplicates are dropped keeping the first occurrence.
    """
    valid, bad = [], []
    for tok in re.split(r"[\s,;]+", text or ""):
        tok = tok.strip().upper()
        if not tok:
            continue
        if _SYMBOL.match(tok):
            if tok not in valid:
                valid.append(tok)
        elif tok not in bad:
            bad.append(tok)
    return valid, bad


def _connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def cached_tickers(path: str | None = None) -> dict[str, dict]:
    """{ticker: {fetched_at, n_rows, first_date, last_date}} for the cache."""
    path = path or CACHE_DB
    if not os.path.exists(path):
        return {}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "fetches" not in names:
            return {}
        return {t: {"fetched_at": f, "n_rows": n, "first_date": a, "last_date": b}
                for t, f, n, a, b in con.execute(
                    "SELECT ticker, fetched_at, n_rows, first_date, last_date "
                    "FROM fetches ORDER BY ticker")}
    finally:
        con.close()


def yahoo_closes(ticker: str, period: str = PERIOD) -> list[tuple[str, float]]:
    """Adjusted daily closes for one ticker as [(YYYY-MM-DD, close)].

    Needs network access and yfinance. Returns [] for an unknown symbol.
    """
    import yfinance as yf
    hist = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    if hist is None or hist.empty or "Close" not in hist:
        return []
    return [(ts.strftime("%Y-%m-%d"), float(c))
            for ts, c in hist["Close"].items()]


def clean_closes(rows, today: str | None = None) -> list[tuple[str, float]]:
    """Keep completed sessions with a usable price.

    Drops non-finite or non-positive closes, and today's bar: during market
    hours it is a moving intraday price, and keeping it would make the same
    analysis give different answers an hour apart. Later duplicates of a date
    replace earlier ones; the result is sorted by date.
    """
    today = today or date.today().isoformat()
    by_date = {}
    for d, c in rows:
        if d >= today:
            continue
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if math.isfinite(c) and c > 0:
            by_date[d] = c
    return sorted(by_date.items())


def fetch(tickers, path: str | None = None, source=None,
          today: str | None = None) -> dict:
    """Download each ticker and REPLACE its cached history.

    Replacing rather than appending matters: adjusted closes are rewritten
    backwards every time a dividend or split occurs, so new rows appended to an
    old adjusted history would put a false jump at the seam.

    `source(ticker) -> [(date, close)]` defaults to `yahoo_closes`, looked up
    at call time so tests can swap it for an offline stub.
    Returns {"stored": {ticker: n_rows}, "missing": [...], "errors": {...}}.
    Each ticker is its own transaction: one bad symbol never loses the others.
    """
    path = path or CACHE_DB
    source = source or yahoo_closes
    stored, missing, errors = {}, [], {}
    con = _connect(path)
    try:
        for t in tickers:
            try:
                rows = clean_closes(source(t), today=today)
            except Exception as e:                 # network, parsing, rate limit
                errors[t] = f"{type(e).__name__}: {e}"
                continue
            if not rows:
                missing.append(t)
                continue
            with con:
                con.execute("DELETE FROM prices WHERE ticker = ?", (t,))
                con.executemany("INSERT INTO prices VALUES (?, ?, ?)",
                                [(t, d, c) for d, c in rows])
                con.execute(
                    "INSERT OR REPLACE INTO fetches VALUES (?, ?, ?, ?, ?)",
                    (t, datetime.now().isoformat(timespec="seconds"), len(rows),
                     rows[0][0], rows[-1][0]))
            stored[t] = len(rows)
    finally:
        con.close()
    return {"stored": stored, "missing": missing, "errors": errors}


def main():
    ap = argparse.ArgumentParser(description="Fetch adjusted daily closes into "
                                             "the research price cache.")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--cache", default=None, help=f"default {CACHE_DB}")
    a = ap.parse_args()
    tickers, bad = parse_tickers(" ".join(a.tickers))
    for b in bad:
        print(f"  skipped {b!r}: not a ticker symbol")
    res = fetch(tickers, a.cache)
    for t, n in res["stored"].items():
        print(f"  {t:<8} {n} days")
    for t in res["missing"]:
        print(f"  {t:<8} no data (unknown or delisted symbol?)")
    for t, e in res["errors"].items():
        print(f"  {t:<8} failed: {e}")
    print(f"Cache: {a.cache or CACHE_DB}")
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
