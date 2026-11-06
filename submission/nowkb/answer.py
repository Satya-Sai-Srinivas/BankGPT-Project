"""Question answering: route a parsed question to a handler, render from resolved facts, guard."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .facts import Fact
from .kb import KnowledgeBase, View
from .lexicon import EXPANSIONS, FAMILY_KIND, FAMILY_NAME
from .pages import TIER1, PageVersion
from .query import QueryFrame, kind, parse
import math

from .text import fmt_date, fmt_money, plain, sentences, tokens

REFUSAL = "I don't know — that isn't listed on Dupaco's website. Please contact Dupaco directly for details."


@dataclass
class Draft:
    text: str
    sources: list[tuple[str, str, str]] = field(default_factory=list)   # (url, snapshot_id, quote)
    confident: bool = True
    note: Optional[str] = None
    trace: list[str] = field(default_factory=list)


def refusal(reason: str, frame: Optional[QueryFrame] = None) -> Draft:
    return Draft(text=REFUSAL, confident=False, trace=[f"refuse: {reason}"])


# =============================================================================================
# Rate tables
# =============================================================================================
FAMILY_GROUPS = {
    "checking": ["free_checking", "first_rate_checking"],
}


def _current_keys(view: View, families: list[str]) -> list[tuple[tuple, Fact]]:
    """(key, representative winner) for keys of these families that are current in the view."""
    fam_set = set(families)
    out = []
    tier1_fams = set()
    for key, attrs in view.by_key.items():
        if key[1] not in fam_set:
            continue
        w = next((attrs[a][0] for a in ("apy", "apr", "rate", "dividend", "points") if attrs.get(a)), None)
        if w is None:
            continue
        if w.page.tier1 and w.primary:
            tier1_fams.add(key[1])
        out.append((key, w))
    kept = []
    for key, w in out:
        if not (w.page.tier1 and w.primary):
            if key[1] in tier1_fams or w.page.ptype in ("calculator", "campaign", "landing", "expired"):
                continue
        kept.append((key, w))
    return kept


def select_rows(view: View, fr: QueryFrame, family: str) -> list[tuple[tuple, Fact]]:
    fams = FAMILY_GROUPS.get(family, [family])
    rows = _current_keys(view, fams)
    sel = []
    for key, f in rows:
        q = f.quals
        scope = key[0]
        if fr.scope and scope != fr.scope:
            continue
        if not fr.scope and scope == "business" and not (family == "credit_card" and "list" in fr.intents):
            if any(k[0] == "personal" for k, _ in rows):
                continue
        if fr.term and q.get("term") and q["term"] != fr.term:
            continue
        if fr.term and not q.get("term") and family in ("certificate", "auto_loan", "mortgage", "personal_loan"):
            continue
        if fr.jumbo and not q.get("jumbo"):
            continue
        if fr.special and family in ("certificate", "ira") and not q.get("special"):
            continue
        if fr.regular and family in ("certificate", "ira") and q.get("special"):
            continue
        if family == "ira" and fr.ira and q.get("ira") and q["ira"] != fr.ira:
            continue
        if family in ("mortgage",):
            want = fr.purpose or "purchase"
            if "home equity" in fr.norm and q.get("purpose") == "equity_refinance":
                pass
            elif q.get("purpose") != want:
                continue
        if fr.model_year and "my" in q:
            lo, hi = q["my"]
            if not (lo <= fr.model_year <= hi):
                continue
        if q.get("intro") and not re.search(r"\bintro|\bbalance transfer|\bpromo", fr.norm):
            continue
        if fr.amount is not None and FAMILY_KIND.get(family) == "deposit" and "bal" in q:
            lo, hi = q["bal"]
            if not (lo <= fr.amount <= hi):
                continue
        sel.append((key, f))
    # loan amount tiers: smallest cap that still covers the amount ("$150,000 loan" -> "$200,000 or less")
    if fr.amount is not None and any("amt" in f.quals for _, f in sel) and FAMILY_KIND.get(family) != "deposit":
        covering = [(k, f) for k, f in sel if f.quals.get("amt") and f.quals["amt"][0] <= fr.amount <= f.quals["amt"][1]]
        if covering:
            by_term: dict = {}
            for k, f in covering:
                t = f.quals.get("term", 0)
                if t not in by_term or f.quals["amt"][1] < by_term[t][1].quals["amt"][1]:
                    by_term[t] = (k, f)
            sel = list(by_term.values()) + [(k, f) for k, f in sel if "amt" not in f.quals]
    return sel


def _sort_rows(rows: list[tuple[tuple, Fact]]) -> list[tuple[tuple, Fact]]:
    def k(item):
        key, f = item
        q = f.quals
        return (
            0 if q.get("special") else 1,
            -(q.get("bal") or (0, 0))[0],
            q.get("my_ord", 0),
            q.get("term", 0) if FAMILY_KIND.get(f.family) != "mortgage" else -q.get("term", 0),
            (q.get("amt") or (0, 0))[1],
            0 if q.get("jumbo") else 1,
            q.get("ira", ""),
            f.label,
        )
    return sorted(rows, key=k)


def _val(view: View, key: tuple, attr: str) -> Optional[Fact]:
    return view.winner(key, attr)


def render_row(view: View, key: tuple, f: Fact, fr: QueryFrame) -> str:
    kd = FAMILY_KIND.get(f.family, "")
    label = _display_label(f)
    if kd == "deposit":
        apy = _val(view, key, "apy")
        div = _val(view, key, "dividend")
        parts = []
        if fr.attr == "dividend" and div:
            parts.append(f"{div.display} dividend rate")
            if apy:
                parts.append(f"{apy.display} APY")
        else:
            if apy:
                parts.append(f"{apy.display} APY")
            if div:
                parts.append(f"{div.display} dividend rate")
        if not parts:
            parts.append(f.display)
        main = parts[0] + (f" ({parts[1]})" if len(parts) > 1 else "")
        return f"{label}: {main}"
    if kd == "mortgage":
        rate = _val(view, key, "rate")
        apr = _val(view, key, "apr")
        bits = []
        if rate:
            bits.append(f"{rate.display} rate")
        if apr:
            bits.append(f"{apr.display} APR")
        return f"{label}: {' / '.join(bits) or f.display}"
    apr = _val(view, key, "apr") or f
    return f"{label}: {apr.display} APR"


def _display_label(f: Fact) -> str:
    lab = plain(f.label).replace(" · ", ", ")
    lab = re.sub(r"\s+", " ", lab).strip(" :")
    q = f.quals
    if f.family == "credit_card":
        name = q.get("card", "platinum visa").title().replace("Visa", "Visa")
        return name + (" (introductory balance transfer rate)" if q.get("intro") else "")
    if f.family == "certificate" and not q.get("special"):
        return f"{q.get('term')}-month certificate" + (" (business)" if q.get("scope") == "business" else "")
    if f.family in ("share_savings", "you_name_it", "holiday_club", "money_market", "high_yield", "hsa",
                    "first_rate_checking", "free_checking", "bright_savings", "launchpad"):
        name = FAMILY_NAME.get(f.family, f.family)
        if f.family == "money_market" and q.get("mm") == "achieve":
            name = "Achieve Money Market"
        tier = ""
        m = re.search(r"\$[\d,.]+\s*(?:[–-]\s*\$[\d,.]+|\+)", f.label)
        if m:
            tier = f" ({m.group(0)})"
        return name + tier
    return lab


def source_list(view: View, keys: list[tuple], limit: int = 6) -> list[tuple[str, str, str]]:
    """Every current page carrying the winning value(s), authority-ordered."""
    seen = {}
    for key in keys:
        for attr, obs in view.by_key.get(key, {}).items():
            if not obs:
                continue
            w = obs[0]
            for f in obs:
                if f.vkey != w.vkey or f.page.ptype in ("calculator", "campaign", "landing", "expired"):
                    continue
                u = f.page.url
                if u not in seen:
                    eff = f" (rates effective {f.effective.strftime('%m/%d/%Y')})" if f.effective else ""
                    seen[u] = (f.page.authority, (u, view.sid, plain(f.row)[:200] + eff))
    ranked = sorted(seen.values(), key=lambda x: -x[0])
    return [s for _, s in ranked[:limit]]


def stale_note(view: View, keys: list[tuple]) -> Optional[str]:
    notes = []
    for key in keys:
        for attr, obs in view.by_key.get(key, {}).items():
            if not obs:
                continue
            w = obs[0]
            for f in obs[1:]:
                if f.vkey != w.vkey:
                    notes.append(f"{f.page.url} still shows {f.display} ({f.page.ptype}"
                                 f"{', effective ' + f.effective.isoformat() if f.effective else ''}); "
                                 f"using {w.display} from {w.page.url}"
                                 f"{' (effective ' + w.effective.isoformat() + ')' if w.effective else ''}.")
    return " ".join(dict.fromkeys(notes))[:1200] or None


def rates_answer(view: View, fr: QueryFrame) -> Optional[Draft]:
    family = fr.family
    if not family:
        return None
    rows = select_rows(view, fr, family)
    if not rows:
        # A recognised product with a salient variant / term the tables do not carry -> not published.
        if fr.salient or fr.term or fr.jumbo or fr.model_year:
            return refusal(f"no {family} row for term={fr.term} jumbo={fr.jumbo} salient={fr.salient}")
        return None
    if fr.salient and family in ("mortgage", "heloc", "home_equity_loan", "certificate", "auto_loan"):
        return refusal(f"salient qualifier {fr.salient} not in any {family} row")
    rows = _sort_rows(rows)
    if "highest" in fr.intents and len(rows) > 1:
        def best(item):
            key, f = item
            w = _val(view, key, "apy") or _val(view, key, "apr") or f
            return w.value
        rows = [max(rows, key=best)]
    lines = [render_row(view, k, f, fr) for k, f in rows[:14]]
    keys = [k for k, _ in rows[:14]]
    name = FAMILY_NAME.get(family, family)
    if fr.pct_in_q and "yesno" in fr.intents:
        vals = {round(v, 2) for k, _ in rows for a in ("apy", "apr", "dividend", "rate")
                for f in [_val(view, k, a)] if f for v in [f.value]}
        hit = any(round(p, 2) in vals for p in fr.pct_in_q)
        lo = min(_val(view, k, "apy").value for k, _ in rows if _val(view, k, "apy")) if any(_val(view, k, "apy") for k, _ in rows) else None
        hi_row = max(rows, key=lambda r: (_val(view, r[0], "apy") or r[1]).value)
        lead = "Yes." if hit else f"No — none of the {name} tiers pays that rate."
        text = f"{lead} {name} rates: " + "; ".join(lines) + "."
        if not hit:
            text = f"No — {name} tiers top out at {render_row(view, hi_row[0], hi_row[1], fr).split(': ', 1)[1]} " \
                   f"({_display_label(hi_row[1])}). Current {name} rates: " + "; ".join(lines) + "."
            others = _others_with_value(view, fr.pct_in_q, exclude=family)
            if others:
                text += f" (Other accounts that do pay that rate: {others}.)"
    elif len(lines) == 1:
        text = lines[0].replace(": ", " — ", 1) + "."
    else:
        text = f"Current {name} rates — " + "; ".join(lines) + "."
    d = Draft(text=text, sources=source_list(view, keys), note=stale_note(view, keys))
    d.trace.append(f"rates: family={family} rows={len(rows)}")
    return d


def _others_with_value(view: View, pcts: list[float], exclude: str) -> str:
    names = []
    for key, attrs in view.by_key.items():
        if key[1] == exclude or key[0] != "personal":
            continue
        w = attrs.get("apy", [None])[0]
        if w and w.page.tier1 and any(abs(w.value - p) < 1e-6 for p in pcts):
            n = _display_label(w)
            if n not in names:
                names.append(n)
    return ", ".join(names[:4])


# =============================================================================================
# Generic retrieval + extractive answer
# =============================================================================================
def _prior(fr: QueryFrame):
    news_like = bool(fr.intents & {"award", "count", "when", "status"})

    def prior(p: PageVersion) -> float:
        a = {"rate_sheet": 1.0, "product": 1.0, "contact": 1.0, "home": 0.8, "about": 0.9, "fee_doc": 0.9,
             "newsroom": 0.85, "pdf": 0.6, "blog": 0.55, "biz_resource": 0.45, "calculator": 0.3,
             "campaign": 0.4, "landing": 0.3, "legal": 0.4, "expired": 0.05}.get(p.ptype, 0.6)
        if news_like and p.ptype == "newsroom" and p.pub_date:
            a *= 1.0 + 0.15 * max(0, p.pub_date.year - 2019)
        return a
    return prior


def _sentences(text: str) -> list[str]:
    out = []
    for line in text.split("\n"):
        if line.strip().startswith("|"):
            row = plain(line).replace("|", " ").strip()
            if row and not re.fullmatch(r"[-\s:]+", row):
                out.append(re.sub(r"\s{2,}", " ", row))
            continue
        p = plain(line)
        if p:
            out.extend(sentences(p))
    return [x for x in out if len(x) > 2]


_YEAR = re.compile(r"\b(?:in|during|for) (20\d\d)\b")
_ANSWER_TYPE = {
    "count": re.compile(r"\b\d[\d,]*\b"),
    "when": re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.? \d{1,2}|\b20\d\d\b"),
    "fee": re.compile(r"\$\d"),
}


def _sentence_score(s: str, qset: set, idf: dict, fr: QueryFrame) -> float:
    st = set(tokens(s))
    ov = qset & st
    if not ov:
        return 0.0
    sc = sum(idf.get(t, 1.0) for t in ov) / (sum(idf.get(t, 1.0) for t in qset) or 1.0)
    for intent, rx in _ANSWER_TYPE.items():
        if intent in fr.intents and rx.search(s):
            sc += 0.15
    if fr.rate_q and "%" in s:
        sc += 0.1
    if s.endswith("?"):
        sc -= 0.1          # an FAQ question restates the query; prefer its answer
    if len(s) < 25:
        sc -= 0.1
    if "dupaco" in fr.norm and "dupaco" in s.lower():
        sc += 0.08         # the question is about Dupaco itself, not the industry
    return sc


def generic_answer(kb: KnowledgeBase, view: View, fr: QueryFrame) -> Draft:
    q_toks = tokens(fr.norm)
    if not q_toks:
        return refusal("empty query")
    weights = {t: 1.0 for t in q_toks}
    for t in list(q_toks):
        for e in EXPANSIONS.get(t, []):
            weights.setdefault(e, 0.35)
    hits = kb.index.search(list(weights), view.idx, k=10, weights=weights, prior=_prior(fr))
    if not hits:
        return refusal("no retrieval hits")
    n = max(1, len(kb.index.chunks))
    idf = {t: math.log(1 + n / (1 + kb.index.df.get(t, 0))) for t in set(q_toks)}
    qset = set(q_toks)
    top = hits[0][0] or 1.0
    best = None
    for rank_i, (score, ch) in enumerate(hits[:6]):
        sents = _sentences(ch.text)
        head_ov = len(qset & set(tokens(ch.heading))) / max(1, len(qset))
        is_list = sum(1 for l in ch.text.split("\n") if l.lstrip().startswith(("- ", "* "))) >= 2
        if head_ov >= 0.5 and is_list:
            items = [plain(l.lstrip("-* ")) for l in ch.text.split("\n") if l.lstrip().startswith(("- ", "* "))]
            sc = 0.6 + head_ov + 0.35 * score / top
            if best is None or sc > best[0]:
                best = (sc, 0, [plain(ch.heading).rstrip(":") + ": " + "; ".join(items[:6]) + "."], ch)
        for i, s in enumerate(sents):
            sc = _sentence_score(s, qset, idf, fr)
            if sc <= 0:
                continue
            sc += 0.35 * score / top + 0.06 / (1 + ch.order) + 0.04 / (1 + i)
            if best is None or sc > best[0]:
                best = (sc, i, sents, ch)
    if best is None or best[0] < 0.55:
        return refusal(f"weak evidence ({best[0] if best else 0:.2f})")
    sc, i, sents, ch = best
    picked = [sents[i]]
    if sents[i].endswith("?") and i + 1 < len(sents):
        picked = [sents[i + 1]]
        i += 1
    j = i + 1
    while j < len(sents) and len(" ".join(picked)) < 260 and len(picked) < 3:
        nxt = sents[j]
        if nxt.endswith("?") or len(nxt) > 400:
            break
        picked.append(nxt)
        j += 1
    text = " ".join(picked)
    pv = ch.versions[view.idx]
    sources = [(pv.url, view.sid, text[:200])]
    # Year-qualified statistics reported in several releases are distinct facts: list them all.
    if _YEAR.search(text) and ("count" in fr.intents or "last year" in fr.norm):
        series = _year_series(kb, view, fr, text, weights)
        if series:
            text = series[0]
            sources += series[1]
    # A rate question answered by text with no rate in it means the rate is not published.
    if fr.rate_q and re.search(r"\b(rate|apr|apy|interest)\b", fr.norm) and "%" not in text \
            and not (fr.intents & {"how", "link", "list", "eligibility"}):
        return refusal("rate question but the evidence has no rate")
    if fr.intents & {"phone"} or re.search(r"\b(update|change)\b.*\b(address|phone|email|contact|information|name)\b", fr.norm):
        from .handlers import main_phone
        mp = main_phone(view)
        if mp and mp[0] not in text:
            text += f" You can also call Dupaco at {mp[0]}."
            sources.append((mp[1].url, view.sid, f"Phone: {mp[0]}"))
    d = Draft(text=text, sources=sources)
    d.trace.append(f"generic: {pv.url} score={sc:.2f}")
    return d


def _year_series(kb: KnowledgeBase, view: View, fr: QueryFrame, text: str, weights: dict):
    """Find the same statistic reported for other years (e.g. VTO users in 2023 and 2024)."""
    base = set(tokens(re.sub(r"\d[\d,]*", " ", text)))
    found = {}
    for score, ch in kb.index.search(list(weights), view.idx, k=25, weights=weights, prior=_prior(fr)):
        for s in _sentences(ch.text):
            ym = _YEAR.search(s)
            if not ym:
                continue
            st = set(tokens(re.sub(r"\d[\d,]*", " ", s)))
            if len(base & st) / max(1, len(base)) >= 0.5:
                found.setdefault(ym.group(1), (s, ch.versions[view.idx]))
    if len(found) < 2:
        return None
    years = sorted(found, reverse=True)
    text = " ".join(found[y][0] for y in years)
    return text, [(found[y][1].url, view.sid, found[y][0][:200]) for y in years]


# =============================================================================================
class Answerer:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.cache: dict[tuple, Draft] = {}

    def answer(self, question: str, as_of: Optional[str] = None) -> Draft:
        view = self.kb.view_for(as_of)
        fr = parse(question)
        if not as_of and fr.date_in_text and "history" in fr.intents and fr.date_in_text < view.taken_on:
            view = self.kb.view_for(fr.date_in_text.isoformat())
        ck = (re.sub(r"\s+", " ", (question or "").strip().lower()), view.idx)
        if ck in self.cache:
            return self.cache[ck]
        d = self._route(view, fr)
        d = guard(d, fr, view)
        if view.idx != len(self.kb.views) - 1 and d.confident:
            d.text = f"As of {fmt_date(view.taken_on)} (the website as it stood then): {d.text}"
        self.cache[ck] = d
        return d

    def _route(self, view: View, fr: QueryFrame) -> Draft:
        from . import handlers as H
        it = fr.intents
        if "link" in it or (re.search(r"\bonline\b", fr.norm) and re.search(r"\b(join|apply|open|sign up|enroll)\b", fr.norm)):
            d = H.link_answer(view, fr)
            if d is not None:
                return d
        if "routing" in it:
            d = H.routing_answer(view, fr)
            if d is not None:
                return d
        if it & {"hours", "drive_up", "lobby"} and not fr.rate_q:
            d = H.hours_answer(view, fr)
            if d is not None:
                return d
        if "address" in it and "branch" in it | {"branch"}:
            d = H.address_answer(view, fr)
            if d is not None:
                return d
        if it & {"status", "when"}:
            d = H.event_answer(view, fr)
            if d is not None:
                return d
        if "count" in it or re.search(r"\bhow big\b", fr.norm):
            d = H.stat_answer(view, fr)
            if d is not None:
                return d
        if fr.family and (fr.rate_q or fr.pct_in_q):
            d = rates_answer(view, fr)
            if d is not None:
                return d
        if "eligibility" in it:
            d = H.eligibility_answer(self.kb, view, fr)
            if d is not None:
                return d
        if fr.salient and fr.rate_q:
            return refusal(f"rate for unpublished product variant {fr.salient}")
        return generic_answer(self.kb, view, fr)


_META = re.compile(r"(?i)\b(in these facts|based on the (?:provided )?(?:context|facts|information)|according to the context)\b")


def guard(d: Draft, fr: QueryFrame, view: View) -> Draft:
    """Last line of defence: no stale values for the asked product, no artefacts, digit-free refusals."""
    if not d.confident:
        q_nums = set(re.findall(r"\d+", fr.raw))
        if any(n not in q_nums for n in re.findall(r"\d+", d.text)):
            d.text = REFUSAL
        return d
    t = d.text
    t = _META.sub("", t)
    t = t.replace("***", "").replace("\\*", "")
    t = re.sub(r"<[^>]{0,40}>", "", t)
    t = re.sub(r"\s{2,}", " ", t).strip()
    d.text = t
    return d
