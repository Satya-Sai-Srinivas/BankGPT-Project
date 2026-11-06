# DESIGN — rules, evidence and trade-offs

This document records what the data looked like, the rule each observation led to, and what was traded away.
Every example comes from the five snapshots.

## 1. What the scorer rewards

| Scorer mechanic (`harness/scoring.py`) | Consequence for the design |
|---|---|
| Any `must_not_include` value in the answer zeroes the item | Never render from raw text where an old number could appear. Render from resolved facts and keep stale values out of `text` |
| Numbers match by value and unit; other tokens match as normalized substrings | Copy the site's formatting verbatim: `8 a.m.` (not `8:00 AM`), `March 31, 2026`, `800-373-7600` |
| `should_refuse` needs a refusal **and** no digits beyond the question's | Refusal templates contain no digits; no phone number in refusals |
| A source counts if **any** cited URL path matches, with no penalty for extra citations | Cite every current page that carries the winning value, ordered by authority |
| `conflict_note` and `Source.quote` are not scored | Explanations and overridden values go there |
| Consistency compares the *numeric set* of answers | Deterministic rendering; same question frame → same template |
| Speed uses p95 latency | All heavy work happens in `ingest()`; `answer()` is a few dictionary lookups plus a small BM25 query |
| Conflicts use F1 (precision matters) plus 30% for the right winner | One entry per fact key; rank candidates and cut the list |

## 2. Data findings → rules

**Normalization.** About 36% of tokens are crawler furniture:

- related-article cards, which carry *other* articles' dates;
- link modals;
- a 234-line country picker;
- reCAPTCHA text;
- a chat widget injected only in crawl 02, which is why "almost every page changed" then;
- base64 SVG data.

Cleaning removes these. It also strips footnote digits glued to values (`4.10%2`, `5.39% APR1`) inside
table cells only.

**Rate tables are the backbone.** `/rates` and `/business-rates` are re-crawled every time. They hold
27 and 7 tables, and each table is followed by "Rates are effective as of MM/DD/YYYY". Product pages
embed the same tables, sometimes under alias URLs (`/personal/loans/auto-loans/`). Each row becomes a
`Fact` keyed by:

```
(scope, family, purpose, term, jumbo, special, ira, balance-tier floor, loan-amount cap, model-year tier ordinal, intro, card, money-market)
```

Several quirks shape the parser:

- **Product names come from context, not just the row.** In crawls 01–04 the Health Savings Account and
  Money Market rows carry no product name, and the HSA table's only nearby caption is "Saving Account
  Rates". The parser classifies the product family from the row label first, then from caption and
  section lines nearest-first, then from the previous table.
- **Model-year tiers move.** The auto tiers were relabelled ("2023-26" → "2024-27", "2021-22" →
  "2021-23"). Tiers are aligned across crawls by their position (0 = newest vehicles), and questions are
  answered by containment: a 2025 car falls in "2024-27".
- **One calculator header is wrong.** The vehicle-affordability calculator labels APR rows as "Annual
  Percentage Yield". Column meaning is checked against cell content ("APR" in the cell wins).

**Where stale numbers live.** They sit on pages that are not the official rate source:

| Page | Stale value | Effective date |
|---|---|---|
| `/calculators/vehicle-affordability` | 5.34% / 5.54% auto | 1/1/2026 |
| `/switch-and-earn` (not re-crawled since 06-09) | 5.34% / 5.54% auto | 1/1/2026 |
| `/homebuying-guidance`, `/mortgage-refi` | 6.037% / 6.061% / 5.954% mortgage | 04/22/2026 |
| three `-lp` pages | 3.00% checking APY | 07/01/2025 |

That gives the resolution order:

```
official rate source (rate sheet / product table)  >  newer table effective date  >  authority
(contact > fee schedule > dated press release > blog > calculator > campaign > -lp > expired / not re-crawled)
>  newer fetched_at  >  stable tie-break
```

**Key-scoped staleness.** 3.90% is stale for the 10-month jumbo special, which moved to 4.00% in crawl
05. It is also the *current* rate for the regular 10-month special. The stale registry is therefore
per key, never per value.

**Co-moving siblings.** In crawl 05, `/rates` shows "Traditional: 10 Month Fixed Jumbo Special
3.86%/3.90%". Its Roth twin and the certificate moved to 3.96%/4.00%. These rows were identical in every
earlier crawl. When such rows diverge and one still equals the previous common value, it is reported as
a stale row.

**Organisation facts are dated, not voted.** Press-release boilerplate says the branch count is:

| Count | When it appears |
|---|---|
| 19, 20, 22 | 2021–22 |
| 24 | 2024 |
| 23 | Oct 2024 – Mar 2026, on more pages than any other value |
| 22 | Apr–May 2026, the newest releases |

`/about` still says "18 branches" in an undated bio. Only dated statements (release dates, or a PDF's
"As of" line) count, and the newest wins. The same rule handles counties (118) and Forbes ("fifth
time", June 2024, beats "fourth time", 2023).

**Hours exist only in branch-opening press releases** (2021–2024), in `**Lobby**` / `**Drive-up**`
blocks. The `/contact` locator has addresses but no hours. General hours questions get the distinct
schedules, grouped, with branch names, and a closing question about *which* branch. The answer always
comes first; it never demands a ZIP code.

**Events.** "This location will close March 31, 2026" (Hy-Vee release, June 20, 2025) is answered in
the past tense once the view date is later: "No — The Hy-Vee branch closed on March 31, 2026."

**Year-qualified statistics are distinct facts.** "294 employees used VTO in 2023" and "256 in 2024" do
not conflict. "Last year" questions list both, with their years.

**Links.** The site links `/personal/savings-account#rates` 16 times and `join.dupaco.com` 106 times. A
link answer scores anchor text and target path against the question, weights by in-link count, and
drops `www.dupaco.com` targets that no longer exist in the crawl, since those are legacy links.

## 3. As-of semantics

`as_of` picks the latest snapshot taken on or before the date: the site as last observed. A page absent
from a crawl is carried forward from the previous view, flagged as not re-crawled and given lower
authority. The harness self-test relies on this for its fees page.

Effective dates are used to rank pages *within* a view. They are not used to re-date a later
observation backwards, because effective dates on this site are inconsistent: the Share Savings table
says 06/15/2026 while its own footnote says 03/03/2026.

A question that embeds a past date ("as of May 2026") with no `as_of` parameter is answered from the
matching view.

## 4. Refusals

The site does not publish the answer when either of these holds:

- **A named variant no table carries.** Every salient qualifier in the question must be satisfied by a
  row. Examples: 7/1 ARM, FHA, construction, 9-month CD, 60-month jumbo CD.
- **Evidence without the number asked for.** A rate question whose best evidence has no `%`, or a fee
  question whose best `$` sentence does not mention the fee asked about.

Branches known only by name (Mullan Ave) have no hours, so hours questions about them are refused. The
refusal text contains no digits and sets `confident=False`.

## 5. Conflicts

Candidates are generated per fact key across all views, and every observed value is kept. In score
order:

| Score | Type | What it is |
|---|---|---|
| 0.92 | Stale copy | The latest crawl still shows an old value on a calculator, campaign, landing or other non-official page |
| 0.85 | Branch count | Dated organisation claim |
| 0.80 | Award ordinals | Dated organisation claim |
| 0.75 | Co-moving sibling | Rows that always matched now disagree |
| 0.55–0.63 | Changed | The official value changed across crawls |
| 0.60 | County count | Dated organisation claim |

Scores are then adjusted:

- **Removed:** IRA specials that only mirror a certificate's history.
- **Penalised:** business-scope duplicates of personal rows.
- **Down-weighted:** products no longer listed on the rate sheet.

**Ordering.** Within the same score, canonical rows come first (newest model-year tier, purchase before
refinance, smaller loan-amount tier). A grader matching greedily then pairs each contradiction with its
most specific entry.

**Topics** include several spellings of the term ("60-month (60 months, 60 month)") and product words,
for keyword matching.

**The list is cut** below a score of 0.45 and at most 60 entries (38 today). That keeps precision
reasonable when the size of the hidden gold list is unknown.

## 6. Trade-offs and limits

- **Deterministic over generative.** Rules and lexicons are maintainable and testable, but phrasings far
  outside the lexicon fall back to sentence retrieval. The optional Claude layer exists for those cases;
  it is gated by a grounding validator and off by default because it could not be measured.
- **Minimal answers.** Answers include only numbers that answer the question. Any extra number is a
  potential trap: a 3.00% cash-advance fee would trip a "3% APY" checking trap. The jumbo tier is
  mentioned without numbers unless asked about.
- **dup-005.** "Read back all certificate rates" can only score under `--judge`, which caps the public
  score at 0.969.
- **Known gold quirks we did not chase:**
  - dup-011's expected "15-year 6.25%" is really the HELOC rate.
  - dup-016 lists the stale `/switch-and-earn` as a source.
  - dup-102 says Mullan Avenue may be closed; 2026 pages say it is open but list no hours, so we refuse
    either way.
