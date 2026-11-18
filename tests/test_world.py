import numpy as np

from recheck.types import Event, Prov, Query
from recheck.world.kinds import KINDS, kind_of, slot_key
from recheck.world.sim import generate


def test_generate_is_deterministic():
    a = generate({"days": 5}, seed=3)
    b = generate({"days": 5}, seed=3)
    assert len(a.items) == len(b.items)
    for x, y in zip(a.items[:500], b.items[:500]):
        assert type(x) is type(y)
        assert x == y


def test_items_are_time_ordered_and_queries_carry_truth():
    ep = generate({"days": 5}, seed=0)
    times = [it.t_write if isinstance(it, Event) else it.t for it in ep.items]
    assert times == sorted(times)
    for q in [it for it in ep.items if isinstance(it, Query)][:200]:
        if not q.derived:
            assert q.truth == ep.world.value(q.slot, q.t)


def test_subagent_reports_are_never_from_the_future():
    ep = generate({"days": 5, "subagent_delay": [0.0, 3.0]}, seed=1)
    for e in ep.items:
        if isinstance(e, Event):
            assert e.t_obs <= e.t_write + 1e-12
            if e.prov == Prov.DELEGATED:
                assert e.value == ep.world.value(e.slot, e.t_obs)


def test_slot_keys_round_trip():
    k = KINDS[0]
    s = slot_key(k.name, "e3")
    assert kind_of(s) == k.name


def test_change_rate_matches_kind_hazard():
    ep = generate({"days": 60}, seed=2)
    k = next(k for k in KINDS if k.name == "branch.head")
    slots = [s for s in ep.world.traj if kind_of(s) == k.name]
    changes = [ep.world.traj[s].changed_between(0.0, 60.0) for s in slots]
    assert np.mean(changes) == 1.0  # at 0.6 changes a day, every slot changes in 60 days
