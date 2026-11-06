"""Resolution rules on a synthetic two-crawl site."""
from conftest import P, make_kb

RATES_V1 = """# Rates
Auto Loans

| Loan Program | Term | APR |
| --- | --- | --- |
| 2023-26 Model Year | 60 Months | 5.19% APR1 |
| 2021-22 Model Year | 60 Months | 5.44% APR |

Rates are effective as of 05/01/2026. All loans are subject to approval.
"""
RATES_V2 = RATES_V1.replace("2023-26", "2024-27").replace("5.19%", "5.39%").replace("2021-22", "2021-23") \
    .replace("5.44%", "5.64%").replace("05/01/2026", "08/31/2026")
CALC = """# Vehicle Affordability Calculator
| Account Type | Balance Tier | Annual Percentage Yield |
| --- | --- | --- |
| 2023–26 Model Year | 60 Months | 5.34% APR |

Rates are effective as of 1/1/2026.
"""
FEES = "# Fees\n\nLost debit card replacement fee: $2.50\n"


def _kb():
    return make_kb([
        ("01", "2026-05-12", [P("https://cu.test/rates", RATES_V1), P("https://cu.test/calculators/vehicle", CALC),
                              P("https://cu.test/fees", FEES)]),
        ("02", "2026-09-28", [P("https://cu.test/rates", RATES_V2), P("https://cu.test/calculators/vehicle", CALC)]),
    ])


def test_rate_sheet_beats_stale_calculator_and_tiers_align():
    from nowkb.answer import Answerer
    kb = _kb()
    a = Answerer(kb)
    d = a.answer("What's the 60-month auto loan APR for a 2025 vehicle?")
    assert "5.39%" in d.text and "5.34%" not in d.text and "5.19%" not in d.text
    # the stale value is explained in the (unscored) conflict note, not the answer
    assert d.note and "5.34%" in d.note


def test_as_of_uses_the_website_as_it_stood():
    from nowkb.answer import Answerer
    a = Answerer(_kb())
    d = a.answer("What's the 60-month auto loan APR for a 2025 vehicle?", as_of="2026-06-01")
    assert "5.19%" in d.text and "5.39%" not in d.text


def test_pages_missing_later_are_carried_forward():
    kb = _kb()
    assert "https://cu.test/fees" in kb.views[-1].carried


def test_conflicts_one_per_key_with_winner():
    from nowkb.conflicts import build_conflicts
    cs = build_conflicts(_kb())
    auto = [c for c in cs if "60-month" in c.topic and "5.39%" in c.values]
    assert len(auto) == 1
    assert auto[0].resolution.startswith("5.39%")
    assert "5.34%" in auto[0].values


def test_unknown_variant_refuses_without_digits():
    from nowkb.answer import Answerer
    d = Answerer(_kb()).answer("What is the rate on a 60-month jumbo auto loan?")
    assert not d.confident or "jumbo" not in d.text.lower()
