"""Online certification of memory reuse with randomized audits and (optionally) noisy judges.

The deployed rule for a staleness threshold theta serves from memory when the estimated
staleness s <= theta, and even then audits (re-checks anyway) with probability pi. Its risk is
the error rate of the system as it actually runs:

    R(theta) = P(s <= theta, not audited, stale).

The certifier keeps one betting e-process per threshold in an ascending grid and certifies
thresholds in fixed sequence (THEORY.md, Theorem 3).

Labels. Whenever the policy re-checks (nothing certified yet, or the score is above the certified
threshold) the staleness Y is observed and the loss of a candidate threshold is computed exactly:
S * (1 - pi) * Y, with pi the audit probability that query would have had if served. When it
serves, it audits with probability pi; otherwise Y is unknown. The served-query loss is

    Z = S * (1 - pi) * (J + (A / pi) * (Y - J)),

whose conditional mean is S * (1 - pi) * P(stale) whatever the judge J in [0, 1] says (J = 0
without a judge: plain inverse-propensity weighting; with a judge: prediction-powered
rectification). Audits that a judge directs to suspicious beliefs therefore lower the certified
risk itself, and the certificate lets the threshold rise to use the saving.

Drift. After a threshold is certified, a CUSUM-style e-detector watches whether its risk has
risen above alpha. An alarm discards the epoch and restarts every test with a smaller level
delta_r = delta / (r (r + 1)), so false certifications over all epochs stay below delta. A false
alarm costs re-checks, never validity, so the detector can be tuned for speed.

Groups. With `groups`, each provenance class (observed, delegated, stated, notified, inferred)
gets its own certifier at level delta / |groups|: a guarantee per class, so a rare but unreliable
class cannot hide inside a pooled average (Theorem 4).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .eprocess import Detector, Wealth
from .ltt import default_grid


@dataclass
class CertifierConfig:
    alpha: float = 0.05
    delta: float = 0.05
    pi_audit: float = 0.1        # minimum audit probability for served queries
    judge_audit_gain: float = 0.0  # audit more when the judge suspects staleness:
                                   # pi = min(1, pi_audit + gain * J); validity does not depend on J
    alarm: bool = True
    alarm_delta: float = 0.01
    use_judge: bool = False      # rectify with the judge (prediction-powered)
    judge_only: bool = False     # INVALID baseline: trust the judge as the label
    grid_size: int = 40


@dataclass
class _Epoch:
    tests: list[Wealth]
    alarm: Detector | None = None
    certified: int = -1          # index into grid of the largest certified threshold


@dataclass
class OnlineCertifier:
    cfg: CertifierConfig = field(default_factory=CertifierConfig)
    delta_share: float = 1.0     # fraction of delta given to this certifier (groups)
    grid: np.ndarray = field(default_factory=lambda: default_grid())
    epoch_index: int = 1
    restarts: int = 0
    first_cert_t: float | None = None
    cert_log: list = field(default_factory=list)
    alarm_times: list = field(default_factory=list)
    _ep: _Epoch | None = None

    def __post_init__(self) -> None:
        self.grid = default_grid(self.cfg.grid_size)
        self._new_epoch()

    def _range(self) -> tuple[float, float]:
        """Range of this step's loss, fixed by the past alone (not by the current query).

        Before anything is certified every query is re-checked, so Z is in [0, 1]. Afterwards a
        served query is audited with probability at least pi_audit and Z lies in
        [-(1 - pi)^2 / pi, (1 - pi) / pi] at pi = pi_audit (the lower end only with a judge).
        The bet must not depend on the current query's features, or the wealth stops being a
        supermartingale under the marginal null (THEORY.md, Theorem 3).
        """
        if self.cfg.judge_only or self._ep.certified < 0:
            return 0.0, 1.0
        pi = self.cfg.pi_audit
        hi = (1.0 - pi) / pi
        lo = -(1.0 - pi) ** 2 / pi if self.cfg.use_judge else 0.0
        return lo, max(hi, 1.0)

    def audit_prob(self, judge: float | None) -> float:
        pi = self.cfg.pi_audit
        if self.cfg.judge_audit_gain and judge is not None:
            pi = min(1.0, pi + self.cfg.judge_audit_gain * float(judge))
        return pi

    def _delta(self) -> float:
        r = self.epoch_index
        return self.cfg.delta * self.delta_share / (r * (r + 1))

    def _new_epoch(self) -> None:
        self._ep = _Epoch([Wealth(self.cfg.alpha, "below") for _ in self.grid])

    # ---- the policy's view ------------------------------------------------------------
    @property
    def threshold(self) -> float | None:
        j = self._ep.certified
        return float(self.grid[j]) if j >= 0 else None

    def decide(self, score: float, rng: np.random.Generator,
               judge: float | None = None) -> tuple[bool, bool, float]:
        """(serve, audit, pi): serve from memory? audit (re-observe anyway)? audit probability.

        With `judge_audit_gain`, the judge directs the audits: suspicious beliefs are audited
        more often, which catches stale answers before they are served. The guarantee does not
        rely on the judge, because the bet's range uses the minimum audit probability."""
        th = self.threshold
        if th is None or score > th:
            return False, True, 1.0
        pi = self.audit_prob(judge)
        return True, bool(rng.random() < pi), pi

    def update(self, t: float, score: float, judge: float | None, audited: bool, pi: float,
               stale: int | None, served: bool = True) -> None:
        """Feed back one query. `served` is False when the policy re-checked because the
        belief was above the certified threshold (or nothing was certified): then Y is known."""
        cfg = self.cfg
        ep = self._ep
        pi_s = self.audit_prob(judge)          # audit probability had it been served
        if cfg.judge_only:
            jv = 0.0 if judge is None else float(judge)
            label = (1.0 - pi_s) * jv
        elif not served:
            if stale is None:
                raise ValueError("a re-checked query needs its observed staleness")
            label = (1.0 - pi_s) * stale
        else:
            jv = float(judge) if (cfg.use_judge and judge is not None) else 0.0
            if audited:
                if stale is None:
                    raise ValueError("an audited query needs its observed staleness")
                label = (1.0 - pi) * (jv + (stale - jv) / pi)
            else:
                label = (1.0 - pi) * jv
        lo, hi = self._range()
        for j, th in enumerate(self.grid):
            s = 1.0 if score <= th else 0.0
            ep.tests[j].update(s * label, lo, hi)
        # fixed-sequence certification from the safest threshold upward
        d = self._delta()
        k = -1
        for j in range(len(self.grid)):
            if ep.tests[j].crossed(d):
                k = j
            else:
                break
        if k > ep.certified:
            ep.certified = k
            if self.first_cert_t is None:
                self.first_cert_t = t
            self.cert_log.append((t, float(self.grid[k])))
            if cfg.alarm:
                ep.alarm = Detector(cfg.alpha)
        # alarm: a CUSUM-style e-detector on the served set's residual risk
        if cfg.alarm and ep.alarm is not None and ep.certified >= 0:
            th = self.grid[ep.certified]
            s = 1.0 if score <= th else 0.0
            ep.alarm.update(s * label, lo, hi)
            if ep.alarm.alarmed(cfg.alarm_delta):
                self.restarts += 1
                self.alarm_times.append(t)
                self.epoch_index += 1
                self._new_epoch()
