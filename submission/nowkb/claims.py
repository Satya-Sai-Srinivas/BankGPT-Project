"""Non-rate facts extracted per view: branches, hours, org statistics, dated events, contacts, links.

Organisation-wide statements (branch count, members, counties...) are resolved by
*newest dated statement wins* — never by how many pages repeat a number (23 appears on more
pages than the current 22).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .pages import PageVersion
from .text import canon_url, links, norm_dashes, parse_date, plain, prose_sentences

DAY = r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day"
_HOURS_LINE = re.compile(rf"^\s*({DAY}(?:\s?(?:-|–|through|to|and|&)\s?{DAY})?)\s*:\s*(.+?)\s*$")
_BLOCK = re.compile(r"^\*\*\s*(Lobby|Drive[- ]?(?:up|thru|through))\s*\*\*\s*(.*)$", re.I)
_DATELINE = re.compile(r"^([A-Z][A-Z .']{2,30}),\s+(Iowa|Ill\.?|Illinois|Wis\.?|Wisconsin|IA|IL|WI)(?![a-z])")
_STREET = re.compile(
    r"\b(\d{2,5})\s+((?:[NSEW]\.?\s)?[A-Z][\w.']*(?:\s[A-Z0-9][\w.']*){0,4}?)\s"
    r"(St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Boulevard|Ln|Lane|Way|Hwy|Highway|Ct|Court|Plaza|Pkwy|Parkway)\.?(?=[\s,.;)]|$)"
)
_LOCATOR = re.compile(r"^(\d{2,6}\s[^,]{2,60}),\s*([A-Za-z .]{2,40}),\s*(IA|IL|WI|MN),\s*(\d{5})")
_DROPDOWN_CITIES = ("Asbury|Carroll|Cedar Falls|Cedar Rapids|Coralville|Dubuque|Dyersville|Galena|Grimes|Madison|"
                    "Manchester|Marion|Peosta|Platteville|Waterloo|Waukee|Dodgeville|Epworth|Cascade|Monticello")
_DROPDOWN = re.compile(rf"({_DROPDOWN_CITIES}): (.+?)(?=(?:{_DROPDOWN_CITIES}): |$)")


@dataclass
class Branch:
    name: str
    city: str = ""
    street: str = ""
    address: str = ""
    phone: str = ""
    lobby: dict = field(default_factory=dict)       # day-range -> hours text
    drive_up: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)     # PageVersion
    closed_on: Optional[date] = None
    closing_note: str = ""


@dataclass
class Stat:
    name: str              # branches | members | counties | employees | assets
    value: float
    display: str
    sentence: str
    page: PageVersion
    when: date


@dataclass
class Event:
    sentence: str
    when: date             # the event date (e.g. closing date)
    published: Optional[date]
    page: PageVersion
    kind: str              # close | open


@dataclass
class Claims:
    branches: list[Branch] = field(default_factory=list)
    stats: dict[str, list[Stat]] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    routing: list[tuple[str, PageVersion]] = field(default_factory=list)
    main_phone: list[tuple[str, PageVersion]] = field(default_factory=list)
    link_lines: list[tuple[str, str, str, PageVersion]] = field(default_factory=list)  # (line, anchor, target, page)
    fees: list[tuple[str, str, PageVersion]] = field(default_factory=list)              # (fee name, amount, page)
    inlinks: Counter = field(default_factory=Counter)

    def latest(self, name: str) -> Optional[Stat]:
        xs = self.stats.get(name) or []
        return max(xs, key=lambda s: (s.when, s.page.authority, s.page.url)) if xs else None


def _schedule(lines: list[str], start: int) -> tuple[dict, dict]:
    """Parse **Lobby** / **Drive-up** blocks that follow `start`."""
    lobby, drive = {}, {}
    cur = None
    blanks = 0
    for i in range(start, min(start + 30, len(lines))):
        s = lines[i].strip()
        if not s:
            blanks += 1
            if blanks > 2 and cur is not None:
                break
            continue
        blanks = 0
        m = _BLOCK.match(s)
        if m:
            cur = lobby if m.group(1).lower().startswith("lobby") else drive
            rest = m.group(2).strip()
            if rest:
                hm = _HOURS_LINE.match(rest)
                if hm:
                    cur[norm_dashes(hm.group(1))] = hm.group(2)
            continue
        hm = _HOURS_LINE.match(s)
        if hm and cur is not None:
            cur[norm_dashes(hm.group(1))] = hm.group(2)
            continue
        if cur is not None and (lobby or drive):
            break
    return lobby, drive


def extract(pages: dict[str, list[PageVersion]], view_date: date) -> Claims:
    c = Claims()
    branches: dict[str, Branch] = {}

    def get_branch(name: str) -> Branch:
        k = name.lower()
        if k not in branches:
            branches[k] = Branch(name=name)
        return branches[k]

    for key, pvs in pages.items():
        for pv in pvs:
            if pv.ptype in ("listing", "junk", "expired"):
                continue
            text = pv.text
            lines = text.split("\n")
            # ---- links (for "what's the URL for ..." questions)
            if pv.ptype not in ("calculator",):
                for line in lines:
                    if "](" not in line:
                        continue
                    for anchor, target in links(line):
                        if not target.startswith("http") or "tel:" in target or "mailto:" in target:
                            continue
                        c.link_lines.append((plain(line)[:300], anchor, target, pv))
                        c.inlinks[canon_url(target)] += 1
            # ---- fee schedule rows ("|Domestic wire|$25.00 each|" or "Stop payment ... $30.00* per item")
            if pv.ptype == "fee_doc" or re.search(r"(?i)\bfee schedule\b|/fees?$", pv.url):
                for line in lines:
                    st = line.strip()
                    if st.startswith("|"):
                        cells = [x.strip() for x in st.strip("|").split("|")]
                        if len(cells) >= 2 and "$" in cells[1] and not cells[0].startswith("$"):
                            c.fees.append((plain(cells[0]), plain(cells[1]).replace("*", "").strip(), pv))
                        continue
                    m = re.match(r"^([A-Za-z][^$:|]{3,90}?)\s*:?\s*(\$\d[\d,.]*\*?(?:\s?(?:per|each|for)[^.;]{0,40})?)", plain(st))
                    if m:
                        c.fees.append((m.group(1).strip(), m.group(2).replace("*", "").strip(), pv))
            # ---- routing number / main phone
            for m in re.finditer(r"(?i)routing(?: number)?\W{0,5}(?:is\W{0,3})?(\d{9})\b", text):
                c.routing.append((m.group(1), pv))
            for m in re.finditer(r"\*\*Phone:\*\*\s*\[?(\d{3}-\d{3}-\d{4})", text):
                c.main_phone.append((m.group(1), pv))
            # ---- contact-page locator: "### Dupaco Credit Union / Dupaco Branch / 3299 Hillcrest Rd., Dubuque, IA, 52001"
            for i, line in enumerate(lines):
                if line.strip() == "Dupaco Branch" and i + 1 < len(lines):
                    nxt = next((x.strip() for x in lines[i + 1:i + 4] if x.strip()), "")
                    m = _LOCATOR.match(nxt)
                    if m:
                        street, city = m.group(1).strip(), m.group(2).strip()
                        b = get_branch(f"{city}: {street}")
                        b.city, b.street = city, street
                        b.address = f"{m.group(1)}, {m.group(2)}, {m.group(3)} {m.group(4)}"
                        b.sources.append(pv)
            # ---- branch dropdown on a blog page ("Select a BranchAsbury: Saratoga Rd.Carroll: W Hwy 30...")
            for line in lines:
                if "Select a Branch" in line:
                    body = line.split("Select a Branch", 1)[1]
                    for m in _DROPDOWN.finditer(body):
                        city, street = m.group(1), m.group(2).strip()
                        b = get_branch(f"{city}: {street}")
                        b.city = b.city or city
                        b.street = b.street or street
                        b.sources.append(pv)
            # ---- branch-opening releases with hours
            for i, line in enumerate(lines):
                if _BLOCK.match(line.strip()):
                    lobby, drive = _schedule(lines, i)
                    if not (lobby or drive):
                        continue
                    city, street, phone = "", "", ""
                    for l2 in lines[:i]:
                        dm = _DATELINE.match(plain(l2))
                        if dm and not city:
                            city = dm.group(1).title()
                        sm = _STREET.search(l2)
                        if sm and not street:
                            street = f"{sm.group(1)} {sm.group(2)} {sm.group(3)}."
                        pm = re.search(r"\(?\d{3}\)?[ -]\d{3}-\d{4}", l2)
                        if pm and "phone number" in l2.lower():
                            phone = pm.group(0)
                    b = get_branch(f"{city or pv.title}: {street}" if street else (city or pv.title))
                    b.city = b.city or city
                    b.street = b.street or street
                    b.phone = b.phone or phone
                    if not b.lobby:
                        b.lobby = lobby
                    if not b.drive_up:
                        b.drive_up = drive
                    b.sources.append(pv)
                    break
            # ---- organisation statistics in dated releases (press-release "About Dupaco" tails etc.)
            when = pv.pub_date
            if pv.ptype == "pdf":
                am = re.search(r"As of:?\s*([A-Z][a-z]+\.? \d{1,2}, \d{4})", text)
                when = parse_date(am.group(1)) if am else None
            if pv.ptype in ("newsroom", "pdf") and when:
                for s in prose_sentences(text):
                    if len(s) > 400:
                        continue
                    for name, rx in _STAT_PATTERNS:
                        m = rx.search(s)
                        if m:
                            grp = next(g for g in m.groups() if g)
                            raw = grp.replace(",", "")
                            try:
                                v = float(raw)
                            except ValueError:
                                continue
                            c.stats.setdefault(name, []).append(Stat(name, v, grp, s, pv, when))
            # ---- dated events: closures
            if pv.ptype in ("newsroom", "about", "contact", "product", "home"):
                for s in prose_sentences(text):
                    if len(s) > 400:
                        continue
                    m = re.search(r"(?i)\b(will close|closing|closed|last day[^.]{0,40}?(?:will be|is|was))\b[^.]{0,40}?"
                                  r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, \d{4})", s)
                    if m:
                        d = parse_date(m.group(2))
                        if d:
                            c.events.append(Event(s, d, pv.pub_date, pv, "close"))
    # merge dropdown-only entries ("Galena: Oldenburg Ln.") into richer ones ("Galena: 11375 Oldenburg Ln.")
    merged: list[Branch] = []
    for b in sorted(branches.values(), key=lambda b: (-(bool(b.address) + bool(b.lobby) + bool(b.phone)), b.name)):
        bt = {w for w in re.findall(r"[a-z]{4,}", (b.street or "").lower())} - {"road", "street", "drive", "avenue", "highway", "business"}
        tgt = next((m for m in merged if m.city == b.city and bt and bt & {w for w in re.findall(r"[a-z]{4,}", (m.street or "").lower())}), None)
        if tgt:
            tgt.sources.extend(b.sources)
            for attr in ("address", "phone"):
                if not getattr(tgt, attr) and getattr(b, attr):
                    setattr(tgt, attr, getattr(b, attr))
            if not tgt.lobby and b.lobby:
                tgt.lobby = b.lobby
            if not tgt.drive_up and b.drive_up:
                tgt.drive_up = b.drive_up
        else:
            merged.append(b)
    c.branches = merged
    return c


_STAT_PATTERNS = [
    ("branches", re.compile(r"(?i)(?<![\d,.$])\b(\d{1,2}) (?:full-service )?branch(?: office)?(?: locations| offices|es)\b")),
    ("branches", re.compile(r"(?i)\boperates (\d{1,3}) branches\b")),
    ("members", re.compile(r"(?i)membership (?:has grown to|of|tops|exceeds) (?:more than |nearly |over |almost )?(\d{2,3},\d{3})|\b(\d{2,3},\d{3}) members\b|Members:\s*(\d{2,3},\d{3})")),
    ("counties", re.compile(r"(?i)\b(\d{2,3}) counties\b")),
    ("employees", re.compile(r"(?i)\b(?:it has|dupaco has) (?:over|more than|nearly|almost) (\d{3,4}) employees\b")),
    ("assets", re.compile(r"(?i)\$(\d{1,2}(?:\.\d{1,2})?) billion in assets|assets (?:exceeding|of nearly|of more than|of) \$(\d{1,2}(?:\.\d{1,2})?) billion")),
]
