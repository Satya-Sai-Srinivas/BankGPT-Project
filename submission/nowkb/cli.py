"""Command line: ask questions with a decision trace, or write a conflict/audit report.

    python -m nowkb.cli ask "What's the 60-month auto loan APR for a 2025 car?" [--as-of 2026-05-31]
    python -m nowkb.cli report [--out conflicts_report.md]

Run from the repo root with `PYTHONPATH=submission:harness` (the harness loads the snapshots).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def _load(snapshots: Path):
    from run_eval import load_snapshots  # harness/
    from nowkb.system import NowKB
    try:
        from contract import Answer, Conflict, Source
    except ImportError:  # pragma: no cover
        raise SystemExit("run with PYTHONPATH=submission:harness from the repo root")
    ks = NowKB(Answer=Answer, Source=Source, Conflict=Conflict)
    t = time.time()
    for s in load_snapshots(snapshots):
        ks.ingest(s)
    print(f"ingested {len(ks.kb.views)} snapshots in {time.time() - t:.1f}s", file=sys.stderr)
    return ks


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="nowkb")
    ap.add_argument("--snapshots", type=Path, default=Path("snapshots"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("question", nargs="+")
    a.add_argument("--as-of")
    r = sub.add_parser("report")
    r.add_argument("--out", type=Path, default=Path("results/conflicts_report.md"))
    args = ap.parse_args(argv)
    ks = _load(args.snapshots)
    if args.cmd == "ask":
        for q in args.question:
            t = time.perf_counter()
            e = ks.explain(q, args.as_of)
            print(json.dumps({"question": q, "as_of": args.as_of, **e,
                              "latency_ms": round(1000 * (time.perf_counter() - t), 1)}, indent=2, default=str))
    else:
        from nowkb.conflicts import build_conflicts
        lines = ["# Conflicts found and how they were resolved", "",
                 "| # | Topic | Values seen | Resolution | Why |", "|---|---|---|---|---|"]
        for i, c in enumerate(build_conflicts(ks.kb), 1):
            lines.append(f"| {i} | {c.topic} | {', '.join(c.values)} | **{c.resolution}** | {c.reason} |")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text("\n".join(lines) + "\n")
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
