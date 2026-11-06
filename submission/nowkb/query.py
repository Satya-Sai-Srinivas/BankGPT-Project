"""Question -> QueryFrame (what is being asked about, with which qualifiers, and why)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .lexicon import FAMILY_KIND, families_in, normalize_q
from .text import MONTHS, money_values, month_num, parse_date, term_months, words_to_digits

RATE_WORDS = re.compile(
    r"\b(rates?|aprs?|apys?|interest|dividends?|yields?|earns?|pays?|percent|%)\b|\bhow much (?:interest|do i earn)", re.I
)
# Qualifiers that name a product variant; if no table row carries them, the site does not publish it.
SALIENT = {
    "arm": r"\barms?\b|\badjustable[- ]rate\b|\badjustable\b|\b\d{1,2}/\d{1,2}\b(?=.*\b(?:arm|mortgage|adjustable)\b)",
    "construction": r"\bconstruction\b",
    "fha": r"\bfha\b",
    "va": r"\bva loans?\b",
    "usda": r"\busda\b",
    "land": r"\bland loans?\b|\blot loans?\b",
    "interest_only": r"\binterest[- ]only\b",
    "jumbo_mortgage": r"\bjumbo\b(?=.*\b(?:mortgage|home loan)\b)",
    "commercial": r"\bcommercial\b",
    "sba": r"\bsba\b",
    "business_loan": r"\bbusiness (?:loans?|line of credit|real estate|equipment)\b",
    "secured_card": r"\bsecured (?:visa|card|credit card)\b",
    "share_secured": r"\bshare[- ]secured\b",
}
_SALIENT = {k: re.compile(v, re.I) for k, v in SALIENT.items()}


@dataclass
class QueryFrame:
    raw: str
    norm: str
    families: list[str] = field(default_factory=list)
    term: Optional[int] = None
    jumbo: Optional[bool] = None
    special: bool = False
    regular: bool = False
    ira: str = ""
    scope: str = ""
    purpose: str = ""
    model_year: Optional[int] = None
    amount: Optional[float] = None
    rate_q: bool = False
    attr: str = ""                      # apy | dividend | apr | rate | ""
    intents: set = field(default_factory=set)
    salient: list[str] = field(default_factory=list)
    date_in_text: Optional[date] = None
    asks_other: bool = False
    change_q: bool = False
    pct_in_q: list[float] = field(default_factory=list)

    @property
    def family(self) -> Optional[str]:
        return self.families[0] if self.families else None


_INTENTS = [
    ("history", r"\b(was|were|used to|previous(?:ly)?|before|changed?|changes|history|went (?:up|down)|increase[ds]?|decrease[ds]?|raised|lowered|as of)\b"),
    ("status", r"\bstill (?:open|available|offered|running)\b|\bis .* (?:open|closed)\b|\bclos(?:e|ed|ing)\b"),
    ("when", r"\bwhen\b|\bwhat date\b|\bwhich date\b"),
    ("hours", r"\bhours?\b|\bopen (?:on|until|till)\b|\bwhat time\b|\bclose[sd]? at\b|\bwhen (?:are|is|do|does) [^?]{0,40}\bopen\b"),
    ("drive_up", r"\bdrive-up\b"),
    ("lobby", r"\blobb(?:y|ies)\b"),
    ("address", r"\baddress\b|\bwhere (?:is|are)\b|\blocated\b|\blocation of\b"),
    ("phone", r"\bphone\b|\bcall\b|\bnumber to call\b|\btelephone\b|\bcontact\b"),
    ("routing", r"\brouting\b"),
    ("link", r"\b(link|url|website address|web ?page|web address)\b|\bwhere (?:can|do) i (?:find|see|go)\b.*\bonline\b"),
    ("count", r"\bhow many\b|\bnumber of\b"),
    ("list", r"\b(all|list|every|each|which .* (?:do you|does dupaco) (?:offer|have)|what .* do you offer|what .* (?:are|is) offered|options)\b"),
    ("highest", r"\b(highest|best|top|maximum|max)\b"),
    ("lowest", r"\b(lowest|minimum|cheapest)\b"),
    ("yesno", r"^(do|does|is|are|can|could|will|has|have)\b"),
    ("eligibility", r"\beligib|\bqualif|\bwho can (?:join|become)\b|\bjoin\b|\bbecome a member\b|\bmembership\b"),
    ("fee", r"\bfees?\b|\bcharge\b|\bcost\b|\bhow much (?:is|does|for)\b"),
    ("how", r"^how\b|\bhow (?:do|can|should) i\b"),
    ("branch", r"\bbranch(?:es)?\b|\boffices?\b|\blocations?\b"),
    ("award", r"\b(award|recogni[sz]\w*|ranked|ranking|forbes|newsweek|best|top workplace|honou?r)\b"),
]
_INTENT_RX = [(n, re.compile(rx, re.I)) for n, rx in _INTENTS]


def _date_in_text(q: str) -> Optional[date]:
    d = parse_date(q)
    if d:
        return d
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?,?\s+(20\d\d)\b", q, re.I)
    if m:
        y, mo = int(m.group(2)), month_num(m.group(1))
        # end of that month
        nxt = date(y + (mo == 12), mo % 12 + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)
    return None


def parse(question: str) -> QueryFrame:
    raw = question or ""
    norm = normalize_q(words_to_digits(raw))
    f = QueryFrame(raw=raw, norm=norm)
    f.families = families_in(norm)
    if "checking" in f.families and len(f.families) > 1:
        f.families = [x for x in f.families if x != "checking"] + ["checking"]
    f.term = term_months(norm)
    if re.search(r"\b(?:not|non|without|excluding|no)[- ]jumbo\b|\bnot the jumbo\b|\bnon-jumbo\b", norm):
        f.jumbo = False
    elif re.search(r"\bjumbo\b", norm):
        f.jumbo = True
    f.special = bool(re.search(r"\bspecials?\b|\bpromo", norm))
    f.regular = bool(re.search(r"\bregular\b|\bstandard\b", norm))
    if re.search(r"\broth\b", norm):
        f.ira = "roth"
    elif re.search(r"\btraditional\b", norm):
        f.ira = "traditional"
    if re.search(r"\bbusiness\b", norm):
        f.scope = "business"
    elif re.search(r"\bpersonal\b|\bconsumer\b", norm):
        f.scope = "personal"
    if re.search(r"\brefinanc", norm):
        f.purpose = "refinance"
    elif re.search(r"\bpurchas|\bbuy", norm):
        f.purpose = "purchase"
    m = re.search(r"\b(19[5-9]\d|20[0-4]\d)\b(?=[^.?]*\b(?:model|vehicle|car|truck|suv|auto|motorcycle|model-year)\b)|\b(?:model[- ]year|a|my)\s+(19[5-9]\d|20[0-4]\d)\b", norm)
    if m:
        f.model_year = int(m.group(1) or m.group(2))
    amts = [a for a in money_values(raw) if a >= 1]
    if amts:
        f.amount = amts[0]
    # product names that contain "rate" ("1st Rate Checking") are not rate questions by themselves
    f.rate_q = bool(RATE_WORDS.search(re.sub(r"\b(?:1st|first) rate\b|\brate relief\b", " ", norm)))
    f.asks_other = bool(re.search(r"\bwhat (?:credit )?score\b|\bcredit score\b|\bqualif|\brequire|\bminimum (?:to|balance|deposit)|"
                                  r"\bhow long\b|\bpenalt|\bterms? and conditions\b|\bloan-to-value\b|\bltv\b", norm))
    f.change_q = bool(re.search(r"\b(gone|go|went) (?:up|down)\b|\b(?:increase|decrease|rise|rose|drop|fall|fell)[ds]?\b|"
                                r"\bchanged?\b|\bused to\b|\bpreviously\b|\bhistory\b|\bover time\b|\bsince (?:may|june|july|august|september)\b", norm))
    if re.search(r"\bdividend", norm):
        f.attr = "dividend"
    elif re.search(r"\bapy\b", norm):
        f.attr = "apy"
    elif re.search(r"\bapr\b", norm):
        f.attr = "apr"
    for name, rx in _INTENT_RX:
        if rx.search(norm):
            f.intents.add(name)
    for name, rx in _SALIENT.items():
        if rx.search(norm):
            f.salient.append(name)
    f.date_in_text = _date_in_text(raw)
    f.pct_in_q = [float(x) for x in re.findall(r"(\d{1,2}(?:\.\d{1,3})?)\s?%", raw)]
    return f


def kind(family: Optional[str]) -> str:
    return FAMILY_KIND.get(family or "", "")
