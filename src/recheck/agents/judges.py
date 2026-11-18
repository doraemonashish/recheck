"""Cheap auditors: they estimate P(stale) for a belief without a tool call.

Simulated judges make the noisy-auditor experiments controllable:

- `CalibratedJudge`: the true staleness probability under the world's real change rate, plus
  Gaussian noise. A good judge.
- `FlipJudge`: sees the real answer but flips it with class-dependent rates (eps on current
  beliefs, eps_stale on stale ones). A judge that misses staleness has eps_stale high.
- `BiasedJudge`: like FlipJudge, but much worse on one provenance class (for example subagent
  reports). Its average error looks fine; its error where it matters is not. Certification that
  trusts the judge fails there; rectified certification does not.

Real judges (an Ollama or OpenAI-compatible model, or Laya) live in `llm.py` and `laya_judge.py`
and take a rendered text description of the belief instead of the world.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..types import Belief
from ..world.sim import World


class Judge:
    name = "none"

    def __call__(self, b: Belief, t: float, world: World, stale: int,
                 rng: np.random.Generator, context: dict | None = None) -> float | None:
        return None


@dataclass
class CalibratedJudge(Judge):
    sigma: float = 0.1
    name: str = "calibrated"

    def __call__(self, b, t, world, stale, rng, context=None):
        q = world.p_stale(b.slot, b.t_obs, t)
        return float(np.clip(q + rng.normal(0.0, self.sigma), 0.0, 1.0))


@dataclass
class FlipJudge(Judge):
    eps: float = 0.05          # says stale when it is current
    eps_stale: float = 0.3     # says current when it is stale
    soft: float = 0.1          # reports 0.1/0.9 rather than 0/1
    name: str = "flip"

    def __call__(self, b, t, world, stale, rng, context=None):
        if stale:
            says = 0 if rng.random() < self.eps_stale else 1
        else:
            says = 1 if rng.random() < self.eps else 0
        return 1.0 - self.soft if says else self.soft


@dataclass
class BiasedJudge(Judge):
    bad_group: str = "delegated"
    eps: float = 0.05
    eps_stale: float = 0.1
    eps_stale_bad: float = 0.9
    soft: float = 0.1
    name: str = "biased"

    def __call__(self, b, t, world, stale, rng, context=None):
        group = (context or {}).get("group", "")
        miss = self.eps_stale_bad if group == self.bad_group else self.eps_stale
        if stale:
            says = 0 if rng.random() < miss else 1
        else:
            says = 1 if rng.random() < self.eps else 0
        return 1.0 - self.soft if says else self.soft


def make_judge(spec: dict | None) -> Judge:
    if not spec:
        return Judge()
    kind = spec.get("type", "none")
    args = {k: v for k, v in spec.items() if k != "type"}
    if kind == "none":
        return Judge()
    if kind == "calibrated":
        return CalibratedJudge(**args)
    if kind == "flip":
        return FlipJudge(**args)
    if kind == "biased":
        return BiasedJudge(**args)
    if kind == "llm":
        from .llm import LLMJudge

        return LLMJudge(**args)
    if kind == "laya":
        from .laya_judge import LayaJudge

        return LayaJudge(**args)
    raise ValueError(f"unknown judge type {kind}")
