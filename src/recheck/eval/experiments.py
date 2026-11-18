"""Experiments from YAML: worlds x seeds x arms (policy, judge, memory options).

    recheck run configs/e1_validity.yaml            # writes runs/<name>/summary.jsonl
    recheck report runs/e1_validity                 # writes results/<name>/README.md + plots

Each (arm, seed) runs in its own process; the world for a seed is shared by every arm, so arms
are compared on identical streams.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import yaml

from ..agents.judges import make_judge
from ..certify.online import CertifierConfig
from ..policies import (
    ACI,
    TTL,
    AlwaysRecheck,
    Certified,
    JudgeThreshold,
    LTTBatch,
    NeverRecheck,
    Policy,
    ScoreThreshold,
)
from ..world.traces import generate_any
from .metrics import summarize
from .runner import RunConfig, run


def make_policy(spec: dict) -> Policy:
    t = spec["type"]
    if t == "always":
        return AlwaysRecheck()
    if t == "never":
        return NeverRecheck()
    if t == "ttl":
        return TTL(float(spec["days"]))
    if t == "hazard":
        return ScoreThreshold(float(spec["theta"]))
    if t == "judge":
        return JudgeThreshold(float(spec.get("theta", 0.5)))
    if t == "ltt":
        return LTTBatch(spec.get("alpha", 0.05), spec.get("delta", 0.05),
                        int(spec.get("n_calib", 2000)), bool(spec.get("by_group", False)))
    if t == "aci":
        return ACI(float(spec.get("alpha", 0.05)), float(spec.get("gamma", 0.05)),
                   float(spec.get("pi_audit", 0.1)), bool(spec.get("by_group", True)))
    if t == "certified":
        keys = CertifierConfig.__dataclass_fields__
        cfg = CertifierConfig(**{k: v for k, v in spec.items() if k in keys})
        return Certified(cfg, bool(spec.get("by_group", True)), label=spec.get("label", ""))
    raise ValueError(f"unknown policy type {t}")


def _daily(res, days: float) -> dict:
    n = int(np.ceil(days))
    q = np.zeros(n)
    w = np.zeros(n)
    c = np.zeros(n)
    for r in res.rows:
        d = min(int(r.t), n - 1)
        q[d] += 1
        w[d] += int(not r.correct)
        c[d] += r.cost
    with np.errstate(invalid="ignore", divide="ignore"):
        return {"error": np.where(q > 0, w / q, np.nan).tolist(),
                "cost": np.where(q > 0, c / q, np.nan).tolist()}


def _job(args) -> dict:
    exp, arm, seed = args
    ep = generate_any(exp.get("world", {}), seed=seed)
    pol = make_policy(arm["policy"])
    judge = make_judge(arm.get("judge"))
    rc = RunConfig(**arm.get("memory", {}))
    probe = None
    if arm.get("probe"):
        from ..agents.agent_loop import LLMAgentProbe

        probe = LLMAgentProbe(**arm["probe"])
    t0 = time.time()
    res = run(ep, pol, judge, rc, seed=seed, probe=probe,
              probe_every=int(arm.get("probe_every", 50)))
    alpha = arm["policy"].get("alpha", exp.get("alpha", 0.05))
    after = float(exp.get("burn_in_days", 10.0))
    s = summarize(res, after=after, alpha=alpha)
    wins = {}
    for wname, (a, b) in (exp.get("windows") or {}).items():
        w = summarize(res, after=float(a), alpha=alpha, before=float(b))
        wins[wname] = {k: w.get(k) for k in ("error_rate", "cost_vs_always", "served_from_memory",
                                             "by_group", "groups_over_alpha")}
    if wins:
        s["windows"] = wins
    s.update({"arm": arm["name"], "seed": seed, "alpha": alpha, "seconds": time.time() - t0,
              "state": res.state, "daily": _daily(res, ep.days)})
    if probe is not None:
        pr = [r for r in res.rows if r.probe]
        s["probe"] = {
            "n": len(pr),
            "answered": sum(r.probe == "answer" for r in pr),
            "stale_answers": sum(r.probe == "answer" and r.stale == 1 for r in pr),
            "needless_checks": sum(r.probe == "check" and r.stale == 0 for r in pr),
        }
    return s


def run_experiment(path: str, workers: int | None = None, out_root: str = "runs") -> Path:
    exp = yaml.safe_load(Path(path).read_text())
    name = exp["name"]
    out = Path(out_root) / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "config.yaml").write_text(yaml.safe_dump(exp, sort_keys=False))
    seeds = exp.get("seeds", [0])
    if isinstance(seeds, int):
        seeds = list(range(seeds))
    jobs = [(exp, arm, s) for arm in exp["arms"] for s in seeds]
    workers = workers or int(os.environ.get("RECHECK_WORKERS", os.cpu_count() or 1))
    if any(arm.get("probe") or (arm.get("judge") or {}).get("type") in ("llm", "laya")
           for arm in exp["arms"]):
        workers = 1   # model calls run in one process (one GPU, one cache)
    t0 = time.time()
    with open(out / "summary.jsonl", "w") as f:
        if workers == 1:
            for j in jobs:
                f.write(json.dumps(_job(j)) + "\n")
                f.flush()
        else:
            with ProcessPoolExecutor(workers) as ex:
                for s in ex.map(_job, jobs):
                    f.write(json.dumps(s) + "\n")
    print(f"{name}: {len(jobs)} runs in {time.time() - t0:.0f}s -> {out}/summary.jsonl")
    return out
