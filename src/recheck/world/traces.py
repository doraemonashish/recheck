"""A world whose changes are real: the latest stable release of ~170 Python packages on PyPI.

The value of slot `pkg.latest|numpy` at time t is the highest stable numpy version uploaded by t
(what `pip install numpy` would resolve). Change times are the real upload times, so release
cadence is as bursty and as uneven as it really is: botocore releases most weekdays, many
packages a few times a year.

What the memory is told is simulated around that real trace, in the same way as in the
simulator:

- seed observations: the agent looked some packages up shortly before the window starts;
- subagent reports: a subagent looked a package up, and the report arrives later; with
  `subagent_error` it reports an older version (it read an old changelog);
- release notifications for a share of releases (`notify_prob`, a watched release feed);
- pasted claims: a README, a forum answer or an old requirements file states a version from
  some time in the past (untrusted, and usually stale);
- queries, with popularity following a Zipf law over a seed-dependent order; some ask for a
  derived value (the resolved versions of a small project's dependencies).

Seed s shifts the window start by `seed_shift_days * s`, so seeds see different stretches of
real history as well as different event streams.
"""
from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..types import Event, Prov, Query
from .kinds import KIND_BY_NAME, slot_key
from .sim import Derived, Episode, Trajectory, World

DATA = Path(__file__).resolve().parents[3] / "data" / "pypi_releases.json.gz"

PYPI_DEFAULTS = {
    "source": "pypi",
    "start": "2021-01-01",
    "seed_shift_days": 91,
    "days": 365.0,
    "history_days": 400.0,
    "queries_per_day": 60.0,
    "zipf": 1.0,
    "derived_slots": 15,
    "derived_frac": 0.1,
    "seed_observe_frac": 0.5,
    "subagent_reports_per_day": 10.0,
    "subagent_delay": [0.0, 3.0],
    "subagent_error": 0.0,
    "quoted_claims_per_day": 3.0,
    "quoted_age_days": [30.0, 720.0],
    "notify_prob": 0.1,
    "min_releases": 1,
}


@lru_cache(maxsize=2)
def load_traces(path: str = str(DATA)) -> dict[str, list[tuple[float, str]]]:
    """package -> [(POSIX days, latest version)] at each change of the latest version."""
    with gzip.open(path, "rt") as f:
        payload = json.load(f)
    out = {}
    for name, tr in payload["latest"].items():
        out[name] = [(_days(t), v) for t, v in tr]
    return out


def _days(iso: str) -> float:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.timestamp() / 86400.0


def _trajectory(trace: list[tuple[float, str]], t0: float, lo: float,
                hi: float) -> Trajectory | None:
    """Trace in window days (t - t0), starting at `lo` with the version current then."""
    rel = [(t - t0, v) for t, v in trace]
    before = [v for t, v in rel if t <= lo]
    if not before:
        return None
    times, values = [lo], [before[-1]]
    for t, v in rel:
        if lo < t < hi:
            times.append(t)
            values.append(v)
    return Trajectory(times, values)


def generate_pypi(config: dict | None = None, seed: int = 0) -> Episode:
    cfg = {**PYPI_DEFAULTS, **(config or {})}
    rng = np.random.default_rng(seed)
    days = float(cfg["days"])
    t0 = _days(cfg["start"] + "T00:00:00") + seed * float(cfg["seed_shift_days"])
    kind = KIND_BY_NAME["pkg.latest"]

    traj: dict[str, Trajectory] = {}
    for name, trace in sorted(load_traces().items()):
        tr = _trajectory(trace, t0, -float(cfg["history_days"]), days + 1.0)
        if tr is not None and len(trace) >= cfg["min_releases"]:
            traj[slot_key(kind.name, name)] = tr
    base = sorted(traj)

    derived: dict[str, Derived] = {}
    for j in range(cfg["derived_slots"]):
        n_prem = int(rng.integers(2, 4))
        prem = tuple(sorted(rng.choice(base, size=n_prem, replace=False).tolist()))
        key = f"derived.lock|project-{j}"
        derived[key] = Derived(key, prem, 0)

    world = World({kind.name: kind}, traj, derived, {})
    items: list[Event | Query] = []

    for s in base:
        if rng.random() < cfg["seed_observe_frac"]:
            ts = -float(rng.uniform(0.0, 30.0))
            items.append(Event(ts, ts, s, world.value(s, ts), Prov.OBSERVED, "agent"))

    def poisson_times(rate: float) -> np.ndarray:
        n = rng.poisson(rate * days)
        return np.sort(rng.uniform(0.0, days, size=n))

    lo, hi = cfg["subagent_delay"]
    for tw in poisson_times(cfg["subagent_reports_per_day"]):
        s = base[rng.integers(len(base))]
        to = float(tw - rng.uniform(lo, hi))
        v = world.value(s, to)
        if cfg["subagent_error"] and rng.random() < cfg["subagent_error"]:
            v = world.value(s, to - float(rng.uniform(30.0, 365.0)))
        items.append(Event(float(tw), to, s, v, Prov.DELEGATED,
                           f"subagent-{int(rng.integers(1, 4))}"))

    for s in base:
        tr = traj[s]
        for tc, v in zip(tr.times[1:], tr.values[1:]):
            if 0.0 <= tc <= days and rng.random() < cfg["notify_prob"]:
                items.append(Event(float(tc + rng.uniform(0.0, 0.05)), float(tc), s, v,
                                   Prov.NOTIFIED, "release-feed"))

    qa, qb = cfg["quoted_age_days"]
    for t in poisson_times(cfg["quoted_claims_per_day"]):
        s = base[rng.integers(len(base))]
        v = world.value(s, float(t) - float(rng.uniform(qa, qb)))
        items.append(Event(float(t), float(t), s, v, Prov.QUOTED, "doc"))

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


def generate_any(config: dict | None = None, seed: int = 0) -> Episode:
    """The simulator, or a real-trace world when `config["source"] == "pypi"`."""
    if (config or {}).get("source") == "pypi":
        return generate_pypi(config, seed)
    from .sim import generate

    return generate(config, seed)
