from datetime import date

from nowkb.text import (canon_url, model_year_range, money_range, parse_date, sentences, strip_footnotes, term_months,
                        tokens)


def test_dates():
    assert parse_date("This location will close March 31, 2026.") == date(2026, 3, 31)
    assert parse_date("Rates are effective as of 8/13/25") == date(2025, 8, 13)
    assert parse_date("Sept. 25, 2025") == date(2025, 9, 25)
    assert parse_date("the 50/30/20 budget rule") is None


def test_terms_and_years():
    assert term_months("30-Year Fixed Conventional") == 360
    assert term_months("Loan – Standard (60 mo)") == 60
    assert term_months("six-month certificate") == 6
    assert term_months("2023-26 Model Year") is None          # 'Model' is not 'mo'
    assert model_year_range("2024-27 Model Year") == (2024, 2027)
    assert model_year_range("Model Year 2026-23") == (2023, 2026)
    assert model_year_range("2016 Model Year (and older)") == (1900, 2016)


def test_money_ranges():
    assert money_range("$10,000 – $24,999.99") == (10000, 24999.99)
    assert money_range("$25,000+") == (25000, float("inf"))
    assert money_range("Purchase: 30-Year Fixed Conventional $832,750 or less") == (0, 832750)
    assert money_range("$10,000.00 – $20,000.00 120 Months") == (10000, 20000)


def test_footnotes_and_urls():
    assert strip_footnotes("4.10%2") == "4.10%"
    assert strip_footnotes("5.39% APR1") == "5.39% APR"
    assert canon_url("https://www.dupaco.com/about/join?hsLang=en") == "https://dupaco.com/about/join"
    assert canon_url("https://www.dupaco.com/personal/savings-account#rates") == "https://dupaco.com/personal/savings-account"


def test_sentences_keep_abbreviations():
    s = sentences("The last day of service will be Oct. 1, 2024. It is at 3299 Hillcrest Rd. in Dubuque. Open 8 a.m. Monday.")
    assert s == ["The last day of service will be Oct. 1, 2024.", "It is at 3299 Hillcrest Rd. in Dubuque.",
                 "Open 8 a.m. Monday."]


def test_tokens_stem():
    assert tokens("recognition") == tokens("recognized")
    assert "17" in tokens("17-month special")
