# recheck

**Trust, but re-check: certified memory reuse for agents in a changing world.**

An agent's memory is a cache of beliefs about a world that keeps changing without telling it:
branch heads move, tickets close, prices change, a subagent's report is two days old by the time
it lands, a pasted document asserts something nobody checked. Every time the agent reads memory
it makes a bet that the value is still current. Chatbot-era memory benchmarks (LongMemEval,
LoCoMo) ask whether the right fact is retrieved. For agents the harder question is whether a
retrieved fact may be *reused* or must be re-checked with a tool call.

This repository answers that question with a guarantee. A read policy serves from memory only
when a certificate says that the rate of stale answers in that class of memory is below alpha.
The certificate holds at every moment of the run, under drift, with noisy LLM or System One
judges, and separately for each provenance class (observed, delegated to a subagent, stated by
the user, notified, inferred, quoted).

## Results so far (CPU: simulator and real PyPI traces)

Ten simulated worlds or more per experiment (sixty days each), plus eight one-year windows of
real PyPI release history; alpha = 0.05. "Class over alpha" is the share of runs in which at
least one provenance class had a stale-answer rate above alpha. Cost is re-checks as a share of
always re-checking. Full tables and plots are in `results/`.

| Finding | Evidence |
|---|---|
| On real change traces the certificate holds and is the cheapest valid rule. | E11, "latest version of package X" for ~150 PyPI packages, real upload times, eight one-year windows: certified with a change rate per package costs 0.34 with 0/8 runs over. ACI 0.40, a per-package staleness threshold 0.39, 1-day TTL 0.52, all 0/8; 3- and 7-day TTLs 8/8 over; batch Learn-then-Test serves 97% and is wrong 19% of the time. Never re-checking: 23%. |
| The certificate holds in every class; batch calibration does not. | E1, 20 worlds: certified 0/20 runs with a class over alpha at cost 0.39. Learn-then-Test calibrated once: 20/20 (performative shift, THEORY §2). Pooled certificate: 15/20. |
| It is cheaper than the strongest heuristic that adapts online. | E1: adaptive threshold (ACI-style) per class at alpha = 0.05 costs 0.43 with 1/20 runs over; pooled ACI 19/20 over. |
| A judge that directs audits cuts cost and errors, and the guarantee survives a blind judge. | E3: a judge that misses 90% of stale subagent reports, used to direct audits: errors 0.0042 (from 0.0195), cost 0.28 (from 0.40), 0/10 runs over. Trusting the same judge outright: 10/10 over; certifying with it as the label: 9/10 over. |
| Monitoring catches drift. | E4, change rates ×6 at day 30: after the change, monitored certificate 1/10 runs over, the same certificate without the detector 7/10, ACI 3/10, batch 10/10. |
| Provenance contains injected content. | E7, 30 pasted claims a day in a provenance-blind store: every pooled rule (certificate, ACI, hazard threshold) serves them, 10/10 runs over; per-class certification keeps 0/10, and a store that tracks provenance costs about 20% less than a blind one. |
| Observation-time ordering matters for subagents. | E6: ordering by observation time instead of arrival is 9% cheaper and halves stale subagent answers at the same guarantee. |
| The guarantee is exactly as valid as the theory says. | E0, 200 streams with known risk per variant: 0–1% false certificates at delta = 0.1 for every valid variant, including an adversarial judge; the judge-only baseline 100%. |
| A guarantee per class has a price, and it is close to the minimum. | Proposition 7: no valid method certifies a class before ~90 clean labels (alpha 0.05, five classes). Ours needs 128. Rare classes are re-checked until then. |

What the guarantee costs is visible in E2: a staleness threshold tuned in hindsight for one world
reaches the same error 15–30% cheaper, but the right threshold differs from world to world
(the same threshold has a class over alpha in 1/10 runs in one world and 4/10 in another, E2
and E7) and
nothing tells you which one you are in. E8 is the chatbot special case: facts change slowly, a
7-day time-to-live is cheap and usually fine, and certification costs more than it buys. That is
the point of the agent-era setting: never re-checking is wrong 9% of the time in E8 and 34% in E1.

Not yet run: E9 and E12 (an LLM through Ollama as judge and as an agent deciding for itself, on
the simulator and on the PyPI traces) and E10 and E13 (Laya as a System One judge, same two
worlds). They need a GPU and run on a free Colab or Kaggle T4 from the notebooks below.

## Quickstart

```bash
pip install -e ".[dev]"
recheck demo                              # one world, five policies, printed (seconds)
recheck run configs/e1_validity.yaml      # runs/ and results/e1_validity/ (about two minutes)
recheck all                               # E1 to E8 and E11 (about twelve minutes on two cores)
python scripts/validity_sim.py            # E0, the direct check of Theorem 3 (about six minutes)
pytest -q                                 # 31 tests
```

## Free GPUs: Ollama and Laya

| Notebook | Where | What it runs |
|---|---|---|
| `notebooks/01_quickstart.ipynb` | Colab or Kaggle, CPU | E0 to E8, E11 |
| `notebooks/02_ollama.ipynb` | Colab or Kaggle, T4 | E9 and E12: `qwen2.5:3b` (or `qwen2.5:7b`) through Ollama as staleness judge and as an agent probe, about an hour |
| `notebooks/03_laya.ipynb` | Kaggle or Colab, T4 | E10 and E13: Laya as a System One staleness judge |

Each notebook clones the repository (set `REPO` in the first cell) or unzips `recheck.zip` if you
upload it, installs it, runs the experiment and zips `runs/`, `results/` and `cache/`. On Kaggle
turn on the T4 and Internet in the notebook settings. Every LLM call is cached in
`cache/llm_cache.sqlite`; with `RECHECK_OFFLINE=1` a rerun replays the cache exactly and fails on
anything not in it. Any OpenAI-compatible endpoint works: set `RECHECK_LLM_BASE` and
`RECHECK_LLM_MODEL`.

Laya: `pip install laya`, then `python scripts/laya_smoke.py --device cuda` prints a raw answer,
the parsed probability for a fresh and an old belief, and the time per call. The judge uses the
general English checkpoint; the `typed-decisions` checkpoint is tuned for four fixed workflows and
is not meant for this question.

## How it works

```
events (tool results, subagent reports, user statements, notifications, pasted text)
   |
   v
memory (memory/store.py)        append-only log; belief = latest *observation* per slot;
                                quoted text never becomes a belief; inferences keep their premises
   |   sleep: refit change rates from re-observations, per kind and optionally per slot
   |          (pooled -> kind -> slot empirical Bayes, memory/hazards.py)
   v
score s = estimated P(stale)    hazard model, Boole bound over premises for inferences
   |
   v
read policy (policies.py)       certified: serve iff s <= certified threshold of the belief's
                                class; audit served answers at random; judge J optional
   |
   v
certificate (certify/)          one betting e-process per threshold and class, fed by re-checks
                                and audits (prediction-powered when a judge is used);
                                CUSUM e-detector; restart on alarm at delta/(r(r+1))
```

`THEORY.md` has the statements and proofs: optimality of thresholds (Theorem 1), why batch
calibration fails for memory (Proposition 2.1), anytime validity with audits and arbitrary judges
(Theorem 3), restarts (Proposition 4), class-conditional guarantees (Theorem 4), the label lower
bound (Proposition 7), the Boole bound for inferences (Theorem 5), concavity of the change-rate
fit (Proposition 6) and dominance of observation-time ordering (Proposition 8).

## Experiments

| Config | Question |
|---|---|
| `e1_validity` | Does each method keep every provenance class under alpha? |
| `e2_frontier` | What does the guarantee cost against tuned thresholds, TTLs and ACI; which audit rate? |
| `e3_judges` | Calibrated, noisy and class-biased judges: rectify, direct audits, or trust? |
| `e4_drift` | Change rates jump at day 30: who notices? |
| `e5_inferences` | Inferences with justifications against inferences stored as plain facts |
| `e6_subagents` | Late subagent reports: observation-time against arrival-time ordering |
| `e7_injection` | Pasted, untrusted claims in a provenance-blind store |
| `e8_chatbot` | The chatbot special case: slow facts that only the user can confirm |
| `e9_llm_ollama` | An LLM as judge and as an agent deciding for itself (needs a model) |
| `e10_laya` | Laya as a System One judge (needs a model) |
| `e11_pypi` | Real change traces: the latest release of ~150 PyPI packages over 2021–2023 |
| `e12_pypi_llm` | The LLM judge on the real traces (needs a model) |
| `e13_pypi_laya` | Laya on the real traces (needs a model) |
| `scripts/validity_sim.py` | E0: false-certificate rate on streams with known risk |

Every arm in a config runs on the same world for a given seed. A config is a world, seeds and
arms (policy, judge, memory options); see `configs/e1_validity.yaml`.

## Layout

```
src/recheck/
  types.py            provenance classes, events, queries, beliefs
  world/              the changing world: kinds of fact, renewal processes, subagents, drift;
                      traces.py builds a world from real PyPI release histories
  memory/             the store (ordering, provenance, justifications) and the change-rate fit
  certify/            Learn-then-Test, betting e-processes, the online certifier
  policies.py         certified, ACI, batch LTT, hazard and judge thresholds, TTL, always/never
  agents/             judges (simulated, LLM via Ollama, Laya), the LLM agent probe
  eval/               runner, metrics, experiments from YAML, reports and plots
configs/              E1 to E13
data/                 PyPI release histories (pypi_releases.json.gz, from fetch_pypi_traces.py)
scripts/              validity_sim.py (E0), laya_smoke.py, fetch_pypi_traces.py
notebooks/            Colab and Kaggle
results/              tables and plots from the runs above
tests/
THEORY.md             statements and proofs
PAPER_PLAN.md         the paper this is meant to become, and what is still missing
```

## Limitations

Most worlds are simulated. The guarantees do not depend on the simulator; the costs and the size
of every effect do. E11 replaces the simulated change process with real release histories, but
what the memory is told around them (subagent reports, pasted claims, notifications, queries) is
still simulated; PAPER_PLAN §4 lists what a fuller real-data evaluation needs. Audits must be
genuinely random. Re-checks are assumed to return the truth. Under arbitrary
drift a certificate says less than under stationarity (THEORY Remark 3.3); the detector limits
how long a drifted certificate stays in force in practice.

## License

MIT.
