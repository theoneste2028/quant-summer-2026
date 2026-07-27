-- ===========================================================================
-- Week 6 — Analytical Queries over the Portfolio Database
-- CS 217 · run them with:  python dashboard.py            (all)
--                          python dashboard.py positions  (one)
--
-- Each query is introduced by a "-- name: <id>" marker so `dashboard.py` can
-- split this file and run them individually. Everything below is plain SQLite;
-- no Python is needed to get the answers.
--
-- THE ONE IDEA THAT RUNS THROUGH THIS FILE
-- ----------------------------------------
-- The database stores only facts that were observed: executions, closing
-- prices, cash received. Positions, cost basis, and P&L are *derived*, so they
-- live here as queries rather than as columns. Nothing can go stale, and there
-- is exactly one definition of each concept.
-- ===========================================================================


-- name: positions
-- ---------------------------------------------------------------------------
-- Current position per ticker: buys minus sells.
--
-- The HAVING clause uses a 1e-9 epsilon rather than "> 0" because quantities
-- are REAL to support fractional shares, and a fully-closed position can land
-- on 4.4e-16 instead of exactly zero. Comparing floats with = or > 0 is how a
-- closed position sneaks back into a report as a dust holding.
-- ---------------------------------------------------------------------------
SELECT
    t.ticker,
    s.name,
    s.sector,
    s.asset_type,
    ROUND(SUM(CASE t.side WHEN 'BUY' THEN t.quantity ELSE -t.quantity END), 6) AS net_quantity,
    COUNT(*)                                                                   AS n_trades,
    MIN(t.trade_date)                                                          AS first_trade,
    MAX(t.trade_date)                                                          AS last_trade
FROM trades t
JOIN securities s ON s.ticker = t.ticker
GROUP BY t.ticker, s.name, s.sector, s.asset_type
HAVING SUM(CASE t.side WHEN 'BUY' THEN t.quantity ELSE -t.quantity END) > 1e-9
ORDER BY net_quantity DESC;


-- name: fifo_matches
-- ---------------------------------------------------------------------------
-- FIFO lot matching — the hard one, done in pure SQL.
--
-- THE TRICK: think of every share of a ticker as occupying a position on a
-- number line. The first share ever bought sits at [0,1), the next at [1,2),
-- and so on. A BUY of `q` shares therefore covers the half-open interval
--   [running_bought_before, running_bought_before + q)
-- and a SELL of `q` shares consumes
--   [running_sold_before,   running_sold_before + q).
--
-- Under FIFO, a sell consumes the lowest unsold positions on that line — which
-- means a buy lot and a sell are matched exactly where their intervals OVERLAP,
-- and the matched quantity is the length of that overlap. No cursor, no loop:
-- two running totals (window functions) and an inequality join.
--
-- Fees are apportioned to each match in proportion to the share of the lot
-- consumed, so realized P&L is net of the costs actually incurred on it.
-- ---------------------------------------------------------------------------
WITH buy_lots AS (
    SELECT
        ticker, trade_date, price, quantity, fees,
        SUM(quantity) OVER w - quantity AS lot_start,   -- interval lower bound
        SUM(quantity) OVER w            AS lot_end      -- interval upper bound
    FROM trades
    WHERE side = 'BUY'
    WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
sell_lots AS (
    SELECT
        ticker, trade_date, price, quantity, fees,
        SUM(quantity) OVER w - quantity AS lot_start,
        SUM(quantity) OVER w            AS lot_end
    FROM trades
    WHERE side = 'SELL'
    WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
SELECT
    b.ticker,
    b.trade_date                                       AS buy_date,
    s.trade_date                                       AS sell_date,
    ROUND(MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start), 6) AS matched_qty,
    b.price                                            AS buy_price,
    s.price                                            AS sell_price,
    ROUND(
        (MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start)) * (s.price - b.price)
        - b.fees * (MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start)) / b.quantity
        - s.fees * (MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start)) / s.quantity
    , 4)                                               AS realized_pnl,
    CAST(julianday(s.trade_date) - julianday(b.trade_date) AS INTEGER) AS holding_days
FROM buy_lots b
JOIN sell_lots s
  ON s.ticker = b.ticker
 -- the intervals genuinely overlap (strictly, so zero-length touches drop out)
 AND MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start) > 1e-9
ORDER BY b.ticker, sell_date, buy_date;


-- name: realized_pnl
-- ---------------------------------------------------------------------------
-- Realized P&L per ticker, aggregated from the FIFO matches above.
-- A "round trip" here is one matched (buy lot, sell) pair.
-- ---------------------------------------------------------------------------
WITH buy_lots AS (
    SELECT ticker, trade_date, price, quantity, fees,
           SUM(quantity) OVER w - quantity AS lot_start,
           SUM(quantity) OVER w            AS lot_end
    FROM trades WHERE side = 'BUY'
    WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
sell_lots AS (
    SELECT ticker, trade_date, price, quantity, fees,
           SUM(quantity) OVER w - quantity AS lot_start,
           SUM(quantity) OVER w            AS lot_end
    FROM trades WHERE side = 'SELL'
    WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
matches AS (
    SELECT b.ticker,
           MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start) AS q,
           b.price AS bp, s.price AS sp, b.fees AS bf, s.fees AS sf,
           b.quantity AS bq, s.quantity AS sq
    FROM buy_lots b
    JOIN sell_lots s ON s.ticker = b.ticker
     AND MIN(b.lot_end, s.lot_end) - MAX(b.lot_start, s.lot_start) > 1e-9
)
SELECT
    ticker,
    COUNT(*)                                              AS round_trips,
    ROUND(SUM(q), 4)                                      AS shares_closed,
    ROUND(SUM(q * bp), 2)                                 AS cost_of_closed,
    ROUND(SUM(q * sp), 2)                                 AS proceeds,
    ROUND(SUM(q * (sp - bp) - bf*q/bq - sf*q/sq), 2)       AS realized_pnl,
    ROUND(100.0 * SUM(q * (sp - bp) - bf*q/bq - sf*q/sq)
          / NULLIF(SUM(q * bp), 0), 2)                    AS return_pct
FROM matches
GROUP BY ticker
ORDER BY realized_pnl DESC;


-- name: cost_basis
-- ---------------------------------------------------------------------------
-- Cost basis and UNREALIZED P&L for open positions, on the same FIFO basis as
-- the realized query above — so the two reconcile instead of quietly using
-- different conventions.
--
-- A buy lot's shares are still held when its interval lies beyond everything
-- sold so far, i.e. above `total_sold` on the number line. The still-held part
-- of a lot is therefore  lot_end - MAX(lot_start, total_sold), floored at 0.
--
-- Uses a LEFT JOIN to the latest price: a security with no price rows (a
-- delisted ticker, say) must still appear with its cost basis rather than
-- vanish from the report, which is exactly what an inner join would do.
-- ---------------------------------------------------------------------------
WITH sold AS (
    SELECT ticker, SUM(quantity) AS total_sold
    FROM trades WHERE side = 'SELL' GROUP BY ticker
),
buy_lots AS (
    SELECT ticker, price, quantity, fees,
           SUM(quantity) OVER w - quantity AS lot_start,
           SUM(quantity) OVER w            AS lot_end
    FROM trades WHERE side = 'BUY'
    WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
open_lots AS (
    SELECT b.ticker, b.price,
           MAX(0, b.lot_end - MAX(b.lot_start, COALESCE(s.total_sold, 0))) AS held_qty
    FROM buy_lots b
    LEFT JOIN sold s ON s.ticker = b.ticker
),
latest AS (
    SELECT ticker, close, date FROM (
        SELECT ticker, close, date,
               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
        FROM prices
    ) WHERE rn = 1
)
SELECT
    o.ticker,
    sec.sector,
    ROUND(SUM(o.held_qty), 6)                                  AS quantity,
    ROUND(SUM(o.held_qty * o.price), 2)                        AS cost_basis,
    ROUND(SUM(o.held_qty * o.price) / NULLIF(SUM(o.held_qty), 0), 4) AS avg_cost,
    l.close                                                    AS last_price,
    l.date                                                     AS price_date,
    ROUND(SUM(o.held_qty) * l.close, 2)                        AS market_value,
    ROUND(SUM(o.held_qty) * l.close - SUM(o.held_qty * o.price), 2) AS unrealized_pnl,
    ROUND(100.0 * (SUM(o.held_qty) * l.close - SUM(o.held_qty * o.price))
          / NULLIF(SUM(o.held_qty * o.price), 0), 2)           AS unrealized_pct
FROM open_lots o
JOIN securities sec ON sec.ticker = o.ticker
LEFT JOIN latest  l ON l.ticker  = o.ticker
WHERE o.held_qty > 1e-9
GROUP BY o.ticker, sec.sector, l.close, l.date
ORDER BY market_value DESC;


-- name: portfolio_value
-- ---------------------------------------------------------------------------
-- Portfolio market value over time.
--
-- For every trading day we need the position held *as of* that day, which is
-- the running sum of all trades up to it. The join condition `t.trade_date <=
-- d.date` is what makes this an as-of calculation rather than a snapshot.
--
-- Only days on or after the first trade are considered, and a position
-- contributes only on days the ticker actually has a close.
-- ---------------------------------------------------------------------------
WITH days AS (
    SELECT DISTINCT date FROM prices
    WHERE date >= (SELECT MIN(trade_date) FROM trades)
),
holdings AS (
    SELECT d.date, t.ticker,
           SUM(CASE t.side WHEN 'BUY' THEN t.quantity ELSE -t.quantity END) AS qty
    FROM days d
    JOIN trades t ON t.trade_date <= d.date
    GROUP BY d.date, t.ticker
)
SELECT
    h.date,
    COUNT(DISTINCT CASE WHEN h.qty > 1e-9 THEN h.ticker END) AS n_positions,
    ROUND(SUM(h.qty * p.close), 2)                           AS portfolio_value
FROM holdings h
JOIN prices p ON p.ticker = h.ticker AND p.date = h.date
WHERE h.qty > 1e-9
GROUP BY h.date
ORDER BY h.date;


-- name: sector_exposure
-- ---------------------------------------------------------------------------
-- Sector exposure as a percentage of total portfolio market value.
--
-- The weight denominator is a scalar subquery over the same open-position
-- expression, so the percentages sum to 100 by construction. ETFs and mutual
-- funds carry a fund category rather than a true sector; anything still
-- unclassified is bucketed as 'Unclassified' instead of dropping out of the
-- report, since a silent omission would make the weights wrong.
-- ---------------------------------------------------------------------------
WITH sold AS (
    SELECT ticker, SUM(quantity) AS total_sold
    FROM trades WHERE side = 'SELL' GROUP BY ticker
),
buy_lots AS (
    SELECT ticker, price, quantity,
           SUM(quantity) OVER w - quantity AS lot_start,
           SUM(quantity) OVER w            AS lot_end
    FROM trades WHERE side = 'BUY'
    WINDOW w AS (PARTITION BY ticker ORDER BY trade_date, trade_id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
),
open_pos AS (
    SELECT b.ticker,
           SUM(MAX(0, b.lot_end - MAX(b.lot_start, COALESCE(s.total_sold, 0)))) AS qty
    FROM buy_lots b
    LEFT JOIN sold s ON s.ticker = b.ticker
    GROUP BY b.ticker
),
latest AS (
    SELECT ticker, close FROM (
        SELECT ticker, close,
               ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
        FROM prices
    ) WHERE rn = 1
),
valued AS (
    SELECT COALESCE(NULLIF(TRIM(sec.sector), ''), 'Unclassified') AS sector,
           o.ticker, o.qty * l.close AS mv
    FROM open_pos o
    JOIN securities sec ON sec.ticker = o.ticker
    JOIN latest l       ON l.ticker  = o.ticker
    WHERE o.qty > 1e-9
)
SELECT
    sector,
    COUNT(*)                                                AS n_holdings,
    ROUND(SUM(mv), 2)                                       AS market_value,
    ROUND(100.0 * SUM(mv) / (SELECT SUM(mv) FROM valued), 2) AS pct_of_portfolio
FROM valued
GROUP BY sector
ORDER BY market_value DESC;


-- name: best_worst_days
-- ---------------------------------------------------------------------------
-- Best and worst single day per holding — the window-function showcase.
--
-- LAG() reaches back one row within each ticker to get the previous close, so
-- the daily return is computable without a self-join. RANK() is then applied
-- twice over the same partition, once ascending and once descending, and the
-- outer filter keeps only the extremes.
--
-- Restricted to currently-held tickers, so the report describes the portfolio
-- you have rather than every ticker you ever touched.
-- ---------------------------------------------------------------------------
WITH held AS (
    SELECT ticker FROM trades GROUP BY ticker
    HAVING SUM(CASE side WHEN 'BUY' THEN quantity ELSE -quantity END) > 1e-9
),
rets AS (
    SELECT
        p.ticker, p.date, p.close,
        LAG(p.close) OVER (PARTITION BY p.ticker ORDER BY p.date) AS prev_close
    FROM prices p
    WHERE p.ticker IN (SELECT ticker FROM held)
),
scored AS (
    SELECT ticker, date, close, prev_close,
           100.0 * (close - prev_close) / prev_close AS ret_pct
    FROM rets
    WHERE prev_close IS NOT NULL AND prev_close > 0
),
ranked AS (
    SELECT ticker, date, ret_pct,
           RANK() OVER (PARTITION BY ticker ORDER BY ret_pct DESC) AS rank_best,
           RANK() OVER (PARTITION BY ticker ORDER BY ret_pct ASC)  AS rank_worst
    FROM scored
)
SELECT
    ticker,
    MAX(CASE WHEN rank_best  = 1 THEN date    END) AS best_day,
    ROUND(MAX(CASE WHEN rank_best  = 1 THEN ret_pct END), 2) AS best_ret_pct,
    MAX(CASE WHEN rank_worst = 1 THEN date    END) AS worst_day,
    ROUND(MIN(CASE WHEN rank_worst = 1 THEN ret_pct END), 2) AS worst_ret_pct
FROM ranked
WHERE rank_best = 1 OR rank_worst = 1
GROUP BY ticker
ORDER BY best_ret_pct DESC;


-- name: dividends_by_quarter
-- ---------------------------------------------------------------------------
-- Dividend and interest income by calendar quarter.
--
-- SQLite has no date_part(), so the quarter comes from integer arithmetic on
-- the month: (month + 2) / 3 maps 1-3 to 1, 4-6 to 2, and so on. Integer
-- division truncates, which is what makes the mapping work.
--
-- `amount` is total cash received (see the schema note), already summed across
-- accounts by the loader.
-- ---------------------------------------------------------------------------
SELECT
    substr(ex_date, 1, 4)                                        AS year,
    'Q' || ((CAST(substr(ex_date, 6, 2) AS INTEGER) + 2) / 3)     AS quarter,
    COUNT(*)                                                     AS n_payments,
    COUNT(DISTINCT ticker)                                       AS n_securities,
    ROUND(SUM(amount), 2)                                        AS income
FROM dividends
GROUP BY year, quarter
ORDER BY year, quarter;


-- name: dividends_by_ticker
-- ---------------------------------------------------------------------------
-- Same income, pivoted by security — which holdings actually pay you.
-- ---------------------------------------------------------------------------
SELECT
    d.ticker,
    s.asset_type,
    COUNT(*)               AS n_payments,
    ROUND(SUM(d.amount), 2) AS total_income,
    MIN(d.ex_date)         AS first_payment,
    MAX(d.ex_date)         AS last_payment
FROM dividends d
JOIN securities s ON s.ticker = d.ticker
GROUP BY d.ticker, s.asset_type
ORDER BY total_income DESC;
