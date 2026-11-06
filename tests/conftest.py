import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
sys.path.insert(0, str(ROOT / "submission"))


class P:  # minimal stand-in for harness contract.Page
    def __init__(self, url, markdown, title="", fetched_at=""):
        self.url, self.markdown, self.title, self.fetched_at = url, markdown, title, fetched_at


@pytest.fixture(scope="session")
def real_system():
    """The full system ingested over the five real snapshots (skipped if they are not unpacked)."""
    from run_eval import load_snapshots, load_submission
    snaps_dir = ROOT / "snapshots"
    snaps = load_snapshots(snaps_dir)
    if len(snaps) < 5:
        pytest.skip("real snapshots not available")
    ks = load_submission(ROOT / "submission")
    for s in snaps:
        ks.ingest(s)
    return ks


def make_kb(snapshots):
    """snapshots: list of (snapshot_id, 'YYYY-MM-DD', [P, ...])"""
    from nowkb.kb import KnowledgeBase
    kb = KnowledgeBase()
    for sid, taken, pages in snapshots:
        kb.add_snapshot(sid, date.fromisoformat(taken), pages)
    return kb
