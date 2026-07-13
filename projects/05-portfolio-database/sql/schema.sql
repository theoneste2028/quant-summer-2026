-- Week 5 — Portfolio Database Schema (SQLite, 3NF)
-- Run: sqlite3 data/portfolio.db < schema.sql

PRAGMA foreign_keys = ON;

-- One row per instrument. Ticker is the natural primary key.
CREATE TABLE IF NOT EXISTS securities (
    ticker      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    sector      TEXT,
    asset_type  TEXT NOT NULL DEFAULT 'ETF'
                CHECK (asset_type IN ('STOCK','ETF','FUND','BOND','OTHER'))
);

-- One row per execution. Fidelity gives signed quantities; we store
-- side explicitly and quantity as a positive REAL (fractional shares exist).
CREATE TABLE IF NOT EXISTS trades (
    trade_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL REFERENCES securities(ticker),
    trade_date  TEXT NOT NULL,                      -- ISO yyyy-mm-dd
    side        TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity    REAL NOT NULL CHECK (quantity > 0), -- REAL: fractional shares
    price       REAL NOT NULL CHECK (price >= 0),
    fees        REAL NOT NULL DEFAULT 0 CHECK (fees >= 0)
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

CREATE TABLE IF NOT EXISTS dividends (
    ticker  TEXT NOT NULL REFERENCES securities(ticker),
    ex_date TEXT NOT NULL,
    amount  REAL NOT NULL CHECK (amount > 0),       -- per share
    PRIMARY KEY (ticker, ex_date)
);
