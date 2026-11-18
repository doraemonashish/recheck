"""Read policies: when to serve a remembered value and when to re-check it.

Every policy sees the same context for a query (the belief, its estimated staleness from the
sleep's hazard model, an optional judge score, its provenance group and the re-check cost) and
returns (serve, audit, pi). After a re-check it is told whether the belief was stale.

Certified policies come with a guarantee (THEORY.md); the rest are the baselines a reviewer will
ask for: always re-check, never re-check, fixed time-to-live, an uncalibrated staleness
threshold, a judge threshold, a batch certificate without monitoring, and judge-only
certification (which looks certified but is not valid when the judge is wrong).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .certify.ltt import default_grid, ltt_threshold
from .certify.online import CertifierConfig, OnlineCertifier


@dataclass
class Ctx:
    t: float
    group: str
    score: float          # estimated P(stale) from the hazard model (or Boole bound)
    age: float
    judge: float | None   # cheap judge's P(stale), if any
    cost: float
    kind: str


class Policy:
    name = "policy"
    certified = False

    def decide(self, c: Ctx, rng: np.random.Generator) -> tuple[bool, bool, float]:
        raise NotImplementedError

    def feedback(self, c: Ctx, audited: bool, pi: float, stale: int | None,
                 served: bool = True) -> None:
        pass

    def state(self) -> dict:
        return {}


class AlwaysRecheck(Policy):
    name = "always-recheck"

    def decide(self, c, rng):
        return False, True, 1.0


class NeverRecheck(Policy):
    name = "never-recheck"

    def decide(self, c, rng):
        return True, False, 1.0


@dataclass
class TTL(Policy):
    days: float = 1.0

    @property
    def name(self):
        return f"ttl-{self.days:g}d"

    def decide(self, c, rng):
        return (True, False, 1.0) if c.age <= self.days else (False, True, 1.0)


@dataclass
class ScoreThreshold(Policy):
    """Serve when the hazard model's staleness estimate is below a fixed, uncertified level."""

    theta: float = 0.05

    @property
    def name(self):
        return f"hazard<{self.theta:g}"

    def decide(self, c, rng):
        return (True, False, 1.0) if c.score <= self.theta else (False, True, 1.0)


@dataclass
class JudgeThreshold(Policy):
    """Serve when the judge says the belief is probably current (the 'ask the LLM' baseline)."""

    theta: float = 0.5

    @property
    def name(self):
        return f"judge<{self.theta:g}"

    def decide(self, c, rng):
        j = 1.0 if c.judge is None else c.judge
        return (True, False, 1.0) if j <= self.theta else (False, True, 1.0)


@dataclass
class LTTBatch(Policy):
    """Learn-then-Test once on the first n queries (all re-checked), then a fixed threshold."""

    alpha: float = 0.05
    delta: float = 0.05
    n_calib: int = 2000
    by_group: bool = False
    _scores: dict = field(default_factory=dict)
    _stale: dict = field(default_factory=dict)
    _theta: dict = field(default_factory=dict)
    _seen: int = 0
    certified = True

    @property
    def name(self):
        return "ltt-batch" + ("-grouped" if self.by_group else "")

    def _g(self, c):
        return c.group if self.by_group else "all"

    def decide(self, c, rng):
        g = self._g(c)
        if self._seen < self.n_calib:
            return False, True, 1.0
        th = self._theta.get(g)
        if th is None or c.score > th:
            return False, True, 1.0
        return True, False, 1.0

    def feedback(self, c, audited, pi, stale, served=True):
        if self._seen >= self.n_calib or stale is None:
            return
        g = self._g(c)
        self._scores.setdefault(g, []).append(c.score)
        self._stale.setdefault(g, []).append(stale)
        self._seen += 1
        if self._seen == self.n_calib:
            groups = list(self._scores)
            for g2 in groups:
                d = self.delta / (len(groups) if self.by_group else 1)
                self._theta[g2] = ltt_threshold(np.array(self._scores[g2]),
                                                np.array(self._stale[g2]), default_grid(),
                                                self.alpha, d)

    def state(self):
        return {"thresholds": {k: v for k, v in self._theta.items()}}


@dataclass
class ACI(Policy):
    """Adaptive threshold (online conformal style, Gibbs and Candes 2021): move log(theta) up after
    a clean step and down after an error, with errors estimated from the same randomized audits.
    The long-run average error approaches alpha in every class, but nothing bounds the error over
    a finite stretch, so roughly half of all runs end above alpha. The strongest heuristic
    baseline: no certificate, but it tracks drift by design."""

    alpha: float = 0.05
    gamma: float = 0.05
    pi_audit: float = 0.1
    by_group: bool = True
    lo: float = 1e-4
    hi: float = 0.95
    _u: dict = field(default_factory=dict)

    @property
    def name(self):
        return f"aci-{self.alpha:g}" + ("" if self.by_group else "-pooled")

    def _g(self, c):
        return c.group if self.by_group else "all"

    def _theta(self, g):
        return float(np.exp(self._u.get(g, np.log(self.lo))))

    def decide(self, c, rng):
        if c.score > self._theta(self._g(c)):
            return False, True, 1.0
        return True, bool(rng.random() < self.pi_audit), self.pi_audit

    def feedback(self, c, audited, pi, stale, served=True):
        g = self._g(c)
        err = (1.0 - pi) * (stale / pi) if (served and audited and stale is not None) else 0.0
        u = self._u.get(g, np.log(self.lo)) + self.gamma * (self.alpha - err)
        self._u[g] = float(np.clip(u, np.log(self.lo), np.log(self.hi)))

    def state(self):
        return {"thresholds": {g: float(np.exp(u)) for g, u in self._u.items()}}


@dataclass
class Certified(Policy):
    """Online certification with randomized audits, optional judge rectification, alarms and
    per-provenance guarantees."""

    cfg: CertifierConfig = field(default_factory=CertifierConfig)
    by_group: bool = True
    groups: tuple[str, ...] = ("observed", "delegated", "stated", "notified", "inferred")
    label: str = ""
    _c: dict = field(default_factory=dict)
    certified = True

    def __post_init__(self):
        share = 1.0 / len(self.groups) if self.by_group else 1.0
        keys = self.groups if self.by_group else ("all",)
        self._c = {g: OnlineCertifier(self.cfg, share) for g in keys}

    @property
    def name(self):
        if self.label:
            return self.label
        base = "certified"
        if self.cfg.judge_only:
            base = "judge-only-cert"
        elif self.cfg.use_judge:
            base = "certified-ppi"
        if self.cfg.judge_audit_gain:
            base += "-guided"
        if not self.by_group:
            base += "-pooled"
        if not self.cfg.alarm:
            base += "-noalarm"
        return base

    def _g(self, c):
        return c.group if self.by_group else "all"

    def decide(self, c, rng):
        cert = self._c.get(self._g(c))
        if cert is None:
            return False, True, 1.0
        return cert.decide(c.score, rng, c.judge)

    def feedback(self, c, audited, pi, stale, served=True):
        cert = self._c.get(self._g(c))
        if cert is not None:
            cert.update(c.t, c.score, c.judge, audited, pi, stale, served)

    def state(self):
        return {g: {"threshold": c.threshold, "restarts": c.restarts,
                    "first_cert_t": c.first_cert_t, "alarm_times": c.alarm_times,
                    "cert_log": c.cert_log[-50:]} for g, c in self._c.items()}
