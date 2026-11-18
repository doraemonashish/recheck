"""How fast each kind of fact changes, learned from the memory's own re-observations.

Every time a slot is observed again, the pair (time since the last observation, changed or not)
is an interval-censored datum about a change time: "unchanged after d days" says the value
survived d days, "changed within d days" says it did not. Under a constant hazard h per kind the
log-likelihood is

    l(h) = sum_unchanged (-h d_i) + sum_changed log(1 - exp(-h d_i)),

which is concave in h (THEORY.md, Proposition 6). A Gamma(a, b) prior centred on the pooled rate
shrinks kinds with little data toward the population: empirical Bayes across kinds, so a kind
seen twice does not get an extreme rate.

A value that changes and changes back between two observations looks unchanged, so the rate is
biased low when changes revert; the world simulator rarely reverts (never to the value it just
left), and the certificate does not rely on the rate being right, only on the ranking it gives.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np


def _negll_grad_hess(h: float, d: np.ndarray, c: np.ndarray, a: float, b: float):
    """Negative log-posterior, its gradient and Hessian in h > 0."""
    hd = h * d
    e = np.exp(-np.clip(hd, 1e-12, 700))
    one_m = np.clip(1.0 - e, 1e-300, None)
    ll = -(hd[c == 0]).sum() + np.log(one_m[c == 1]).sum()
    g = -(d[c == 0]).sum() + ((d * e / one_m)[c == 1]).sum()
    hs = -((d * d * e / one_m**2)[c == 1]).sum()
    if a > 1.0:
        ll += (a - 1.0) * math.log(h) - b * h
        g += (a - 1.0) / h - b
        hs += -(a - 1.0) / h**2
    else:
        ll -= b * h
        g -= b
    return -ll, -g, -hs


def fit_rate(d: np.ndarray, c: np.ndarray, a: float = 1.0, b: float = 0.0,
             h0: float = 0.1, iters: int = 60) -> float:
    """MAP rate for interval-censored exponential data (Newton on log h, safeguarded)."""
    d = np.asarray(d, dtype=float)
    c = np.asarray(c, dtype=int)
    if len(d) == 0:
        return h0
    if c.sum() == 0 and a <= 1.0:
        return 1e-6 if b == 0 else 1e-6
    x = math.log(max(h0, 1e-6))
    for _ in range(iters):
        h = math.exp(x)
        f, g, hs = _negll_grad_hess(h, d, c, a, b)
        # derivatives in x = log h
        gx = g * h
        hx = hs * h * h + g * h
        step = -gx / hx if hx > 1e-12 else -0.5 * math.copysign(1.0, gx)
        step = max(-2.0, min(2.0, step))
        x_new = x + step
        f_new = _negll_grad_hess(math.exp(x_new), d, c, a, b)[0]
        while f_new > f + 1e-12 and abs(step) > 1e-8:
            step *= 0.5
            x_new = x + step
            f_new = _negll_grad_hess(math.exp(x_new), d, c, a, b)[0]
        x = x_new
        if abs(step) < 1e-9:
            break
    return float(min(max(math.exp(x), 1e-6), 1e3))


@dataclass
class HazardModel:
    """Per-kind change rates with a pooled fallback, and optionally per-slot rates shrunk toward
    their kind's rate (a three-level empirical-Bayes hierarchy: pool, kind, slot)."""

    rates: dict[str, float] = field(default_factory=dict)
    pooled: float = 0.1
    counts: dict[str, tuple[int, int]] = field(default_factory=dict)  # kind -> (pairs, changes)
    slot_rates: dict[str, float] = field(default_factory=dict)

    def rate(self, kind: str, slot: str | None = None) -> float:
        if slot is not None and slot in self.slot_rates:
            return self.slot_rates[slot]
        return self.rates.get(kind, self.pooled)

    def p_stale(self, kind: str, age: float, slot: str | None = None) -> float:
        return 1.0 - math.exp(-self.rate(kind, slot) * max(age, 0.0))


def fit_hazards(pairs: dict[str, list[tuple[float, int]]], prior_strength: float = 2.0,
                default: float = 0.1) -> HazardModel:
    """Fit every kind with empirical-Bayes shrinkage toward the pooled rate.

    `pairs[kind]` is a list of (days between consecutive observations, changed 0/1).
    `prior_strength` is the Gamma shape a; the prior mode is the pooled rate.
    """
    all_d = np.array([d for v in pairs.values() for d, _ in v], dtype=float)
    all_c = np.array([c for v in pairs.values() for _, c in v], dtype=int)
    if len(all_d) == 0:
        return HazardModel({}, default, {})
    pooled = fit_rate(all_d, all_c, h0=default)
    a = max(prior_strength, 1.0)
    b = (a - 1.0) / pooled if a > 1.0 else 0.0
    rates, counts = {}, {}
    for kind, v in pairs.items():
        d = np.array([x for x, _ in v], dtype=float)
        c = np.array([y for _, y in v], dtype=int)
        rates[kind] = fit_rate(d, c, a=a, b=b, h0=pooled)
        counts[kind] = (len(v), int(c.sum()))
    return HazardModel(rates, pooled, counts)


def pairs_from_observations(obs: dict[str, list[tuple[float, str]]], kind_of) -> dict:
    """Consecutive trusted observations of each slot, in observation-time order."""
    out: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for slot, seq in obs.items():
        seq = sorted(seq)
        for (t0, v0), (t1, v1) in zip(seq, seq[1:]):
            d = t1 - t0
            if d > 1e-6:
                out[kind_of(slot)].append((d, int(v0 != v1)))
    return dict(out)


def fit_slot_rates(slot_pairs: dict[str, list[tuple[float, int]]], kind_rates: dict[str, float],
                   kind_of, pooled: float, prior_strength: float = 2.0,
                   cache: dict | None = None) -> dict[str, float]:
    """Per-slot MAP rates with a Gamma prior whose mode is the slot's kind rate.

    `cache` maps slot -> (number of pairs, kind rate, fitted rate) and skips refits when neither
    the slot's data nor its kind's rate has moved (by more than 5%)."""
    a = max(prior_strength, 1.0)
    out = {}
    for slot, v in slot_pairs.items():
        kr = kind_rates.get(kind_of(slot), pooled)
        if cache is not None and slot in cache:
            n0, kr0, r0 = cache[slot]
            if n0 == len(v) and abs(kr - kr0) <= 0.05 * kr0:
                out[slot] = r0
                continue
        b = (a - 1.0) / kr if a > 1.0 else 0.0
        d = np.array([x for x, _ in v], dtype=float)
        c = np.array([y for _, y in v], dtype=int)
        out[slot] = fit_rate(d, c, a=a, b=b, h0=kr)
        if cache is not None:
            cache[slot] = (len(v), kr, out[slot])
    return out
