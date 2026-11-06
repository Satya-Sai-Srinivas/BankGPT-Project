"""The harness's own self-test site (a different, synthetic credit union) must score perfectly."""
import json

from conftest import ROOT


def test_harness_selftest_scores_one():
    from run_eval import load_snapshots, load_submission, to_answer
    from scoring import score_conflicts, score_item, summarize
    sdir = ROOT / "harness" / "selftest"
    ks = load_submission(ROOT / "submission")
    for s in load_snapshots(sdir / "snapshots"):
        ks.ingest(s)
    items = [json.loads(l) for l in (sdir / "eval.jsonl").read_text().splitlines() if l.strip()]
    results = []
    for it in items:
        r = score_item(it, to_answer(ks.answer(it["question"], it.get("as_of"))))
        r.update(latency_s=0.0, answer={"text": ks.answer(it["question"], it.get("as_of")).text})
        results.append(r)
    rep = summarize(results, score_conflicts(json.loads((sdir / "conflicts_gold.json").read_text()), ks.conflicts()))
    assert rep["qa_score"] == 1.0
    assert rep["conflicts"]["f1"] == 1.0 and rep["conflicts"]["resolution_accuracy"] == 1.0
