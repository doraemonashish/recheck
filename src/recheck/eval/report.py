"""Tables and plots from runs/<name>/summary.jsonl, with no model calls."""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np


def _load(run_dir: Path) -> list[dict]:
    return [json.loads(x) for x in (run_dir / "summary.jsonl").read_text().splitlines() if x]


def aggregate(rows: list[dict]) -> list[dict]:
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    out = []
    for arm, rs in by.items():
        err = np.array([r["error_rate"] for r in rs])
        cost = np.array([r["cost_vs_always"] for r in rs])
        alpha = rs[0]["alpha"]
        groups = sorted({g for r in rs for g in r.get("by_group", {})} - {"none"})
        g_err = {g: float(np.mean([r["by_group"].get(g, {}).get("error_rate", 0.0) for r in rs]))
                 for g in groups}
        g_over = {g: float(np.mean([r["by_group"].get(g, {}).get("error_rate", 0.0) > alpha
                                    for r in rs])) for g in groups}
        row = {
            "arm": arm,
            "seeds": len(rs),
            "alpha": alpha,
            "error_mean": float(err.mean()),
            "error_p95": float(np.quantile(err, 0.95)),
            "seeds_over_alpha": float((err > alpha).mean()),
            "seeds_any_group_over_alpha": float(np.mean([bool(r.get("groups_over_alpha"))
                                                        for r in rs])),
            "cost_vs_always": float(cost.mean()),
            "served_from_memory": float(np.mean([r["served_from_memory"] for r in rs])),
            "group_error": g_err,
            "group_over_alpha": g_over,
        }
        if any("windows" in r for r in rs):
            row["windows"] = {}
            for w in rs[0]["windows"]:
                ws = [r["windows"][w] for r in rs]
                row["windows"][w] = {
                    "error_mean": float(np.mean([x["error_rate"] for x in ws])),
                    "seeds_any_group_over_alpha": float(np.mean([bool(x["groups_over_alpha"])
                                                                for x in ws])),
                    "cost_vs_always": float(np.mean([x["cost_vs_always"] for x in ws])),
                }
        st = [r.get("state") or {} for r in rs]
        certified_arm = bool(st and st[0]) and all(isinstance(v, dict) and "first_cert_t" in v
                                                   for v in st[0].values())
        if certified_arm:
            cert = {}
            for g in st[0]:
                fc = [x[g]["first_cert_t"] for x in st if g in x]
                cert[g] = {
                    "certified_share": float(np.mean([v is not None for v in fc])),
                    "first_cert_day_median": (float(np.median([v for v in fc if v is not None]))
                                              if any(v is not None for v in fc) else None),
                    "restarts_mean": float(np.mean([x[g]["restarts"] for x in st if g in x])),
                }
            row["certification"] = cert
        if any("probe" in r for r in rs):
            p = defaultdict(int)
            for r in rs:
                for k, v in r.get("probe", {}).items():
                    p[k] += v
            row["probe"] = dict(p)
        out.append(row)
    return out


def _plots(rows: list[dict], agg: list[dict], out: Path, name: str) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    files = []
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    for a in agg:
        rs = [r for r in rows if r["arm"] == a["arm"]]
        x = [r["cost_vs_always"] for r in rs]
        y = [r["error_rate"] for r in rs]
        ax.scatter(x, y, s=10, alpha=0.35)
        ax.annotate(a["arm"], (np.mean(x), np.mean(y)), fontsize=7)
    alpha = agg[0]["alpha"] if agg else 0.05
    ax.axhline(alpha, ls="--", lw=1, color="grey")
    ax.set_xlabel("re-check cost (share of always re-checking)")
    ax.set_ylabel("stale answers per query")
    ax.set_title(f"{name}: cost against error (dashed: alpha)")
    fig.tight_layout()
    f = out / "frontier.png"
    fig.savefig(f, dpi=150)
    plt.close(fig)
    files.append(f.name)

    if rows and "daily" in rows[0]:
        fig, ax = plt.subplots(figsize=(6.5, 4.2))
        for a in agg:
            rs = [r for r in rows if r["arm"] == a["arm"]]
            d = np.nanmean(np.array([r["daily"]["error"] for r in rs], dtype=float), axis=0)
            k = 3
            sm = np.convolve(np.nan_to_num(d), np.ones(k) / k, mode="same")
            ax.plot(sm, label=a["arm"], lw=1.2)
        ax.axhline(alpha, ls="--", lw=1, color="grey")
        ax.set_xlabel("day")
        ax.set_ylabel("stale answers per query (3-day mean)")
        ax.legend(fontsize=7)
        fig.tight_layout()
        f = out / "daily_error.png"
        fig.savefig(f, dpi=150)
        plt.close(fig)
        files.append(f.name)
    return files


def report(run_dir: str, out_root: str = "results") -> Path:
    run_dir = Path(run_dir)
    name = run_dir.name
    rows = _load(run_dir)
    agg = aggregate(rows)
    out = Path(out_root) / name
    out.mkdir(parents=True, exist_ok=True)
    (out / "aggregate.json").write_text(json.dumps(agg, indent=1))
    with open(out / "summary.csv", "w", newline="\n") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["arm", "seeds", "alpha", "error_mean", "error_p95", "seeds_over_alpha",
                    "seeds_any_group_over_alpha", "cost_vs_always", "served_from_memory"])
        for a in agg:
            w.writerow([a["arm"], a["seeds"], a["alpha"], f"{a['error_mean']:.4f}",
                        f"{a['error_p95']:.4f}", f"{a['seeds_over_alpha']:.2f}",
                        f"{a['seeds_any_group_over_alpha']:.2f}", f"{a['cost_vs_always']:.3f}",
                        f"{a['served_from_memory']:.3f}"])
    figs = _plots(rows, agg, out, name)
    lines = [f"# {name}", "", f"{len(rows)} runs. Errors are stale or wrong answers per query "
             "after the burn-in; cost is re-checks as a share of always re-checking.", "",
             "| Arm | Seeds | Error (mean) | Error (95th pct) | Seeds over alpha | Seeds with a "
             "group over alpha | Cost vs always | Served from memory |",
             "|---|---|---|---|---|---|---|---|"]
    for a in agg:
        lines.append(f"| {a['arm']} | {a['seeds']} | {a['error_mean']:.4f} | "
                     f"{a['error_p95']:.4f} | "
                     f"{a['seeds_over_alpha']:.2f} | {a['seeds_any_group_over_alpha']:.2f} | "
                     f"{a['cost_vs_always']:.3f} | {a['served_from_memory']:.3f} |")
    groups = sorted({g for a in agg for g in a["group_error"]})
    if groups:
        lines += ["", "Error by provenance class (mean over seeds):", "",
                  "| Arm | " + " | ".join(groups) + " |", "|---|" + "---|" * len(groups)]
        for a in agg:
            lines.append(f"| {a['arm']} | " + " | ".join(f"{a['group_error'].get(g, 0):.4f}"
                                                         for g in groups) + " |")
    wins = [a for a in agg if "windows" in a]
    if wins:
        wn = list(wins[0]["windows"])
        lines += ["", "By time window (error mean / seeds with a group over alpha / cost):", "",
                  "| Arm | " + " | ".join(wn) + " |", "|---|" + "---|" * len(wn)]
        for a in wins:
            cells = [f"{a['windows'][w]['error_mean']:.4f} / "
                     f"{a['windows'][w]['seeds_any_group_over_alpha']:.2f} / "
                     f"{a['windows'][w]['cost_vs_always']:.3f}" for w in wn]
            lines.append(f"| {a['arm']} | " + " | ".join(cells) + " |")
    certs = [a for a in agg if "certification" in a]
    if certs:
        lines += ["", "Certification by group (share of seeds certified / median day of first "
                  "certificate / alarms per run):", ""]
        gs = sorted({g for a in certs for g in a["certification"]})
        lines += ["| Arm | " + " | ".join(gs) + " |", "|---|" + "---|" * len(gs)]
        for a in certs:
            cells = []
            for g in gs:
                c = a["certification"].get(g)
                if c is None:
                    cells.append("")
                    continue
                fc = c["first_cert_day_median"]
                d = "-" if fc is None else f"{fc:.1f}"
                cells.append(f"{c['certified_share']:.2f} / {d} / {c['restarts_mean']:.1f}")
            lines.append(f"| {a['arm']} | " + " | ".join(cells) + " |")
    probes = [a for a in agg if "probe" in a]
    if probes:
        lines += ["", "LLM agent probe (what the agent would have done on its own):", "",
                  "| Arm | Probed | Answered from memory | Stale answers | Needless checks |",
                  "|---|---|---|---|---|"]
        for a in probes:
            p = a["probe"]
            lines.append(f"| {a['arm']} | {p.get('n', 0)} | {p.get('answered', 0)} | "
                         f"{p.get('stale_answers', 0)} | {p.get('needless_checks', 0)} |")
    lines += [""] + [f"![{f}]({f})" for f in figs]
    (out / "README.md").write_text("\n".join(lines) + "\n")
    print(f"wrote {out}/README.md")
    return out
