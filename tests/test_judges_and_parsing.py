from recheck.agents.laya_judge import _p_true
from recheck.agents.llm import parse_probability


def test_laya_answer_parsing():
    assert _p_true(0.8) == 0.8
    assert _p_true({"noul": 0.3}) == 0.3
    assert _p_true({"label": "yes", "p_true": 0.7}) == 0.7
    assert _p_true({"something_else": 0.4}) == 0.4
    assert _p_true({"flag": True}) is None
    assert _p_true("yes") is None


def test_llm_probability_parsing():
    # the prompt asks for a number from 0 to 100
    assert parse_probability('{"p_changed": 20}') == 0.2
    assert parse_probability('{"p_changed": "35"}') == 0.35
    assert parse_probability("I would say 90") == 0.9
    assert parse_probability("{}") is None
    assert parse_probability('{"p_changed": 700}') == 1.0
