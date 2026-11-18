from recheck.agents.judges import BiasedJudge, Judge
from recheck.certify.online import CertifierConfig
from recheck.eval.metrics import summarize
from recheck.eval.runner import RunConfig, run
from recheck.policies import TTL, AlwaysRecheck, Certified, JudgeThreshold, NeverRecheck
from recheck.world.sim import generate


def test_always_recheck_is_never_wrong_and_never_recheck_is_free():
    ep = generate({"days": 6, "queries_per_day": 80}, seed=0)
    a = summarize(run(ep, AlwaysRecheck(), Judge()))
    n = summarize(run(ep, NeverRecheck(), Judge()))
    assert a["error_rate"] == 0.0
    assert n["served_from_memory"] > 0.8
    assert n["error_rate"] > a["error_rate"]


def test_certified_policy_runs_and_reports_state():
    ep = generate({"days": 8, "queries_per_day": 100}, seed=1)
    res = run(ep, Certified(CertifierConfig(alpha=0.1)), Judge(), RunConfig())
    s = summarize(res, after=2, alpha=0.1)
    assert 0.0 <= s["error_rate"] <= 1.0
    assert "observed" in res.state and "threshold" in res.state["observed"]


def test_judge_threshold_trusts_a_blind_judge():
    ep = generate({"days": 8, "queries_per_day": 100, "subagent_error": 0.3,
                   "subagent_reports_per_day": 60}, seed=2)
    j = BiasedJudge(eps=0.01, soft=0.01)
    s = summarize(run(ep, JudgeThreshold(0.5), j), after=2, alpha=0.05)
    assert s["by_group"]["delegated"]["error_rate"] > 0.05


def test_ttl_name():
    assert TTL(0.5).name == "ttl-0.5d"
