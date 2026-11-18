"""Batch certificate: Learn-then-Test with exact binomial p-values and fixed-sequence testing.

Serve from memory when the estimated staleness score s(x) <= theta. Risk R(theta) = P(serve and
stale) grows with theta. On n calibration queries whose staleness was checked exactly, the count
of served-and-stale queries is Binomial(n, R(theta)), so

    p(theta) = P(Binomial(n, alpha) <= observed count)

is a valid p-value for H0: R(theta) >= alpha. Testing thresholds from the safest upward and
stopping at the first non-rejection controls the family-wise error, so the largest certified
threshold has R <= alpha with probability at least 1 - delta (THEORY.md, Theorem 2).
"""
from __future__ import annotations

import numpy as np
from scipy.stats import binom


def binom_pvalue(k: int, n: int, alpha: float) -> float:
    if n == 0:
        return 1.0
    return float(binom.cdf(k, n, alpha))


def ltt_threshold(scores: np.ndarray, stale: np.ndarray, grid: np.ndarray, alpha: float,
                  delta: float) -> float | None:
    """Largest theta in `grid` (ascending) certified by fixed-sequence testing, or None."""
    scores = np.asarray(scores, dtype=float)
    stale = np.asarray(stale, dtype=int)
    n = len(scores)
    best = None
    for th in np.sort(grid):
        k = int(((scores <= th) & (stale == 1)).sum())
        if binom_pvalue(k, n, alpha) <= delta:
            best = float(th)
        else:
            break
    return best


def default_grid(m: int = 40, lo: float = 1e-4, hi: float = 0.95) -> np.ndarray:
    """Staleness thresholds, dense near zero where the certified ones usually sit."""
    return np.unique(np.concatenate([[0.0], np.geomspace(lo, hi, m - 1)]))
