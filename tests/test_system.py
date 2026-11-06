"""Integration tests on the real snapshots: key answers, determinism, latency, contract shape."""
import re
import time

import pytest

CASES = [
    ("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?", None, ["5.39%"], ["5.34%"]),
    ("Can you tell me the interest rate for a 30-year mortgage?", None, ["7.13", "7.25"], ["6.037%"]),
    ("What was the rate on the 10-month jumbo certificate special as of May 2026?", "2026-05-31", ["3.90%"], ["4.00%"]),
    ("How many branches does Dupaco have?", None, ["22"], ["24 branch"]),
    ("What recognition has Dupaco received from Forbes?", None, ["fifth"], ["fourth"]),
    ("Provide current checking account interest rates", None, ["2.50%"], ["3.00%"]),
    ("What is Dupaco's routing number?", None, ["273974581"], []),
    ("When does the Hy-Vee branch close?", None, ["March 31, 2026"], []),
]


@pytest.mark.parametrize("q,as_of,must,must_not", CASES)
def test_key_answers(real_system, q, as_of, must, must_not):
    a = real_system.answer(q, as_of)
    for m in must:
        assert m in a.text, a.text
    for m in must_not:
        assert m not in a.text, a.text


@pytest.mark.parametrize("q", ["What is your rate on a 7/1 adjustable-rate mortgage?",
                               "What interest rate do you charge on a construction loan?",
                               "Can you give me the lobby hours for the Mullan Avenue branch?"])
def test_refusals_are_digit_free(real_system, q):
    a = real_system.answer(q)
    assert a.confident is False
    q_nums = set(re.findall(r"\d+", q))
    assert not (set(re.findall(r"\d+", a.text)) - q_nums), a.text


def test_deterministic_and_fast(real_system):
    qs = [c[0] for c in CASES]
    first = [real_system.answer(q).text for q in qs]
    real_system.answerer.cache.clear()
    t = time.perf_counter()
    second = [real_system.answer(q).text for q in qs]
    per_q = (time.perf_counter() - t) / len(qs)
    assert first == second
    assert per_q < 0.5


def test_conflicts_shape(real_system):
    cs = real_system.conflicts()
    assert 10 <= len(cs) <= 80
    for c in cs:
        assert c.topic and len(c.values) >= 2 and c.resolution and c.reason and c.sources
