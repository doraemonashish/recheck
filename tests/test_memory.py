from recheck.memory.store import Memory
from recheck.types import Event, Prov


def test_observation_time_ordering_ignores_late_old_reports():
    m = Memory(order="obs")
    m.add(Event(5.0, 5.0, "branch.head|repo0", "new", Prov.OBSERVED, "agent"))
    m.add(Event(6.0, 2.0, "branch.head|repo0", "old", Prov.DELEGATED, "subagent"))
    b = m.belief("branch.head|repo0", 6.0)
    assert b.value == "new" and b.prov == Prov.OBSERVED


def test_write_time_ordering_takes_the_late_report_and_dates_it_by_arrival():
    m = Memory(order="write")
    m.add(Event(5.0, 5.0, "branch.head|repo0", "new", Prov.OBSERVED, "agent"))
    m.add(Event(6.0, 2.0, "branch.head|repo0", "old", Prov.DELEGATED, "subagent"))
    b = m.belief("branch.head|repo0", 6.0)
    assert b.value == "old" and b.t_obs == 6.0


def test_quoted_content_never_becomes_a_belief_unless_provenance_is_ignored():
    e = Event(1.0, 1.0, "product.price|p0", "999", Prov.QUOTED, "doc")
    m = Memory()
    m.add(e)
    assert m.belief("product.price|p0", 1.0) is None
    blind = Memory(trust_quoted=True)
    blind.add(e)
    b = blind.belief("product.price|p0", 1.0)
    assert b.value == "999" and b.prov == Prov.STATED


def test_inferences_retract_when_a_premise_changes():
    m = Memory()
    m.observe("a|0", 0.0, "x")
    m.observe("b|0", 0.0, "y")
    m.infer("d|0", 0.0, "xy", ("a|0", "b|0"))
    assert m.inference("d|0", 1.0).value == "xy"
    m.observe("a|0", 2.0, "z")
    assert m.inference("d|0", 2.0) is None
    assert m.retractions == 1


def test_boole_bound_is_at_least_the_product_bound():
    m = Memory()
    m.observe("branch.head|r", 0.0, "x")
    m.observe("ticket.status|t", 0.0, "open")
    for t in (0.0, 1.0, 3.0):  # give the hazard model some data
        m.observe("branch.head|r", t, "x")
    m.sleep()
    m.infer("d|0", 0.0, "v", ("branch.head|r", "ticket.status|t"))
    b = m.inference("d|0", 4.0)
    assert m.p_stale(b, 5.0, "boole") >= m.p_stale(b, 5.0, "product") - 1e-12
