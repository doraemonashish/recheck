"""Core data types shared by the world simulator, the memory and the evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Prov(str, Enum):
    """Where a belief came from. Each class goes stale differently and is certified separately."""

    OBSERVED = "observed"    # the agent's own tool observation
    DELEGATED = "delegated"  # a subagent's report (observed earlier than it was written)
    STATED = "stated"        # the user said it
    NOTIFIED = "notified"    # a system notification that a value changed
    INFERRED = "inferred"    # derived by the agent from premises
    QUOTED = "quoted"        # pasted or untrusted content: never overrides a trusted belief


TRUSTED = (Prov.OBSERVED, Prov.DELEGATED, Prov.STATED, Prov.NOTIFIED)


@dataclass(frozen=True)
class Event:
    """Something the memory is told: `t_obs` is when the value held, `t_write` when it arrived."""

    t_write: float
    t_obs: float
    slot: str
    value: str
    prov: Prov
    source: str = "agent"
    premises: tuple[str, ...] = ()


@dataclass(frozen=True)
class Query:
    """A task step that needs the current value of a slot (or of a derived slot) at time t."""

    t: float
    slot: str
    truth: str
    derived: bool = False
    premises: tuple[str, ...] = ()
    qid: int = 0


@dataclass(frozen=True)
class Belief:
    """What the memory holds for a slot when asked."""

    slot: str
    value: str
    t_obs: float
    prov: Prov
    premises: tuple[str, ...] = ()
    premise_obs: tuple[float, ...] = ()

    def age(self, t: float) -> float:
        return max(0.0, t - self.t_obs)
