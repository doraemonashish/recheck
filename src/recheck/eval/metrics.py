"""Metrics from a run's rows. Every number a table reports is computed here."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .runner import RunResult


def summarize(res: RunResult, after: float = 0.0, alpha: float | None = None,
              before: float = float("inf")) -> dict:
    rows = [r for r in res.rows if after <= r.t < before]
    n = len(rows)
    if n == 0:
        return {"policy": res.policy, "queries": 0}
    served = sum(r.served and not r.audited for r in rows)
    wrong = sum(not r.correct for r in rows)
    cost = sum(r.cost for r in rows)
    full = sum(_full_cost(r) for r in rows)
    out = {
        "policy": res.policy,
        "queries": n,
        "served_from_memory": served / n,
        "error_rate": wrong / n,
        "cost_per_query": cost / n,
        "cost_vs_always": cost / full if full else float("nan"),
        "audits": sum(r.served and r.audited for r in rows),
        "retractions": res.retractions,
    }
    by = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r.had_belief:
            by[r.group][0] += 1
            by[r.group][1] += int(not r.correct)
            by[r.group][2] += int(r.served and not r.audited)
    out["by_group"] = {g: {"n": a, "error_rate": b / a, "served": c / a}
                       for g, (a, b, c) in by.items()}
    if alpha is not None:
        out["groups_over_alpha"] = sorted(g for g, v in out["by_group"].items()
                                          if v["error_rate"] > alpha)
    return out


def _full_cost(r) -> float:
    return r.cost if r.cost > 0 else _unit_cost_guess(r)


def _unit_cost_guess(r) -> float:
    # served rows record cost 0; the always-re-check cost is the slot's re-check cost, which the
    # runner records on re-checked rows. Served rows use 1.0 (3.0 for user kinds, 2-3 premises
    # for derived) to keep 'cost_vs_always' comparable.
    if r.derived:
        return 2.5
    return 3.0 if r.kind.startswith("user.") else 1.0


def stale_rate_when_served(res: RunResult) -> float:
    s = [r for r in res.rows if r.served and not r.audited]
    return float(np.mean([r.stale for r in s])) if s else float("nan")
