import math

import numpy as np

from recheck.certify.eprocess import Detector, Wealth


def _steps_to_certify(wealth, delta, z=0.0, limit=10_000):
    n = 0
    while not wealth.crossed(delta) and n < limit:
        wealth.update(z)
        n += 1
    return n


def test_clean_class_certifies_near_the_lower_bound():
    alpha, delta = 0.05, 0.01
    lower = math.ceil(math.log(1 / delta) / -math.log(1 - alpha))      # Proposition 7: 90
    mixed = _steps_to_certify(Wealth(alpha), delta)
    single = _steps_to_certify(Wealth(alpha, caps=(0.5,)), delta)
    assert lower == 90
    assert lower <= mixed <= 1.5 * lower
    assert mixed < single


def test_false_certification_rate_under_the_null():
    """Losses with mean exactly alpha: the wealth must cross 1/delta in at most ~delta of runs."""
    rng = np.random.default_rng(0)
    alpha, delta, runs, steps = 0.05, 0.1, 400, 1500
    crossed = 0
    for _ in range(runs):
        w = Wealth(alpha)
        for _ in range(steps):
            w.update(float(rng.random() < alpha))
            if w.crossed(delta):
                crossed += 1
                break
    # binomial(400, 0.1) exceeds 0.14 * 400 with probability < 0.01
    assert crossed / runs <= 0.14


def test_ipw_losses_under_the_null():
    """Audited losses Z = (A/pi) Y with E[Z] = alpha and a range of 1/pi."""
    rng = np.random.default_rng(1)
    alpha, delta, pi, runs, steps = 0.05, 0.1, 0.2, 300, 2000
    crossed = 0
    for _ in range(runs):
        w = Wealth(alpha)
        for _ in range(steps):
            y = rng.random() < alpha
            a = rng.random() < pi
            w.update((a / pi) * y, 0.0, 1.0 / pi)
            if w.crossed(delta):
                crossed += 1
                break
    assert crossed / runs <= 0.15


def test_detector_raises_an_alarm_after_a_change_and_not_before():
    rng = np.random.default_rng(2)
    det = Detector(0.05)
    for _ in range(3000):
        det.update(float(rng.random() < 0.01))
    assert not det.alarmed(1e-3)
    for i in range(3000):  # noqa: B007
        det.update(float(rng.random() < 0.2))
        if det.alarmed(1e-3):
            break
    assert det.alarmed(1e-3) and i < 300
