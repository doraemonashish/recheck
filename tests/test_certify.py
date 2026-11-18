import numpy as np

from recheck.certify.ltt import binom_pvalue, default_grid, ltt_threshold
from recheck.certify.online import CertifierConfig, OnlineCertifier


def test_binom_pvalue_is_monotone():
    ps = [binom_pvalue(k, 200, 0.05) for k in range(0, 15)]
    assert all(a <= b for a, b in zip(ps, ps[1:]))
    assert binom_pvalue(0, 0, 0.05) == 1.0


def test_ltt_threshold_on_a_calibrated_score():
    rng = np.random.default_rng(0)
    s = rng.random(20000)
    y = (rng.random(20000) < s).astype(int)
    th = ltt_threshold(s, y, default_grid(), alpha=0.05, delta=0.05)
    # risk(theta) = theta^2 / 2, so the largest safe threshold is sqrt(0.1) ~ 0.316
    assert th is not None and 0.2 < th <= 0.316


def _stream(cert, steps, judge, rng):
    for t in range(steps):
        s = rng.random()
        y = int(rng.random() < s)
        jv = judge(y, rng)
        serve, audit, pi = cert.decide(s, rng, jv)
        cert.update(float(t), s, jv, audit, pi, y if (audit or not serve) else None, serve)
    return cert


def test_online_certificate_is_safe_with_an_adversarial_judge():
    rng = np.random.default_rng(3)
    cfg = CertifierConfig(alpha=0.05, delta=0.05, use_judge=True)
    cert = _stream(OnlineCertifier(cfg), 6000, lambda y, r: float(1 - y), rng)
    # with pi = 0.1 the risk of theta is 0.9 theta^2 / 2: safe up to sqrt(0.1/0.9) ~ 0.333
    assert cert.threshold is not None and cert.threshold <= 0.334


def test_guided_audits_with_a_good_judge_raise_the_threshold():
    good = lambda y, r: float(y) if r.random() < 0.9 else float(1 - y)  # noqa: E731
    plain = _stream(OnlineCertifier(CertifierConfig(use_judge=True)), 6000, good,
                    np.random.default_rng(4))
    guided = _stream(OnlineCertifier(CertifierConfig(use_judge=True, judge_audit_gain=0.9)), 6000,
                     good, np.random.default_rng(4))
    assert guided.threshold > plain.threshold


def test_restart_levels_sum_to_delta():
    c = OnlineCertifier(CertifierConfig(delta=0.05))
    total = 0.0
    for r in range(1, 2000):
        c.epoch_index = r
        total += c._delta()
    assert total <= 0.05 + 1e-12
