# Week 1 Summary — Distribution Fitting on Real Market Returns
**Course:** IEMS 302 · **Author:** Tteddy · **Holdings analyzed:** GOOGL, PLTR, VRT, STX, SPY, MU, IREN, NBIS, TQQQ (up to 5 years of daily log returns)

> All numbers below are real output from `distribution_fitting.py` on live yfinance data (run June 2026); the full table is auto-generated in `results/results_table.md`. Note NBIS (420 trading days) and IREN (1,154) have shorter listed histories than the ~1,254 days of the rest.

## Question
Black-Scholes, Markowitz, and simple VaR all assume daily returns are **normally distributed**. This project tests that assumption directly on real holdings by fitting three distributions — Normal, Student-t, and Laplace — to daily log returns and comparing them with formal goodness-of-fit measures.

## Method
1. Pulled 5 years of split/dividend-adjusted daily prices via `yfinance` and converted to log returns, `r_t = ln(P_t / P_{t-1})`.
2. Measured the first four moments, focusing on **excess kurtosis** (0 for a Normal; positive means fatter tails) and **skewness** (negative means crashes outweigh melt-ups).
3. Fit each distribution by maximum likelihood (`scipy.stats.<dist>.fit`).
4. Scored fits three ways: **KS statistic** (smaller = closer fit), **log-likelihood**, and **AIC** (lower = better, with a penalty for the t's extra parameter so it can't win on flexibility alone).
5. Visual checks: return histograms with all three PDFs overlaid, plus Normal-vs-t QQ-plots.

## Results (live run)

| Ticker | Daily σ | Skew | Excess kurt. | t df | KS (Normal) | KS (t) | Best fit (AIC) |
|:-------|:--------|-----:|-------------:|-----:|------------:|-------:|:---------------|
| GOOGL  | 1.98%   |  0.02 |         3.2 |  4.4 |      0.0515 | 0.0160 | Student-t |
| PLTR   | 4.08%   |  0.40 |         5.2 |  3.8 |      0.0637 | 0.0173 | Student-t |
| VRT    | 4.01%   | −1.51 |        20.4 |  4.3 |      0.0723 | 0.0193 | Student-t |
| STX    | 2.85%   |  0.13 |         4.9 |  3.9 |      0.0594 | 0.0124 | Student-t |
| SPY    | 1.08%   |  0.15 |         8.0 |  3.8 |      0.0720 | 0.0233 | Student-t |
| MU     | 3.42%   |  0.08 |         3.6 |  4.0 |      0.0625 | 0.0229 | Student-t |
| IREN   | 7.27%   |  0.39 |         3.7 |  7.3 |      0.0404 | 0.0239 | Student-t |
| NBIS   | 6.84%   | −0.17 |         7.3 |  6.0 |      0.0429 | 0.0258 | Student-t |
| TQQQ   | 4.25%   | −0.23 |         3.6 |  4.3 |      0.0694 | 0.0257 | Laplace |

![Excess kurtosis by ticker](results/excess_kurtosis.png)

The single clearest evidence is the QQ-plot: against a Normal, the points form an **S-curve** that peels away at both ends (real extreme days are more extreme than the bell curve allows); against a Student-t, the same points lie nearly straight.

![PLTR QQ-plots](results/PLTR_qq.png)

## What the numbers mean
- **Every ticker has positive excess kurtosis** (3.2 up to VRT's 20.4): fat tails are not an exception, they're the norm. Extreme daily moves happen far more often than a Normal predicts.
- **A fat-tailed distribution wins on AIC for every name** — Student-t for 8 of 9, Laplace for TQQQ — with a KS statistic 2–5× smaller than the Normal's, even after the t's extra-parameter penalty. The Normal never wins.
- **Low degrees of freedom (~3.8–4.4 for the long-history names)** confirm heavy tails (the t approaches the Normal only as df → ∞). IREN (7.3) and NBIS (6.0) show higher df, but their shorter histories give less data on rare extremes.
- **Even SPY — the diversified index — has heavy tails** (excess kurtosis 8.0, t df 3.8, a window that includes the 2022 bear market and 2025 drawdowns). Diversification slashes day-to-day volatility (σ 1.08% vs 2–7% for single names) but does not normalize the tail shape.
- **Skew is name-specific in this sample**: most tickers sit near zero or slightly positive, while VRT's −1.51 shows how a few violent down days can dominate the third moment.

## Caveat (honest limitation)
Because each distribution's parameters were estimated from the same data used to test it, the KS **p-values are not strictly valid** (the Lilliefors problem). This doesn't affect the conclusion: KS and AIC are used here to **rank** the three distributions against each other, and that ranking is robust.

## So what? (why this grounds the rest of the summer)
Any model built on the Normal assumption will **understate tail risk** for these holdings — Black-Scholes will misprice deep out-of-the-money options, Markowitz will treat standard deviation as if it captures all risk, and a Normal-based VaR will report a rosier worst case than reality (the exact failure that bit risk managers in 2008). Later projects still *use* the Normal where it buys tractability (Week 3's GBM pricer), but now with eyes open about where and why it lies — and Week 11's optimizer will carry this caveat explicitly.
