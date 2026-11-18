from packaging.version import Version

from recheck.memory.store import Memory
from recheck.types import Query
from recheck.world.traces import generate_pypi, load_traces


def test_real_traces_load_and_the_latest_version_only_goes_up():
    traces = load_traces()
    assert len(traces) > 100
    for tr in list(traces.values())[:50]:
        versions = [Version(v) for _, v in tr]
        assert versions == sorted(versions)
        times = [t for t, _ in tr]
        assert times == sorted(times)


def test_pypi_world_is_deterministic_and_queries_carry_the_real_answer():
    a = generate_pypi({"days": 30}, seed=1)
    b = generate_pypi({"days": 30}, seed=1)
    assert [type(x) for x in a.items[:300]] == [type(x) for x in b.items[:300]]
    qs = [x for x in a.items if isinstance(x, Query) and not x.derived][:100]
    assert qs
    for q in qs:
        assert q.truth == a.world.value(q.slot, q.t)
        Version(q.truth)  # a real version string


def test_seeds_shift_the_window():
    a = generate_pypi({"days": 30}, seed=0)
    b = generate_pypi({"days": 30}, seed=4)
    numpy_a = a.world.value("pkg.latest|numpy", 0.0)
    numpy_b = b.world.value("pkg.latest|numpy", 0.0)
    assert Version(numpy_b) >= Version(numpy_a)


def test_per_slot_rates_separate_fast_and_slow_slots():
    m = Memory(per_slot=True)
    for i in range(40):  # one slot changes every day, the other never
        m.observe("pkg.latest|fast", float(i), f"1.{i}")
        m.observe("pkg.latest|slow", float(i), "1.0")
    hz = m.sleep()
    assert hz.rate("pkg.latest", "pkg.latest|fast") > 5 * hz.rate("pkg.latest", "pkg.latest|slow")
