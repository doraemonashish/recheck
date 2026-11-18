# Paper plan

Working title: **Trust, but Re-check: Certified Memory Reuse for Agents in a Changing World.**

## 1. Thesis

Agent memory is a cache of beliefs about a world that changes without notice. The question that
matters for agents is not whether memory retrieves the right fact but whether a retrieved fact
may be reused or must be re-checked. We give a read policy with an anytime-valid guarantee on the
rate of stale answers, per provenance class, that survives drift and judges of any quality, and
we show that the obvious alternative, calibrating once, is invalid for memory because serving
from memory changes the distribution that was calibrated.

## 2. Contributions, as built

1. **Problem.** Memory reuse as risk-controlled caching over beliefs with provenance (observed,
   delegated, stated, notified, inferred, quoted) and two clocks (observation and arrival).
   Thresholds on staleness per unit cost are optimal (THEORY Theorem 1).
2. **A negative result.** Batch calibration (Learn-then-Test, split conformal) is invalid for
   memory reuse: calibration keeps beliefs fresh, deployment lets them age (Proposition 2.1).
   Measured: 20/20 simulated runs and 8/8 real-trace windows over alpha.
3. **The certificate.** One betting e-process per threshold and provenance class, labelled by
   randomized audits; prediction-powered rectification makes any judge safe to use; judge-directed
   audits turn judge quality into lower cost without touching validity; a CUSUM e-detector with
   restart budgets delta/(r(r+1)) handles drift (Theorems 3 and 4, Proposition 4).
4. **What a class guarantee costs.** A lower bound on labels per class for any valid method
   (Proposition 7: 90 at alpha 0.05 with five classes) and an e-process within 1.5x of it.
5. **Memory design that the certificate needs.** Observation-time ordering (Proposition 8),
   justification-tracked inferences with the Boole bound (Theorem 5), quoted content kept out of
   beliefs, and a sleep that fits change rates by pool, kind and slot (Proposition 6).
6. **An agent-era testbed.** A simulator with subagents, notifications, injected content, derived
   facts and drift; real change traces from PyPI; LLM (Ollama) and System One (Laya) judges, all on
   free hardware.

## 3. Evidence so far (README has the tables)

| Claim | Status |
|---|---|
| Valid per class where batch, pooled and fixed rules are not | E1 (sim, 20 runs), E7 (injection), E11 (real traces): done |
| Cheaper than ACI, the strongest online heuristic | E1, E2, E11: done (0.39 vs 0.43; 0.37 vs 0.41; 0.34 vs 0.40) |
| Judges: safe when wrong, useful when directing audits | E3 (synthetic judges), E0 (adversarial): done. Real judges: E9, E10, E12, E13 to run |
| Drift handled by monitoring | E4: done (1/10 vs 7/10 runs over after the change) |
| Memory design choices matter | E5, E6, E7: done; effects are real but modest under certification |
| Guarantee is tight in practice | E0: done (0–1% false certificates at delta 0.1) |
| Chatbot regime is the easy special case | E8: done |

Honest weak spots in the current evidence:

- A staleness threshold tuned in hindsight for one world beats the certificate on cost by 15–30%
  (E2). The argument is that nothing tells you the right threshold in advance (the same threshold
  fails in other worlds), but a reviewer will push on it. Present it as the price of a guarantee
  and show the oracle explicitly.
- PPI rectification alone barely helps (E1, E3); the gain comes from directed audits. Say so.
- Justified inferences cost about the same as laundered ones once certified (E5). The case for
  justifications is the uncertified regime and the honesty of class-level guarantees.
- Rare classes (user statements, notifications) are re-checked for most of a run. Proposition 7
  says this is unavoidable for a per-class guarantee; consider an optional hierarchical mode with a
  weaker, clearly stated guarantee.

## 4. What is still missing for a main-track paper

In order of how much each moves the odds:

1. **Real models in the loop (E9, E10, E12, E13).** Run the notebooks. The headline needed: a real
   LLM or Laya judge, used to direct audits, lowers cost at the same guarantee; trusted outright,
   it breaks the guarantee in some class. Also the agent probe: how often does an LLM agent serve
   stale values on its own, and does a certificate in context change that?
2. **More real traces.** E11 uses real change times but simulated events around them. Add two
   sources with different dynamics, both free: GitHub (default-branch heads and issue states of
   ~100 repositories from the REST API or GH Archive) and Wikidata (office holders, CEOs, software
   versions with their edit times). Same pipeline: `world/traces.py`.
3. **A downstream agent task.** A small SWE-style or tool-use benchmark where stale memory causes
   task failure (wrong version pinned, wrong branch), to show the metric matters for success
   rate, not only for answer accuracy.
4. **Memory-system baselines.** Mem0-style (LLM-decided update, arrival order), Zep/Graphiti-style
   (bi-temporal edges, invalidation on conflict) and MemGPT/Letta-style (agent-managed). They are
   storage policies; the certificate wraps any of them. Implement their read rules in the
   simulator and, if time allows, run one through its API.
5. **Writing.** Lead with the negative result and the guarantee; keep the simulator in the
   appendix; one figure per claim.

## 5. Related work to position against

- Conformal risk control, Learn-then-Test, and online conformal (Angelopoulos, Bates et al.;
  Gibbs and Candès's adaptive conformal inference). We differ by anytime validity, per-class
  guarantees, labels from randomized audits, and the performative-shift result.
- Testing by betting and e-processes (Waudby-Smith and Ramdas; Shafer and Vovk; Ramdas et al.),
  e-detectors for change detection (Shin, Ramdas and Rinaldo).
- Prediction-powered inference and active statistical inference (Angelopoulos, Zrnic, Candès).
- Performative prediction (Perdomo et al.): serving from memory is a performative decision.
- Agent memory: MemGPT/Letta, Mem0, Zep/Graphiti, A-MEM, generative-agent memory streams; and
  benchmarks LongMemEval, LoCoMo and newer agent-memory benchmarks. They score retrieval; none
  certifies reuse.
- Truth maintenance (Doyle's JTMS) and cache consistency (TTLs, leases, adaptive TTL in CDNs and
  DNS): the systems lineage of the question.
- Knowledge editing and temporal QA (facts that change over time): related evaluation questions,
  different mechanism.

Before submission, search again for 2026 work on certified or calibrated agent memory and
memory staleness; the area moves quickly.

## 6. Venues and timing

- ICML 2027 (deadline late January 2027) is tight but possible if items 1 and 2 of §4 are done by
  mid-January.
- NeurIPS 2027 (deadline around May 2027) is the realistic main-track target with all of §4.
- A strong workshop version (agents, memory, or uncertainty workshops) is possible now.

Check each call for papers for exact dates and page limits.

## 7. Odds, honestly

As it stands (theory plus simulator plus one real-trace experiment, no real models yet): a good
workshop paper; a main-track submission would likely be rejected for the simulator and the missing
real-model results, perhaps 10–20%.

With §4 items 1 and 2 done and clean writing: a solid main-track submission, perhaps 30–40%, in
line with a good paper at a selective venue. With items 3 and 4 as well: 40–50%. Nothing pushes
this to "very likely"; acceptance at these venues is noisy for every paper. The parts that are
genuinely new and defensible are the performative-shift result, the per-class anytime guarantee
with judge-directed audits, and the lower bound.

## 8. Compute

Everything above runs on free hardware: the CPU experiments in about twenty minutes, the model
experiments on a Colab or Kaggle T4 in one to two hours each. A downstream agent benchmark with a
hosted model would be the first thing that costs money.
