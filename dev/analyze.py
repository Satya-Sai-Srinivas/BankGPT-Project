"""Print misses from a harness run: python dev/analyze.py results/v1 [eval.jsonl] [--all]"""
import json, sys
from pathlib import Path

out = Path(sys.argv[1])
evalf = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else Path("eval/public_eval.jsonl")
show_all = "--all" in sys.argv
items = {json.loads(l)["id"]: json.loads(l) for l in evalf.read_text().splitlines() if l.strip()}
rows = [json.loads(l) for l in (out / "per_question.jsonl").read_text().splitlines() if l.strip()]
for r in rows:
    if r["score"] >= 0.999 and not show_all:
        continue
    it = items[r["id"]]
    a = r["answer"]
    print(f"--- {r['id']} [{r['category']}] score={r['score']} corr={r['correctness']} src={r['source_hit']} lat={r['latency_s']}")
    print(f"  Q: {it['question']}  as_of={it.get('as_of')}")
    print(f"  missed={r['missed']} traps={r['trap_hits']} exp_src={it.get('expected_sources')}")
    print(f"  A: {a['text'][:500]}")
    print(f"  cited: {[s['url'] for s in a['sources']][:4]} confident={a['confident']}")
rep = json.loads((out / "report.json").read_text())
print("\nqa_score", rep["qa_score"], "final", rep["final_score"], "traps", rep["stale_trap_hits"], rep.get("consistency", {}).get("score"))
