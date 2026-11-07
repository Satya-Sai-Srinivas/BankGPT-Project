"""Rate facts: pipe-table rows and 'label: value' lines -> typed, qualified facts.

A fact's *key* identifies what it is about (scope, product family, purpose, term, tier, ...);
its *value* is what the page claims. Different keys never conflict; the resolver compares
values only within a key.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .lexicon import FAMILY_KIND, family_of
from .pages import PageVersion
from .text import (
    first_pct, model_year_range, money_range, norm_dashes, parse_date, pct_values, plain, strip_footnotes,
    term_months,
)

WEAK_ROW_FAMILIES = {"auto_loan", "checking", "credit_card", "certificate"}
_EFFECTIVE = re.compile(
    r"(?i)\brates?\s+(?:are\s+)?(?:updated\s+)?effective(?:\s+as\s+of)?,?:?\s*([0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}|[A-Z][a-z]+\.? \d{1,2}, \d{4})"
)


@dataclass
class Fact:
    key: tuple
    attr: str                      # dividend | apy | apr | rate | points | min_open | min_earn
    value: float
    value2: Optional[float]        # upper end of a range ("12.50% – 19.50%")
    display: str                   # value as printed on the site, footnotes stripped
    family: str
    label: str                     # row label for display ("17 Month Fixed Certificate Special")
    quals: dict
    effective: Optional[date]
    page: PageVersion
    row: str                       # the full row text (quote)
    table_id: int = 0
    primary: bool = True           # from a rate table / rate line on its own page (vs a prose mention)
    meta: dict = field(default_factory=dict)

    @property
    def vkey(self) -> tuple:
        return (round(self.value, 3), None if self.value2 is None else round(self.value2, 3))


_PCT_TOKEN = re.compile(r"\d{1,2}(?:\.\d{1,3})?\s?%")


def pct_display(cell: str) -> str:
    """'12.50% – 19.50%' -> '12.50% – 19.50%'; '2.90% APR for 6 mos. (after ...)' -> '2.90%'."""
    toks = _PCT_TOKEN.findall(cell)
    if len(toks) >= 2 and re.search(r"%\s*[-–]\s*\d", norm_dashes(cell).replace("–", "-")[: cell.find(toks[1]) + len(toks[1])]):
        return f"{toks[0].replace(' ', '')} – {toks[1].replace(' ', '')}"
    return toks[0].replace(" ", "") if toks else cell


def _value_attr(header: str, cell: str) -> Optional[str]:
    h = header.lower()
    c = cell.upper()
    if "dividend" in h:
        return "dividend"
    if "yield" in h or "apy" in h:
        return "apr" if "APR" in c else "apy"
    if "apr" in h or "annual percentage rate" in h:
        return "apr"
    if h.strip() in ("rate", "interest rate", "rates"):
        return "rate"
    if h.startswith("points"):
        return "points"
    if "min. to open" in h or "minimum to open" in h:
        return "min_open"
    if "min. to earn" in h or "minimum to earn" in h:
        return "min_earn"
    return None


def _is_value_header(h: str) -> bool:
    return _value_attr(h, "") is not None or "payment" in h.lower()


def _context_lines(lines: list[str], start: int, stop: int) -> list[str]:
    """Short caption-like lines between the previous table and this one, nearest first."""
    out = []
    for i in range(start - 1, stop - 1, -1):
        s = plain(lines[i])
        if not s or len(s) > 90 or s.startswith("|"):
            continue
        if re.match(r"^\d[A-Z]", s) or _EFFECTIVE.search(s) or s.lower() in ("explore", "see details"):
            continue
        if re.match(r"^(open my|apply|see details|explore|compare|email us|call to open|learn more|get more info)", s, re.I):
            continue
        out.append(s)
        if len(out) >= 6:
            break
    return out


def _quals(row_text: str, ctx: list[str], family: str, url: str) -> dict:
    t = norm_dashes(row_text)
    tl = t.lower()
    near = " ".join(ctx[:2]).lower()
    q: dict = {}
    tm = term_months(t)
    if tm:
        q["term"] = tm
    if "jumbo" in tl:
        q["jumbo"] = True
    if "special" in tl or (family in ("certificate", "ira") and "special" in near and "regular" not in near):
        q["special"] = True
    if re.search(r"\broth\b", tl):
        q["ira"] = "roth"
    elif re.search(r"\btraditional\b", tl):
        q["ira"] = "traditional"
    my = model_year_range(t)
    if my:
        q["my"] = my
    rng = money_range(t)
    if rng:
        if family in FAMILY_KIND and FAMILY_KIND[family] == "deposit":
            q["bal"] = rng
        else:
            q["amt"] = rng
    if re.search(r"\bintro", tl):
        q["intro"] = True
    if family in ("mortgage", "mortgage_relief"):
        if "refinanc" in tl:
            q["purpose"] = "refinance"
        elif "purchase" in tl:
            q["purpose"] = "purchase"
        if re.search(r"home equity|cash-out", near):
            q["purpose"] = "equity_refinance"
        if "fixed" in tl:
            q["fixed"] = True
    scope_text = tl + " " + near + " " + url.lower()
    q["scope"] = "business" if "business" in scope_text else "personal"
    if family == "credit_card":
        name = "rewards visa" if "reward" in (tl + " " + near) else "platinum visa"
        if "business" in (tl + " " + near):
            name = "business " + name
        q["card"] = name
    if family == "money_market":
        q["mm"] = "achieve" if "achieve" in (tl + near) else "investors_choice"
    return q


def key_of(family: str, q: dict) -> tuple:
    bal = q.get("bal")
    amt = q.get("amt")
    return (
        q.get("scope", "personal"), family, q.get("purpose", ""), q.get("term", 0), bool(q.get("jumbo")),
        bool(q.get("special")), q.get("ira", ""), bal[0] if bal else -1, amt[1] if amt else -1,
        q.get("my_ord", -1), bool(q.get("intro")), q.get("card", ""), q.get("mm", ""),
    )


def _row_label(cells: list[str], headers: list[str], family: str, ctx: list[str]) -> str:
    keys = [c for c, h in zip(cells, headers) if not _is_value_header(h) and c and c not in ("—", "-")]
    label = " · ".join(keys)
    fam_ok = family_of(label) == family
    if not fam_ok and ctx:
        # "60 Month" under "Regular Certificates" -> "Regular Certificates: 60 Month"
        cap = next((c for c in ctx if family_of(c) == family), ctx[0])
        cap = cap.lstrip("-• ").strip()
        label = f"{cap}: {label}" if label else cap
    return label


def table_facts(page: PageVersion, table_counter: list[int]) -> list[Fact]:
    lines = page.text.split("\n")
    facts: list[Fact] = []
    prev_end = 0
    prev_family: Optional[str] = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not (line.startswith("|") and i + 1 < n and re.match(r"^\|\s*:?-{3}", lines[i + 1])):
            i += 1
            continue
        headers = [strip_footnotes(h).strip() for h in line.strip().strip("|").split("|")]
        j = i + 2
        rows = []
        while j < n and lines[j].startswith("|"):
            rows.append([strip_footnotes(c).strip() for c in lines[j].strip().strip("|").split("|")])
            j += 1
        # effective date: first non-footnote "Rates are effective ..." line after the table
        eff = None
        for k in range(j, min(j + 14, n)):
            s = lines[k].strip()
            if s.startswith("|"):
                break
            if re.match(r"^_?\d_{0,2}[A-Z]", s):  # footnote definition: its dates belong to the footnote
                continue
            m = _EFFECTIVE.search(s)
            if m:
                eff = parse_date(m.group(1))
                break
        ctx = _context_lines(lines, i, prev_end)
        has_value_col = any(_value_attr(h, "") in ("dividend", "apy", "apr", "rate") for h in headers)
        if has_value_col and any("%" in c for r in rows for c in r):
            table_counter[0] += 1
            tid = table_counter[0]
            ctx_family = next((f for f in (family_of(c) for c in ctx) if f), None)
            table_rows = []
            for cells in rows:
                if len(cells) < len(headers):
                    cells = cells + [""] * (len(headers) - len(cells))
                key_text = " ".join(c for c, h in zip(cells, headers) if not _is_value_header(h))
                row_family = family_of(key_text)
                if row_family and ctx_family and row_family in WEAK_ROW_FAMILIES and ctx_family != row_family:
                    family = ctx_family          # "Model Year 2026-23" under "ATV, Snowmobile & Jet Ski"
                else:
                    family = row_family or ctx_family or prev_family
                if not family:
                    continue
                q = _quals(key_text, ctx, family, page.url)
                label = _row_label(cells, headers, family, ctx)
                ll = label.lower()
                if "business" in ll:
                    q["scope"] = "business"
                if family == "credit_card":
                    q["card"] = ("business " if q["scope"] == "business" else "") + (
                        "rewards visa" if "reward" in ll or "reward" in q.get("card", "") else "platinum visa")
                table_rows.append((cells, family, q, label))
            # model-year tier ordinal within the table (0 = newest vehicles), stable across relabelling
            mys = sorted({r[2]["my"] for r in table_rows if "my" in r[2]}, key=lambda r: -r[1])
            for cells, family, q, label in table_rows:
                if "my" in q:
                    q["my_ord"] = mys.index(q["my"])
                key = key_of(family, q)
                for h, c in zip(headers, cells):
                    attr = _value_attr(h, c)
                    if attr not in ("dividend", "apy", "apr", "rate", "points"):
                        if attr in ("min_open", "min_earn") and c:
                            q[attr] = c
                        continue
                    vals = pct_values(c)
                    if not vals:
                        continue
                    disp = pct_display(c)
                    facts.append(Fact(
                        key=key, attr=attr, value=vals[0], value2=vals[1] if (len(vals) > 1 and "–" in disp) else None,
                        display=disp, family=family, label=label, quals=q, effective=eff, page=page,
                        row=" | ".join(cells), table_id=tid,
                    ))
            if table_rows:
                prev_family = table_rows[-1][1]
        prev_end = j
        i = j
    return facts


_KV = re.compile(r"^(?P<label>[A-Za-z0-9][^:|\n]{2,80}?)\s*:\s*(?P<val>\$?\d[\d,.]*%?)\s*$")


def line_facts(page: PageVersion) -> list[Fact]:
    """'6-month certificate APY: 2.95%' style lines, plus rate mentions in short promo sentences."""
    out: list[Fact] = []
    eff = None
    m = _EFFECTIVE.search(page.text)
    if m:
        eff = parse_date(m.group(1))
    for line in page.text.split("\n"):
        s = plain(line)
        if not s or s.startswith("|") or len(s) > 220 or "%" not in s:
            continue
        fam = family_of(s)
        if not fam:
            continue
        pc = first_pct(s)
        if not pc:
            continue
        rng = re.search(r"(\d{1,2}\.\d{2})%\s*(?:APR\s*)?(?:to|-|–)\s*(\d{1,2}\.\d{2})%\s*APR", norm_dashes(s))
        if fam == "credit_card" and rng and page.ptype in ("product", "rate_sheet", "landing"):
            q = _quals(s, [], fam, page.url)
            q["card"] = ("business " if q.get("scope") == "business" else "") + ("rewards visa" if "reward" in s.lower() else "platinum visa")
            if re.search(r"\bintro", s, re.I) and not re.search(r"(?i)standard|revert|after that|ongoing", s):
                continue
            q.pop("intro", None)
            out.append(Fact(key=key_of(fam, q), attr="apr", value=float(rng.group(1)), value2=float(rng.group(2)),
                            display=f"{rng.group(1)}% – {rng.group(2)}%", family=fam, label=s[:80], quals=q,
                            effective=parse_date(s) or eff, page=page, row=s, primary=False))
            continue
        kv = _KV.match(s)
        q = _quals(s, [], fam, page.url)
        if not q.get("term") and fam in ("certificate", "auto_loan", "mortgage", "personal_loan"):
            continue
        sl = s.lower()
        attr = "apy" if ("apy" in sl or "yield" in sl) else "apr" if "apr" in sl else "dividend" if "dividend" in sl else "rate"
        out.append(Fact(
            key=key_of(fam, q), attr=attr, value=pc[0], value2=None, display=pc[1], family=fam,
            label=s.split(":")[0] if kv else s[:80], quals=q, effective=eff, page=page, row=s,
            primary=bool(kv) and page.ptype in ("rate_sheet", "product"),
        ))
    return out
