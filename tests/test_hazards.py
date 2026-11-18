import numpy as np

from recheck.memory.hazards import fit_hazards, fit_rate


def _pairs(h, n, rng):
    d = rng.exponential(1.0, n)
    changed = (rng.random(n) < 1 - np.exp(-h * d)).astype(int)
    return d, changed


def test_fit_rate_recovers_the_hazard():
    rng = np.random.default_rng(0)
    for h in (0.05, 0.3, 1.5):
        d, c = _pairs(h, 4000, rng)
        est = fit_rate(d, c)
        assert abs(est - h) / h < 0.15, (h, est)


def test_prior_shrinks_sparse_kinds_toward_the_pool():
    rng = np.random.default_rng(1)
    pairs = {}
    d, c = _pairs(0.3, 3000, rng)
    pairs["common"] = list(zip(d, c))
    pairs["rare"] = [(1.0, 1), (1.0, 1)]          # two changes: the raw MLE is very large
    hm = fit_hazards(pairs, prior_strength=2.0)
    raw = fit_rate(np.array([1.0, 1.0]), np.array([1, 1]), a=1.0, b=0.0)
    assert hm.rates["rare"] < raw
    assert 0.2 < hm.rates["common"] < 0.4
    assert 0.0 <= hm.p_stale("common", 1.0) <= 1.0
