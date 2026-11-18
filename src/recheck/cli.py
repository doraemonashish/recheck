"""recheck: certified memory reuse for agents in a changing world.

    recheck run configs/e1_validity.yaml [--workers 8]
    recheck report runs/e1_validity
    recheck all                         # every config in configs/ that needs no model
    recheck demo                        # one world, a few policies, printed
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _demo() -> None:
    from .agents.judges import Judge
    from .certify.online import CertifierConfig
    from .eval.metrics import summarize
    from .eval.runner import RunConfig, run
    from .policies import TTL, AlwaysRecheck, Certified, NeverRecheck, ScoreThreshold
    from .world.sim import generate

    ep = generate({"days": 40}, seed=0)
    print(f"world: {len(ep.world.traj)} slots, {len(ep.queries)} queries, {len(ep.events)} events")
    for pol in (AlwaysRecheck(), NeverRecheck(), TTL(1.0), ScoreThreshold(0.05),
                Certified(CertifierConfig(alpha=0.05))):
        s = summarize(run(ep, pol, Judge(), RunConfig()), after=10, alpha=0.05)
        print(f"{s['policy']:18} error {s['error_rate']:.4f}  cost {s['cost_vs_always']:.3f}  "
              f"served {s['served_from_memory']:.3f}  groups over alpha: {s['groups_over_alpha']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="recheck")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("config")
    r.add_argument("--workers", type=int, default=None)
    p = sub.add_parser("report")
    p.add_argument("run_dir")
    a = sub.add_parser("all")
    a.add_argument("--workers", type=int, default=None)
    sub.add_parser("demo")
    args = ap.parse_args(argv)

    from .eval.experiments import run_experiment
    from .eval.report import report

    if args.cmd == "run":
        out = run_experiment(args.config, args.workers)
        report(str(out))
    elif args.cmd == "report":
        report(args.run_dir)
    elif args.cmd == "all":
        import yaml

        for cfg in sorted(Path("configs").glob("e*.yaml")):
            exp = yaml.safe_load(cfg.read_text())
            if exp.get("needs_model"):
                print(f"skip {cfg} (needs a model: run it in a notebook)")
                continue
            report(str(run_experiment(str(cfg), args.workers)))
    elif args.cmd == "demo":
        _demo()
    return 0


if __name__ == "__main__":
    sys.exit(main())
