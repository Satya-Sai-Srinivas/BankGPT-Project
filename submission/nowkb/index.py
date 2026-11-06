"""Snapshot-aware BM25F chunk index.

Chunks are de-duplicated by (page key, text): a chunk that is identical across crawls is stored
once with a bitmask of the snapshot views it is valid in, so "as of" retrieval is a mask filter.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .pages import PageVersion
from .text import plain, tokens

MAX_CHUNK_WORDS = 140


@dataclass
class Chunk:
    cid: int
    key: str                  # canonical page key
    heading: str
    text: str                 # markdown text of the chunk
    order: int = 0            # position of the chunk within its page (0 = first)
    mask: int = 0             # bit v set -> valid in view v
    versions: dict = field(default_factory=dict)   # view -> PageVersion
    tf: dict = field(default_factory=dict)
    length: int = 0


def split_chunks(page: PageVersion) -> list[tuple[str, str]]:
    """(heading path, chunk text) pairs. Tables stay whole together with their caption lines."""
    out: list[tuple[str, str]] = []
    heading = page.title
    buf: list[str] = []
    words = 0

    def flush():
        nonlocal buf, words
        txt = "\n".join(buf).strip()
        if txt:
            out.append((heading, txt))
        buf, words = [], 0

    lines = page.text.split("\n")
    if page.ptype == "newsroom":
        # press-release tail ("###" then "ABOUT DUPACO ...") is boilerplate; its facts live in the claims store
        for k, ln in enumerate(lines):
            st = ln.strip()
            if st in ("###", "# # #", "\\# # #") or re.match(r"(?i)^\**about dupaco community credit union", st):
                lines = lines[:k]
                break
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if re.match(r"^#{1,6}\s", s):
            flush()
            heading = plain(s)
            i += 1
            continue
        if s.startswith("|"):
            # keep a table (plus the caption lines already buffered) as one chunk
            tbl = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i].strip())
                i += 1
            # include the effective-date line right after the table
            tail = []
            k = i
            while k < len(lines) and len(tail) < 2:
                t = lines[k].strip()
                if t:
                    tail.append(t)
                    if "effective" in t.lower():
                        break
                k += 1
            cap = buf[-3:] if buf else []
            flush()
            out.append((heading, "\n".join(cap + tbl + [t for t in tail if "effective" in t.lower()])))
            continue
        if not s:
            if words >= MAX_CHUNK_WORDS // 2:
                flush()
            i += 1
            continue
        n = len(s.split())
        if words + n > MAX_CHUNK_WORDS and buf:
            flush()
        buf.append(s)
        words += n
        i += 1
    flush()
    return out


class ChunkIndex:
    FIELD_W = {"title": 2.5, "heading": 1.5, "url": 1.5, "body": 1.0}

    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._by_ident: dict[tuple, int] = {}
        self.postings: dict[str, dict[int, float]] = defaultdict(dict)
        self.df: dict[str, int] = defaultdict(int)
        self.total_len = 0
        self._dirty = True

    def add_page(self, page: PageVersion, view: int) -> None:
        if page.ptype in ("listing", "junk"):
            return
        url_toks = " ".join(re.split(r"[/\-_.?=&]+", page.key.split("//", 1)[-1]))
        for order, (heading, txt) in enumerate(split_chunks(page)):
            ident = (page.key, txt)
            cid = self._by_ident.get(ident)
            if cid is None:
                cid = len(self.chunks)
                ch = Chunk(cid=cid, key=page.key, heading=heading, text=txt, order=order)
                tf: dict[str, float] = defaultdict(float)
                for t in tokens(plain(txt)):
                    tf[t] += self.FIELD_W["body"]
                for t in tokens(heading):
                    tf[t] += self.FIELD_W["heading"]
                for t in tokens(page.title):
                    tf[t] += self.FIELD_W["title"]
                for t in tokens(url_toks):
                    tf[t] += self.FIELD_W["url"]
                ch.tf = dict(tf)
                ch.length = sum(tf.values())
                self.chunks.append(ch)
                self._by_ident[ident] = cid
                for t, w in tf.items():
                    self.postings[t][cid] = w
                    self.df[t] += 1
                self.total_len += ch.length
            ch = self.chunks[cid]
            ch.mask |= 1 << view
            ch.versions[view] = page

    def search(self, q_tokens: list[str], view: int, k: int = 12, weights: dict | None = None,
               prior=None) -> list[tuple[float, Chunk]]:
        n = max(1, len(self.chunks))
        avg = self.total_len / n if n else 1.0
        k1, b = 1.2, 0.75
        bit = 1 << view
        scores: dict[int, float] = defaultdict(float)
        for t in set(q_tokens):
            post = self.postings.get(t)
            if not post:
                continue
            idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            qw = (weights or {}).get(t, 1.0)
            for cid, tf in post.items():
                ch = self.chunks[cid]
                if not ch.mask & bit:
                    continue
                scores[cid] += qw * idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * ch.length / avg))
        ranked = []
        for cid, s in scores.items():
            ch = self.chunks[cid]
            if prior:
                s *= prior(ch.versions[view])
            ranked.append((s, ch))
        ranked.sort(key=lambda x: (-x[0], x[1].cid))
        return ranked[:k]
