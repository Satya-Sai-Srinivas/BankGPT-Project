"""Structured handlers for non-rate questions: hours, branches, counts, events, links, routing."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Optional

from .claims import Branch, Claims, dept_name
from .kb import View
from .query import QueryFrame
from .text import canon_url, fmt_date, norm_dashes, plain, stem, tokens

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


# A date in the question picks the snapshot (see Answerer.answer); it is not part of what is counted.
_DATE_WORDS = set(tokens("january february march april may june july august september october november december "
                         "jan feb mar apr jun jul aug sep sept oct nov dec did back then"))


def stat_answer(view: View, fr: QueryFrame) -> Optional[object]:
    if "count" not in fr.intents and not re.search(r"\bhow big\b|\bassets\b", fr.norm):
        return None
    c: Claims = view.claims
    allowed = set(tokens("many number total current currently now today dupaco branch branches location locations "
                         "office offices member members employee employees staff county counties assets asset big "
                         "operate operates operating physical membership full-service service services have has "
                         "serve serves run runs open"))
    content = {t for t in set(tokens(fr.norm)) - allowed - _DATE_WORDS if not re.fullmatch(r"(?:19|20)\d\d", t)}
    if content:
        return None          # "how many employees used Volunteer Time Off" is not an org-size question
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
    if not c.events or not re.search(r"\bclos|\bopen\b|\bstill\b|\blast day\b|\bhappen|\bshut", fr.norm):
        return None
    if not re.search(r"^(when|is|was|did|has|does|what date|what day)\b|\bstill\b|\bclosing date\b|\blast day\b|"
                     r"\bhappen|\bshut", fr.norm):
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
        if re.search(r"\bstill\b|\bopen\b", fr.norm):
            lead = "No — "
        elif re.search(r"^(?:is|are|will)\b.*\bclos", fr.norm):
            lead = "It has already closed: "
        else:
            lead = ""
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
LINK_STOP = {stem(w) for w in ("link", "url", "use", "see", "should", "find", "page", "website", "web", "site",
                               "online", "where", "go", "dupaco", "how", "can", "get", "show", "list", "display")}


def link_answer(view: View, fr: QueryFrame) -> Optional[object]:
    """Canonical URL for an intent: anchor/target relevance (line context weighted lower) x in-link
    popularity on current pages; www.dupaco.com targets that are not in the crawl are legacy links."""
    c: Claims = view.claims
    qt = set(tokens(fr.norm)) - LINK_STOP
    syn = {tokens(a)[0]: tokens(b)[0] for a, b in (("membership", "join"), ("member", "join"), ("apply", "join"),
                                                    ("locator", "contact"), ("atm", "location"), ("branch", "location"))}
    if re.search(r"\b(membership|member|join)\b", fr.norm):
        qt = {syn.get(t, t) for t in qt}
    if not qt:
        return None
    scores: dict[str, float] = defaultdict(float)
    examples: dict[str, tuple] = {}
    for line, anchor, target, pv in c.link_lines:
        if not _HOST_OK.match(target):
            continue
        tgt = _clean_target(target)
        key = canon_url(tgt)
        if key in ("https://dupaco.com/", "https://dupaco.com"):
            continue
        if key.startswith("https://dupaco.com/") and key not in view.pages:
            continue                               # legacy link to a page that no longer exists
        at = set(tokens(anchor)) | set(tokens(" ".join(re.split(r"[/#.\-_]", tgt.split("//", 1)[-1]))))
        lt = set(tokens(line))
        s = (len(qt & at) + 0.3 * len(qt & (lt - at))) / len(qt)
        if s > scores[tgt]:
            scores[tgt] = s
            examples[tgt] = (line, pv)
    if not scores:
        return None
    ranked = sorted(scores.items(), key=lambda kv: (-(kv[1] * math.log(3 + c.inlinks[canon_url(kv[0])])), kv[0]))
    best_url, best_s = ranked[0]
    if best_s < 0.5:
        return None
    line, pv = examples[best_url]
    text = f"Use {best_url}"
    second = next((u for u, s2 in ranked[1:4] if s2 >= best_s - 1e-9 and canon_url(u) != canon_url(best_url)), None)
    if second and re.search(r"\bjoin\b", fr.norm):
        text += f" (more about joining: {second})"
    return _draft(text + ".", [(best_url, view.sid, line[:200]), (pv.url, view.sid, line[:200])],
                  trace=f"link: score={best_s:.2f}")


def _clean_target(t: str) -> str:
    t = t.strip()
    t = re.sub(r"[?&]hsLang=en", "", t)
    if "#" in t:
        base, frag = t.split("#", 1)
        if not re.fullmatch(r"[a-z]{2,12}", frag):
            t = base
    return t


# ---------------------------------------------------------------------------------------------
# Membership eligibility
# ---------------------------------------------------------------------------------------------
def eligibility_answer(kb, view: View, fr: QueryFrame) -> Optional[object]:
    if not re.search(r"\beligib|\bwho can (?:join|become)|\bqualif\w* (?:for|to) (?:join|membership)|\bcan i join\b|"
                     r"\b(?:how much|minimum|deposit|requirements?|need)\b.*\b(?:join|membership|become a member)\b|"
                     r"\b(?:join|membership|become a member)\b.*\b(?:how much|minimum|deposit|require\w*)\b", fr.norm):
        return None
    best = None
    for ch in kb.index.chunks:
        if not ch.mask & (1 << view.idx):
            continue
        if re.search(r"(?i)eligible|who can join", ch.heading) and "- " in ch.text:
            pv = ch.versions[view.idx]
            if best is None or pv.authority > best[1].authority:
                best = (ch, pv)
    if not best:
        return None
    ch, pv = best
    items = [plain(l.lstrip("-* ")) for l in ch.text.split("\n") if l.lstrip().startswith(("- ", "* "))]
    text = "You're eligible to join Dupaco if any of these apply: " + "; ".join(i.rstrip(".") for i in items[:5]) + "."
    srcs = [(pv.url, view.sid, "; ".join(items)[:200])]
    st = view.claims.latest("counties")
    if st:
        m = re.search(r"serves residents in [^.]*", st.sentence)
        if m:
            text += f" The charter area: Dupaco {m.group(0).rstrip('.')}."
            srcs.append((st.page.url, view.sid, st.sentence[:200]))
    tail = re.search(r"To join Dupaco[^.]*\.", ch.text)
    if tail:
        text += " " + plain(tail.group(0))
    return _draft(text, srcs, trace="eligibility")


# ---------------------------------------------------------------------------------------------
# Contacting Dupaco / updating account details
# ---------------------------------------------------------------------------------------------
_CONTACT_Q = re.compile(r"\b(update|change|correct)\b.*\b(address|phone|email|contact|information|info|name)\b|"
                        r"\bhow (?:do|can) i (?:contact|reach|call|get in touch)\b|\bcontact (?:dupaco|you|customer service)\b")


def contact_answer(view: View, fr: QueryFrame) -> Optional[object]:
    if not _CONTACT_Q.search(fr.norm):
        return None
    pvs = view.pages.get("https://dupaco.com/contact") or []
    mp = main_phone(view)
    if not pvs or not mp:
        return None
    pv = pvs[0]
    from .text import prose_sentences
    picks = [s for s in prose_sentences(pv.text) if re.search(r"Contact Us|Shine|call us", s)][:2]
    text = " ".join(picks) if picks else ""
    if mp[0] not in text:
        text += f" You can also call Dupaco at {mp[0]}."
    text = re.sub(r"\s+", " ", text).strip()
    return _draft(text, [(pv.url, view.sid, text[:200])], trace="contact")


# ---------------------------------------------------------------------------------------------
# Fees (rate & fee schedule)
# ---------------------------------------------------------------------------------------------
FEE_STOP = {"fee", "much", "cost", "charge", "price", "pay", "do", "for", "what", "how", "is", "the", "a"}
# Member wording -> fee-schedule wording ("cashier's check" is listed as "Official check").
FEE_SYNONYMS = [
    (re.compile(r"\b(?:cashier'?s?|teller'?s?|bank) checks?\b"), "official check"),
    (re.compile(r"\bwire (?:money|funds)\b"), "wire"),
]
_OUTGOING = re.compile(r"\b(?:outgoing|outbound|send(?:ing)?|sent)\b")
_WEAK_FEE_TOKENS = set(tokens("transfer fee fees charge charges service item items each per"))
# Words that make two fees different fees ("Free Checking" is not "Analysis checking monthly fee").
_FEE_QUALIFIERS = set(tokens("free analysis 1st first business consumer personal lost replacement replace stolen "
                             "international domestic incoming outgoing foreign rush expedited"))


def _amount_key(amount: str) -> str:
    """'$0.50 per transaction/balance inquiry (ATM surcha' -> '$0.50' (two copies of the schedule differ in tails)."""
    m = re.search(r"\$\s?[\d,]+(?:\.\d+)?", amount)
    return m.group(0).replace(" ", "") if m else amount.strip().lower()


def fee_answer(view: View, fr: QueryFrame) -> Optional[object]:
    c: Claims = view.claims
    if not c.fees or not re.search(r"\bfees?\b|\bcharge\b|\bcost\b|\bhow much\b|\bprice\b", fr.norm):
        return None
    if fr.rate_q and fr.family:
        return None
    norm = fr.norm
    for rx, rep in FEE_SYNONYMS:
        norm = rx.sub(rep, norm)
    outgoing = bool(_OUTGOING.search(norm)) and "wire" in norm
    if outgoing:
        norm = _OUTGOING.sub(" ", norm)       # an outgoing wire is a domestic or an international wire
    qt = set(tokens(norm)) - FEE_STOP
    if not qt:
        return None
    distinct = _FEE_QUALIFIERS
    best = []
    for name, amount, pv in c.fees:
        nt = set(tokens(name))
        if outgoing and "incomi" in nt:
            continue
        ov = len(qt & nt)
        if ov == 0 or (qt - nt) & distinct:
            continue          # "Free Checking" must not match "Analysis checking monthly fee"
        sc = ov / len(qt) - 0.02 * max(0, len(nt) - ov)
        if "busine" in nt and "busine" not in qt:
            sc -= 0.05
        best.append((sc, -pv.authority, name, amount, pv))
    if not best:
        return None
    best.sort(key=lambda x: (-x[0], x[1], x[2]))
    sc, _, name, amount, pv = best[0]
    if sc < 0.6:
        return None
    # An unqualified question ("wire transfer fee") covers every variant of that fee with a different amount
    # (incoming, domestic, international); a qualified one ("domestic wire") keeps only its own row.
    core = (qt & set(tokens(name))) - _WEAK_FEE_TOKENS
    rows, seen = [], set()
    for s2, _, n2, a2, p2 in best:
        akey = (_amount_key(a2), tuple(sorted(set(tokens(n2)) - core)))
        if n2 in seen or akey in seen or not core or not core <= set(tokens(n2)):
            continue
        if (set(tokens(n2)) - set(tokens(name))) & (qt - core):
            continue
        if not all(t in _FEE_QUALIFIERS or t in _WEAK_FEE_TOKENS or re.fullmatch(r"\d+|x", t)
                   for t in set(tokens(n2)) - core):
            continue          # a variant differs only by a qualifier or size; "past due late fee" is another charge
        seen.update((n2, akey))
        rows.append((n2, a2, p2))
    if len({_amount_key(a) for _, a, _ in rows}) < 2:
        rows = [(name, amount, pv)]
    rows = rows[:6]
    eff = re.search(r"(?i)effective ([A-Z][a-z]+\.? \d{1,2}, \d{4})", pv.text)
    text = "; ".join(f"{n}: {a}" for n, a, _ in rows) + \
        (f" (Rate and Fee Schedule, effective {eff.group(1)})" if eff else "") + "."
    return _draft(text, [(p.url, view.sid, f"{n} {a}") for n, a, p in rows[:1]] +
                  [(p.url, view.sid, f"{n} {a}") for n, a, p in rows[1:]], trace=f"fee: {sc:.2f} rows={len(rows)}")


# ---------------------------------------------------------------------------------------------
# Awards ("Has Forbes ranked Dupaco?")
# ---------------------------------------------------------------------------------------------
_RECOGNITION = re.compile(r"\b(award\w*|recogni\w*|rank\w*|named|honou?r\w*|list\w*|top|best)\b")


def award_answer(view: View, fr: QueryFrame) -> Optional[object]:
    """Recognition by a named organisation: the running count in its newest release ('the fifth time
    Forbes recognized Dupaco'), never an older release's count."""
    c: Claims = view.claims
    if not c.awards or not _RECOGNITION.search(fr.norm):
        return None
    orgs = [o for o in c.awards if o.lower() in fr.norm]
    if not orgs:
        return None
    a = c.latest_award(orgs[0])
    if a is None:
        return None
    text = f"{a.quote} (newest {a.org} release: {fmt_date(a.published)})."
    return _draft(text, [(a.page.url, view.sid, a.quote[:200])], trace=f"award: {a.org} {a.ordinal}")


# ---------------------------------------------------------------------------------------------
# Department phone numbers ("What number do I call about a mortgage?")
# ---------------------------------------------------------------------------------------------
_PHONE_Q = re.compile(r"\b(phone|call|telephone|number to call|reach|talk to|speak (?:to|with))\b")
_DEPT_STOP = set(tokens("phone number call calling contact reach telephone talk speak dupaco department team line "
                        "someone person directly ext extension toll free general main"))


def phone_answer(view: View, fr: QueryFrame) -> Optional[object]:
    """Toll-free number for a department: the extension stated next to that topic on current pages, on
    Dupaco's main line (an extension on a different base number is a typo on the site, see conflicts)."""
    c: Claims = view.claims
    if not _PHONE_Q.search(fr.norm) or fr.intents & {"routing", "hours", "address"}:
        return None
    if re.search(r"\b(update|change|correct)\b", fr.norm):
        return None                                  # handled by contact_answer
    mp = main_phone(view)
    qt = set(tokens(fr.norm)) - _DEPT_STOP
    if not qt:
        if not mp or _CONTACT_Q.search(fr.norm):
            return None                              # "how do I contact you" -> contact_answer
        return _draft(f"You can call Dupaco at {mp[0]}.", [(mp[1].url, view.sid, f"Phone: {mp[0]}")], trace="phone: main")
    if not c.dept_phones:
        return None
    scored: dict[tuple, list] = defaultdict(list)
    for d in c.dept_phones:
        if not d.ext:
            continue
        ctx = set(tokens(d.sentence)) | set(tokens(d.page.title)) | set(tokens(d.page.url.replace("-", " ")))
        ov = len(qt & set(tokens(d.sentence))) + 0.5 * len(qt & (ctx - set(tokens(d.sentence))))
        if ov > 0:
            scored[(d.number, d.ext)].append((ov / len(qt), d))
    if not scored:
        return None
    best = max(scored.items(), key=lambda kv: (max(s for s, _ in kv[1]), len({d.page.url for _, d in kv[1]})))
    (number, ext), hits = best
    if max(s for s, _ in hits) < 0.5:
        return None
    s, d = max(hits, key=lambda h: (h[0], h[1].page.authority, h[1].page.url))
    dept = dept_name(d.sentence)
    src = d
    if mp and number != mp[0]:
        # The same extension on Dupaco's main line wins over a stray base number for it.
        on_main = [x for x in c.dept_phones if x.number == mp[0] and x.ext == ext]
        if on_main:
            number = mp[0]
            src = max(on_main, key=lambda x: (len(qt & set(tokens(x.page.title + " " + x.page.url.replace("-", " ")))),
                                              x.page.authority, x.page.url))
    who = f"Dupaco's {dept}" if dept else "Dupaco"
    return _draft(f"You can reach {who} at {number}, ext. {ext}.", [(src.page.url, view.sid, src.sentence[:200])],
                  trace=f"phone: dept {number} x{ext}")
