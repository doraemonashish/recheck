"""Run one read policy over one episode of the changing world.

The memory sees only events and its own re-checks; the evaluator knows the truth. For every
query the runner records whether the answer was served from memory, whether it was right, what
the re-checks cost, and the staleness the policy could not see.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..agents.judges import Judge
from ..memory.store import Memory
from ..policies import Ctx, Policy
from ..types import Event, Prov, Query
from ..world.kinds import kind_of
from ..world.sim import Episode


@dataclass
class RunConfig:
    sleep_every: float = 1.0        # days between sleeps (hazard refits)
    order: str = "obs"              # "obs" or "write" (subagent ordering baseline)
    trust_quoted: bool = False      # let pasted content override (baseline)
    launder: bool = False           # store inferences as plain facts (baseline)
    combine: str = "boole"          # premise bound for inferred beliefs: "boole" or "product"
    prior_strength: float = 2.0
    per_slot: bool = False          # per-slot change rates (hierarchical empirical Bayes)


@dataclass
class Row:
    t: float
    qid: int
    slot: str
    kind: str
    group: str
    derived: bool
    had_belief: bool
    served: bool
    audited: bool
    correct: bool
    cost: float
    score: float
    judge: float
    stale: int
    probe: str = ""          # what an LLM agent probe would have done ("answer"/"check")


@dataclass
class RunResult:
    policy: str
    rows: list[Row]
    state: dict
    retractions: int = 0
    meta: dict = field(default_factory=dict)


def _group(prov: Prov) -> str:
    return prov.value


def run(ep: Episode, policy: Policy, judge: Judge, cfg: RunConfig | None = None,
        seed: int = 0, probe=None, probe_every: int = 50) -> RunResult:
    cfg = cfg or RunConfig()
    world = ep.world
    mem = Memory(order=cfg.order, trust_quoted=cfg.trust_quoted, launder=cfg.launder,
                 prior_strength=cfg.prior_strength, per_slot=cfg.per_slot)
    rng = np.random.default_rng(seed + 7919)
    rows: list[Row] = []
    next_sleep = -1e9

    def recheck(slot: str, t: float) -> str:
        v = world.value(slot, t)
        mem.observe(slot, t, v)
        return v

    for item in ep.items:
        t = item.t_write if isinstance(item, Event) else item.t
        if t >= next_sleep:
            mem.sleep()
            next_sleep = (np.floor(t / cfg.sleep_every) + 1) * cfg.sleep_every
        if isinstance(item, Event):
            mem.add(item)
            continue
        q: Query = item
        if not q.derived:
            cost = world.obs_cost(q.slot)
            b = mem.belief(q.slot, q.t)
            if b is None:
                recheck(q.slot, q.t)
                rows.append(Row(q.t, q.qid, q.slot, kind_of(q.slot), "none", False, False, False,
                                False, True, cost, 1.0, float("nan"), -1))
                continue
        else:
            cost = sum(world.obs_cost(p) for p in q.premises)
            b = mem.belief(q.slot, q.t) if cfg.launder else mem.inference(q.slot, q.t)
            if b is None:
                for p in q.premises:
                    recheck(p, q.t)
                mem.infer(q.slot, q.t, world.value(q.slot, q.t), q.premises)
                rows.append(Row(q.t, q.qid, q.slot, kind_of(q.slot), "none", True, False, False,
                                False, True, cost, 1.0, float("nan"), -1))
                continue

        group = _group(b.prov)
        score = mem.p_stale(b, q.t, cfg.combine)
        stale = int(b.value != q.truth)
        jv = judge(b, q.t, world, stale, rng, {"group": group})
        c = Ctx(q.t, group, score, b.age(q.t), jv, cost, kind_of(q.slot))
        serve, audit, pi = policy.decide(c, rng)
        pr = ""
        if probe is not None and q.qid % probe_every == 0:
            pr = probe(b, q.slot, q.t, serve) or ""
        if serve and not audit:
            policy.feedback(c, False, pi, None, True)
            rows.append(Row(q.t, q.qid, q.slot, c.kind, group, q.derived, True, True, False,
                            stale == 0, 0.0, score, float("nan") if jv is None else jv, stale, pr))
            continue
        # re-check: observe (or re-derive) and learn whether the belief was stale
        if q.derived:
            for p in q.premises:
                recheck(p, q.t)
            mem.infer(q.slot, q.t, world.value(q.slot, q.t), q.premises)
        else:
            recheck(q.slot, q.t)
        policy.feedback(c, serve, pi, stale, serve)
        rows.append(Row(q.t, q.qid, q.slot, c.kind, group, q.derived, True, serve, True, True,
                        cost, score, float("nan") if jv is None else jv, stale, pr))

    return RunResult(policy.name, rows, policy.state(), mem.retractions,
                     {"hazards": dict(mem.hazards.rates), "pooled": mem.hazards.pooled})
