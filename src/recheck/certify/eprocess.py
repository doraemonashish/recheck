"""Betting e-processes for a bounded loss whose conditional mean may drift.

`Wealth` tests one side of a mean against a level `alpha` with predictable bets (an aGRAPA-style
rule, Waudby-Smith and Ramdas 2024). At step t the loss Z_t lies in a range [lo_t, hi_t] that is
known before Z_t is drawn (it depends on the audit probability chosen for that query), and the
bet is capped so every factor stays nonnegative on that range:

- side="below": H0 is E[Z_t | past] >= alpha for every t (the threshold is unsafe). Wealth
  W_t = prod (1 + g_i (alpha - Z_i)) is a nonnegative supermartingale under H0, so by Ville's
  inequality P(sup W_t >= 1/delta) <= delta. Crossing 1/delta certifies.
- side="above": H0 is E[Z_t | past] <= alpha for every t (the threshold is safe). Crossing raises
  an alarm that the risk has risen above alpha.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class Wealth:
    """A mixture of betting e-processes that share one adaptive bet and differ in how much of the
    largest safe bet they stake (`caps`). Each component is a nonnegative supermartingale under
    H0, so their average is too and Ville's inequality applies to it. The cautious component
    survives a bad draw; the aggressive one certifies a clean class in close to the minimum
    number of labels (THEORY.md, Proposition 7)."""

    alpha: float
    side: str = "below"
    caps: tuple[float, ...] = (0.5, 0.95)
    prior_n: float = 10.0       # pseudo-observations for the bet's mean/variance estimates
    n: int = 0
    _sum: float = 0.0
    _sumsq: float = 0.0
    _logs: list = None

    def __post_init__(self) -> None:
        self._logs = [0.0 for _ in self.caps]

    @property
    def log_w(self) -> float:
        m = max(self._logs)
        return m + math.log(sum(math.exp(x - m) for x in self._logs) / len(self._logs))

    def _bet(self, lo: float, hi: float) -> tuple[float, float]:
        """(fraction of the largest safe bet, largest safe bet) for this step."""
        a = self.alpha
        m0 = a * (2.0 if self.side == "below" else 0.5)
        m = (self._sum + self.prior_n * m0) / (self.n + self.prior_n)
        second = (self._sumsq + self.prior_n * (m0 * m0 + m0)) / (self.n + self.prior_n)
        v = max(second - m * m, 1e-6)
        if self.side == "below":
            edge = a - m
            gmax = 1.0 / max(hi - a, 1e-9)
        else:
            edge = m - a
            gmax = 1.0 / max(a - lo, 1e-9)
        if edge <= 0:
            return 0.0, gmax
        return min(1.0, edge / (v + edge * edge) / gmax), gmax

    def update(self, z: float, lo: float = 0.0, hi: float = 1.0) -> float:
        frac, gmax = self._bet(lo, hi)
        inc = (self.alpha - z) if self.side == "below" else (z - self.alpha)
        for i, c in enumerate(self.caps):
            g = min(frac, c) * gmax
            self._logs[i] += math.log(max(1.0 + g * inc, 1e-300))
        self.n += 1
        self._sum += z
        self._sumsq += z * z
        return self.log_w

    def crossed(self, delta: float) -> bool:
        return self.log_w >= math.log(1.0 / delta)


@dataclass
class Detector:
    """A CUSUM-style e-detector for 'the mean has risen above alpha' (Shin, Ramdas and Rinaldo,
    2024). It runs one CUSUM per fixed bet fraction: log M_t = max(log M_{t-1}, 0) +
    log(1 + g (Z_t - alpha)), so evidence from a long safe stretch never has to be paid back
    before a change is noticed. Under the null (mean <= alpha throughout) the expected time to a
    false alarm at threshold K/delta is at least K/delta steps; a false alarm only costs a
    restart, never validity.
    """

    alpha: float
    fractions: tuple[float, ...] = (0.1, 0.3, 0.6)
    _log: list = None

    def __post_init__(self) -> None:
        self._log = [0.0 for _ in self.fractions]

    def update(self, z: float, lo: float = 0.0, hi: float = 1.0) -> None:
        gmax = 1.0 / max(self.alpha - lo, 1e-9)
        for i, f in enumerate(self.fractions):
            g = f * gmax
            self._log[i] = max(self._log[i], 0.0) + math.log(max(1.0 + g * (z - self.alpha),
                                                                1e-300))

    def alarmed(self, delta: float) -> bool:
        return max(self._log) >= math.log(len(self.fractions) / delta)
