"""Reworded and new-topic questions: routing without a rate word, off-topic refusals, fee wording,
department phones, awards, closures, locator links, and the de-duplicated conflict list."""
import re

import pytest

from nowkb.answer import implicit_rate
from nowkb.query import parse


@pytest.mark.parametrize("q,expected", [
    ("17-month certificate special", True),
    ("What's the 10-month jumbo special now?", True),
    ("What credit cards do you offer?", True),
    ("Tell me about your credit card options", True),
    ("How do I open a 17-month certificate?", False),            # a how-to question, not a rate question
    ("What's the penalty on a 17-month certificate special?", False),
    ("What are the lobby hours?", False),                         # no product at all
])
def test_implicit_rate_questions(q, expected):
    assert implicit_rate(parse(q)) is expected


REWORDED = [
    # (question, must contain, must not contain)
    ("17-month certificate special", ["4.10%"], ["4.20%", "3.95%"]),
    ("What's the 10-month jumbo special now?", ["4.00%"], ["3.90%"]),
    ("What credit cards do you offer?", ["Platinum Visa", "Rewards Visa", "Business Platinum", "Business Rewards"], []),
    ("What does a cashier's check cost?", ["$5.00"], []),
    ("What is the outgoing wire transfer fee?", ["$25.00", "$55.00"], ["$10.00"]),
    ("How much does a wire transfer cost?", ["$10.00", "$25.00", "$55.00"], []),
    ("What number do I call about a mortgage?", ["800-373-7600, ext. 204"], ["800-383-1700"]),
    ("Has Forbes ranked Dupaco?", ["fifth"], ["fourth"]),
    ("What's happening to the Hy-Vee location?", ["March 31, 2026"], []),
    ("Where do I find a branch or ATM?", ["dupaco.com/contact"], []),
    ("What are the membership requirements?", ["Iowa", "Illinois", "Wisconsin"], []),
    ("Can I become a member online?", ["join.dupaco.com"], []),
]


@pytest.mark.parametrize("q,must,must_not", REWORDED)
def test_reworded_questions(real_system, q, must, must_not):
    a = real_system.answer(q)
    assert a.confident, a.text
    for m in must:
        assert m in a.text, a.text
    for m in must_not:
        assert m not in a.text, a.text


@pytest.mark.parametrize("q", [
    "What is Dupaco's SWIFT code?",                 # not on the site at all
    "Is Dupaco closed on Thanksgiving?",            # no holiday schedule is published
    "What's the 12-month IRA certificate rate?",    # IRA certificates come in 10/17/18/36/60 months only
    "How much is a lost debit card?",               # the fee schedule has no replacement-card fee
])
def test_unpublished_facts_are_refused(real_system, q):
    a = real_system.answer(q)
    assert a.confident is False, a.text
    assert not (set(re.findall(r"\d+", a.text)) - set(re.findall(r"\d+", q))), a.text


def test_date_in_question_picks_the_snapshot(real_system):
    a = real_system.answer("How many branches did Dupaco have in May 2026?")
    assert "22" in a.text and a.text.startswith("As of May 19, 2026"), a.text
    b = real_system.answer("Did the 17-month special change since May 2026?")
    assert "4.10%" in b.text and not b.text.startswith("As of"), b.text
