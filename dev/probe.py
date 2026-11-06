"""Dev tool: build the KB once and inspect retrieval/answers. python dev/probe.py "question" [as_of]"""
import pickle, sys, time
from datetime import date
from pathlib import Path
sys.path.insert(0, "harness"); sys.path.insert(0, "submission")
from run_eval import load_snapshots
from nowkb.kb import KnowledgeBase
from nowkb.answer import Answerer, _prior
from nowkb.query import parse
from nowkb.text import tokens

kb = KnowledgeBase()
for s in load_snapshots(Path("snapshots")):
    kb.add_snapshot(s.snapshot_id, date.fromisoformat(s.taken_on), s.pages)
a = Answerer(kb)
for q in sys.argv[1:]:
    fr = parse(q)
    print("Q:", q, "| families", fr.families, "intents", sorted(fr.intents), "term", fr.term)
    v = kb.views[-1]
    for sc, ch in kb.index.search(tokens(fr.norm), v.idx, k=5, prior=_prior(fr)):
        print(f"   {sc:6.2f} {ch.versions[v.idx].url[-70:]} | {ch.text[:150]!r}")
    d = a.answer(q)
    print("A:", d.text[:400], "\n  trace", d.trace, "\n")
