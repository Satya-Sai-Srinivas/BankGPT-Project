"""Page model and page-level classification: type, authority, publish date, expiry.

Rules are written against URL keywords and content cues (not only dupaco.com paths) so that the
harness self-test site (example-cu.test) is classified sensibly too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .text import canon_url, clean_markdown, parse_date, to_date, url_path

# Authority ladder (higher = more trustworthy for product facts). Tier 1 = official rate sources.
AUTHORITY = {
    "rate_sheet": 100,
    "product": 95,
    "contact": 85,
    "fee_doc": 75,
    "home": 70,
    "about": 70,
    "newsroom": 60,
    "pdf": 55,
    "blog": 40,
    "biz_resource": 35,
    "calculator": 20,
    "campaign": 18,
    "landing": 15,
    "legal": 30,
    "listing": 5,
    "expired": 1,
    "junk": 0,
}
TIER1 = {"rate_sheet", "product"}

_EXPIRED = re.compile(r"this offer has ended|offer has expired|offer is no longer available|offer ended", re.I)


@dataclass
class PageVersion:
    url: str                 # original URL (used for citations)
    key: str                 # canonical URL key
    title: str
    text: str                # cleaned markdown
    fetched: date
    snap: int                # snapshot index (0-based)
    ptype: str = "other"
    authority: int = 50
    pub_date: Optional[date] = None
    expired: bool = False
    stale_fetch: bool = False        # fetched before the snapshot date (carried over by the crawler)
    content_hash: int = 0
    meta: dict = field(default_factory=dict)

    @property
    def tier1(self) -> bool:
        return self.ptype in TIER1 and not self.expired


def classify(url: str, title: str, text: str) -> str:
    p = url_path(url)
    t = (title or "").lower()
    if re.search(r"campaignid=|pageurl=", url, re.I) and "privacy" in p:
        return "junk"
    if p.startswith("/hubfs/") or p.endswith((".pdf", ".xlsx", ".xls", ".csv")):
        if re.search(r"fee[-_ ]?schedule|fees", p):
            return "fee_doc"
        return "pdf"
    if re.search(r"/(tag|author)/|/page/\d+", p) or p in {"/learn/blog", "/newsroom", "/business/resources", "/resources",
                                                           "/resources/personal-resources", "/resources/business-resources",
                                                           "/resources/dupaco-news", "/covid-19"}:
        return "listing"
    if re.fullmatch(r"/(rates|business-rates)", p) or re.search(r"/rates?(/|$)", p) and "calculator" not in p:
        return "rate_sheet"
    if p.startswith("/newsroom/") or "press-release" in p or "/news/" in p:
        return "newsroom"
    if p.startswith("/calculators") or p == "/business-calculators" or p.endswith("-calculator"):
        return "calculator"
    if p.startswith("/business/resources/"):
        return "biz_resource"
    if p.startswith("/learn/") or re.match(r"^/\d{4}/\d\d/\d\d/", p) or p.startswith(("/dupacodaily", "/protection", "/blog")):
        return "blog"
    if p.endswith("-lp") or p in {"/offer-expired"} or "promo" in p or "offer" in p:
        return "landing"
    if p in {"/switch-and-earn", "/homebuying-guidance", "/mortgage-refi", "/earn-more", "/money-makeover"}:
        return "campaign"
    if re.search(r"privacy|disclosure|subscription-preferences|photo-release", p):
        return "legal"
    if p.startswith("/contact") or p in {"/about/join", "/membership", "/about/member-services", "/thankuse"}:
        return "contact"
    if p in {"/", ""}:
        return "home"
    if p.startswith(("/about", "/community", "/foundation", "/careers", "/scholarships", "/not-for-sale")):
        return "about"
    if "fee" in p:
        return "fee_doc"
    if p.startswith(("/personal", "/business", "/checking", "/loans", "/personal-loans", "/savings", "/shine",
                     "/brighttrack", "/financial-services", "/online-and-mobile-banking", "/connect", "/mobile",
                     "/manage-account-alerts")) or p.endswith("-grant") or "grant" in p:
        return "product"
    if "certificate" in p or "loan" in p or "saving" in p or "checking" in p:
        return "product"
    return "other"


_ART_DATE = re.compile(
    r"^(?:\d+ min read\s*\n+)?\s*\[[^\]\n]{1,80}\]\([^)\n]*/author/[^)\n]*\)\s*\n+\s*([A-Z][a-z]{2,9}\.? \d{1,2}, \d{4})",
    re.M,
)
_WRITTEN_BY = re.compile(r"Written by \[[^\]\n]{1,80}\]\([^)\n]*\)\s*\\?\|\s*([A-Z][a-z]{2,9}\.? \d{1,2}, \d{4})")
_UPDATED = re.compile(r"_Updated ([A-Z][a-z]{2,9}\.? \d{1,2}, \d{4})")


def article_date(raw_md: str) -> Optional[date]:
    head = raw_md[:4000]
    for rx in (_UPDATED, _ART_DATE, _WRITTEN_BY):
        m = rx.search(head)
        if m:
            d = parse_date(m.group(1))
            if d:
                return d
    # Fallback: a bare "Month DD, YYYY" line in the first lines of the page.
    for line in head.split("\n")[:12]:
        s = line.strip()
        if re.fullmatch(r"[A-Z][a-z]{2,9}\.? \d{1,2}, \d{4}", s):
            return parse_date(s)
    return None


def build_page(url: str, title: str, markdown: str, fetched_at: str, snap: int, taken_on: date) -> PageVersion:
    fetched = to_date(fetched_at) or taken_on
    text = clean_markdown(markdown)
    ptype = classify(url, title, text)
    expired = bool(_EXPIRED.search(text[:3000]))
    if expired and ptype not in ("newsroom", "blog"):
        ptype = "expired"
    pub = article_date(markdown) if ptype in ("newsroom", "blog", "biz_resource") else None
    pv = PageVersion(
        url=url, key=canon_url(url), title=title or "", text=text, fetched=fetched, snap=snap, ptype=ptype,
        authority=AUTHORITY.get(ptype, 50), pub_date=pub, expired=expired, stale_fetch=fetched < taken_on,
        content_hash=hash(text),
    )
    if pv.stale_fetch:
        pv.authority -= 5
    return pv
