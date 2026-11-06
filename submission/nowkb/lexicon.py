"""Domain vocabulary shared by the table parser (rows -> product families) and the question
parser (questions -> product families). One source of truth keeps the two sides consistent."""
from __future__ import annotations

import re
from typing import Optional

# (family id, display name, kind, regex). Order matters: most specific first.
# kind: "deposit" (dividend rate + APY) | "loan" (APR) | "mortgage" (rate + APR) | "card" (APR)
FAMILIES: list[tuple[str, str, str, str]] = [
    ("hsa", "Health Savings Account", "deposit", r"\bhealth savings\b|\bhsa\b"),
    ("ira", "IRA", "deposit", r"\bira\b|\biras\b|\broth\b|\btraditional\b(?!.*\bmortgage)|\bretirement (?:account|certificate)s?\b"),
    ("launchpad", "Launchpad Savings", "deposit", r"\blaunch\s?pad\b"),
    ("bright_savings", "Bright Savings", "deposit", r"\bbright savings\b|\bonline[- ]only savings\b|\bonline savings\b"),
    ("high_yield", "High-Yield Savings", "deposit", r"\bhigh[- ]yield\b"),
    ("money_market", "Investor's Choice Money Market", "deposit", r"\bmoney market\b|\binvestor'?s choice\b|\bachieve\b|\bmma\b"),
    ("you_name_it", "You Name It Savings", "deposit", r"\byou[- ]name[- ]it\b"),
    ("holiday_club", "Holiday Club Savings", "deposit", r"\bholiday club\b"),
    ("share_savings", "Share Savings", "deposit", r"\bshare savings\b|\bregular savings\b|\bbasic savings\b|\bsavings account\b(?! rates)|\bshare account\b|\bsavings (?:tiers?|rates?|apy)\b"),
    ("certificate", "Certificate", "deposit", r"\bcertificates?\b|\bcds?\b|\bcertificate of deposit\b|\bshare certificates?\b|\bterm[- ]share\b"),
    ("first_rate_checking", "1st Rate Checking", "deposit", r"\b1st rate checking\b|\bfirst rate checking\b|\binterest[- ]bearing checking\b"),
    ("free_checking", "Free Checking", "deposit", r"\bfree checking\b"),
    ("checking", "Checking", "deposit", r"\bchecking\b"),
    ("heloc", "Home Equity Line of Credit (HELOC)", "loan", r"\bheloc\b|\bhome equity line\b|\bline of credit\b.*\bhome\b"),
    ("home_equity_loan", "Home Equity Loan (Fixed)", "loan", r"\bhome equity loan\b|\bloan\s?-\s?standard\b"),
    ("home_improvement", "Home Improvement Loan", "loan", r"\bhome improvement\b"),
    ("mortgage_relief", "Mortgage Rate Relief Program", "mortgage", r"\brate relief\b"),
    ("mortgage", "Mortgage", "mortgage", r"\bmortgages?\b|\bhome loans?\b|\b(?:30|20|15|10)[- ]?(?:year|yr)\b.*\bfixed\b|\bfixed conventional\b|\bconventional\b|\brefinanc\w*\b.*\b(?:home|house|mortgage)\b|\bhome purchase\b|\bbuy(?:ing)? a (?:home|house)\b"),
    ("atv_loan", "ATV, Snowmobile & Jet Ski Loan", "loan", r"\batv\b|\bsnowmobile\b|\bjet ?ski\b|\bpowersport"),
    ("boat_rv_loan", "Boat & RV Loan", "loan", r"\bboats?\b|\brv\b|\bcamper\b|\brecreational\b"),
    ("auto_loan", "Auto & Motorcycle Loan", "loan", r"\bauto\b|\bcar\b|\bcars\b|\bvehicles?\b|\bmotorcycles?\b|\btruck\b|\bsuv\b|\bmodel[- ]year\b"),
    ("student_loan", "Student Loan", "loan", r"\bstudent loans?\b"),
    ("personal_loan", "Personal Loan", "loan", r"\bpersonal loans?\b|\bsignature loan\b|\bunsecured loan\b"),
    ("credit_card", "Visa Credit Card", "card", r"\bcredit cards?\b|\bvisa\b|\bcards?\b(?=.*\b(?:apr|rate)\b)|\bbalance transfer\b"),
]
_COMPILED = [(fid, name, kind, re.compile(rx, re.I)) for fid, name, kind, rx in FAMILIES]
FAMILY_KIND = {fid: kind for fid, _, kind, _ in FAMILIES}
FAMILY_NAME = {fid: name for fid, name, _, _ in FAMILIES}


def family_of(text: str) -> Optional[str]:
    t = normalize_q(text)
    for fid, _, _, rx in _COMPILED:
        if rx.search(t):
            return fid
    return None


def families_in(text: str) -> list[str]:
    t = normalize_q(text)
    return [fid for fid, _, _, rx in _COMPILED if rx.search(t)]


# Question-side synonym rewriting (applied before parsing / retrieval).
SYNONYMS: list[tuple[str, str]] = [
    (r"\bcds?\b", "certificate"),
    (r"\bcertificates? of deposits?\b", "certificate"),
    (r"\bcertificate of accounts?\b", "certificate"),
    (r"\bshare certificates?\b", "certificate"),
    (r"(?<!high-)(?<!high )\byield\b", "apy"),
    (r"\bannual percentage yield\b", "apy"),
    (r"\bannual percentage rate\b", "apr"),
    (r"\bdrive[- ]?(?:thru|through|in)\b", "drive-up"),
    (r"\bdrive up\b", "drive-up"),
    (r"\baba\b", "routing"),
    (r"\bcar loans?\b", "auto loan"),
    (r"\bvehicle loans?\b", "auto loan"),
    (r"\brefi\b", "refinance"),
    (r"\bhome equity line of credit\b", "heloc"),
    (r"\bmo\b", "month"),
    (r"\byr\b", "year"),
    (r"\bonline banking\b", "shine online banking"),
]
_SYN = [(re.compile(a, re.I), b) for a, b in SYNONYMS]


def normalize_q(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    for rx, rep in _SYN:
        t = rx.sub(rep, t)
    return t


# Retrieval query expansion (token -> extra tokens), applied after tokenisation.
EXPANSIONS = {
    "certificate": ["cd", "term"],
    "apy": ["yield", "dividend"],
    "routing": ["number"],
    "hour": ["lobby", "monday", "saturday"],
    "lobby": ["hour"],
    "drive-up": ["drive", "hour"],
    "join": ["member", "membership"],
    "member": ["membership", "join"],
    "membership": ["join"],
    "eligible": ["membership", "live", "work"],
    "wallet": ["apple", "google", "samsung", "pay"],
    "address": ["branch", "location"],
    "located": ["address", "branch"],
    "branch": ["location"],
    "phone": ["call"],
    "student": ["school", "college"],
}
