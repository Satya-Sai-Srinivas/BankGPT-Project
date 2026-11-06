"""Structured handlers for non-rate questions: hours, branches, counts, events, links, routing."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Optional

from .claims import Branch, Claims
from .kb import View
from .query import QueryFrame
from .text import canon_url, fmt_date, norm_dashes, plain, tokens

GENERIC_WORDS = {"branch", "location", "office", "dupaco", "hour", "lobby", "drive", "drive-up", "open", "close",
                 "closed", "address", "located", "credit", "union", "what", "time", "today", "still", "member",
                 "street", "avenue", "ave", "road", "st", "rd", "go", "full-s", "servic", "bankin"}


def _draft(text: str, sources: list, note: Optional[str] = None, trace: str = ""):
    from .answer import Draft
    d = Draft(text=text, sources=sources, note=note)
    if trace:
        d.trace.append(trace)
    return d


def _refuse(reason: str):
    from .answer import refusal
    return refusal(reason)


# ---------------------------------------------------------------------------------------------
# Branch lookup
# ---------------------------------------------------------------------------------------------
def find_branches(claims: Claims, fr: QueryFrame) -> tuple[list[Branch], bool]:
    """Branches named in the question. Returns (matches, named) where named=True if the question
    names a specific place (city/street/landmark) at all."""
    q = norm_dashes(fr.raw.lower())
    qt = set(tokens(q)) - GENERIC_WORDS
    matches = []
    for b in claims.branches:
        bt = set(tokens(f"{b.city} {b.street}")) - GENERIC_WORDS
        if not bt:
            continue
        ov = qt & bt
        if ov:
            matches.append((len(ov) / len(bt), b))
    matches.sort(key=lambda x: -x[0])
    best = [b for s, b in matches if s >= matches[0][0] - 1e-9] if matches else []
    named = bool(re.search(r"\b(?:the |our )?([A-Z][a-z]+(?:[ -][A-Z][a-z]+)?) (?:branch|office|location)\b", fr.raw)) \
        or bool(re.search(r"\b(?:in|at) [A-Z][a-z]+", fr.raw)) or bool(best)
    return best, named


def _fmt_sched(s: dict) -> str:
    return "; ".join(f"{k}: {v}" for k, v in s.items())


def _sched_key(s: dict) -> tuple:
    return tuple((k, norm_dashes(v)) for k, v in s.items())


def _branch_label(b: Branch) -> str:
    return b.city or b.name.split(":")[0]


def hours_answer(view: View, fr: QueryFrame) -> Optional[object]:
    c: Claims = view.claims
    want_drive = "drive_up" in fr.intents and "lobby" not in fr.intents
    attr = "drive_up" if want_drive else "lobby"
    matches, named = find_branches(c, fr)
    if matches:
        withh = [b for b in matches if getattr(b, attr)]
        if not withh:
            name = matches[0].street or matches[0].city
            return _refuse(f"branch {name} known but no {attr} hours published")
        b = withh[0]
        sched = getattr(b, attr)
        where = f"{b.city} branch ({b.street.rstrip('.')})" if b.street else f"{b.city} branch"
        label = "Drive-up" if want_drive else "Lobby"
        return _draft(f"{label} hours at the {where}: {_fmt_sched(sched)}.",
                      [(p.url, view.sid, _fmt_sched(sched)[:200]) for p in b.sources[:3]], trace="hours: branch")
    if named and re.search(r"\b(?:the )?[A-Z][a-z]+(?: [A-Z][a-z]+)? (?:Avenue|Ave|Street|St|Road|Rd|Drive|Dr)\b", fr.raw):
        return _refuse("named branch not found in the branch directory")
    groups: dict[tuple, list[Branch]] = defaultdict(list)
    for b in c.branches:
        s = getattr(b, attr)
        if s:
            groups[_sched_key(s)].append(b)
    if not groups:
        return None
    ordered = sorted(groups.values(), key=lambda bs: (-len(bs), _branch_label(bs[0])))
    label = "drive-up" if want_drive else "lobby"
    parts = []
    for bs in ordered:
        names = ", ".join(dict.fromkeys(_branch_label(b) for b in bs))
        parts.append(f"{_fmt_sched(getattr(bs[0], attr))} ({names})")
    head = f"{label.capitalize()} hours vary by branch."
    if len(ordered) > 1:
        head += f" Typical {label} hours: {parts[0]}. Other branches: " + " | ".join(parts[1:]) + "."
    else:
        head += f" {parts[0]}."
    head += " Tell me which branch (or all branches) and I can narrow it down; the branch locator is at https://www.dupaco.com/contact."
    srcs = [("https://www.dupaco.com/contact", view.sid, "Find a location near you (branch and ATM locator)")]
    for bs in ordered:
        for b in bs:
            for p in b.sources[:1]:
                srcs.append((p.url, view.sid, _fmt_sched(getattr(b, attr))[:200]))
    return _draft(head, srcs[:8], trace=f"hours: {len(ordered)} schedules")


def address_answer(view: View, fr: QueryFrame) -> Optional[object]:
    c: Claims = view.claims
    matches, named = find_branches(c, fr)
    withaddr = [b for b in matches if b.address]
    if withaddr:
        b = withaddr[0]
        return _draft(f"The {b.city} branch is at {b.address}.",
                      [(p.url, view.sid, b.address) for p in b.sources[:3]], trace="address")
    if matches:
        b = matches[0]
        if b.street:
            return _draft(f"The {b.city} branch is on {b.street.rstrip('.')} in {b.city}. "
                          f"For the full address and hours, use the branch locator at https://www.dupaco.com/contact.",
                          [(p.url, view.sid, b.street) for p in b.sources[:2]], trace="address: partial")
    return None


# ---------------------------------------------------------------------------------------------
# Organisation statistics
# ---------------------------------------------------------------------------------------------
STAT_CUES = [
    ("branches", r"\bbranch(?:es)?\b|\blocations\b|\boffices\b"),
    ("members", r"\bmembers?\b|\bmembership\b"),
    ("employees", r"\bemployees\b|\bstaff\b|\bpeople work\b"),
    ("counties", r"\bcounties\b"),
    ("assets", r"\bassets\b|\bhow big\b"),
]


def stat_answer(view: View, fr: QueryFrame) -> Optional[object]:
    if "count" not in fr.intents and not re.search(r"\bhow big\b|\bassets\b", fr.norm):
        return None
    c: Claims = view.claims
    for name, rx in STAT_CUES:
        if re.search(rx, fr.norm):
            st = c.latest(name)
            if not st:
                return None
            when = fmt_date(st.when)
            phr = {
                "branches": f"Dupaco has {st.display} branch office locations",
                "members": f"Dupaco has more than {st.display} members",
                "employees": f"Dupaco has over {st.display} employees",
                "counties": f"Dupaco serves residents in {st.display} counties throughout Iowa, northwest Illinois and southwest Wisconsin",
                "assets": f"Dupaco has assets exceeding ${st.display} billion",
            }[name]
            older = sorted({s.display for s in c.stats.get(name, []) if s.display != st.display})
            note = (f"Older pages state {', '.join(older)}; the most recent dated statement ({st.page.url}, "
                    f"{st.when.isoformat()}) wins.") if older else None
            return _draft(f"{phr}, according to its most recent press release ({when}).",
                          [(st.page.url, view.sid, st.sentence[:200])], note=note, trace=f"stat: {name}")
    return None


# ---------------------------------------------------------------------------------------------
# Dated events (closures)
# ---------------------------------------------------------------------------------------------
def event_answer(view: View, fr: QueryFrame) -> Optional[object]:
    c: Claims = view.claims
    if not c.events or not re.search(r"\bclos|\bopen\b|\bstill\b|\blast day\b", fr.norm):
        return None
    qt = set(tokens(fr.raw)) - GENERIC_WORDS
    best = None
    for ev in c.events:
        et = set(tokens(ev.sentence + " " + ev.page.title + " " + ev.page.url.rsplit("/", 1)[-1].replace("-", " "))) - GENERIC_WORDS
        ov = len(qt & et)
        if ov and (best is None or (ov, ev.published or ev.when) > (best[0], best[1].published or best[1].when)):
            best = (ov, ev)
    if not best:
        return None
    ev = best[1]
    now = view.taken_on
    ref = fr.date_in_text if fr.date_in_text and fr.date_in_text > now else now
    date_txt = re.search(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, \d{4}", ev.sentence)
    dt = date_txt.group(0) if date_txt else ev.when.isoformat()
    subject = _event_subject(ev, fr)
    pub = f" (announced {fmt_date(ev.published)})" if ev.published else ""
    if ev.when <= ref:
        lead = "No — " if re.search(r"\bstill\b|^is\b|^are\b", fr.norm) else ""
        text = f"{lead}{subject} closed on {dt}{pub}."
    else:
        text = f"{subject} is scheduled to close on {dt}{pub}."
    return _draft(text, [(ev.page.url, view.sid, ev.sentence[:200])], trace="event")


def _event_subject(ev, fr: QueryFrame) -> str:
    m = re.search(r"\bthe ([A-Z][\w'-]+(?: [A-Z][\w'-]+)?) (branch|office|location)\b", fr.raw)
    if m:
        return f"The {m.group(1)} {m.group(2)}"
    t = re.search(r"plans ([\w-]+) branch closure|close ([A-Z][\w-]+) branch", ev.page.title, re.I)
    if t:
        return f"The {t.group(1) or t.group(2)} branch"
    return "The branch"


# ---------------------------------------------------------------------------------------------
# Routing number, phone
# ---------------------------------------------------------------------------------------------
def routing_answer(view: View, fr: QueryFrame) -> Optional[object]:
    c: Claims = view.claims
    if not c.routing:
        return None
    cnt = Counter(r for r, _ in c.routing)
    num = cnt.most_common(1)[0][0]
    pages = sorted({p.url: p for r, p in c.routing if r == num}.values(), key=lambda p: -p.authority)
    return _draft(f"Dupaco's routing number is {num}.", [(p.url, view.sid, f"Routing number: {num}") for p in pages[:6]],
                  trace="routing")


def main_phone(view: View) -> Optional[tuple[str, object]]:
    c: Claims = view.claims
    if not c.main_phone:
        return None
    cnt = Counter(p for p, _ in c.main_phone)
    num = cnt.most_common(1)[0][0]
    page = next(pv for p, pv in c.main_phone if p == num)
    return num, page


# ---------------------------------------------------------------------------------------------
# Canonical links
# ---------------------------------------------------------------------------------------------
_HOST_OK = re.compile(r"^https?://(?:[\w-]+\.)?dupaco\.com", re.I)
LINK_STOP = {"link", "url", "use", "see", "should", "find", "page", "website", "web", "site", "online", "where",
             "go", "dupaco", "how", "can", "get"}


def link_answer(view: View, fr: QueryFrame) -> Optional[object]:
    c: Claims = view.claims
    qt = set(tokens(fr.norm)) - LINK_STOP
    if not qt:
        return None
    scores: dict[str, float] = defaultdict(float)
    examples: dict[str, tuple] = {}
    for line, anchor, target, pv in c.link_lines:
        if not _HOST_OK.match(target):
            continue
        tgt = _clean_target(target)
        lt = set(tokens(line + " " + anchor)) | set(tokens(" ".join(re.split(r"[/#.\-_]", tgt.split("//", 1)[-1]))))
        ov = len(qt & lt)
        if ov == 0:
            continue
        s = ov / len(qt)
        if s > scores[tgt] - 1e-12:
            scores[tgt] = max(scores[tgt], s)
            examples[tgt] = (line, pv)
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: (-(kv[1] * math.log(3 + c.inlinks[canon_url(kv[0])])), kv[0]))
    best_url, best_s = ranked[0]
    if best_s < 0.5:
        return None
    urls = [best_url]
    for u, s in ranked[1:4]:
        if s >= best_s - 1e-9 and canon_url(u) != canon_url(best_url) and len(urls) < 2:
            urls.append(u)
    line, pv = examples[best_url]
    text = f"Use {urls[0]}" + (f" (see also {urls[1]})" if len(urls) > 1 else "") + "."
    return _draft(text, [(u, view.sid, examples[u][0][:200]) for u in urls] + [(pv.url, view.sid, line[:200])],
                  trace=f"link: score={best_s:.2f}")


def _clean_target(t: str) -> str:
    t = t.strip()
    t = re.sub(r"[?&]hsLang=en", "", t)
    if "#" in t:
        base, frag = t.split("#", 1)
        if not re.fullmatch(r"[a-z]{2,12}", frag):
            t = base
    return t
