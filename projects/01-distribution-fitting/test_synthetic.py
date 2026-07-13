"""Verify the analysis pipeline end-to-end on synthetic fat-tailed data.
This is NOT a deliverable — it just proves distribution_fitting.py is correct
without needing live Yahoo data. Each ticker gets Student-t returns with a
realistic degrees-of-freedom so the pipeline sees genuine fat tails."""
import numpy as np, pandas as pd
from scipy import stats
import distribution_fitting as df_

rng = np.random.default_rng(7)
# (annualised-ish daily sigma, true t df) per ticker — SPY thinnest tails.
spec = {"GOOGL": (0.018, 4.5), "PLTR": (0.045, 3.0), "VRT": (0.035, 3.5),
        "STX": (0.028, 3.8), "SPY": (0.011, 5.5)}
n = 1260  # ~5y of trading days
data = {}
for tk, (sig, dfree) in spec.items():
    # scale a standard t so its std ~ sig
    raw = stats.t.rvs(dfree, size=n, random_state=rng)
    raw = raw / np.sqrt(dfree/(dfree-2))      # normalise to unit variance
    data[tk] = raw * sig + 0.0004             # small positive drift
returns = pd.DataFrame(data)

table = df_.analyze(returns, outdir="results")
pd.set_option("display.width", 160)
print(table[["ticker","std","skewness","excess_kurtosis","t_df",
             "ks_normal","ks_t","best_fit"]].to_string(index=False))
