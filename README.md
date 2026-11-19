# Quant Summer 2026

A 12-week quantitative finance platform built to consolidate three Northwestern
courses, ending in a portfolio optimizer that runs on a real brokerage history.

**Status:** complete — all 12 weeks · **740 tests across 12 suites, all passing**
(`python run_all_tests.py`)

📊 **[Live results page](site/capstone.html)** — self-contained, no build step.
🔬 **[Research app](#explore-interactively)** — the same pipeline with every input on a slider.

## Contents

- [Course map](#course-map)
- [The capstone](#the-capstone)
- [Research app](#research-app)
- [Projects](#projects)
- [Writeups and docs](#writeups-and-docs)
- [Getting started](#getting-started)
- [Repository layout](#repository-layout)
- [Three things I got wrong](#three-things-i-got-wrong)
- [A note on the data](#a-note-on-the-data)

## Course map

| Phase | Course | Weeks | Topics |
|---|---|---|---|
| 1 | IEMS 302 · Probability | 1–4 | Distribution fitting, simulation, Monte Carlo pricing, Bayesian updating |
| 2 | CS 217 · Data Management | 5–8 | Portfolio database, SQL analytics, ETL, query optimization |
| 3 | CivEnv 205 · Economics & Finance | 9–10 | Capital budgeting, decision analysis, utility theory |
| 4 | Capstone · all three | 11–12 | Utility-based portfolio optimizer |

## The capstone

Five layers, each drawing on a different phase:

```
  ┌─────────────────────────────────────────────────────────────────┐
  │ 1. DATA          SQLite → returns matrix          CS 217 (5–8)  │
  │                  no live API calls; the DB is the source        │
  ├─────────────────────────────────────────────────────────────────┤
  │ 2. STATISTICS    mean vector, covariance,         IEMS 302 (1–4)│
  │                  + distribution fits to caveat normality        │
  ├─────────────────────────────────────────────────────────────────┤
  │ 3. OPTIMIZATION  Markowitz via CVXPY across γ     CivEnv 205    │
  │                  shrunk estimates + position cap                │
  ├─────────────────────────────────────────────────────────────────┤
  │ 4. DECISION      certainty equivalents pick one   Week 10       │
  │                  portfolio for a risk tolerance                 │
  ├─────────────────────────────────────────────────────────────────┤
  │ 5. SIMULATION    1-year forward paths, VaR,       Week 3        │
  │                  normal vs fat-tailed tails                     │
  └─────────────────────────────────────────────────────────────────┘
```

### Result

The recommended portfolio against the actual one (1-year horizon, fat-tailed
simulation):

| Metric | Current | Recommended | Change |
|---|---:|---:|---|
| Volatility | 65.9% | 25.3% | −62% |
| Sharpe ratio | 0.64 | 1.00 | +55% |
| P(loss > 10%) | 32.0% | 9.8% | about a third as likely |
| Expected return | 42.3% | 25.2% | −17 points |

## Research app

`app.py` is a Streamlit front end to the capstone pipeline. Every number comes
from the same functions the command line uses; the app only chooses inputs,
caches results, and draws them.

- **Controls:** risk tolerance, position cap, shrunk vs raw estimates, which
  assets are allowed, a date window, the fat-tail model, simulation paths and
  seed.
- **Your own tickers and positions:** add tickers you are considering to the
  optimizer's universe, and set the share counts you actually hold when the
  database is behind your account. Prices for tickers the database lacks are
  fetched on request into a separate cache; the portfolio database is never
  written to.
- **Views:** current vs recommended, the efficient frontier, how the answer
  moves with risk tolerance, one-year simulations under normal and fat-tailed
  shocks, per-asset statistics, and exactly what data went in.
- **Live on the database, not a market feed:** it recomputes when the SQLite
  file changes, so after the daily ETL run the next interaction uses the new
  prices.
- **Reproducible:** at the default controls with 100,000 paths it shows the
  published numbers exactly, and its Data tab prints the code to reproduce any
  other configuration from the command line.
- **Private by default:** values are indexed to 100 and share counts hidden
  unless you switch to dollars. The only network call is the "Fetch prices"
  button, which sends ticker symbols and nothing else.

## Projects

| # | Project | Key result |
|---|---|---|
| 01 | [Distribution fitting](projects/01-distribution-fitting) | Fat-tailed fits beat Normal on all 9 tickers; even SPY has excess kurtosis ≈ 8 |
| 02 | [Blackjack probability engine](projects/02-blackjack-probability) | Exact vs 1M-trial simulation agree to ~0.001 across 12 quantities |
| 03 | [Monte Carlo option pricer](projects/03-monte-carlo-pricer) | Black-Scholes inside the 95% CI on all 12 cases; error slope −0.500 |
| 04 | [Options extensions + Bayes](projects/04-options-extensions) | Antithetic variates cut variance 1.66×; common random numbers cut Greek noise 74× |
| 05–06 | [Portfolio database + SQL analytics](projects/05-portfolio-database) | FIFO lot matching in pure SQL; found 44.0% hidden leveraged-ETF concentration |
| 07 | [ETL pipeline + SQL/NoSQL](projects/07-etl-pipeline) | Validated, transactional, idempotent; 6 of 7 queries identical across both stores |
| 08 | [Query optimization study](projects/08-query-optimization) | 10.0× speed-up on 2.96M rows — and one query where indexes bought only 1.4× |
| 09 | [Capital budgeting](projects/09-capital-budgeting) | Detects multiple IRRs (25% and 400%); break-even at −31.5% production |
| 10 | [Decision analysis](projects/10-decision-analysis) | EVPI $355,500 caps study value; real seismic survey worth $214,750 |
| 11–12 | [Capstone platform](projects/11-capstone-platform) | Shrinkage cuts covariance conditioning 23×; Sharpe 0.64 → 1.00; interactive research app |

Each project folder holds its code, tests, `results/`, and a weekly summary.

## Writeups and docs

Long-form writeups, one per phase:

- [Phase 1 — The distribution nobody checks](writeups/phase-1-probability.md)
- [Phase 2 — The database found bugs I could not see](writeups/phase-2-data-management.md)
- [Phase 3 — Expected value is the wrong rule](writeups/phase-3-decisions.md)
- [Phase 4 — The optimizer told me exactly what I wanted to hear](writeups/phase-4-capstone.md)

Reference:

- [User manual](docs/USER_MANUAL.docx) — written for a reader with no finance or programming background
- [Original 12-week plan](docs/PLAN.md)
- [Presenting this project](writeups/PRESENTING.md) — talking points and a pre-demo checklist

## Getting started

### Install

```bash
git clone https://github.com/theoneste2028/quant-summer-2026.git
cd quant-summer-2026
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Run on your own brokerage history

```bash
python projects/05-portfolio-database/build_db.py ~/Downloads/Accounts_History.csv
python projects/11-capstone-platform/capstone.py
```

### Run without one

Every project also runs on synthetic or public data:

```bash
python projects/05-portfolio-database/build_db.py --demo   # offline sample DB
python projects/08-query-optimization/load_taxi.py         # public NYC taxi data
```

### Explore interactively

```bash
streamlit run projects/11-capstone-platform/app.py         # opens in your browser
```

### Test

```bash
python run_all_tests.py                                    # all 740 checks, ~2 min
python run_all_tests.py --fast                             # skip the slow suites
```

## Repository layout

```
projects/          One folder per project: code, tests, results, weekly summary
writeups/          Long-form writeup per phase + presentation notes
site/              JSON export + self-contained results page
                   (the interactive app is projects/11-capstone-platform/app.py)
docs/              Original plan and user manual (with its build scripts)
data/              Databases and market data (gitignored — contains real trades)
run_all_tests.py   Runs every test suite and prints a summary
```

## Three things I got wrong

Each was found by a test, not by reading code:

1. **`INSERT OR IGNORE` is error suppression, not idempotency.** It silently
   dropped a negative-price row and committed the rest of the batch — the exact
   partial write the pipeline existed to prevent.
2. **An index changed which rows a report returned.** Two queries had ties with
   no tie-breaker, so the output depended on the access path.
3. **Markowitz on raw sample means is an error maximizer.** It put 100% of the
   recommendation into the four assets with the noisiest favourable estimates
   and projected a 124% annual return.

## A note on the data

The `data/` directory holds a real brokerage history and is gitignored. The
published results page indexes portfolio values to 100 rather than showing
dollar amounts — the method is fully demonstrable without them.

This is coursework, not investment advice.
