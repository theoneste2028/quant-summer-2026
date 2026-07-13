### Asian vs European call (K=180, T=1)

- Asian call: **13.0454** (95% CI [12.9582, 13.1327])
- European call: **23.2923**
- Asian < European: **True**

### Antithetic variance reduction (European call)

| Paths | SE plain | SE antithetic | Variance reduction |
|--:|--:|--:|--:|
| 2,000 | 0.80902 | 0.60241 | 1.80x |
| 10,000 | 0.36581 | 0.28434 | 1.66x |
| 50,000 | 0.16342 | 0.12747 | 1.64x |
| 200,000 | 0.08280 | 0.06424 | 1.66x |
| 1,000,000 | 0.03703 | 0.02871 | 1.66x |

Correctness: Black-Scholes 23.3761 inside antithetic 95% CI [23.3249, 23.4375] -> True

### Greeks: finite-difference MC vs Black-Scholes

| Greek | MC | Black-Scholes | abs diff |
|:--|--:|--:|--:|
| Delta | 0.6125 | 0.6114 | 0.0011 |
| Vega | 69.0533 | 68.9936 | 0.0597 |

### Bayesian P(up tomorrow)

- Source: live GOOGL data, 500 days
- Final posterior mean: **0.5259** (95% CI [0.4822, 0.5694])
- Credible interval narrowed from 0.532 (day 10) to 0.087
