-- Weeks 5-6 — Portfolio Database Schema (SQLite, 3NF)
-- Run: sqlite3 data/portfolio.db < schema.sql

PRAGMA foreign_keys = ON;

-- One row per instrument. Ticker is the natural primary key.
-- sector is NULL-able because ETFs and mutual funds are baskets with no single
-- sector; the loader stores their fund category there instead.
CREATE TABLE IF NOT EXISTS securities (
    ticker      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    sector      TEXT,
    asset_type  TEXT NOT NULL DEFAULT 'ETF'
                CHECK (asset_type IN ('STOCK','ETF','FUND','BOND','OTHER'))
);

-- One row per execution. Fidelity gives signed quantities; we store
-- side explicitly and quantity as a positive REAL (fractional shares exist).
--
-- source_ref is a stable fingerprint of the source CSV row (its content plus
-- its line number). The UNIQUE constraint is what makes loading IDEMPOTENT:
-- re-running the same export inserts nothing the second time, because every row
-- maps to a ref already present. Including the line number means two genuinely
-- separate fills of identical size and price on the same day are both kept --
-- they sit on different lines, so they get different refs.
CREATE TABLE IF NOT EXISTS trades (
    trade_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES securities(ticker),
    trade_date  TEXT NOT NULL,                      -- ISO yyyy-mm-dd
    side        TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity    REAL NOT NULL CHECK (quantity > 0), -- REAL: fractional shares
    price       REAL NOT NULL CHECK (price >= 0),
    fees        REAL NOT NULL DEFAULT 0 CHECK (fees >= 0),
    source_ref  TEXT UNIQUE                         -- idempotency key
);

-- One row per ticker per day. Composite PK prevents duplicate days.
CREATE TABLE IF NOT EXISTS prices (
    ticker  TEXT NOT NULL REFERENCES securities(ticker),
    date    TEXT NOT NULL,
    open    REAL, high REAL, low REAL,
    close   REAL NOT NULL CHECK (close > 0),
    volume  INTEGER,
    PRIMARY KEY (ticker, date)
);

-- Cash income per security per ex-date.
--
-- SEMANTICS: `amount` is TOTAL CASH RECEIVED in dollars, not a per-share rate.
-- The brokerage export reports cash received, and the Week 6 "dividend income
-- by quarter" query wants dollars. Deriving a per-share rate would need the
-- position held on the ex-date, which is itself a query result -- storing it
-- would break the no-derived-values rule the rest of this schema follows.
--
-- The account dimension is deliberately collapsed: one security paying a
-- dividend in several brokerage accounts on the same date produces several
-- export rows, which the loader SUMS into one row here. Modelling accounts as
-- a first-class entity would replace this PK with (account_id, ticker, ex_date).
CREATE TABLE IF NOT EXISTS dividends (
    ticker  TEXT NOT NULL REFERENCES securities(ticker),
    ex_date TEXT NOT NULL,
    amount  REAL NOT NULL CHECK (amount > 0),       -- total cash received, USD
    PRIMARY KEY (ticker, ex_date)
);

-- Indexes supporting the Week 6 analytical queries, which all scan
-- ticker-then-date. (Week 8 measures what indexes like these actually buy.)
CREATE INDEX IF NOT EXISTS idx_trades_ticker_date ON trades(ticker, trade_date);
CREATE INDEX IF NOT EXISTS idx_prices_date        ON prices(date);
