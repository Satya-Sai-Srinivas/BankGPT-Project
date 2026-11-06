"""NowKB submission entry point: `build()` returns a KnowledgeSystem for the harness.

All logic lives in the `nowkb` package next to this file; see NOTES.md / DESIGN.md.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:  # the harness puts harness/ on sys.path before loading us
    from contract import Answer, Conflict, Snapshot, Source  # type: ignore  # noqa: F401
except ImportError:  # pragma: no cover - fallback when run outside the harness
    _h = next((d / "harness" for d in _HERE.parents if (d / "harness" / "contract.py").exists()), None)
    if _h is not None:
        sys.path.insert(0, str(_h))
        from contract import Answer, Conflict, Snapshot, Source  # type: ignore  # noqa: F401
    else:
        @dataclass
        class Source:  # type: ignore[no-redef]
            url: str
            snapshot_id: Optional[str] = None
            quote: Optional[str] = None

        @dataclass
        class Answer:  # type: ignore[no-redef]
            text: str
            sources: list = field(default_factory=list)
            confident: bool = True
            conflict_note: Optional[str] = None

        @dataclass
        class Conflict:  # type: ignore[no-redef]
            topic: str
            values: list
            sources: list
            resolution: Optional[str] = None
            reason: Optional[str] = None

from nowkb.system import NowKB  # noqa: E402


def build() -> NowKB:
    return NowKB(Answer=Answer, Source=Source, Conflict=Conflict)
