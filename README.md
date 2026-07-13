# Quant Summer 2026

A 12-week, end-to-end quantitative finance platform built to consolidate three Northwestern courses:

| Course | Topic | Projects |
|---|---|---|
| IEMS 302 | Probability | Distribution fitting, simulation, Monte Carlo option pricing, Bayesian updating |
| CS 217 | Data Management | Portfolio database, SQL analytics, ETL pipeline, query optimization |
| CivEnv 205 | Economics & Finance for Engineers | Capital budgeting, decision analysis, utility theory |

Everything converges in a **capstone quant research platform**: SQL data layer → statistical modeling → Markowitz optimization → utility-based decision layer → Monte Carlo risk analysis.

## Architecture

```
data layer (CS 217)          stats layer (IEMS 302)        decision layer (CivEnv 205)
SQLite + ETL pipeline  --->  return modeling, MC sim  ---> optimization + utility/CE
        |                                                          |
        +------------------> capstone platform <-------------------+
                          (efficient frontier, VaR,
                       recommended vs. actual allocation)
```

## Repository layout

```
src/quantlib/        Shared, importable library code (pricer, decision trees, db utils)
projects/            One folder per weekly project — notebooks, writeups, results
data/                Local data files and .db files (gitignored, never committed)
docs/                The 12-week plan and writeups
```

## Setup

```bash
git clone https://github.com/<you>/quant-summer-2026.git
cd quant-summer-2026
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .            # makes `import quantlib` work everywhere
```

## Projects

| # | Project | Status | Key result |
|---|---|---|---|
| 01 | Distribution fitting on real returns | 🔲 | — |
| 02 | Blackjack probability engine | 🔲 | — |
| 03 | Monte Carlo option pricer | 🔲 | — |
| 05 | Portfolio database + SQL analytics | 🔲 | — |
| 07 | ETL pipeline (SQL + MongoDB) | 🔲 | — |
| 08 | Query optimization study | 🔲 | — |
| 09 | Capital budgeting tool | 🔲 | — |
| 10 | Decision analysis engine | 🔲 | — |
| 11 | Capstone: quant research platform | 🔲 | — |

Update each row with ✅ and a one-line quantified result as you finish (e.g., "MC price within 0.1% of Black-Scholes at 1M paths").
