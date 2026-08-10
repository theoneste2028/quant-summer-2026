"""
Week 7 — Daily OHLCV ETL Pipeline
=================================
CS 217. Pulls daily price bars for every ticker in the portfolio database,
validates them, and loads them inside a single transaction.

The four properties that separate a pipeline from a script that happens to
insert rows:

  VALIDATED    Every row is checked before anything is written — no nulls,
               prices strictly positive, high >= low, the OHLC band actually
               containing open and close, no future dates, ticker known to the
               `securities` table. Bad rows are rejected with a reason, not
               silently coerced.

  TRANSACTIONAL One BEGIN ... COMMIT for the whole batch. If row 400 of 500
               violates a constraint, the first 399 do not survive: a partial
               day is worse than no day, because it looks complete.

  IDEMPOTENT   Running the same date twice inserts nothing the second time.
               Validation drops rows whose (ticker, date) is already stored,
               and the catch-up window starts from the last date present so
               settled days are not re-fetched at all. The primary key is the
               backstop rather than the mechanism — see load() for why that
               distinction decides whether a bad batch fails loudly or quietly.

  LOGGED       Rows extracted, rejected (with reasons), inserted, and elapsed
               runtime go to logs/etl.log. A pipeline that fails silently at
               3am is indistinguishable from one that never ran.

Run:
    python etl.py                          # catch up from the last stored date
    python etl.py --date 2026-07-24        # one specific day
    python etl.py --since 2026-07-01       # a range, up to today
    python etl.py --dry-run                # validate and report, write nothing
"""
from __future__ import annotations
import os, sys, time, logging, sqlite3, argparse
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
DB_PATH = os.path.join(REPO, "data", "portfolio.db")
LOG_DIR = os.path.join(HERE, "logs")
LOG_PATH = os.path.join(LOG_DIR, "etl.log")

log = logging.getLogger("etl")


def setup_logging(verbose=True, log_path=LOG_PATH):
    """File log always; console log optional. Idempotent across calls."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    log.setLevel(logging.DEBUG)
    log.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_path)
    fh.setFormatter(fmt); fh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    if verbose:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        ch.setLevel(logging.INFO)
        log.addHandler(ch)
    return log


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
def target_tickers(con) -> list[str]:
    """Tickers worth fetching: those the portfolio has ever traded."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM securities WHERE ticker IN "
        "(SELECT DISTINCT ticker FROM trades) ORDER BY ticker")]


def existing_dates(con, ticker: str) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT date FROM prices WHERE ticker = ?", (ticker,))}


def last_stored_date(con) -> str | None:
    r = con.execute("SELECT MAX(date) FROM prices").fetchone()
    return r[0] if r and r[0] else None


def extract(tickers, start: str, end: str) -> list[dict]:
    """Fetch OHLCV bars in [start, end] inclusive. Requires yfinance."""
    import yfinance as yf
    # yfinance treats `end` as exclusive, so push it out by a day.
    end_excl = (dt.date.fromisoformat(end) + dt.timedelta(days=1)).isoformat()
    log.info(f"extract: {len(tickers)} tickers, {start} .. {end}")
    data = yf.download(tickers, start=start, end=end_excl, auto_adjust=True,
                       progress=False, group_by="ticker")
    rows = []
    for t in tickers:
        try:
            frame = data[t].dropna() if len(tickers) > 1 else data.dropna()
        except (KeyError, TypeError):
            log.warning(f"extract: no data returned for {t}")
            continue
        for date, r in frame.iterrows():
            rows.append({
                "ticker": t, "date": date.strftime("%Y-%m-%d"),
                "open": _f(r.get("Open")), "high": _f(r.get("High")),
                "low": _f(r.get("Low")), "close": _f(r.get("Close")),
                "volume": _i(r.get("Volume")),
            })
    log.info(f"extract: {len(rows)} raw rows")
    return rows


def _f(v):
    try:
        f = float(v)
        return None if f != f else f      # NaN -> None
    except (TypeError, ValueError):
        return None


def _i(v):
    try:
        f = float(v)
        return None if f != f else int(f)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Validate
# ---------------------------------------------------------------------------
def validate(rows, known_tickers: set[str], seen: dict[str, set[str]],
             today: str | None = None) -> tuple[list[dict], list[tuple]]:
    """Split rows into (accepted, rejected). rejected = [(row, reason), ...].

    Every check here corresponds to a way the upstream feed has actually been
    wrong at some point: missing bars come back as NaN, a thin ticker can print
    a zero, and a mis-parsed date can land in the future.
    """
    today = today or dt.date.today().isoformat()
    ok, bad = [], []
    batch_seen: set[tuple] = set()

    for r in rows:
        t, d = r.get("ticker"), r.get("date")
        if not t or not d:
            bad.append((r, "missing ticker or date")); continue
        if t not in known_tickers:
            bad.append((r, f"unknown ticker {t!r} (not in securities)")); continue
        try:
            dt.date.fromisoformat(d)
        except (ValueError, TypeError):
            bad.append((r, f"unparseable date {d!r}")); continue
        if d > today:
            bad.append((r, f"date {d} is in the future")); continue

        vals = {k: r.get(k) for k in ("open", "high", "low", "close")}
        missing = [k for k, v in vals.items() if v is None]
        if missing:
            bad.append((r, f"null price field(s): {','.join(missing)}")); continue
        if any(v <= 0 for v in vals.values()):
            bad.append((r, "non-positive price")); continue
        if vals["high"] < vals["low"]:
            bad.append((r, "high < low")); continue
        # The band must contain the endpoints, else the bar is internally
        # inconsistent even though each individual number looks plausible.
        if not (vals["low"] <= vals["open"] <= vals["high"]):
            bad.append((r, "open outside [low, high]")); continue
        if not (vals["low"] <= vals["close"] <= vals["high"]):
            bad.append((r, "close outside [low, high]")); continue
        if r.get("volume") is not None and r["volume"] < 0:
            bad.append((r, "negative volume")); continue

        if d in seen.get(t, ()):
            bad.append((r, "already present in database")); continue
        if (t, d) in batch_seen:
            bad.append((r, "duplicate within this batch")); continue

        batch_seen.add((t, d))
        ok.append(r)

    return ok, bad


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load(con, rows) -> int:
    """Insert accepted rows in ONE transaction. Any failure rolls back all.

    Deliberately a plain INSERT, not INSERT OR IGNORE. `OR IGNORE` suppresses
    *every* constraint violation, not just duplicate keys — a row with a
    negative close would be silently dropped and the rest of the batch would
    commit, which is exactly the silent-partial-success this pipeline exists to
    prevent. Idempotency is already handled upstream: validate() removes rows
    whose (ticker, date) is present. The primary key is the backstop, and with
    a plain INSERT it turns a duplicate that slipped through into a loud
    rollback instead of a quiet no-op.
    """
    if not rows:
        return 0
    before = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    cur = con.cursor()
    try:
        cur.execute("BEGIN")
        cur.executemany(
            "INSERT INTO prices (ticker,date,open,high,low,close,volume) "
            "VALUES (:ticker,:date,:open,:high,:low,:close,:volume)", rows)
        con.commit()
    except Exception as e:
        con.rollback()
        log.error(f"load: transaction rolled back — {type(e).__name__}: {e}")
        raise
    return con.execute("SELECT COUNT(*) FROM prices").fetchone()[0] - before


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(db_path=DB_PATH, date=None, since=None, dry_run=False, rows=None):
    """One ETL run. `rows` may be supplied to bypass extraction (for tests)."""
    t0 = time.perf_counter()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row

    known = {r[0] for r in con.execute("SELECT ticker FROM securities")}
    tickers = target_tickers(con)
    today = dt.date.today().isoformat()

    if date:
        start = end = date
    elif since:
        start, end = since, today
    else:
        last = last_stored_date(con)
        start = ((dt.date.fromisoformat(last) + dt.timedelta(days=1)).isoformat()
                 if last else (dt.date.today() - dt.timedelta(days=5)).isoformat())
        end = today
    if start > end:
        log.info(f"nothing to do: database is current through {end}")
        con.close()
        return {"extracted": 0, "accepted": 0, "rejected": 0, "inserted": 0,
                "seconds": time.perf_counter() - t0}

    log.info(f"=== ETL run start (window {start} .. {end}, "
             f"{'DRY RUN' if dry_run else 'live'}) ===")

    if rows is None:
        rows = extract(tickers, start, end)

    seen = {t: existing_dates(con, t) for t in tickers}
    ok, bad = validate(rows, known, seen, today=today)

    reasons: dict[str, int] = {}
    for _, why in bad:
        key = why.split("(")[0].strip()
        reasons[key] = reasons.get(key, 0) + 1
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        log.info(f"rejected {n:>6} row(s): {why}")
    for r, why in bad[:5]:
        log.debug(f"  sample reject: {r.get('ticker')} {r.get('date')} — {why}")

    inserted = 0 if dry_run else load(con, ok)
    if dry_run:
        log.info(f"dry run: would insert {len(ok)} rows")

    elapsed = time.perf_counter() - t0
    log.info(f"extracted={len(rows)} accepted={len(ok)} rejected={len(bad)} "
             f"inserted={inserted} elapsed={elapsed:.2f}s")
    log.info("=== ETL run end ===")
    con.close()
    return {"extracted": len(rows), "accepted": len(ok), "rejected": len(bad),
            "inserted": inserted, "seconds": elapsed, "reasons": reasons}


def main():
    ap = argparse.ArgumentParser(description="Daily OHLCV ETL into SQLite")
    ap.add_argument("--date", help="single date YYYY-MM-DD")
    ap.add_argument("--since", help="start date; runs through today")
    ap.add_argument("--dry-run", action="store_true", help="validate only")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    setup_logging(verbose=not a.quiet)
    try:
        s = run(a.db, date=a.date, since=a.since, dry_run=a.dry_run)
    except Exception as e:
        log.exception(f"ETL FAILED: {e}")
        return 2
    return 0 if s["rejected"] == 0 or s["inserted"] > 0 or s["extracted"] == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
