"""Laya (Convai Innovations, Apache 2.0) as a System One staleness judge.

Laya answers typed questions about a state in one forward pass with calibrated probabilities.
Here the state is the rendered belief and the question is a `noul` (yes/no) check: "Is the
stored value still correct now?". The judge returns J = 1 - P(yes).

    pip install laya          # Python 3.10+; downloads the checkpoint on first use
    # on a Kaggle or Colab T4: device="cuda"

The default is the general English checkpoint (the repo root of convaiinnovations/laya). The
`typed-decisions` subfolder is fine-tuned on four fixed workflows and is not meant for open
questions like this one; `multilingual` is the subfolder for non-English states. A noul answer
is a dict whose `noul` key is P(true) (laya 0.4.x); `_p_true` also accepts a few other shapes,
and `scripts/laya_smoke.py` prints a raw answer so you can confirm it on your install.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..types import Belief
from ..world.render import describe_belief
from .judges import Judge

QUESTION = {
    "current": {
        "type": "noul",
        "instructions": "Is the stored value still correct right now, given how long ago it was "
                        "recorded, who reported it and how often this kind of fact changes?",
        "criteria": {"true": "the stored value is still correct",
                     "false": "the value has probably changed since it was recorded"},
    }
}


def _p_true(ans) -> float | None:
    if isinstance(ans, (int, float)):
        return float(ans)
    if isinstance(ans, dict):
        for k in ("noul", "p_true", "probability", "prob", "value", "answer", "p"):
            v = ans.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
        for v in ans.values():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return float(v)
    return None


@dataclass
class LayaJudge(Judge):
    checkpoint: str = "convaiinnovations/laya"
    subfolder: str | None = None
    device: str | None = None
    max_calls: int = 20000       # beyond this the judge returns None (J = 0: still valid)
    name: str = "laya"
    calls: int = 0
    _agent: object = None
    _cache: dict = None

    def _load(self):
        import laya  # noqa: PLC0415

        kw = {}
        if self.subfolder:
            kw["subfolder"] = self.subfolder
        if self.device:
            kw["device"] = self.device
        self._agent = laya.load(self.checkpoint, **kw)

    def __call__(self, b: Belief, t, world, stale, rng, context=None):
        text = describe_belief(b, t)
        if self._cache is None:
            self._cache = {}
        if text in self._cache:
            return self._cache[text]
        if self.calls >= self.max_calls:
            return None
        if self._agent is None:
            self._load()
        res = self._agent.predict(text, QUESTION)
        self.calls += 1
        p = _p_true(res["answers"]["current"])
        out = None if p is None else min(1.0, max(0.0, 1.0 - p))
        self._cache[text] = out
        return out
