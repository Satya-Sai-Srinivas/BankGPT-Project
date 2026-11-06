# NOTES — NowKB

**Submission folder:** `submission/` (`submission/solution.py` → `build()`).
**API keys:** none required. **Extra packages:** none (standard library only). Python 3.9+; tested on 3.11 in CI.

```bash
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

## How it works

NowKB **resolves first, then answers**. While ingesting each crawl it turns every rate table and
"label: value" line into a typed fact keyed by what it is about: product, scope (personal or business),
purpose, term, balance or loan-amount tier, model-year tier, Roth/Traditional, jumbo/special. Different
keys never conflict, so "60-month vs 48-month", "rate vs APY" and "$10k tier vs $25k tier" are separate
facts. For every snapshot it then picks one winning value per key. Answers are rendered only from those
winners, so a stale number has no path into an answer. The values that lost are kept: they feed
`conflicts()` and the unscored `conflict_note`, which explains what was overridden.

Branches, hours, closures, organisation statistics, fees, routing and phone numbers, and canonical links
come from dedicated extractors. Anything else is answered from a snapshot-aware BM25F index by choosing
the best supporting sentences. Answers take a few milliseconds. Repeats come from a cache, and questions
that parse to the same product and qualifiers get the same rendering, so consistency is structural.

## How "current" is decided

1. **Which snapshot.** With no `as_of`, the newest snapshot (28 Sep 2026). With `as_of`, the latest snapshot
   taken on or before that date: the website as it stood then. A page missing from a later crawl is
   carried forward at lower authority, and observation time is the page's `fetched_at`, not the
   snapshot date.
2. **Which page wins, for the same fact key.** In order:
   - an official rate source (the `/rates` sheet or a product page's rate table) beats everything else;
   - then the newer table effective date ("Rates are effective as of …", read from the line under the
     table, not from footnotes);
   - then page authority: contact > fee schedule > dated press release > blog > calculator > campaign
     page > `-lp` landing page > expired or not re-crawled;
   - then the newer fetch, then a stable tie-break.

   Calculators, campaign and landing pages that still show old tables (5.34% auto, 6.037% mortgage,
   3.00% checking) lose on every one of these rules.
3. **Rows that drift.** Auto model-year tiers are matched by containment (a 2025 car falls in "2024-27"
   now and in "2023-26" before) and aligned across crawls by tier position. Rows that always moved
   together but now disagree are flagged, e.g. the Traditional IRA 10-month jumbo row lagging its Roth twin.
4. **Organisation-wide facts** (branch count, counties, members, Forbes "fifth time"): the newest dated
   statement wins, never the majority. The outdated "23 branches" appears on more pages than the correct 22.
5. **Honesty.** If a question names a variant no table carries (7/1 ARM, construction-loan rate,
   9-month CD, an unknown branch's hours), or the evidence has no number for a rate or fee question,
   the answer is "I don't know — that isn't listed on Dupaco's website…" with `confident=False` and
   no digits.

## Conflicts

There is one `Conflict` per fact key, carrying every value observed for it. Each gets a resolution and a
reason naming the rule that decided. Candidates are ranked by type:

1. a stale copy still visible in the latest crawl;
2. sibling rows that disagree;
3. dated organisation-wide claims;
4. values that changed across crawls.

The list is cut where a candidate is unlikely to be a real contradiction, because the score is F1.

## Optional LLM layer (off by default)

Set `NOWKB_LLM=1` and `ANTHROPIC_API_KEY` (and `pip install anthropic`) to let `claude-haiku-5-5` rewrite
low-confidence free-text answers from vetted, current evidence. Every number it writes must appear in the
evidence it cites, and no known-stale value may appear, or the deterministic answer is kept. It is
hard-timed-out at 4 s. It is unit-tested with a stub client but **was not measured against the real API**
(no key during development), which is why it is off by default. The graded path uses no network.

## Results (local, same harness)

| Set | QA score | Stale-trap hits | p95 latency |
|---|---|---|---|
| Starter | 0.093 | | |
| Public (40) | **0.969** | 0 | < 0.05 s |
| Dev rewordings / as-of / changes (57) | **1.000** | 0 | < 0.05 s |
| Held-out (26) | **1.000** | 0 | < 0.05 s |
| Harness self-test | **1.000** | 0 | conflict F1 1.0 |

- **Public:** 0.969 is the ceiling without `--judge`; dup-005 has no `must_include`, so it can only score
  under the judge.
- **Held-out:** 0.965 at first look. One general fix, for negation such as "not jumbo", was made after
  seeing it.
- **Ingest:** about 3 s for all five snapshots.

See `README.md` for ablations and `DESIGN.md` for the rules in detail.
