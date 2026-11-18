"""Kinds of facts an agent remembers, grouped into domains, with how fast each changes.

Hazards are changes per day. A Weibull shape below 1 makes changes bursty (a value that just
changed is likely to change again soon), above 1 makes them age (a value is likelier to change
the longer it has stood). `observable=False` kinds can only be re-checked by asking the user.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Kind:
    name: str
    domain: str
    hazard: float              # mean changes per day
    values: tuple[str, ...]
    shape: float = 1.0         # Weibull shape of the time between changes
    observable: bool = True    # False: re-checking means asking the user
    obs_cost: float = 1.0      # cost of one re-observation (a tool call)
    notify_prob: float = 0.0   # chance a change is announced by a notification
    entity_fmt: str = "{i}"
    description: str = ""


def _v(*xs: str) -> tuple[str, ...]:
    return tuple(xs)


KINDS: tuple[Kind, ...] = (
    # a code workspace
    Kind("file.config", "dev", 0.05, _v("db-1", "db-2", "db-3", "db-replica", "db-new"),
         shape=0.7, entity_fmt="service-{i}/config.yaml:db_host",
         description="the database host in a service's config file"),
    Kind("dep.version", "dev", 0.03, _v("1.4.2", "1.5.0", "1.5.1", "2.0.0", "2.1.0"),
         shape=1.3, entity_fmt="package-{i}", description="the pinned version of a dependency"),
    Kind("branch.head", "dev", 0.6, _v("a1f3", "b7c9", "c2d4", "d8e0", "e5f6", "f0a1"),
         entity_fmt="branch-{i}", notify_prob=0.3,
         description="the latest commit on a branch"),
    # an issue tracker
    Kind("ticket.status", "tickets", 0.3, _v("open", "in progress", "in review", "blocked", "done"),
         shape=1.5, entity_fmt="T-{i}", notify_prob=0.2, description="a ticket's status"),
    Kind("ticket.assignee", "tickets", 0.08, _v("Asha", "Ravi", "Meera", "Kabir", "Noor"),
         entity_fmt="T-{i}", description="who a ticket is assigned to"),
    # a shop backend
    Kind("product.price", "commerce", 0.4, _v("499", "549", "599", "649", "699", "749"),
         shape=0.8, entity_fmt="SKU-{i}", description="a product's price in rupees"),
    Kind("product.stock", "commerce", 0.9, _v("in stock", "low", "out of stock", "backorder"),
         entity_fmt="SKU-{i}", description="a product's stock state"),
    # people and the organisation
    Kind("person.manager", "org", 0.006, _v("Priya", "Arjun", "Leela", "Dev", "Sana"),
         shape=1.2, entity_fmt="employee-{i}", description="who an employee reports to"),
    Kind("person.team", "org", 0.004, _v("search", "infra", "payments", "growth", "ml"),
         entity_fmt="employee-{i}", description="an employee's team"),
    # a calendar
    Kind("meeting.time", "calendar", 0.12, _v("Mon 10:00", "Mon 15:00", "Tue 11:00", "Wed 09:30",
                                              "Thu 16:00", "Fri 12:00"),
         entity_fmt="meeting-{i}", notify_prob=0.5, description="when a recurring meeting is held"),
    # the user (only the user can tell)
    Kind("user.city", "user", 0.003, _v("Pune", "Bengaluru", "Delhi", "Chennai", "Hyderabad"),
         observable=False, obs_cost=3.0, entity_fmt="user-{i}", description="where the user lives"),
    Kind("user.preference", "user", 0.02, _v("vegetarian", "vegan", "no restriction", "jain"),
         observable=False, obs_cost=3.0, entity_fmt="user-{i}", description="the user's diet"),
)

# Kinds whose changes come from real traces (world/traces.py), not from the simulator. They are
# not part of any simulated domain; `hazard` is only a rough typical rate for display.
REAL_KINDS: tuple[Kind, ...] = (
    Kind("pkg.latest", "pypi", 0.015, (), entity_fmt="{name}", notify_prob=0.1,
         description="the latest stable release of a Python package on PyPI"),
)

KIND_BY_NAME = {k.name: k for k in KINDS + REAL_KINDS}
DOMAINS = tuple(sorted({k.domain for k in KINDS}))


def kinds_for(domains: list[str] | None) -> list[Kind]:
    if not domains:
        return list(KINDS)
    unknown = set(domains) - set(DOMAINS)
    if unknown:
        raise ValueError(f"unknown domains {sorted(unknown)}; known: {DOMAINS}")
    return [k for k in KINDS if k.domain in domains]


def slot_key(kind: str, entity: str) -> str:
    return f"{kind}|{entity}"


def kind_of(slot: str) -> str:
    return slot.split("|", 1)[0]


def entity_of(slot: str) -> str:
    return slot.split("|", 1)[1]
