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

| | Public (40) | Dev (57) | Held-out (26) | Harness self-test |
|---|---|---|---|---|
| Starter | 0.093 | | | |
| **NowKB QA score** | **0.969** (ceiling) | **1.000** | **1.000** | **1.000**, conflict F1 1.0 |
| Stale-value trap hits | 0 | 0 | 0 | 0 |

**Runtime:** about 3 s to ingest all 5 snapshots; p95 answer latency under 50 ms, so the speed pillar
gets full marks. **Consistency:** 1.0 for paraphrase groups and 1.0 for repeats.

**Conflicts pillar:** against a 15-item dev gold reconstructed from the public traps and verified page
diffs, recall is 0.80 and the right winner is picked 80% of the time. The real gold is hidden, so this is
only a sanity check.

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
| Retrieval only (no structured handlers) | 0.489 / 0.521 / 0.524 | The rate engine and the claim handlers carry the score; plain RAG also repeats stale values (4 trap hits) |
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
  router           links ▸ routing ▸ hours ▸ address ▸ closures ▸ stats ▸ fees ▸ contact ▸ rates ▸ eligibility ▸ generic
  render           only from resolved winners, values verbatim
  guard            digit-free refusals, no artefacts
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
- **Refusals are strict and digit-free.** A question naming a variant that no table carries gets "I don't
  know". Examples: the 7/1 ARM, a construction-loan rate, a 9-month CD, an unknown branch's hours.
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
tests/                        32 pytest tests: parsing, resolution, as_of, conflicts, refusals, determinism,
                              latency, harness self-test, LLM stub
dev/                          dev and held-out sets (make_dev_set.py), dev conflict gold, analyze.py, probe.py
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
