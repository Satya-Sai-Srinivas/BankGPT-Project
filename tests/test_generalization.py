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


STRESS_FIXES = [
    # (question, must contain, must not contain) — failures found by the independent stress set
    ("Tell me the annual percentage yield on the 17-month fixed certificate special (the regular one, not the jumbo).",
     ["4.10%"], ["4.20%"]),
    ("List all the Visa cards Dupaco offers, personal and business, with their APRs.",
     ["Platinum Visa", "Rewards Visa", "Business Platinum", "Business Rewards"], []),
    ("What's the total number of Dupaco branch locations right now?", ["22"], ["23 branch", "24 branch"]),
    ("How much does Dupaco charge to send a domestic wire? What about an international one?", ["$25.00", "$55.00"], ["$10.00"]),
    ("How many Dupaco employees used Volunteer Time Off in 2024?", ["256"], ["294"]),
    ("How much grant funding has the Dupaco Foundation distributed since 2012?", ["$3.2 million"], ["$2.7 million"]),
    ("How many members does Dupaco have?", ["182,627"], ["179,000"]),
    ("Which web page shows Dupaco's current certificate (CD) rates?", ["dupaco.com/personal/savings-account"], ["home-loans"]),
    ("What are the drive-up hours for the Hy-Vee branch?", ["March 31, 2026"], []),
]


@pytest.mark.parametrize("q,must,must_not", STRESS_FIXES)
def test_stress_set_fixes(real_system, q, must, must_not):
    a = real_system.answer(q)
    for m in must:
        assert m in a.text, a.text
    for m in must_not:
        assert m not in a.text, a.text


@pytest.mark.parametrize("q", [
    "What's the interest rate on a VA home loan?",                          # no VA product on the rate sheet
    "Are Dupaco branches open on Thanksgiving, and what are the holiday hours?",
    "What are the lobby hours for Dupaco's Davenport, Iowa branch?",        # no such branch
    "What interest rate does Dupaco charge on private student loans?",      # only articles mention a rate
    "What rate is available through Dupaco's Mortgage Rate Relief Program?",  # off the rate sheet since June
])
def test_more_unpublished_facts_are_refused(real_system, q):
    a = real_system.answer(q)
    assert a.confident is False, a.text
    assert not (set(re.findall(r"\d+", a.text)) - set(re.findall(r"\d+", q))), a.text
