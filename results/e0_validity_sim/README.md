# e0_validity_sim

200 streams of 4000 queries per setting, alpha = 0.05, delta = 0.1. Score s ~ U(0, 1), P(stale | s) = s, audit probability 0.1, so without guided audits the largest safe threshold is 0.333. A run counts as a false certificate if it ever certified a threshold whose risk is above alpha.

| Setting | False certificates | 95% upper bound | Final threshold (median) | Served unaudited | Alarms per run |
|---|---|---|---|---|---|
| ipw (no judge) | 1/200 = 0.005 | 0.023 | 0.224 | 0.171 | 0.14 |
| ppi, adversarial judge | 2/200 = 0.010 | 0.031 | 0.176 | 0.145 | 0.01 |
| ppi, guided audits, adversarial judge | 1/200 = 0.005 | 0.023 | 0.224 | 0.019 | 0.00 |
| ppi, guided audits, good judge | 0/200 = 0.000 | 0.015 | 0.747 | 0.349 | 0.00 |
| judge-only (invalid baseline), optimistic judge | 200/200 = 1.000 | 1.000 | 0.587 | 0.469 | 0.47 |

Run time 355 s.
