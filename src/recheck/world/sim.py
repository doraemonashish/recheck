"""A changing world and the stream an agent's memory sees.

Every slot (a kind of fact about one entity) follows a renewal process: its value stays put for
a Weibull-distributed time, then changes to a different value. Nothing tells the memory about
most changes. What the memory does get is a stream of events (its own observations, subagent
reports that arrive late, user statements, occasional notifications, untrusted pasted claims)
interleaved with queries whose right answer is the world's value at query time.

Derived slots are functions of two or three base slots (a deploy target computed from a branch
and a config value, say). Some derived functions are many-to-one, so a premise can change while
the derived value stays the same: the premise bound in THEORY.md is conservative there.

Everything is a deterministic function of the config and the seed.
"""
from __future__ import annotations

import bisect
import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

from ..types import Event, Prov, Query
from .kinds import KIND_BY_NAME, Kind, kind_of, kinds_for, slot_key


@dataclass
class Trajectory:
    times: list[float]   # change times, ascending; times[0] is the start
    values: list[str]

    def at(self, t: float) -> str:
        i = bisect.bisect_right(self.times, t) - 1
        return self.values[max(i, 0)]

    def changed_between(self, t0: float, t1: float) -> bool:
        lo, hi = sorted((t0, t1))
        return self.at(lo) != self.at(hi) or any(lo < c <= hi for c in self.times[1:])


@dataclass
class Derived:
    key: str
    premises: tuple[str, ...]
    buckets: int              # 0 = injective (any premise change changes it)

    def value(self, premise_values: list[str]) -> str:
        joined = "/".join(premise_values)
        if not self.buckets:
            return joined
        h = int(hashlib.sha256(f"{self.key}:{joined}".encode()).hexdigest(), 16)
        return f"bucket-{h % self.buckets}"


@dataclass
class World:
    kinds: dict[str, Kind]
    traj: dict[str, Trajectory]
    derived: dict[str, Derived]
    hazard_now: dict[str, list[tuple[float, float]]] = field(default_factory=dict)

    def value(self, slot: str, t: float) -> str:
        if slot in self.derived:
            d = self.derived[slot]
            return d.value([self.traj[p].at(t) for p in d.premises])
        return self.traj[slot].at(t)

    def observable(self, slot: str) -> bool:
        return self.kinds[kind_of(slot)].observable

    def obs_cost(self, slot: str) -> float:
        return self.kinds[kind_of(slot)].obs_cost

    def true_hazard(self, kind: str, t: float) -> float:
        """Changes per day for a kind at time t (drift included)."""
        h = self.kinds[kind].hazard
        for t0, factor in self.hazard_now.get(kind, []):
            if t >= t0:
                h = self.kinds[kind].hazard * factor
        return h

    def p_stale(self, slot: str, t_obs: float, t: float) -> float:
        """Probability a value observed at t_obs has changed by t, under a memoryless approximation
        of the true process. Used only by the simulated 'oracle' judges."""
        if slot in self.derived:
            surv = 1.0
            for p in self.derived[slot].premises:
                surv *= 1.0 - self.p_stale(p, t_obs, t)
            return 1.0 - surv
        k = kind_of(slot)
        return 1.0 - math.exp(-self.true_hazard(k, t) * max(0.0, t - t_obs))


@dataclass
class Episode:
    world: World
    items: list[Event | Query]          # time-ordered
    days: float
    config: dict

    @property
    def queries(self) -> list[Query]:
        return [x for x in self.items if isinstance(x, Query)]

    @property
    def events(self) -> list[Event]:
        return [x for x in self.items if isinstance(x, Event)]


DEFAULTS = {
    "days": 60.0,
    "entities_per_kind": 12,
    "domains": None,
    "hazard_scale": 1.0,
    "drift": None,                      # {"at_day": 30, "factor": 3.0, "kinds": [...]}
    "queries_per_day": 200.0,
    "zipf": 1.1,
    "derived_slots": 20,
    "derived_frac": 0.15,
    "seed_observe_frac": 0.6,
    "subagent_reports_per_day": 20.0,
    "subagent_delay": [0.0, 3.0],
    "subagent_error": 0.0,              # chance a subagent misreads the value it reports
    "user_error": 0.0,                  # chance a user statement is wrong
    "user_statements_per_day": 4.0,
    "quoted_claims_per_day": 3.0,
    "notifications": True,
}


def _other(rng: np.random.Generator, values: tuple[str, ...], v: str) -> str:
    choices = [x for x in values if x != v]
    return choices[rng.integers(len(choices))]


def _weibull_scale(mean: float, shape: float) -> float:
    return mean / math.gamma(1.0 + 1.0 / shape)


def _trajectory(rng: np.random.Generator, kind: Kind, start: float, end: float,
                hazard_scale: float, drift: dict | None) -> Trajectory:
    vals = kind.values
    v = vals[rng.integers(len(vals))]
    times, values = [start], [v]
    t = start
    while True:
        h = kind.hazard * hazard_scale
        if drift and kind.name in drift.get("kinds", []) and t >= drift["at_day"]:
            h *= drift["factor"]
        scale = _weibull_scale(1.0 / h, kind.shape)
        gap = scale * rng.weibull(kind.shape)
        if drift and kind.name in drift.get("kinds", []) and t < drift["at_day"] < t + gap:
            # memoryless restart at the drift point keeps the new hazard exact after it
            t = float(drift["at_day"])
            continue
        t += gap
        if t >= end:
            break
        choices = [x for x in vals if x != v]
        v = choices[rng.integers(len(choices))]
        times.append(t)
        values.append(v)
    return Trajectory(times, values)


def generate(config: dict | None = None, seed: int = 0) -> Episode:
    cfg = {**DEFAULTS, **(config or {})}
    rng = np.random.default_rng(seed)
    days = float(cfg["days"])
    kinds = kinds_for(cfg["domains"])
    drift = cfg["drift"]

    traj: dict[str, Trajectory] = {}
    for k in kinds:
        for i in range(1, cfg["entities_per_kind"] + 1):
            ent = k.entity_fmt.format(i=100 + i if "{i}" in k.entity_fmt else i)
            traj[slot_key(k.name, ent)] = _trajectory(rng, k, -60.0, days + 1.0,
                                                      cfg["hazard_scale"], drift)
    base = sorted(traj)
    observable = [s for s in base if KIND_BY_NAME[kind_of(s)].observable]

    derived: dict[str, Derived] = {}
    for j in range(cfg["derived_slots"]):
        n_prem = int(rng.integers(2, 4))
        prem = tuple(sorted(rng.choice(observable, size=n_prem, replace=False).tolist()))
        buckets = 0 if j % 2 == 0 else 3
        key = f"derived.plan|plan-{j}"
        derived[key] = Derived(key, prem, buckets)

    hz: dict[str, list[tuple[float, float]]] = {}
    if drift:
        for kn in drift.get("kinds", []):
            hz[kn] = [(float(drift["at_day"]), float(drift["factor"]))]
    world = World({k.name: k for k in kinds}, traj, derived, hz)
    items: list[Event | Query] = []

    # what the memory already knows at t = 0
    for s in base:
        k = KIND_BY_NAME[kind_of(s)]
        if rng.random() < cfg["seed_observe_frac"]:
            t0 = -float(rng.uniform(0.0, 10.0 if k.observable else 30.0))
            prov = Prov.OBSERVED if k.observable else Prov.STATED
            src = "agent" if k.observable else "user"
            items.append(Event(t0, t0, s, world.value(s, t0), prov, src))

    def poisson_times(rate: float) -> np.ndarray:
        n = rng.poisson(rate * days)
        return np.sort(rng.uniform(0.0, days, size=n))

    # subagents report what they observed, some time after they observed it
    lo, hi = cfg["subagent_delay"]
    for tw in poisson_times(cfg["subagent_reports_per_day"]):
        s = observable[rng.integers(len(observable))]
        to = float(tw - rng.uniform(lo, hi))
        v = world.value(s, to)
        if cfg["subagent_error"] and rng.random() < cfg["subagent_error"]:
            v = _other(rng, KIND_BY_NAME[kind_of(s)].values, v)
        src = f"subagent-{int(rng.integers(1, 4))}"
        items.append(Event(float(tw), to, s, v, Prov.DELEGATED, src))

    # the user mentions things about themselves and their colleagues
    talk = [s for s in base if KIND_BY_NAME[kind_of(s)].domain in ("user", "org")]
    if talk:
        for t in poisson_times(cfg["user_statements_per_day"]):
            s = talk[rng.integers(len(talk))]
            v = world.value(s, float(t))
            if cfg["user_error"] and rng.random() < cfg["user_error"]:
                v = _other(rng, KIND_BY_NAME[kind_of(s)].values, v)
            items.append(Event(float(t), float(t), s, v, Prov.STATED, "user"))

    # notifications for some changes (webhooks, calendar updates)
    if cfg["notifications"]:
        for s in base:
            k = KIND_BY_NAME[kind_of(s)]
            if not k.notify_prob:
                continue
            for tc, v in zip(traj[s].times[1:], traj[s].values[1:]):
                if 0.0 <= tc <= days and rng.random() < k.notify_prob:
                    tw = float(tc + rng.uniform(0.0, 0.05))
                    items.append(Event(tw, float(tc), s, v, Prov.NOTIFIED, "webhook"))

    # untrusted pasted claims, usually wrong
    for t in poisson_times(cfg["quoted_claims_per_day"]):
        s = base[rng.integers(len(base))]
        vals = KIND_BY_NAME[kind_of(s)].values
        v = vals[rng.integers(len(vals))]
        items.append(Event(float(t), float(t), s, v, Prov.QUOTED, "doc"))

    # queries: popular slots are asked often (Zipf), some ask for a derived value
    ranks = np.arange(1, len(base) + 1, dtype=float)
    pop = ranks ** (-cfg["zipf"])
    pop /= pop.sum()
    order = rng.permutation(len(base))
    dkeys = sorted(derived)
    for qi, t in enumerate(poisson_times(cfg["queries_per_day"])):
        t = float(t)
        if dkeys and rng.random() < cfg["derived_frac"]:
            key = dkeys[rng.integers(len(dkeys))]
            items.append(Query(t, key, world.value(key, t), True, derived[key].premises, qi))
        else:
            s = base[order[rng.choice(len(base), p=pop)]]
            items.append(Query(t, s, world.value(s, t), False, (), qi))

    items.sort(key=lambda x: (x.t_write if isinstance(x, Event) else x.t,
                              0 if isinstance(x, Event) else 1))
    return Episode(world, items, days, {**cfg, "seed": seed})
