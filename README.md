# NowKB — a knowledge system that knows what's true *now*

Five crawls of a credit union's website (May–Sep 2026) contradict each other: rates change but old pages,
calculators and promo pages keep the old numbers, tiers look like conflicts, and press releases carry
outdated counts. NowKB answers members' questions with the **current, correctly-tiered value, a source,
and an honest "I don't know"**, can answer **as the site stood on any date**, and lists the site's
**contradictions with a resolution and the reason**.

```bash
python harness/run_eval.py --submission submission --eval eval/public_eval.jsonl
```

No API keys and no third-party packages are needed (standard library only). See [NOTES.md](NOTES.md) for
the short version and [DESIGN.md](DESIGN.md) for the rules.

## Results

| | Public (40) | Dev (57) | Held-out (26) | Reworded + probes (128) | Harness self-test |
|---|---|---|---|---|---|
| Starter | 0.093 | | | | |
| **NowKB QA score** | **0.969** (ceiling) | **1.000** | **1.000** | **1.000** | **1.000**, conflict F1 1.0 |
| Stale-value trap hits | 0 | 0 | 0 | 0 | 0 |

**Runtime:** about 3.5 s to ingest all 5 snapshots; p95 answer latency under 50 ms, so the speed pillar
gets full marks. **Consistency:** 1.0 for paraphrase groups and 1.0 for repeats.

**Rewordings:** the 101 rewordings of the public questions in `dev/reword_eval.jsonl` scored 0.91 (paraphrase
consistency 0.84) before routing stopped depending on rate words and on exact handler phrasings; see
DESIGN.md section 4.

**Conflicts pillar:** 33 entries. The dev gold has 15 items, reconstructed from the public traps and
verified page diffs; two of them do not occur in any crawl. Against it:

- 13 of 15 are matched;
- the right winner is picked for 87%;
- F1 is 0.54.

The real gold is hidden, so this is only a sanity check.

**How the dev and held-out sets were built:** they were written by hand from the snapshots:

- rewordings of the public questions;
- `as_of` questions at every snapshot boundary;
- questions about values that changed between crawls;
- refusal probes and new products.

The held-out split scored 0.965 at first look. One general fix (negation such as "not jumbo") followed.

### Ablations (QA score: public / dev / held-out)

| Variant | Score | What it shows |
|---|---|---|
| Full system | 0.969 / 1.000 / 1.000 | |
| Retrieval only (no structured handlers) | 0.489 / 0.537 / 0.594 | The rate engine and the claim handlers carry the score; plain RAG also repeats stale values (4 trap hits) |
| Naive resolution ("most recently fetched wins", no authority ladder) | 0.954 / 0.984 / 0.965 | Stale values start leaking (1 trap hit per set) and conflict F1 drops |

Reproduce with `NOWKB_ABLATE=handlers` or `NOWKB_ABLATE=resolution`.

## Architecture — resolve, then generate

```
ingest(snapshot)
  normalize        URL canon, strip widgets / cards / data-URIs, footnote digits glued to values
  classify page    rate sheet | product | contact | fee doc | newsroom | blog | calculator | campaign | -lp | expired
  extract          rate-table rows → typed facts (scope, family, purpose, term, tier, model-year tier, Roth/Trad, jumbo)
                   claims → branches + hours, dated org stats, closures, fees, routing / phone, canonical links
  resolve views    per snapshot: winner per fact key = official source ▸ newer effective date ▸ authority ▸ fetch date
  index            BM25F chunks, de-duplicated across crawls, with a per-snapshot validity bitmask

answer(q, as_of)
  view             latest snapshot ≤ as_of
  QueryFrame       product, term, tier, amount, model year, intent, salient qualifiers
  router           links ▸ routing ▸ phones ▸ hours ▸ address ▸ closures ▸ stats ▸ awards ▸ fees ▸ rates
                   (incl. product questions with no rate word) ▸ contact ▸ eligibility ▸ generic
  render           only from resolved winners, values verbatim
  guard            off-topic evidence → "I don't know"; digit-free refusals, no artefacts
  cache

conflicts()        one per fact key, all observed values, winner + reason, ranked and cut for F1
```

Design choices that matter most:

- **Stale numbers are filtered before generation, not after.** The renderer can only see resolved
  winners. Old values survive only in `conflict_note` and `conflicts()`, which the scorer does not read
  as answer text.
- **Fact keys are semantic.** Tier labels drift between crawls ("2023-26" became "2024-27"), so
  model-year tiers are matched by containment and aligned by tier position. The stale-value registry
  is scoped to a key, never global: 3.90% is stale for the 10-month jumbo special but current for the
  regular 10-month special.
- **Organisation facts use the newest dated statement, never the majority.** The outdated "23 branches"
  appears on more pages than the correct 22.
- **Routing survives rewording.** The hidden set rewords the public questions. A product question
  without a rate word ("17-month certificate special") still reaches the rate engine. Member wording maps
  to the fee schedule's wording (a cashier's check is an "Official check").
- **Refusals are strict and digit-free.** A question naming a variant that no table carries gets "I don't
  know". Examples: the 7/1 ARM, a construction-loan rate, a 9-month CD, an unknown branch's hours. So
  does a question whose only evidence is off-topic ("What is Dupaco's SWIFT code?").
- **The answer path is deterministic and pure in-memory.** That makes consistency and speed structural
  properties of the design rather than something to tune.

## Optional Claude layer

Off by default. `NOWKB_LLM=1` plus `ANTHROPIC_API_KEY` lets `claude-haiku-5-5` rewrite low-confidence
free-text answers from vetted evidence. It sits behind a validator: every number must be grounded in
the cited evidence, no stale value may appear, and the deterministic answer is used otherwise. It is
stub-tested only (no key was available during development), so it is not part of the graded path.

## Repo layout

```
submission/solution.py        build() for the harness (imports the harness contract types)
submission/nowkb/             normalize, pages, facts, kb (views + resolution), claims, index, query,
                              answer (router, rates, generic, guard), handlers, conflicts, llm, cli, system
tests/                        59 pytest tests: parsing, resolution, as_of, conflicts, refusals, determinism,
                              latency, reworded questions, harness self-test, LLM stub
dev/                          dev and held-out sets (make_dev_set.py), reword_eval.jsonl (rewordings + probes),
                              dev conflict gold, analyze.py, probe.py
harness/ eval/ starter/ snapshots_zip/   the kit, unmodified
```

## Developer workflow

```bash
python -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
python harness/run_eval.py --submission submission --eval dev/dev_eval.jsonl --conflicts-gold dev/conflicts_gold_dev.json --out results/dev
python dev/analyze.py results/dev dev/dev_eval.jsonl        # misses, trap hits, answers
PYTHONPATH=submission:harness python -m nowkb.cli ask "What was the 12-month CD APY?" --as-of 2026-05-20
PYTHONPATH=submission:harness python -m nowkb.cli report    # results/conflicts_report.md
```

The website data is shared for this event only. Keep this repository private.
