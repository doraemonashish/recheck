# Theory

This file states what the code guarantees and what it does not. Section numbers are cited from
docstrings. The proofs are short because the tools are standard (the Neyman–Pearson lemma,
Learn-then-Test, testing by betting, Ville's inequality, inverse-propensity weighting and
prediction-powered inference). The contribution is in how they are put together for agent memory,
and in two facts that make the combination necessary: serving from memory changes the
distribution being certified (Proposition 2.1), and a guarantee for each provenance class has a
minimum price in labels (Proposition 7).

## 1. Setting

An agent answers a stream of queries t = 1, 2, .... Query t asks for the current value of a slot
(a branch head, a ticket status, a price, a user's preference) or for a value derived from
several slots. Memory holds a belief b_t for it: a value, the time it was observed and its
provenance class G_t (observed by the agent, delegated to a subagent, stated by the user,
notified by a webhook, inferred by the agent, quoted from pasted content). The world changes, so
the belief may be stale: Y_t = 1 if b_t differs from the truth now.

The agent has two options. Serving from memory is free but wrong when Y_t = 1. Re-checking
(calling the tool, asking the user, re-deriving) costs c_t > 0 and is always right. A sleep step
between sessions fits a staleness score s_t in [0, 1] from the memory's own re-observations
(Section 6); an optional judge (an LLM or a System One model) gives J_t in [0, 1].

The deployed rule for a threshold theta serves when s_t <= theta, and even then audits (re-checks
anyway) with probability pi_t = pi(J_t) >= pi_min, drawn by the agent independently of Y_t given
everything it has seen. Its loss and risk at step t are

    L_t(theta) = 1{s_t <= theta} (1 - A_t) Y_t,
    r_t(theta) = E[ 1{s_t <= theta} (1 - pi_t) Y_t | F_{t-1} ],

where F_{t-1} is the history before query t. The risk is the rate of wrong answers the deployed
system gives. It is nondecreasing in theta.

The goal is to serve as much as possible while keeping r_t(theta) <= alpha, with a guarantee
that holds when the world drifts and when the judge is wrong, separately for every provenance
class.

## 2. Thresholds are the right rules, and batch calibration is not enough

**Theorem 1 (optimal rules).** Fix a distribution over queries with staleness probability
p(x) = P(Y = 1 | x) and re-check cost c(x) > 0. Among randomised rules phi(x) in [0, 1] (serve
with probability phi) with risk E[phi(X) p(X)] <= alpha, expected re-check cost
E[(1 - phi(X)) c(X)] is minimised by phi*(x) = 1{p(x)/c(x) < k}, randomised on the boundary,
with k chosen so the risk constraint binds.

*Proof.* Minimising cost is maximising E[phi c] subject to E[phi p] <= alpha: a fractional
knapsack in which item x has value c(x) and weight p(x). Taking items in increasing order of
p/c until the weight budget is spent is optimal (the Neyman–Pearson lemma with p as the null
density and c as the alternative). ∎

With equal costs within a class and a score that orders beliefs like p does, the optimal rule is
a threshold on the score. The code thresholds s within each provenance class; thresholding
s / c is the same certificate on a different score.

**Theorem 2 (batch certificate; Angelopoulos et al., Learn-then-Test).** Take n calibration
queries drawn i.i.d. from a distribution D, all re-checked. For each theta on an ascending grid
let k(theta) count the served-and-stale queries and p(theta) = P(Binomial(n, alpha) <= k(theta)).
Testing the grid from the smallest theta upward and stopping at the first p(theta) > delta gives
a threshold theta_hat with P_D(R_D(theta_hat) > alpha) <= delta. (`certify/ltt.py`)

*Proof.* Under H0(theta): R_D(theta) >= alpha, k(theta) is stochastically at least
Binomial(n, alpha), so p(theta) is a valid p-value. The null set is upward closed because R is
monotone, so fixed-sequence testing controls the family-wise error at delta with no correction. ∎

**Proposition 2.1 (serving changes what was certified).** The guarantee in Theorem 2 is about D,
the distribution of beliefs during calibration. Calibration re-checks every query, which keeps
beliefs fresh; deployment serves, which lets them age. The deployed distribution D'(theta_hat)
depends on the certified threshold itself (a performative shift), and R_{D'}(theta_hat) can
exceed alpha with probability tending to one.

*Example.* One slot whose value changes at rate h, queried at rate q, and an uninformative score
(constant). During calibration every query re-checks, so a belief is as old as the gap between
queries and P(stale) = h / (h + q). If h / (h + q) < alpha, Learn-then-Test certifies "always
serve". Deployed, nothing is re-checked again and P(stale) tends to one. A hazard-based score
softens this but does not remove it: the score is fitted on fresh beliefs and is miscalibrated
exactly where deployment pushes the beliefs. Experiment E1 measures the effect (`ltt-batch`).

## 3. Online certification with audits and judges

The certifier (`certify/online.py`) keeps one test per threshold on a grid
theta_1 < ... < theta_m and updates all of them on every query, including thresholds it is not
deploying.

**Labels.** If the policy re-checked query t (nothing certified yet, or s_t above the certified
threshold), Y_t is observed and

    Z_t(theta) = 1{s_t <= theta} (1 - pi(J_t)) Y_t,

with pi(J_t) the audit probability the query would have had if served. If it served,

    Z_t(theta) = 1{s_t <= theta} (1 - pi_t) ( J~_t + (A_t / pi_t)(Y_t - J~_t) ),

where J~_t = J_t when the judge is used for rectification and 0 otherwise.

**Lemma 3.1 (unbiased whatever the judge says).** E[Z_t(theta) | F_{t-1}] = r_t(theta).

*Proof.* Whether query t is served is a function of s_t and the certified threshold, which is
F_{t-1}-measurable. If it is re-checked, Z_t(theta) is the loss itself. If it is served,
condition on (F_{t-1}, s_t, J_t, Y_t): A_t is Bernoulli(pi_t) independent of Y_t, so
E[(A_t/pi_t)(Y_t - J~_t)] = Y_t - J~_t and the bracket has mean Y_t. In both cases the
conditional mean is 1{s_t <= theta}(1 - pi_t) Y_t. Taking expectations given F_{t-1} gives
r_t(theta). Nothing about J_t was used: it may be miscalibrated, biased by class, or adversarial. ∎

**Lemma 3.2 (a range known in advance).** Z_t(theta) lies in [l_t, u_t] with l_t, u_t fixed by
F_{t-1}: [0, 1] before anything is certified, and afterwards
[-(1 - pi_min)^2 / pi_min, max(1, (1 - pi_min) / pi_min)] with a judge, lower end 0 without one.
The bound uses pi_min, not the current query's pi_t, because the bet may not depend on the
current query (Remark 3.4).

*Proof.* (1 - pi)/pi decreases in pi; with J~ in [0, 1] the served label is at least
(1 - pi) J~ (1 - 1/pi) >= -(1 - pi)^2 / pi. ∎

**Theorem 3 (anytime-valid certification).** For each theta let

    W_t(theta) = (1/K) sum_k prod_{i <= t} (1 + c_k lambda_i (alpha - Z_i(theta))),

with lambda_i in [0, 1/(u_i - alpha)] chosen from F_{i-1} (an aGRAPA-style estimate) and
fractions c_k in (0, 1] (the code uses 0.5 and 0.95). Certify theta_j at the first time W(theta_1),
..., W(theta_j) have all reached 1/delta. Then

    P( some theta is ever certified while r_t(theta) >= alpha for all t ) <= delta.

*Proof.* Under H0(theta): r_t(theta) >= alpha for every t, each factor has conditional mean
1 + c_k lambda_t (alpha - r_t(theta)) <= 1 (Lemma 3.1) and is nonnegative (Lemma 3.2), so each
product is a nonnegative supermartingale with initial value 1, and so is their average. Ville's
inequality gives P(sup_t W_t(theta) >= 1/delta) <= delta. Because r_t is monotone in theta, the
null thresholds form an upward-closed set; certifying any of them requires first certifying the
smallest, which happens with probability at most delta. ∎

**Remark 3.3 (what a certificate says when the world drifts).** H0(theta) is "theta is unsafe at
every step". Rejecting it under stationarity means r(theta) < alpha. Under drift it means less,
which is why the certificate is monitored (Section 4). Experiment E0 checks Theorem 3 directly on
streams where the true risk of every threshold is known; E4 checks the monitored version.

**Remark 3.4 (why the bet ignores the current query).** It is tempting to bet more on queries
whose label range is small, for example re-checked ones, whose loss is at most 1. The bet would
then depend on s_t, and the product is a supermartingale only under the much stronger null that
the risk is at least alpha conditionally on every score value. An earlier version of this code
did that; the range now depends on the past alone.

**Proposition 3.5 (what judges buy).** Given the history and the features, the conditional
variance of a served label is (1 - pi)^3 (Y - J~)^2 / pi: zero when the judge is right. This
lowers the variance of the bet but not its range, so a judge used only for rectification
certifies little faster (E1, E3). A judge that *directs* audits, pi(J) = min(1, pi_min + g J),
changes the risk itself: a stale belief the judge flags is audited, hence re-checked, before it
is served. Then r_t(theta) = E[1{s <= theta}(1 - pi(J)) Y], which is small where the judge
is sharp, and the certificate raises the threshold to use the saving. Where the judge is blind
(a class whose stale beliefs it misses), pi stays near pi_min, the risk stays high and the
certificate holds the threshold down. The guarantee never depends on the judge; the cost does.

## 4. Drift: alarms and restarts

After a threshold is certified, a detector watches the served set for risk above alpha. The code
uses a CUSUM-style e-detector (Shin, Ramdas and Rinaldo): for a few bet fractions f,

    log M_t = max(log M_{t-1}, 0) + log(1 + f g_max (Z_t - alpha)),

and alarms when the largest M_t reaches (number of fractions)/delta_alarm. Under the null that the
risk stays at most alpha, the expected time to a false alarm is at least that threshold, and the
max with zero means a long safe stretch does not have to be paid back before a change shows.

**Proposition 4 (restarts keep the guarantee).** On an alarm the certifier discards every test and
starts epoch r + 1 with level delta_r = delta / (r (r + 1)). The probability of any false
certificate over all epochs is at most sum_r delta_r = delta.

*Proof.* The epoch-r tests start at a stopping time; conditional on the past they are
supermartingales under the epoch's null, so Theorem 3 applies to each epoch at its own level. A
union bound over epochs gives the sum, and sum_r 1/(r(r+1)) = 1. False alarms only cost
re-checks. ∎

## 5. One guarantee per provenance class

**Theorem 4 (class-conditional certificates).** Run one certifier per class g in G at level
delta_g, with sum_g delta_g <= delta (the code uses delta/|G|), each fed only the queries of its
class. With probability at least 1 - delta, no class is ever falsely certified, simultaneously
for every class.

*Proof.* Whether query t belongs to class g is known before Y_t, so each class's subsequence of
factors is a supermartingale in its own filtration (optional skipping). Theorem 3 holds for each
class at delta_g; a union bound finishes. ∎

**Why pooling is not enough.** A pooled certificate controls the mixture sum_g w_g r^g <= alpha,
which allows a class with weight w_g to have risk up to min(1, alpha / w_g). Subagent reports,
notifications and pasted content are small classes, and they are exactly the ones whose errors do
not show in the age of a belief: a subagent that misread a page is wrong at age zero. E1 and E7
show pooled certificates meeting alpha on average while one class fails on most seeds.

**Proposition 7 (the price of a class guarantee).** Suppose labels in a class are fully observed.
Any procedure that, for every i.i.d. stream, falsely certifies with probability at most delta_g
needs at least

    n_min = ceil( log(1/delta_g) / log(1/(1 - alpha)) )

labelled queries from the class before it can certify any threshold that serves, even when every
label is clean.

*Proof.* Compare the stream with risk exactly alpha to the clean stream. Whatever the procedure
does on its first n labels, it sees all zeros under the null with probability (1 - alpha)^n, and
then it behaves as it does on the clean stream. If it certifies on the clean stream after n
labels, it certifies falsely with probability at least (1 - alpha)^n, which exceeds delta_g when
n < n_min. ∎

At alpha = 0.05 and delta_g = 0.01 (five classes sharing delta = 0.05), n_min = 90. The mixture
e-process certifies a clean class after 128 labels; with a single stake of 0.5 it needs 194
(`tests/test_eprocess.py`). Rare classes are therefore re-checked until they have earned their
labels. That is the cost of a guarantee per class, and Proposition 7 says no method avoids it.

## 6. The memory: what the score is built from

**Inferred beliefs (Theorem 5).** An inference keeps its justification: the premise slots and
their values when it was made. It is retracted as soon as any premise's current belief differs
(justification-based truth maintenance), so a served inference is stale only if some premise has
changed in the world since it was last observed. Hence

    max_i P(premise i changed) <= P(inference stale) <= min(1, sum_i P(premise i changed)),

and both bounds are attained by some dependence between the premises (the Fréchet bounds), so
the Boole sum is the tightest bound valid without assuming independence. Under independence the
bound is 1 - prod_i (1 - P(premise i changed)). A premise change that does not change the derived
value makes either bound conservative, never invalid. A store that "launders" inferences into
plain facts loses the premise list, so neither retraction nor the bound is available (E5).

**Change rates (Proposition 6).** Each re-observation of a slot gives a pair (d, changed): the
value survived d days, or changed within d days. Under a constant hazard h per kind the
log-likelihood is

    l(h) = - h sum_{unchanged} d_i + sum_{changed} log(1 - exp(-h d_i)),

and d^2/dh^2 log(1 - e^{-hd}) = - d^2 e^{-hd} / (1 - e^{-hd})^2 < 0, so l is strictly concave
whenever some pair changed. A Gamma(a, b) prior with a >= 1 adds a concave term, so the MAP rate
is unique. The prior is centred on the rate pooled over kinds (empirical Bayes), which keeps
rarely observed kinds from extreme rates. With `per_slot`, each slot gets its own rate under a
Gamma prior centred on its kind's rate: a three-level hierarchy (pool, kind, slot) that lets a
package that releases daily and one that releases twice a year share a kind without sharing a
rate (E11). Real release times are bursty, not exponential, so the model is misspecified there.
The certificate does not need the rates to be right; a wrong rate only costs re-checks.

**Observation-time ordering (Proposition 8).** Suppose values never recur (a change always moves
to a value the slot has not had). If two observations of a slot were made at t1 < t2 and the one
from t1 is current at time t, the one from t2 is current too: v(t1) = v(t) means there was no
change in (t1, t], so none in (t2, t]. Keeping the observation with the later *observation* time
therefore dominates path by path. A store ordered by *arrival* lets a subagent's late report of
an old observation replace a newer one, and if it also dates beliefs by arrival, the old value
looks fresh to the score (E6).

## 7. What is not claimed

- The world is simulated. The simulator's change processes, provenance error rates and query mix
  are choices; the configs make them explicit, and the guarantees in Sections 3 to 5 do not
  depend on them. The costs do.
- Theorem 3 is about the stated null. Under arbitrary drift a certificate says less than under
  stationarity (Remark 3.3); the detector bounds how long a drifted certificate stays in force
  in practice, not in theory.
- The audit probability must be truly random and independent of staleness given what the agent
  has seen. An agent that "audits" when it already suspects the answer is wrong breaks Lemma 3.1
  unless the suspicion is the judge J and the audit probability is a function of it.
- Labels from re-checks are assumed correct. A tool that itself returns stale data is a different
  problem (it moves the error into the tool).
