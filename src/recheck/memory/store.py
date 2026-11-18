"""The agent's memory: an append-only event log, beliefs derived from it, and the sleep.

Design (THEORY.md section 2):

- Every event is kept, with its provenance class, observation time and write time.
- The belief for a slot is the trusted observation with the latest *observation* time. A
  subagent's late report of an old observation never overrides a newer one (`order="obs"`). The
  baseline `order="write"` is what a store that timestamps on insert does: it takes whatever
  arrived last and dates it by arrival, so a two-day-old report looks fresh.
- Quoted (pasted, untrusted) content is stored but never becomes a belief. The baseline
  `trust_quoted=True` is a provenance-blind store: pasted text is filed like something the user
  said.
- An inferred belief keeps its justification: the premise values it was derived from. It is
  retracted the moment any premise's current belief has a different value (justification-based
  truth maintenance). The `launder` baseline stores the derived value as a plain fact instead.
- The sleep refits per-kind change rates from consecutive observations (memory.hazards).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from ..types import TRUSTED, Belief, Event, Prov
from ..world.kinds import kind_of
from .hazards import HazardModel, fit_hazards, fit_slot_rates, pairs_from_observations


@dataclass
class Inference:
    key: str
    value: str
    t_made: float
    premises: tuple[str, ...]
    premise_values: tuple[str, ...]


@dataclass
class Memory:
    order: str = "obs"            # "obs" (observation time) or "write" (arrival time)
    trust_quoted: bool = False
    launder: bool = False         # store inferences as plain facts (baseline)
    prior_strength: float = 2.0
    per_slot: bool = False        # fit a change rate per slot, shrunk toward its kind's rate
    log: list[Event] = field(default_factory=list)
    _obs: dict[str, list[tuple[float, float, str, Prov]]] = field(default_factory=dict)
    _quoted: dict[str, tuple[float, str]] = field(default_factory=dict)
    _inf: dict[str, Inference] = field(default_factory=dict)
    hazards: HazardModel = field(default_factory=HazardModel)
    retractions: int = 0
    _slot_cache: dict = field(default_factory=dict)

    # ---- writing -------------------------------------------------------------------------
    def add(self, e: Event) -> None:
        self.log.append(e)
        if e.prov == Prov.QUOTED:
            if self.trust_quoted:   # provenance-blind baseline: pasted text reads as a statement
                self._insert(e.slot, e.t_obs, e.t_write, e.value, Prov.STATED)
            else:
                self._quoted[e.slot] = (e.t_write, e.value)
            return
        if e.prov == Prov.INFERRED:
            if self.launder:
                self._insert(e.slot, e.t_obs, e.t_write, e.value, Prov.OBSERVED)
            else:
                self._inf[e.slot] = Inference(e.slot, e.value, e.t_obs, e.premises,
                                              tuple(self._value_now(p) or "" for p in e.premises))
            return
        if e.prov in TRUSTED:
            self._insert(e.slot, e.t_obs, e.t_write, e.value, e.prov)

    def _insert(self, slot: str, t_obs: float, t_write: float, value: str, prov: Prov) -> None:
        seq = self._obs.setdefault(slot, [])
        key = (t_obs, t_write, value, prov)
        bisect.insort(seq, key)

    def observe(self, slot: str, t: float, value: str) -> None:
        """The agent's own tool observation (or the user's answer to a question)."""
        self.add(Event(t, t, slot, value, Prov.OBSERVED, "agent"))

    def infer(self, key: str, t: float, value: str, premises: tuple[str, ...]) -> None:
        self.add(Event(t, t, key, value, Prov.INFERRED, "agent", premises))

    # ---- reading -------------------------------------------------------------------------
    def _current(self, slot: str):
        seq = self._obs.get(slot)
        if not seq:
            return None
        if self.order == "obs":
            return seq[-1]
        return max(seq, key=lambda x: x[1])

    def _value_now(self, slot: str) -> str | None:
        cur = self._current(slot)
        return cur[2] if cur else None

    def belief(self, slot: str, t: float) -> Belief | None:
        cur = self._current(slot)
        if cur is None:
            return None
        t_obs, t_write, value, prov = cur
        if self.order == "write":
            t_obs = t_write
        return Belief(slot, value, t_obs, prov)

    def inference(self, key: str, t: float) -> Belief | None:
        """A still-justified inferred belief, or None (missing or retracted)."""
        inf = self._inf.get(key)
        if inf is None:
            return None
        now = tuple(self._value_now(p) or "" for p in inf.premises)
        if now != inf.premise_values:
            del self._inf[key]
            self.retractions += 1
            return None
        i = 0 if self.order == "obs" else 1
        obs = tuple(self._current(p)[i] for p in inf.premises)
        return Belief(key, inf.value, min(obs), Prov.INFERRED, inf.premises, obs)

    # ---- the sleep ---------------------------------------------------------------------
    def sleep(self) -> HazardModel:
        seqs = {s: [(t, v) for t, _, v, _ in seq] for s, seq in self._obs.items()}
        pairs = pairs_from_observations(seqs, kind_of)
        self.hazards = fit_hazards(pairs, self.prior_strength)
        if self.per_slot:
            slot_pairs = pairs_from_observations(seqs, lambda s: s)
            self.hazards.slot_rates = fit_slot_rates(slot_pairs, self.hazards.rates, kind_of,
                                                     self.hazards.pooled, self.prior_strength,
                                                     self._slot_cache)
        return self.hazards

    def p_stale(self, b: Belief, t: float, combine: str = "boole") -> float:
        """Estimated probability that belief b is stale at time t.

        For inferred beliefs: Boole/Frechet bound over premises (no independence needed) or the
        product under independence (THEORY.md, Theorem 5).
        """
        if b.prov == Prov.INFERRED:
            qs = [self.hazards.p_stale(kind_of(p), t - to, p)
                  for p, to in zip(b.premises, b.premise_obs)]
            if combine == "product":
                surv = 1.0
                for q in qs:
                    surv *= 1.0 - q
                return 1.0 - surv
            return min(1.0, sum(qs))
        if b.prov == Prov.QUOTED:
            return 1.0
        return self.hazards.p_stale(kind_of(b.slot), b.age(t), b.slot)
