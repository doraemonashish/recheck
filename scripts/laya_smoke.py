"""Check that Laya loads and answers the staleness question, and time it.

    pip install laya
    python scripts/laya_smoke.py --device cuda      # on a Kaggle or Colab T4
    python scripts/laya_smoke.py                    # CPU works too, slowly

Prints the raw answer for one belief (so you can see which key holds the probability), the
parsed P(stale) for a fresh and an old belief of the same fact, and the time per call.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from recheck.agents.laya_judge import QUESTION, LayaJudge, _p_true  # noqa: E402
from recheck.types import Belief, Prov  # noqa: E402
from recheck.world.render import describe_belief  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default=None)
    ap.add_argument("--checkpoint", default="convaiinnovations/laya")
    ap.add_argument("--subfolder", default="", help="empty: English; or multilingual")
    ap.add_argument("--n", type=int, default=50)
    a = ap.parse_args()

    judge = LayaJudge(a.checkpoint, a.subfolder or None, a.device)
    t0 = time.time()
    judge._load()
    print(f"loaded in {time.time() - t0:.1f}s")

    fresh = Belief("ticket.status|TCK-104", "in_review", 9.9, Prov.OBSERVED)
    old = Belief("ticket.status|TCK-104", "in_review", 2.0, Prov.OBSERVED)
    text = describe_belief(fresh, 10.0)
    raw = judge._agent.predict(text, QUESTION)
    print("state:\n" + text)
    print("raw answer:", raw["answers"]["current"])
    print("parsed P(true):", _p_true(raw["answers"]["current"]))
    for name, b in (("fresh (0.1 days)", fresh), ("old (8 days)", old)):
        print(f"P(stale), {name}: {judge(b, 10.0, None, 0, None)}")

    t0 = time.time()
    for i in range(a.n):
        b = Belief("ticket.status|TCK-104", "in_review", 10.0 - 0.1 * i, Prov.DELEGATED)
        judge._agent.predict(describe_belief(b, 10.0), QUESTION)
    print(f"{(time.time() - t0) / a.n * 1000:.0f} ms per call")


if __name__ == "__main__":
    main()
