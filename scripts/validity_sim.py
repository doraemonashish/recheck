"""How often does a certificate certify an unsafe threshold? A direct check of Theorem 3.

Each run is a stream of queries with a staleness score s ~ U(0, 1) and P(stale | s) = s, so the
risk of the deployed rule at threshold theta is known exactly. A certificate is false if it ever
certifies a threshold whose risk is above alpha. Theorem 3 says this happens with probability at
most delta, whatever the judge does; the judge-only baseline has no such guarantee.

    python scripts/validity_sim.py            # about five minutes on two cores
    python scripts/validity_sim.py --quick    # a smoke run
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recheck.certify.online import CertifierConfig, OnlineCertifier  # noqa: E402

ALPHA, DELTA = 0.05, 0.10

SETTINGS = {
    "ipw (no judge)": dict(cfg={}, judge="none"),
    "ppi, adversarial judge": dict(cfg={"use_judge": True}, judge="adversarial"),
    "ppi, guided audits, adversarial judge": dict(cfg={"use_judge": True, "judge_audit_gain": 0.9},
                                                  judge="adversarial"),
    "ppi, guided audits, good judge": dict(cfg={"use_judge": True, "judge_audit_gain": 0.9},
                                           judge="good"),
    "judge-only (invalid baseline), optimistic judge": dict(cfg={"judge_only": True},
                                                           judge="optimistic"),
}


def _judge(kind: str, y: int, rng) -> float | None:
    if kind == "none":
        return None
    if kind == "adversarial":        # always wrong, and confidently so
        return float(1 - y)
    if kind == "good":
        return float(y) if rng.random() < 0.9 else float(1 - y)
    if kind == "optimistic":         # misses most stale beliefs
        return 0.0 if (y == 0 or rng.random() < 0.8) else 1.0
    raise ValueError(kind)


def _judge_vec(kind: str, y: np.ndarray, rng) -> np.ndarray | None:
    if kind == "none":
        return None
    u = rng.random(len(y))
    if kind == "adversarial":
        return (1 - y).astype(float)
    if kind == "good":
        return np.where(u < 0.9, y, 1 - y).astype(float)
    if kind == "optimistic":
        return np.where((y == 0) | (u < 0.8), 0.0, 1.0)
    raise ValueError(kind)


def _risk(theta: float, cert: OnlineCertifier, kind: str, rng, n: int = 400_000) -> float:
    """Exact-enough risk of the deployed rule: P(s <= theta, not audited, stale)."""
    s = rng.random(n)
    y = (rng.random(n) < s).astype(int)
    j = _judge_vec(kind, y, rng)
    pi = np.full(n, cert.cfg.pi_audit)
    if j is not None and cert.cfg.judge_audit_gain:
        pi = np.minimum(1.0, pi + cert.cfg.judge_audit_gain * j)
    return float(np.mean((s <= theta) * (1 - pi) * y))


def one_run(args) -> dict:
    name, seed, steps = args
    st = SETTINGS[name]
    rng = np.random.default_rng(seed)
    cfg = CertifierConfig(alpha=ALPHA, delta=DELTA, alarm=True, **st["cfg"])
    cert = OnlineCertifier(cfg)
    # exact risk per grid threshold (Monte Carlo with a large sample, shared seed per setting)
    risk_rng = np.random.default_rng(12345)
    unsafe = [_risk(float(th), cert, st["judge"], risk_rng) > ALPHA for th in cert.grid]
    false_cert = False
    served = 0
    for t in range(steps):
        s = rng.random()
        y = int(rng.random() < s)
        jv = _judge(st["judge"], y, rng)
        serve, audit, pi = cert.decide(s, rng, jv)
        served += serve and not audit
        cert.update(float(t), s, jv, audit, pi, y if (audit or not serve) else None, serve)
        k = cert._ep.certified
        if k >= 0 and unsafe[k]:
            false_cert = True
    return {"setting": name, "seed": seed, "false_cert": false_cert,
            "final_threshold": cert.threshold, "served": served / steps,
            "restarts": cert.restarts}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default="results/e0_validity_sim")
    a = ap.parse_args()
    if a.quick:
        a.runs, a.steps = 10, 800
    jobs = [(name, seed, a.steps) for name in SETTINGS for seed in range(a.runs)]
    t0 = time.time()
    with ProcessPoolExecutor() as ex:
        res = list(ex.map(one_run, jobs, chunksize=4))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "runs.jsonl").write_text("\n".join(json.dumps(r) for r in res) + "\n")
    theta_star = (2 * ALPHA / (1 - 0.1)) ** 0.5
    lines = ["# e0_validity_sim", "",
             f"{a.runs} streams of {a.steps} queries per setting, alpha = {ALPHA}, "
             f"delta = {DELTA}. Score s ~ U(0, 1), P(stale | s) = s, audit probability 0.1, so "
             f"without guided audits the largest safe threshold is {theta_star:.3f}. A run counts "
             "as a false certificate if it ever certified a threshold whose risk is above alpha.",
             "", "| Setting | False certificates | 95% upper bound | Final threshold (median) | "
             "Served unaudited | Alarms per run |", "|---|---|---|---|---|---|"]
    for name in SETTINGS:
        rs = [r for r in res if r["setting"] == name]
        k = sum(r["false_cert"] for r in rs)
        n = len(rs)
        # one-sided Clopper-Pearson upper bound
        from scipy.stats import beta
        ub = 1.0 if k == n else float(beta.ppf(0.95, k + 1, n - k))
        th = [r["final_threshold"] for r in rs if r["final_threshold"] is not None]
        med = f"{np.median(th):.3f}" if th else "-"
        lines.append(f"| {name} | {k}/{n} = {k / n:.3f} | {ub:.3f} | {med} | "
                     f"{np.mean([r['served'] for r in rs]):.3f} | "
                     f"{np.mean([r['restarts'] for r in rs]):.2f} |")
    lines += ["", f"Run time {time.time() - t0:.0f} s."]
    (out / "README.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
