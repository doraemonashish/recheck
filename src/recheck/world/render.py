"""Plain-language descriptions of beliefs and tasks, for LLM and System One judges and agents."""
from __future__ import annotations

from ..types import Belief, Prov
from .kinds import KIND_BY_NAME, entity_of, kind_of

_SOURCE = {
    Prov.OBSERVED: "you checked it yourself with a tool",
    Prov.DELEGATED: "a subagent reported it (it observed the value at that time)",
    Prov.STATED: "the user told you",
    Prov.NOTIFIED: "a system notification announced it",
    Prov.INFERRED: "you derived it from other facts",
    Prov.QUOTED: "it appeared in pasted, untrusted content",
}


def describe_kind(slot: str) -> str:
    k = KIND_BY_NAME.get(kind_of(slot))
    if k is None:
        return "a value derived from several other facts"
    return k.description or k.name


def describe_belief(b: Belief, t: float) -> str:
    what = describe_kind(b.slot)
    age = b.age(t)
    lines = [
        f"Fact: {what} for {entity_of(b.slot)}.",
        f"Stored value: {b.value}.",
        f"Recorded {age:.1f} days ago; {_SOURCE[b.prov]}.",
    ]
    if b.prov == Prov.INFERRED and b.premises:
        parts = [f"{describe_kind(p)} for {entity_of(p)} (checked {t - to:.1f} days ago)"
                 for p, to in zip(b.premises, b.premise_obs)]
        lines.append("It depends on: " + "; ".join(parts) + ".")
    return "\n".join(lines)


def describe_task(slot: str) -> str:
    return f"What is the current {describe_kind(slot)} for {entity_of(slot)}?"
