"""Question answering: route a parsed question to a handler, render from resolved facts, guard."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .facts import Fact
from .kb import ABLATE, KnowledgeBase, View
from .lexicon import EXPANSIONS, FAMILY_KIND, FAMILY_NAME
from .pages import PageVersion
from .query import QueryFrame, parse
import math

from .text import fmt_date, plain, sentences, tokens

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
        if "resolution" in ABLATE:
            kept.append((key, w))
            continue
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
        if not fr.scope and scope == "business" and not (family == "credit_card" and not re.search(r"\b(platinum|reward)", fr.norm)):
            if any(k[0] == "personal" for k, _ in rows):
                continue
        if fr.term and q.get("term") and q["term"] != fr.term:
            continue
        if fr.term and not q.get("term") and family in ("certificate", "ira", "auto_loan", "mortgage", "personal_loan"):
            continue
        if fr.jumbo and not q.get("jumbo"):
            continue
        if fr.jumbo is False and q.get("jumbo"):
            continue
        if fr.special and family in ("certificate", "ira") and not q.get("special"):
            continue
        if fr.regular and family in ("certificate", "ira") and q.get("special"):
            continue
        if family == "ira" and fr.ira and q.get("ira") and q["ira"] != fr.ira:
            continue
        if family == "credit_card":
            if "platinum" in fr.norm and "platinum" not in q.get("card", ""):
                continue
            if re.search(r"\breward", fr.norm) and "reward" not in q.get("card", ""):
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
            0 if q.get("scope", "personal") == "personal" else 1,
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
    if f.family in ("auto_loan", "personal_loan", "atv_loan", "boat_rv_loan", "home_improvement", "home_equity_loan"):
        return f"{FAMILY_NAME.get(f.family)} — {lab.split(': ', 1)[-1]}"
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
    jumbo_note = ""
    if fr.jumbo is None and not fr.amount and family in ("certificate", "ira") and "list" not in fr.intents:
        nonj = [r for r in rows if not r[1].quals.get("jumbo")]
        if nonj and len(nonj) < len(rows) and fr.term:
            rows = nonj
            jumbo_note = " A jumbo version (higher minimum deposit) is also available."
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
    d = Draft(text=text + jumbo_note, sources=source_list(view, keys), note=stale_note(view, keys))
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


def change_answer(kb: KnowledgeBase, view: View, fr: QueryFrame) -> Optional[Draft]:
    """"Has the 17-month special gone up?" -> the value in every crawl where it changed, oldest to newest."""
    family = fr.family
    rows = select_rows(view, fr, family)
    if not rows:
        return None
    rows = _sort_rows(rows)
    if fr.jumbo is None and family in ("certificate", "ira"):
        rows = [r for r in rows if not r[1].quals.get("jumbo")] or rows
    attr = {"deposit": "apy", "mortgage": "rate", "loan": "apr", "card": "apr"}.get(FAMILY_KIND.get(family, ""), "apy")
    parts, keys = [], []
    for key, f in rows[:3]:
        hist = []
        for v in kb.views:
            w = v.winner(key, attr)
            if w is not None and w.page.tier1 and w.primary and (not hist or hist[-1][1].vkey != w.vkey):
                hist.append((v, w))
        if not hist:
            continue
        keys.append(key)
        label = _display_label(f)
        if len(hist) == 1:
            parts.append(f"{label}: unchanged at {hist[0][1].display} across our crawls (May 12 to {fmt_date(view.taken_on)}).")
            continue
        steps = "; ".join(f"{w.display} as of {fmt_date(v.taken_on)}" for v, w in hist)
        direction = "up" if hist[-1][1].value > hist[0][1].value else "down" if hist[-1][1].value < hist[0][1].value else "back"
        parts.append(f"{label}: went {direction} — {steps} (current: {hist[-1][1].display}).")
    if not parts:
        return None
    lead = "Yes — " if any("went up" in p or "went down" in p for p in parts) else ""
    d = Draft(text=lead + " ".join(parts), sources=source_list(view, keys), note=stale_note(view, keys))
    d.trace.append(f"change: family={family}")
    return d


_YEAR = re.compile(r"\b(?:in|during|for) (20\d\d)\b")
_ANSWER_TYPE = {
    "count": re.compile(r"\b\d[\d,]*\b"),
    "when": re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.? \d{1,2}|\b20\d\d\b"),
    "fee": re.compile(r"\$\d"),
    "how_much": re.compile(r"\$\d"),
}


def _bigrams(text: str) -> set:
    ws = [w for w in re.findall(r"[a-z0-9$]+", text.lower()) if w not in ("the", "a", "an", "my", "your", "of", "to")]
    return {f"{a} {b}" for a, b in zip(ws, ws[1:])}


def _sentence_score(s: str, qset: set, idf: dict, fr: QueryFrame, expansions: set = frozenset()) -> float:
    st = set(tokens(s))
    ov = qset & st
    if not ov and not (expansions & st):
        return 0.0
    sc = sum(idf.get(t, 1.0) for t in ov) / (sum(idf.get(t, 1.0) for t in qset) or 1.0)
    sc += 0.12 * len(expansions & st)
    sc += 0.2 * len(_bigrams(fr.raw) & _bigrams(s))
    intents = fr.intents | ({"how_much"} if "how much" in fr.norm else set())
    for intent, rx in _ANSWER_TYPE.items():
        if intent in intents and rx.search(s):
            sc += 0.15
    if fr.rate_q and "%" in s:
        sc += 0.1
    if re.search(r"\bfees?\b", fr.norm):
        if re.search(r"\bfees?\b", s, re.I) and ("$" in s or re.search(r"(?i)\bno\b[^.]{0,25}\bfees?\b", s)):
            sc += 0.3          # a fee question wants the sentence that states the fee (or that there is none)
        elif "%" in s and not fr.rate_q:
            sc -= 0.15         # rate-table rows do not answer fee questions
    if s.endswith("?"):
        sc -= 0.1          # an FAQ question restates the query; prefer its answer
    if len(s) < 25:
        sc -= 0.1
    if "dupaco" in fr.norm and "dupaco" in s.lower():
        sc += 0.08         # the question is about Dupaco itself, not the industry
    if re.search(r"(?i)^(for more information|to learn more|learn more|click|visit|call us|contact us)\b", s):
        sc -= 0.3          # calls to action do not answer anything
    if re.search(r"^(what is|what's|what are|tell me about|explain|describe)\b", fr.norm) and \
            re.search(r"\b(provides?|offers?|is an?|allows?|helps?|gives?|partnering|designed)\b", s):
        sc += 0.06
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
    exp = {t for t, w in weights.items() if w < 1.0}
    top = hits[0][0] or 1.0
    best = None
    for rank_i, (score, ch) in enumerate(hits[:6]):
        sents = _sentences(ch.text)
        head_ov = len(qset & set(tokens(ch.heading))) / max(1, len(qset))
        is_list = sum(1 for l in ch.text.split("\n") if l.lstrip().startswith(("- ", "* "))) >= 2
        rare = {t for t in qset if idf.get(t, 0) >= 0.6 * max(idf.values())}
        list_q = bool(fr.intents & {"list", "eligibility"}) or bool(re.search(r"^(what are|which|how do i|how can i|what do i need)\b", fr.norm))
        if list_q and head_ov >= 0.5 and is_list and rare <= (set(tokens(ch.heading)) | set(tokens(ch.text))):
            items = [plain(l.lstrip("-* ")) for l in ch.text.split("\n") if l.lstrip().startswith(("- ", "* "))]
            sc = 0.6 + head_ov + 0.35 * score / top
            if best is None or sc > best[0]:
                best = (sc, 0, [plain(ch.heading).rstrip(":") + ": " + "; ".join(items[:6]) + "."], ch)
        for i, s in enumerate(sents):
            sc = _sentence_score(s, qset, idf, fr, exp)
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
    # Off-topic guard: the question's most specific term is one the site barely uses, it is not in the
    # passage we picked, and the passage covers little of the question ("What is Dupaco's SWIFT code?",
    # "Is Dupaco closed on Thanksgiving?"). The site does not say, so say so instead of quoting a near miss.
    rel = _relevance(fr, qset, idf, text, ch, pv)
    rel_df = kb.index.df.get(rel[2], 0)
    if not rel[1] and rel_df <= RARE_DF and rel[3] < MIN_PASSAGE_COVER:
        return refusal(f"off-topic evidence (rarest term {rel[2]!r} df={rel_df} not in passage, cover {rel[3]:.2f})")
    # Year-qualified statistics reported in several releases are distinct facts: list them all.
    if _YEAR.search(text) and ("count" in fr.intents or "last year" in fr.norm):
        series = _year_series(kb, view, fr, text, weights)
        if series:
            text = series[0]
            sources += series[1]
    # A fee question needs an amount that is about *this* fee (not just any "$" on the page).
    if "fee" in fr.intents and (re.search(r"\b(fee|charge|cost)\b", fr.norm) or
                                (re.search(r"\bhow much (?:is|does)\b", fr.norm) and not fr.rate_q)):
        ctx = set(tokens(ch.heading + " " + pv.title))
        total = sum(idf.get(t, 1.0) for t in qset) or 1.0
        cover = max((sum(idf.get(t, 1.0) for t in qset & (set(tokens(s)) | ctx)) / total
                     for s in sentences(text) if _STATES_FEE.search(s)),
                    default=0.0)
        if cover < 0.7:
            alt = _fee_sentence(view, hits[:6], qset, idf, total)
            if alt is None:
                return refusal(f"fee question but no amount for this fee (coverage {cover:.2f})")
            _, text, pv = alt
            sources = [(pv.url, view.sid, text[:200])]
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
    d.trace.append(f"generic: {pv.url} score={sc:.2f} cover={rel[0]:.2f} pcover={rel[3]:.2f} df={rel_df} rarest={rel[2]}:{rel[1]}")
    return d


RARE_DF = 3                 # a term on at most this many passages site-wide is specific to one topic
MIN_PASSAGE_COVER = 0.5     # idf-weighted share of the question the passage must cover otherwise


def _relevance(fr: QueryFrame, qset: set, idf: dict, text: str, ch, pv) -> tuple[float, bool, str, float]:
    """How much of the question the picked evidence is about: (idf-weighted share of the question's terms
    found in the answer sentences + section heading + page title, whether the question's most specific
    term occurs anywhere in the passage, that term, idf-weighted share found anywhere in the passage)."""
    content = {t for t in qset if not t.isdigit()}
    if not content:
        return 1.0, True, "", 1.0
    near = set(tokens(text)) | set(tokens(ch.heading + " " + pv.title))
    passage = near | set(tokens(ch.text))
    total = sum(idf.get(t, 1.0) for t in content) or 1.0
    cover = sum(idf.get(t, 1.0) for t in content & near) / total
    pcover = sum(idf.get(t, 1.0) for t in content & passage) / total
    rarest = max(sorted(content), key=lambda t: idf.get(t, 0.0))
    return cover, rarest in passage, rarest, pcover


_STATES_FEE = re.compile(r"\$\d|(?i:\bno\b[^.]{0,25}\bfees?\b)")


def _fee_sentence(view: View, hits: list, qset: set, idf: dict, total: float):
    """Best sentence in the top passages that states an amount or 'no ... fee' for what was asked, judged
    with its own paragraph as context ('...no annual fees...' in a footnote about the Platinum Visa)."""
    best = None
    for _, ch in hits:
        pv = ch.versions[view.idx]
        head = set(tokens(ch.heading + " " + pv.title))
        for para in ch.text.split("\n"):
            p = plain(para)
            if not p or not _STATES_FEE.search(p):
                continue
            ptoks = set(tokens(p)) | head
            for s in sentences(p):
                if not _STATES_FEE.search(s):
                    continue
                cover = sum(idf.get(t, 1.0) for t in qset & ptoks) / total
                direct = sum(idf.get(t, 1.0) for t in qset & set(tokens(s))) / total
                key = (cover, direct, -len(s))
                if cover >= 0.7 and direct >= 0.3 and (best is None or key > best[0]):
                    best = (key, s, pv)
    if best is None:
        return None
    s = re.sub(r"^[-*•]\s*", "", best[1])                 # list marker
    s = re.sub(r"(?<=[a-z])\s?\d{1,2}(?=\.?$)", "", s)     # footnote digit: "No annual fee 2."
    return best[0][0], s, best[2]


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
# Intents that a rate table cannot answer; a product question carrying one of them is not a rate question.
_NON_RATE_INTENTS = {"hours", "drive_up", "lobby", "link", "eligibility", "phone", "address", "routing", "count",
                     "when"}


def implicit_rate(fr: QueryFrame) -> bool:
    """A product question without a rate word that only the rate table can answer.

    '17-month certificate special', "What's the 10-month jumbo special now?", 'What credit cards do you
    offer?' name a rate-bearing product plus a variant (term, special, jumbo, model year, balance tier,
    Roth/Traditional) or ask for the product list, and ask for nothing else."""
    if not fr.family or fr.rate_q or fr.asks_other or fr.intents & _NON_RATE_INTENTS:
        return False
    if FAMILY_KIND.get(fr.family) not in ("deposit", "loan", "mortgage", "card"):
        return False
    if re.search(r"\b(?:fees?|charges?|cost|price|penalt\w*)\b|\bhow (?:do|can|should|would) i\b", fr.norm):
        return False
    variant = bool(fr.term or fr.special or fr.jumbo or fr.model_year or fr.ira) or \
        (fr.amount is not None and FAMILY_KIND.get(fr.family) == "deposit")
    listing = "list" in fr.intents and fr.family in ("credit_card", "certificate")
    return variant or listing


class Answerer:
    def __init__(self, kb: KnowledgeBase, composer=None) -> None:
        self.kb = kb
        self.cache: dict[tuple, Draft] = {}
        from . import llm
        self.composer = composer if composer is not None else (llm.Composer() if llm.enabled() else None)

    def answer(self, question: str, as_of: Optional[str] = None) -> Draft:
        view = self.kb.view_for(as_of)
        fr = parse(question)
        # "What was X in May 2026?" is an as-of question; "has X gone up since May?" is a change question.
        if not as_of and fr.date_in_text and "history" in fr.intents and not fr.change_q \
                and fr.date_in_text < view.taken_on:
            view = self.kb.view_for(fr.date_in_text.isoformat())
        ck = (re.sub(r"\s+", " ", (question or "").strip().lower()), view.idx)
        if ck in self.cache:
            return self.cache[ck]
        try:
            d = self._route(view, fr)
        except Exception as e:  # never crash the harness: degrade to an honest refusal
            d = refusal(f"internal error {type(e).__name__}: {e}")
        if self.composer is not None and d.trace and d.trace[0].startswith(("generic", "refuse: weak", "refuse: off-topic")):
            d = self._llm_rewrite(view, fr, d)
        d = guard(d, fr, view)
        if view.idx != len(self.kb.views) - 1 and d.confident:
            d.text = f"As of {fmt_date(view.taken_on)} (the website as it stood then): {d.text}"
        self.cache[ck] = d
        return d

    def _route(self, view: View, fr: QueryFrame) -> Draft:
        from . import handlers as H
        from .kb import ABLATE
        if "handlers" in ABLATE:        # retrieval-only baseline
            return generic_answer(self.kb, view, fr)
        it = fr.intents
        if "link" in it or (re.search(r"\bonline\b", fr.norm) and
                            re.search(r"\b(join|apply|open|sign up|enroll|become a member|membership)\b", fr.norm)):
            d = H.link_answer(view, fr)
            if d is not None:
                return d
        if "routing" in it:
            d = H.routing_answer(view, fr)
            if d is not None:
                return d
        if "phone" in it:
            d = H.phone_answer(view, fr)
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
        if "count" in it or re.search(r"\b(how big|how large|assets)\b", fr.norm):
            d = H.stat_answer(view, fr)
            if d is not None:
                return d
        if "award" in it:
            d = H.award_answer(view, fr)
            if d is not None:
                return d
        d = H.fee_answer(view, fr)
        if d is not None:
            return d
        fee_q = bool(re.search(r"\bfees?\b", fr.norm)) or (bool(re.search(r"\b(charges?|cost)\b", fr.norm)) and not fr.rate_q)
        if fr.family and (fr.rate_q or fr.pct_in_q or implicit_rate(fr)) and not fee_q and not fr.asks_other:
            if fr.change_q and view.idx == len(self.kb.views) - 1:
                d = change_answer(self.kb, view, fr)
                if d is not None:
                    return d
            d = rates_answer(view, fr)
            if d is not None:
                return d
        d = H.contact_answer(view, fr)
        if d is not None:
            return d
        if "eligibility" in it:
            d = H.eligibility_answer(self.kb, view, fr)
            if d is not None:
                return d
        if fr.salient and fr.rate_q:
            return refusal(f"rate for unpublished product variant {fr.salient}")
        return generic_answer(self.kb, view, fr)


def _llm_evidence(kb: KnowledgeBase, view: View, fr: QueryFrame):
    from .llm import Evidence
    q_toks = tokens(fr.norm)
    hits = kb.index.search(q_toks, view.idx, k=6, prior=_prior(fr))
    return [Evidence(eid=f"E{i + 1}", url=ch.versions[view.idx].url, text=plain(ch.text)) for i, (_, ch) in enumerate(hits)]


def _stale_values(view: View) -> set:
    out = set()
    for attrs in view.by_key.values():
        for obs in attrs.values():
            if obs and obs[0].page.tier1:
                out |= {f.display for f in obs[1:] if f.vkey != obs[0].vkey and f.display != obs[0].display}
    return out


def _llm_rewrite_impl(self, view: View, fr: QueryFrame, d: Draft) -> Draft:
    res = self.composer.compose(fr.raw, _llm_evidence(self.kb, view, fr), _stale_values(view))
    if res is None:
        return d
    if res["status"] == "not_listed":
        r = refusal("llm: not listed")
        r.trace.append("llm")
        return r
    out = Draft(text=res["answer"], sources=[(e.url, view.sid, e.text[:200]) for e in res["evidence"]])
    out.trace = ["llm: composed from " + ",".join(e.eid for e in res["evidence"])] + d.trace
    return out


Answerer._llm_rewrite = _llm_rewrite_impl


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
