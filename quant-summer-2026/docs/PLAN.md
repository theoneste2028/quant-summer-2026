# Summer 2026 Project Plan — 12 Weeks
**Goal:** Consolidate IEMS 302, CS 217, and CivEnv 205 through portfolio-ready projects, culminating in a unified quant research platform.

**Tooling baseline (set up before Week 1):** Python 3.11+, Jupyter, pandas, numpy, scipy, matplotlib, yfinance, CVXPY, SQLite (you have SQLite Studio from CS 217), MongoDB Community Edition, Git/GitHub repo per project.

---

## PHASE 1 — IEMS 302: Probability (Weeks 1–4)

### Week 1: Distribution Fitting on Real Market Returns
**Project:** Fit probability distributions to real stock returns and test the normality assumption.

**Problem it solves:** Nearly every intro finance model (Black-Scholes, basic Markowitz, simple VaR) assumes returns are normally distributed — but real returns have fat tails, meaning extreme crashes happen far more often than the normal distribution predicts. If you take the normality assumption at face value, you systematically underestimate the risk in your own portfolio. This project quantifies exactly how wrong that assumption is for the stocks you actually own, giving you an evidence-based foundation for every model you build afterward.

**Tasks:**
1. Pull 5 years of daily adjusted close prices for GOOGL, PLTR, VRT, STX, and SPY using yfinance.
2. Compute daily log returns: `r_t = ln(P_t / P_{t-1})`.
3. For each ticker, compute sample mean, variance, skewness, and kurtosis. Compare kurtosis against the normal benchmark of 3 — this is your first evidence of fat tails.
4. Fit three candidate distributions using `scipy.stats.fit` (or `.fit()` on each distribution object): Normal, Student's t, and Laplace.
5. Run goodness-of-fit tests: Kolmogorov–Smirnov (`scipy.stats.kstest`) and visual QQ-plots (`scipy.stats.probplot`) for each fit.
6. Plot histograms of returns overlaid with each fitted PDF (one figure per ticker).
7. Write a 1–2 page summary: which distribution fits best, what the t-distribution's degrees of freedom imply about tail risk, and why this matters for risk management.

**Deliverable:** Jupyter notebook + writeup pushed to GitHub.
**Concepts reinforced:** Continuous distributions, PDF mechanics, parameter estimation, normal distribution and its limits.

---

### Week 2: Combinatorics & Simulation — Blackjack Probability Engine
**Project:** Compute exact card-game probabilities analytically, then verify by simulation.

**Problem it solves:** Human probability intuition is notoriously unreliable — even simple conditional probabilities trip people up. In quant work, you constantly face a choice: derive a probability exactly (fast, but only possible for tractable problems) or simulate it (always possible, but approximate). This project builds trust in both tools by forcing them to agree on the same problem, and teaches you how many simulation trials you need before an estimate is trustworthy — a question that matters every time you run a Monte Carlo model.

**Tasks:**
1. Analytically derive (by hand, then in code with `math.comb`):
   - P(blackjack on first two cards) from a single 52-card deck.
   - P(dealer busts | dealer upcard = k) for k = 2..Ace, using conditional probability over the dealer's draw sequence (simplify: dealer stands on 17).
   - P(player is dealt a pair).
2. Build a Monte Carlo simulator: shuffle a deck, deal hands, run ≥1,000,000 trials, estimate the same probabilities empirically.
3. Compare analytical vs. simulated values in a table; show convergence by plotting estimate vs. number of trials (this demonstrates the Law of Large Numbers).
4. Bonus: compute expected value of standing vs. hitting at a given hand total — a first taste of decision-making under uncertainty (foreshadows CivEnv work).

**Deliverable:** Notebook with derivations (LaTeX cells), simulator code, convergence plots.
**Concepts reinforced:** Combinatorics, conditional probability, Law of Total Probability, LLN.

---

### Week 3: Monte Carlo Option Pricer — Core Engine
**Project:** Price European options via simulation of Geometric Brownian Motion (GBM).

**Problem it solves:** Most derivatives in the real world have no closed-form pricing formula — Black-Scholes only covers the simplest cases. Monte Carlo simulation is the industry's workhorse for pricing everything else, which is why it shows up in nearly every quant interview. The catch: how do you know your simulator is correct? This project answers that by building the engine and validating it against the one case (European options) where an exact answer exists. Once validated, the same engine can price things with no formula at all (Week 4).

**Tasks:**
1. Implement GBM path simulation: `S_T = S_0 * exp((r - σ²/2)T + σ√T · Z)` where `Z ~ N(0,1)`. Vectorize with numpy (simulate 100k+ paths in one array operation, no loops).
2. Price a European call: discounted mean of `max(S_T - K, 0)`. Same for a put.
3. Implement Black-Scholes closed-form pricing (use `scipy.stats.norm.cdf`) as your ground truth.
4. Validate: for several strikes/maturities on a ticker you own (e.g., GOOGL), confirm Monte Carlo price → Black-Scholes price as path count grows. Plot error vs. number of paths and confirm the O(1/√n) convergence rate.
5. Compute standard errors and 95% confidence intervals for your MC estimates.
6. Estimate σ two ways: historical volatility from Week 1's returns data, and note the difference vs. implied volatility (pull a real option chain via `yfinance.Ticker(...).option_chain()` and compare your model price to market prices).

**Deliverable:** A clean Python module (`pricer.py`) + demo notebook.
**Concepts reinforced:** Functions of random variables, normal distribution, expectation, CLT/confidence intervals.

---

### Week 4: Option Pricer Extensions + Bayesian Mini-Project
**Problem it solves (pricer extensions):** Week 3's terminal-value shortcut breaks for path-dependent options like Asians, whose payoff depends on the whole price trajectory — these have no Black-Scholes formula, so simulation is the *only* way to price them. Separately, naive Monte Carlo is expensive: halving your error requires 4× the paths. Variance reduction techniques get you better answers for the same compute, which is what makes simulation practical at scale.

**Problem it solves (Bayesian updater):** A single point estimate ("this stock goes up 53% of days") hides how confident you should be in it — 53% from 10 days of data means almost nothing; from 5 years, quite a lot. Bayesian updating gives you a principled, mathematically consistent way to revise beliefs as each new data point arrives, which is the foundation of online learning and adaptive trading models.

**Tasks (Option pricer extensions, Mon–Wed):**
1. Add path-dependent options: Asian option (average price over the path — now simulate full paths with multiple time steps, not just terminal value).
2. Add a variance-reduction technique: antithetic variates. Show empirically that it cuts standard error for the same number of paths.
3. Add Greeks via finite differences: Delta and Vega.

**Tasks (Bayesian updater, Thu–Sun):**
1. Build a simple Bayesian model: estimate P(stock closes up tomorrow) with a Beta prior, updating daily with Bernoulli observations from real data (Beta-Binomial conjugacy).
2. Plot the posterior evolving over 6 months of data for one ticker.
3. Write up the intuition: prior → likelihood → posterior, and connect it to Bayes' Rule from class.

**Deliverable:** Updated pricer module + Bayesian notebook.
**Milestone check:** You now have two polished IEMS 302 repos. Write README files for both with plots embedded.

---

## PHASE 2 — CS 217: Data Management (Weeks 5–8)

### Week 5: Portfolio Database — Schema Design & Build
**Project:** A properly normalized relational database for your real portfolio.

**Problem it solves:** Right now your portfolio data lives in brokerage exports, spreadsheets, and ad-hoc yfinance calls — scattered, duplicated, and impossible to query reliably. Spreadsheets silently allow inconsistencies (a trade for a ticker that doesn't exist, a negative quantity, the same dividend entered twice). A normalized database with constraints makes bad data structurally impossible to insert and gives you one queryable source of truth that every later project builds on.

**Tasks:**
1. Design an ER diagram in Lucidchart (like Class 11/12) with at least these entities: `securities` (ticker, name, sector, asset_type), `trades` (trade_id, ticker, date, side, quantity, price, fees), `prices` (ticker, date, open, high, low, close, volume), `dividends` (ticker, ex_date, amount).
2. Normalize to 3NF — document your reasoning for each table (what functional dependencies exist, why no partial/transitive dependencies remain).
3. Create the schema in SQLite with proper PRIMARY KEYs, FOREIGN KEYs, NOT NULL and CHECK constraints (e.g., `quantity > 0`, `side IN ('BUY','SELL')`).
4. Load your actual trade history (export from your brokerage as CSV, import via Python `sqlite3`).
5. Backfill the `prices` table with 2+ years of daily data via yfinance.

**Deliverable:** Schema SQL file, ER diagram image, populated `.db` file, loader script.
**Concepts reinforced:** Relational design, normalization, constraints, data types.

---

### Week 6: Portfolio Database — Analytical Queries
**Problem it solves:** Brokerage apps answer only the questions they choose to answer — they typically won't show you FIFO-matched realized P&L per lot, sector drift over time, or dividend income by quarter the way you want it. Owning the data means you can ask any question, but only if you can express it in SQL. This week turns your database from storage into an analytics engine, and the FIFO matching problem in particular teaches you why some questions are genuinely hard to answer in pure SQL.

**Tasks:**
1. Write and document these queries (single- and multi-table, joins, aggregation, subqueries, window functions):
   - Current position per ticker (net quantity from buys minus sells).
   - Cost basis and unrealized P&L per position (join trades with latest price).
   - Realized P&L per closed trade (FIFO matching — this one is hard; use a window function or do FIFO logic in Python and store results).
   - Portfolio value over time (daily, joining positions against the prices table).
   - Sector exposure as % of portfolio (GROUP BY with computed weights).
   - Best/worst day per holding (window functions: `RANK() OVER (PARTITION BY ticker ORDER BY return)`).
   - Dividend income by quarter.
2. Wrap key transactional operations (inserting a trade + updating derived tables) in explicit SQL transactions with BEGIN/COMMIT/ROLLBACK. Write a short note on which ACID property each part relies on.
3. Build a small Python CLI or notebook dashboard that runs these queries and prints/plots results.

**Deliverable:** `queries.sql` with comments, transaction demo script, dashboard notebook.
**Concepts reinforced:** Multi-table queries, outer joins, advanced SQL, transactions, ACID.

---

### Week 7: ETL Pipeline + SQL vs. NoSQL Comparison
**Project:** Automated data pipeline feeding both SQLite and MongoDB.

**Problem it solves:** Manually refreshing data doesn't scale and fails silently — you forget a day, a bad row sneaks in, and weeks later your analysis is quietly wrong. Real data systems solve this with automated pipelines that validate before inserting, roll back on failure, log everything, and can be safely re-run (idempotency). The MongoDB half addresses a second problem: not all data fits neatly into tables — news articles and earnings reports have variable structure, and forcing them into rigid SQL schemas is painful. Knowing *when* to use each model is the actual skill employers test.

**Tasks:**
1. Write `etl.py`: pulls yesterday's OHLCV for all portfolio tickers, validates the rows (no nulls, prices > 0, date not already present), and inserts into SQLite inside a single transaction (rollback on any failure).
2. Add idempotency: running the script twice for the same day must not create duplicates (use `INSERT OR IGNORE` or check first).
3. Add logging to a file (Python `logging` module): rows inserted, errors, runtime.
4. MongoDB side: store unstructured data that fits documents poorly in SQL — fetch company news headlines or earnings data and insert as JSON documents into a `news` collection with pymongo.
5. Write 5 equivalent lookups both ways (e.g., "latest 10 items for ticker X") — once in SQL, once with MongoDB `find()`/aggregation.
6. Write a 1-page comparison: schema-on-write vs. schema-on-read, when you'd choose each, how transactions differ.
7. Schedule the ETL with `cron` (Mac) so it runs daily.

**Deliverable:** ETL script with logging, Mongo loader, comparison writeup.
**Concepts reinforced:** Transactions in practice, Python+SQL integration, MongoDB/pymongo.

---

### Week 8: Query Optimization Study
**Project:** Benchmark indexing on a large dataset.

**Problem it solves:** Queries that feel instant on 1,000 rows can take minutes on 3 million — and in finance, data is always millions of rows. The difference between a usable and unusable system is usually indexing, yet indexes aren't free (they slow writes and can even fail to help). This project replaces "add an index and hope" with measured evidence: you'll see exactly when an index gives a 100× speedup, when it does nothing, and why — which is the difference between writing SQL and engineering a database.

**Tasks:**
1. Download a large public dataset (NYC Yellow Taxi trips, one month ≈ 3M rows, available as Parquet) and load it into SQLite.
2. Write 5 realistic queries: point lookup, range scan on date, aggregation by group, a join against a small zones lookup table, and a filtered sort.
3. Time each query with Python (`time.perf_counter`, average of 5 runs) with NO indexes.
4. Inspect query plans with `EXPLAIN QUERY PLAN` — screenshot/record what scan types appear.
5. Add appropriate indexes (single-column and one composite). Re-run timings and query plans.
6. Produce a results table and bar chart: query × (before ms, after ms, speedup). Identify one query where the index did NOT help and explain why (e.g., low selectivity, full aggregation).
7. Write up: how B-tree indexes work conceptually, why composite index column order matters, the write-cost tradeoff of indexes.

**Deliverable:** Benchmark notebook + writeup with charts.
**Milestone check:** Three CS 217 repos done. Update your portfolio site to link them.

---

## PHASE 3 — CivEnv 205: Economics & Finance (Weeks 9–10)

### Week 9: Capital Budgeting & Sensitivity Tool
**Project:** A reusable NPV/IRR analyzer with sensitivity analysis.

**Problem it solves:** Every capital decision — a company buying equipment, you choosing a 401(k) vs. Roth, a bank evaluating a loan — boils down to comparing cash flows that arrive at different times, and a dollar today is not worth a dollar in 2030. NPV/IRR solve that, but a single NPV number is dangerously overconfident: it hides the fact that the answer hinges on assumptions (discount rate, growth) you guessed. Sensitivity analysis solves the second problem by revealing *which* assumption your decision actually depends on, so you know where to focus your research before committing money.

**Tasks:**
1. Build a Python module (or Excel workbook — Python preferred for the capstone) that takes a cash-flow series and discount rate and computes: NPV, IRR (`numpy_financial.irr`), discounted payback period, and profitability index.
2. Handle the edge cases you saw in class: non-conventional cash flows (multiple IRRs — detect sign changes and warn), and mutually exclusive project comparison via incremental analysis.
3. Sensitivity analysis: vary each input (discount rate, revenue growth, initial cost) ±30% one at a time; build a tornado chart showing which input NPV is most sensitive to.
4. Scenario analysis: best/base/worst cases with assigned probabilities → expected NPV and standard deviation of NPV.
5. Test it on a real case: redo your Harborview-style analysis (or model a rental property / solar panel installation decision) and confirm results match a hand calculation.

**Deliverable:** `capital_budgeting.py` module + worked case study notebook with tornado chart.
**Concepts reinforced:** Cash-flow evaluation, project selection, sensitivity analysis.

---

### Week 10: Decision Trees, Value of Information & Utility
**Project:** Decision analysis engine.

**Problem it solves:** Maximizing expected value (EMV) is the textbook rule, but it's wrong for most real people: you would not bet your tuition on a coin flip with slightly positive expected value, because losses hurt more than equivalent gains help. Utility theory fixes this by formally encoding risk aversion — it explains why insurance exists (people rationally pay more than the fair premium) and why two investors should hold different portfolios. The value-of-information piece solves a second everyday problem: information (a test, a survey, a consultant) costs money, and EVPI/EVSI tell you the maximum it's rationally worth paying *before* you buy it.

**Tasks:**
1. Implement a decision tree data structure in Python: decision nodes, chance nodes (with probabilities), terminal payoffs. Solve by backward induction (rollback) to get the EMV-optimal strategy.
2. Compute EVPI (Expected Value of Perfect Information): solve the tree with and without perfect information, take the difference.
3. Compute EVSI for an imperfect signal: define a test with given accuracy, use Bayes' Rule to get posterior probabilities (this directly reuses IEMS 302), re-solve the tree.
4. Add utility: replace payoffs with an exponential utility function `U(x) = 1 - e^(-x/R)`; show how the optimal decision changes as risk tolerance R decreases. Compute certainty equivalents.
5. Price a simple insurance contract: given a loss distribution and a utility function, find the maximum premium a risk-averse agent would pay (where expected utility with insurance = without). Compare to the actuarially fair premium.
6. Model one real decision of your own (e.g., accept an early internship offer vs. wait for other interviews) as a worked example.

**Deliverable:** Decision tree module + worked examples notebook.
**Concepts reinforced:** Decision analysis, value of information, utility theory, insurance pricing.

---

## PHASE 4 — Capstone: Quant Research Platform (Weeks 11–12)

### Week 11: Integration — Utility-Based Portfolio Optimizer
**Project:** Tie all three courses together in one pipeline.

**Problem it solves:** Most retail investors (including, probably, your current allocation) pick weights by gut feel — a bit of this, a bit of that — with no idea what risk-return tradeoff they've actually accepted or whether a different mix dominates theirs on both dimensions. This capstone answers three concrete questions about your real money: (1) what's the best achievable return for the risk I'm taking, (2) which allocation matches *my* risk tolerance rather than a generic one, and (3) what's the honest probability I lose more than 10% next year? It also solves the recruiter problem: isolated class projects are forgettable, but an end-to-end system — data engineering → statistical modeling → optimization → decision — is a portfolio piece that demonstrates you can build, not just study.

**Tasks:**
1. **Data layer (CS 217):** Pull returns for your holdings + candidate ETFs (SCHD, XLK, etc.) from your SQLite database via the ETL pipeline — not fresh yfinance calls. The DB is now your single source of truth.
2. **Statistics layer (IEMS 302):** Estimate the mean vector and covariance matrix of returns. Run your Week 1 distribution fits to justify (or caveat) any normality assumption in writing.
3. **Optimization layer (CivEnv 205 + your CVXPY experience):** Solve the Markowitz problem `max μᵀw - (γ/2)wᵀΣw` subject to `Σw = 1, w ≥ 0` for a range of risk-aversion values γ. Trace the efficient frontier.
4. **Decision layer:** Use Week 10's certainty-equivalent machinery to pick a single recommended portfolio for a given risk tolerance, rather than just showing the frontier.
5. **Monte Carlo layer (Week 3 reuse):** Simulate 1-year forward paths of the recommended portfolio; report P(loss > 10%), 5% VaR, and expected value with confidence intervals.
6. Compare the recommended portfolio against your actual current allocation: expected return, risk, and certainty equivalent.

**Deliverable:** One integrated repo with a clear `README` architecture diagram showing the four layers.

---

### Week 12: Deploy, Document, Present
**Problem it solves:** Work that nobody can see might as well not exist — recruiters spend seconds on a profile, and a repo with no README, no charts, and no story gets skipped no matter how good the code is. This week converts ten weeks of technical work into evidence: live demos, readable writeups, and quantified resume bullets. Communicating results is the half of the job that most students skip, which is exactly why doing it stands out.

**Tasks:**
1. Add the capstone results to your Next.js/Vercel portfolio site: a page with the efficient frontier chart, Monte Carlo fan chart, and recommended vs. actual allocation. Precompute results in Python, export JSON, render with a React chart library — fits your existing static-site architecture.
2. Write a project page / blog-style writeup (800–1200 words) per phase: problem, method, key chart, what you learned. Recruiters read these.
3. Clean every repo: README with motivation + setup + results screenshots, `requirements.txt`, consistent structure.
4. Record a 3–5 min Loom walkthrough of the capstone for your linktree/LinkedIn.
5. Update LinkedIn + resume bullets (quantify: "Built Monte Carlo pricing engine validating against Black-Scholes within 0.1% using 1M simulated paths," etc.).

**Deliverable:** Live site update, writeups, polished GitHub profile.

---

## Weekly Rhythm (suggested)
- **Mon–Thu:** ~2 hrs/day build time.
- **Fri:** Polish, document, commit, write the weekly summary.
- **Weekend:** Buffer/catch-up only — plan assumes ~10–12 hrs/week.

## Flex Rules
- If a week runs over, cut the "bonus" items first, never the deliverable.
- Weeks 2 and 8 are the most droppable if you need slack; Weeks 3, 5–6, 9–11 are the spine of the capstone.
