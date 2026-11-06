from nowkb.query import parse


def test_frame_basics():
    f = parse("What's the APR for a 60-month auto loan on a 2025 model-year vehicle?")
    assert f.family == "auto_loan" and f.term == 60 and f.model_year == 2025 and f.rate_q
    f = parse("Current APY on a six month share certificate?")
    assert f.family == "certificate" and f.term == 6


def test_jumbo_negation_and_salient():
    assert parse("10-month special APY (not jumbo)?").jumbo is False
    assert parse("10-month jumbo special APY").jumbo is True
    assert "arm" in parse("What is your rate on a 7/1 adjustable-rate mortgage?").salient
    assert "construction" in parse("What interest rate do you charge on a construction loan?").salient


def test_synonyms():
    assert parse("What's the yield on a 12 month CD?").family == "certificate"
    assert parse("High-Yield Savings APY for $1,000,000").family == "high_yield"
