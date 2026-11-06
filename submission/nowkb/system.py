"""The object the harness drives: ingest() / answer() / conflicts()."""
from __future__ import annotations

from datetime import date
from typing import Optional

from .answer import Answerer
from .kb import KnowledgeBase
from .text import to_date


class NowKB:
    def __init__(self, Answer, Source, Conflict) -> None:
        self._Answer, self._Source, self._Conflict = Answer, Source, Conflict
        self.kb = KnowledgeBase()
        self.answerer = Answerer(self.kb)
        self._conflicts: Optional[list] = None

    # -- harness contract -------------------------------------------------------------------
    def ingest(self, snapshot) -> None:
        taken = to_date(snapshot.taken_on) or date.today()
        self.kb.add_snapshot(snapshot.snapshot_id, taken, snapshot.pages)
        self.answerer.cache.clear()
        self._conflicts = None

    def answer(self, question: str, as_of: Optional[str] = None):
        if not self.kb.views:
            return self._Answer(text="I don't know — no website snapshots have been loaded.", confident=False)
        d = self.answerer.answer(question, as_of)
        return self._Answer(
            text=d.text,
            sources=[self._Source(url=u, snapshot_id=s, quote=q) for u, s, q in d.sources],
            confident=d.confident,
            conflict_note=d.note,
        )

    def conflicts(self) -> list:
        if self._conflicts is None:
            from .conflicts import build_conflicts
            self._conflicts = [
                self._Conflict(topic=c.topic, values=c.values,
                               sources=[self._Source(url=u, snapshot_id=s, quote=q) for u, s, q in c.sources],
                               resolution=c.resolution, reason=c.reason)
                for c in build_conflicts(self.kb)
            ]
        return self._conflicts

    # -- extras (not part of the contract) ---------------------------------------------------
    def explain(self, question: str, as_of: Optional[str] = None) -> dict:
        d = self.answerer.answer(question, as_of)
        return {"text": d.text, "confident": d.confident, "sources": d.sources, "note": d.note, "trace": d.trace}
