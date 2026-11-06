"""Dev tool: dump table facts for one page across snapshots (python dev/dump_facts.py /rates [snap])."""
import json, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "submission"))
from nowkb.pages import build_page
from nowkb.facts import table_facts, line_facts
from nowkb.text import canon_url

path = sys.argv[1]
snaps = sorted(p for p in Path("snapshots").iterdir() if (p / "manifest.json").exists())
only = int(sys.argv[2]) if len(sys.argv) > 2 else None
for si, d in enumerate(snaps):
    if only is not None and si != only:
        continue
    m = json.loads((d / "manifest.json").read_text())
    for p in m["pages"]:
        if canon_url(p["url"]).endswith(path) or path == "*":
            pv = build_page(p["url"], p.get("title", ""), (d / p["file"]).read_text(), p.get("fetched_at", ""), si, date.fromisoformat(m["taken_on"]))
            fs = table_facts(pv, [0]) + line_facts(pv)
            print(f"== {d.name} {p['url']} type={pv.ptype} pub={pv.pub_date} facts={len(fs)}")
            for f in fs:
                print(f"   {f.family:20s} {f.attr:9s} {f.display:16s} eff={f.effective} key={f.key[:11]} | {f.label[:60]}")
