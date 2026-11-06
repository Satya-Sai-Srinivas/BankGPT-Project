"""The temporal knowledge base: page versions per snapshot, facts, and per-view resolution.

A *view* is the website as it stood at one snapshot (pages present in that crawl, plus pages
last seen earlier, carried forward with reduced authority). Resolution picks, for every fact
key and attribute, the winning observation in that view:

    1. tier-1 source (official rate sheet or product page) over everything else
    2. newer "Rates are effective as of" date
    3. higher page authority (contact > fee schedule > newsroom > blog > calculator > campaign > -lp)
    4. newer fetch date, then a stable tie-break on URL

Everything else observed for the same key in that view is a loser; losers whose value differs
from the winner feed the conflict list and the stale-value guard.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .facts import Fact, line_facts, table_facts
from .index import ChunkIndex
from .pages import PageVersion, build_page


@dataclass
class View:
    idx: int
    sid: str
    taken_on: date
    pages: dict[str, list[PageVersion]] = field(default_factory=dict)
    carried: set = field(default_factory=set)
    facts: list[Fact] = field(default_factory=list)
    by_key: dict[tuple, dict[str, list[Fact]]] = field(default_factory=dict)
    claims: object = None

    def winner(self, key: tuple, attr: str) -> Optional[Fact]:
        obs = self.by_key.get(key, {}).get(attr)
        return obs[0] if obs else None


def rank(f: Fact) -> tuple:
    p = f.page
    return (
        1 if (p.tier1 and f.primary) else 0,
        f.effective or date.min,
        p.authority,
        p.fetched,
        p.key,
    )


class KnowledgeBase:
    def __init__(self) -> None:
        self.snapshots: list[tuple[str, date]] = []
        self.raw: list[dict[str, list[PageVersion]]] = []
        self.views: list[View] = []
        self.index = ChunkIndex()
        self._fact_cache: dict[tuple, list[Fact]] = {}
        self._tables = [0]

    # ---------------------------------------------------------------------------------------
    def add_snapshot(self, sid: str, taken_on: date, pages: list) -> None:
        snap = len(self.snapshots)
        self.snapshots.append((sid, taken_on))
        by_key: dict[str, list[PageVersion]] = defaultdict(list)
        for p in pages:
            pv = build_page(p.url, p.title, p.markdown, p.fetched_at, snap, taken_on)
            by_key[pv.key].append(pv)
        self.raw.append(dict(by_key))
        view = View(idx=snap, sid=sid, taken_on=taken_on)
        view.pages = dict(by_key)
        # carry forward pages last seen in an earlier crawl (the selftest expects their facts to persist)
        if snap > 0:
            prev = self.views[snap - 1]
            for key, pvs in prev.pages.items():
                if key not in view.pages:
                    view.pages[key] = pvs
                    view.carried.add(key)
        self.views.append(view)
        for key, pvs in view.pages.items():
            for pv in pvs:
                self.index.add_page(pv, snap)
        self._resolve(view)

    def facts_of(self, pv: PageVersion) -> list[Fact]:
        ck = (pv.url, pv.content_hash, pv.snap if pv.ptype in ("rate_sheet", "product") else -1)
        fs = self._fact_cache.get(ck)
        if fs is None:
            fs = table_facts(pv, self._tables) + line_facts(pv)
            self._fact_cache[ck] = fs
        return fs

    def _resolve(self, view: View) -> None:
        facts: list[Fact] = []
        for key, pvs in view.pages.items():
            for pv in pvs:
                if pv.ptype in ("listing", "junk"):
                    continue
                facts.extend(self.facts_of(pv))
        view.facts = facts
        by_key: dict[tuple, dict[str, list[Fact]]] = defaultdict(lambda: defaultdict(list))
        for f in facts:
            by_key[f.key][f.attr].append(f)
        for attrs in by_key.values():
            for obs in attrs.values():
                obs.sort(key=rank, reverse=True)
        view.by_key = {k: dict(v) for k, v in by_key.items()}
        from .claims import extract
        view.claims = extract(view.pages, view.taken_on)

    # ---------------------------------------------------------------------------------------
    def view_for(self, as_of: Optional[str]) -> View:
        """Latest snapshot taken on or before as_of (earliest snapshot if as_of predates them all)."""
        if not as_of:
            return self.views[-1]
        from .text import to_date
        d = to_date(as_of)
        if d is None:
            return self.views[-1]
        chosen = self.views[0]
        for v in self.views:
            if v.taken_on <= d:
                chosen = v
        return chosen
