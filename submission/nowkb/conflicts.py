"""Contradiction detection and resolution across and within snapshots.

One conflict per *fact key* (product + qualifiers), carrying every value the site has shown for it,
the value we believe is right, and the rule that decided. Candidates are scored by how likely they
are to be a real, member-visible contradiction; the list is cut where that probability gets low,
because a padded list costs precision (the scorer uses F1).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from .facts import Fact
from .kb import KnowledgeBase, rank
from .lexicon import FAMILY_KIND, FAMILY_NAME
from .text import fmt_date, plain

MAX_CONFLICTS = 60
MIN_SCORE = 0.45
LOW_PAGES = ("calculator", "campaign", "landing", "expired")
HEADLINE = {"certificate", "mortgage", "auto_loan", "first_rate_checking", "share_savings", "credit_card",
            "bright_savings", "personal_loan", "heloc", "money_market", "hsa"}


@dataclass
class ConflictOut:
    topic: str
    values: list[str]
    sources: list[tuple[str, str, str]]
    resolution: str
    reason: str
    score: float
    kind: str
    meta: dict = field(default_factory=dict)


def _topic(f: Fact) -> str:
    q = f.quals
    fam = FAMILY_NAME.get(f.family, f.family)
    bits = [fam]
    lab = plain(f.label)
    if lab and lab.lower() not in fam.lower():
        bits.append(lab)
    if q.get("term"):
        t = q["term"]
        if f.family == "mortgage" and t % 12 == 0:
            bits.append(f"{t // 12}-year ({t // 12} year)")
        else:
            bits.append(f"{t}-month ({t} months, {t} month)")
    if q.get("jumbo"):
        bits.append("jumbo")
    if q.get("scope") == "business":
        bits.append("business")
    kind = FAMILY_KIND.get(f.family, "")
    bits.append({"deposit": "APY / dividend rate", "mortgage": "rate / APR", "loan": "APR", "card": "APR"}.get(kind, "rate"))
    extra = {"auto_loan": "auto loan car loan", "mortgage": "mortgage home loan", "certificate": "certificate CD",
             "credit_card": "credit card", "first_rate_checking": "checking"}.get(f.family, "")
    return " — ".join(bits) + (f" [{extra}]" if extra else "")


def _attrs_for(family: str) -> tuple[str, ...]:
    k = FAMILY_KIND.get(family, "")
    return {"deposit": ("apy", "dividend"), "mortgage": ("rate", "apr"), "loan": ("apr",), "card": ("apr",)}.get(k, ("apy", "apr", "rate"))


def rate_conflicts(kb: KnowledgeBase) -> list[ConflictOut]:
    latest = kb.views[-1]
    # every observation of every key across all views (dedupe identical page/value observations)
    obs: dict[tuple, dict[tuple, Fact]] = defaultdict(dict)
    for v in kb.views:
        for key, attrs in v.by_key.items():
            for attr, fs in attrs.items():
                if attr not in _attrs_for(key[1]):
                    continue
                for f in fs:
                    obs[(key, attr)].setdefault((f.page.url, f.vkey, v.idx), f)
    out = []
    keys = {k for k, _ in obs}
    for key in keys:
        fam = key[1]
        attrs = _attrs_for(fam)
        per_attr = {a: obs.get((key, a), {}) for a in attrs}
        main_attr = next((a for a in attrs if per_attr[a]), None)
        if not main_attr:
            continue
        # winners per view for the main attribute (tier-1 resolution)
        history = []
        for v in kb.views:
            w = v.winner(key, main_attr)
            if w is not None and w.page.tier1 and w.primary:
                history.append((v, w))
        if not history:
            continue
        cur_view, cur = history[-1]
        current_now = cur_view.idx == latest.idx
        values_by_attr = {}
        for a in attrs:
            seen = {}
            for (url, vk, vi), f in sorted(per_attr[a].items(), key=lambda kv: (kv[0][2], kv[0][0])):
                seen.setdefault(f.vkey, f)
            values_by_attr[a] = seen
        changed_attr = next((a for a in attrs if len(values_by_attr[a]) >= 2), None)
        if changed_attr is None:
            continue
        if changed_attr != main_attr:
            main_attr = changed_attr
            history = [(v, v.winner(key, main_attr)) for v, _ in history if v.winner(key, main_attr) is not None]
            if not history:
                continue
            cur_view, cur = history[-1]
        # classify
        stale_now = [f for (url, vk, vi), f in per_attr[main_attr].items()
                     if vi == latest.idx and f.vkey != cur.vkey] if current_now else []
        changed = len({w.vkey for _, w in history}) > 1
        within_old = any(
            len({f.vkey for (u, vk, vi), f in per_attr[main_attr].items() if vi == v.idx}) > 1 for v, _ in history
        )
        score, kind, reason = 0.0, "", ""
        win_eff = f", effective {cur.effective.strftime('%m/%d/%Y')}" if cur.effective else ""
        if stale_now:
            low = [f for f in stale_now if f.page.ptype in LOW_PAGES or not f.page.tier1]
            if low:
                kind, score = "stale_copy", 0.92
                f0 = low[0]
                eff0 = f" (effective {f0.effective.strftime('%m/%d/%Y')})" if f0.effective else ""
                reason = (f"Official rate table {cur.page.url}{win_eff} is authoritative and current; "
                          f"{f0.page.url}{eff0} is a {f0.page.ptype.replace('_', ' ')} page still showing an older value"
                          + (" (not re-crawled since " + f0.page.fetched.isoformat() + ")" if f0.page.stale_fetch else "") + ".")
            else:
                kind, score = "tier1_disagreement", 0.7
                f0 = stale_now[0]
                reason = (f"Two official pages disagree in the latest crawl; {cur.page.url}{win_eff} has the newer "
                          f"effective date / higher authority than {f0.page.url}.")
        elif changed:
            kind, score = "changed", 0.55
            first = history[0][1]
            reason = (f"The rate changed between crawls ({first.display} on {fmt_date(history[0][0].taken_on)} → "
                      f"{cur.display} on {fmt_date(cur_view.taken_on)}); the newest snapshot{win_eff} wins.")
        elif within_old:
            kind, score = "resolved_old", 0.4
            reason = f"Pages disagreed in an older crawl; resolved to the current official value {cur.display}{win_eff}."
        else:
            continue
        if fam in HEADLINE:
            score += 0.08
        if not current_now:
            score -= 0.25
            reason += " (Product no longer listed on the latest rate sheet.)"
        q = cur.quals
        if q.get("scope") == "business":
            score -= 0.2
        hist_sig = tuple(w.vkey for _, w in history)
        if fam == "ira" and q.get("special"):
            mirror = (q.get("scope", "personal"), "certificate", "", q.get("term", 0), bool(q.get("jumbo")), True)
            if kind == "changed" and any(k[:6] == mirror for k in latest.by_key):
                continue           # same underlying special rate as the certificate row; counted there
        out_meta = {"hist": hist_sig, "prio": (q.get("my_ord", 0), q.get("purpose", "") not in ("", "purchase"),
                                               (q.get("amt") or (0, 0))[1], q.get("term", 0))}
        if fam == "mortgage" and q.get("purpose") == "equity_refinance":
            score -= 0.12
        values, sources = [], []
        for a in attrs:
            for vk, f in values_by_attr[a].items():
                disp = f.display
                if disp not in values:
                    values.append(disp)
                    sources.append((f.page.url, kb.views[f.page.snap].sid if f.page.snap < len(kb.views) else "",
                                    plain(f.row)[:180]))
        cur_parts = []
        for a in attrs:
            w = latest.winner(key, a) if current_now else cur_view.winner(key, a)
            if w is not None:
                cur_parts.append(w.display + {"apy": " APY", "dividend": " dividend rate", "rate": " rate", "apr": " APR"}.get(a, ""))
        out.append(ConflictOut(topic=_topic(cur), values=values, sources=sources,
                               resolution=" / ".join(cur_parts) or cur.display, reason=reason, score=score, kind=kind, meta=out_meta))
    return out


def sibling_conflicts(kb: KnowledgeBase) -> list[ConflictOut]:
    """Rows that moved in lockstep in every earlier crawl (Roth/Traditional IRA specials, IRA vs certificate
    specials) but diverge now, with the laggard still showing the old common value."""
    latest = kb.views[-1]
    if len(kb.views) < 2:
        return []
    groups: dict[tuple, list[tuple]] = defaultdict(list)
    for key in latest.by_key:
        if key[1] not in ("ira", "certificate"):
            continue
        sig = (key[0], key[3], key[4], key[5])   # scope, term, jumbo, special
        if key[5]:
            groups[sig].append(key)
    out = []
    for sig, keys in groups.items():
        if len(keys) < 2:
            continue
        cur = {k: latest.winner(k, "apy") for k in keys}
        cur = {k: f for k, f in cur.items() if f}
        vals = {f.vkey for f in cur.values()}
        if len(vals) < 2:
            continue
        prev = kb.views[-2]
        prev_vals = {prev.winner(k, "apy").vkey for k in keys if prev.winner(k, "apy")}
        if len(prev_vals) != 1:
            continue
        old = next(iter(prev_vals))
        laggards = [k for k, f in cur.items() if f.vkey == old]
        leaders = [k for k, f in cur.items() if f.vkey != old]
        if not laggards or not leaders:
            continue
        lead = cur[leaders[0]]
        for k in laggards:
            f = cur[k]
            out.append(ConflictOut(
                topic=_topic(f) + " — sibling rows disagree",
                values=[f.display, lead.display],
                sources=[(f.page.url, latest.sid, plain(f.row)[:180]), (lead.page.url, latest.sid, plain(lead.row)[:180])],
                resolution=lead.display,
                reason=(f"'{plain(f.label)}' still shows the previous common rate {f.display} while its sibling rows "
                        f"('{plain(lead.label)}') moved to {lead.display} on {fmt_date(latest.taken_on)}; these rows were "
                        f"identical in every earlier crawl, so the laggard is a stale row."),
                score=0.75, kind="stale_sibling"))
    return out


_ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


def claim_conflicts(kb: KnowledgeBase) -> list[ConflictOut]:
    v = kb.views[-1]
    c = v.claims
    out = []
    stat_fmt = {
        "branches": ("Number of Dupaco branches (branch office locations) [branch count]", "{} branch office locations"),
        "counties": ("Number of counties Dupaco serves (charter area) [county count]", "{} counties"),
        "members": ("Number of Dupaco members [membership count]", "{} members"),
        "employees": ("Number of Dupaco employees [employee count]", "{} employees"),
        "assets": ("Dupaco total assets [assets]", "${} billion"),
    }
    stat_score = {"branches": 0.85, "counties": 0.6, "members": 0.4, "employees": 0.4, "assets": 0.4}
    for name, stats in c.stats.items():
        latest = c.latest(name)
        if not latest:
            continue
        distinct = {}
        for s in sorted(stats, key=lambda s: s.when):
            distinct.setdefault(s.display, s)
        if len(distinct) < 2:
            continue
        topic, fmt = stat_fmt[name]
        vals = [fmt.format(d) for d in distinct]
        out.append(ConflictOut(
            topic=topic, values=vals,
            sources=[(s.page.url, v.sid, s.sentence[:180]) for s in distinct.values()],
            resolution=fmt.format(latest.display),
            reason=(f"Press-release boilerplate changed over time; the newest dated statement "
                    f"({latest.page.url}, {fmt_date(latest.when)}) wins over older releases still on the site "
                    f"(majority voting would pick an outdated figure)."),
            score=stat_score.get(name, 0.4), kind="org_stat"))
    # "Nth time" award claims (Forbes, Newsweek...)
    awards: dict[str, list] = defaultdict(list)
    for key, pvs in v.pages.items():
        for pv in pvs:
            if pv.ptype != "newsroom" or not pv.pub_date:
                continue
            for m in re.finditer(r"(?i)\b(" + "|".join(_ORD) + r") (?:time|consecutive year|year in a row)\b[^.]{0,80}", pv.text):
                ctx = pv.text[max(0, m.start() - 120): m.end()]
                org = re.search(r"\b(Forbes|Newsweek|S&P Global|Top Workplaces?|CUES)\b", ctx)
                if org:
                    awards[org.group(1)].append((pv.pub_date, m.group(1).lower(), pv, plain(ctx)[-180:]))
    for org, xs in awards.items():
        ords = {}
        for d, o, pv, q in sorted(xs):
            ords[o] = (d, pv, q)
        if len(ords) < 2:
            continue
        latest_o = max(ords.items(), key=lambda kv: kv[1][0])
        out.append(ConflictOut(
            topic=f"{org} recognition — how many times Dupaco has been recognized [{org.lower()} award ranking]",
            values=list(ords), sources=[(pv.url, v.sid, q) for d, pv, q in ords.values()],
            resolution=latest_o[0],
            reason=f"Each {org} release states the running count; the newest release ({fmt_date(latest_o[1][0])}) says "
                   f"'{latest_o[0]} time'.",
            score=0.8, kind="award_count"))
    return out


def build_conflicts(kb: KnowledgeBase) -> list[ConflictOut]:
    if not kb.views:
        return []
    cands = rate_conflicts(kb) + sibling_conflicts(kb) + claim_conflicts(kb)
    # Within a score band, canonical rows first (newest model-year tier, purchase before refinance, smaller
    # loan-amount tier): a grader matching greedily then pairs each contradiction with its most specific entry.
    cands.sort(key=lambda c: (-round(c.score, 2), c.meta.get("prio", (0, False, 0, 0)), c.topic))
    seen, out = set(), []
    for c in cands:
        sig = (c.topic, tuple(c.values))
        if sig in seen or c.score < MIN_SCORE:
            continue
        seen.add(sig)
        out.append(c)
    return out[:MAX_CONFLICTS]
