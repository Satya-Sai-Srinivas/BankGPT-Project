"""Text utilities: markdown cleanup, URL canonicalisation, number / money / date parsing.

Every regex here runs on bounded inputs (single lines or short strings) and avoids nested
quantifiers, so nothing can backtrack catastrophically at answer time.
"""
from __future__ import annotations

import html
import re
from datetime import date
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# --------------------------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------------------------
_TRACKING = re.compile(r"^(hslang|campaignid|pageurl|portalid|webinteractive\w*|containertype|utm_\w+|_hs\w+)$", re.I)


def canon_url(url: str) -> str:
    """Canonical key for a URL: https, no www., no fragment, no tracking params, no trailing slash."""
    u = (url or "").strip()
    if "//" not in u:
        u = "https://" + u.lstrip("/")
    parts = urlsplit(u)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunsplit(("https", host, path, urlencode(query), ""))


def url_path(url: str) -> str:
    return urlsplit(canon_url(url)).path.lower()


# --------------------------------------------------------------------------------------------
# Markdown cleanup
# --------------------------------------------------------------------------------------------
_DATA_URI = re.compile(r"\(data:[^)\s]{0,200000}\)")
_IMAGE = re.compile(r"!\[[^\]\n]{0,300}\]\([^)\n]{0,2000}\)")
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u200e\u200f\u202a-\u202e\u2060\ufeff]")
_FLAG_LINE = re.compile("^\\s*-?\\s*[\U0001F1E6-\U0001F1FF]{2}")
_ESCAPE = re.compile(r"\\([|*#_\[\]().\-+!`>])")
_DROP_LINES = re.compile(
    r"^(✕|Third Party Plugins|Messenger Launcher|Messenger|Twitter Widget Iframe|Table|Load More|PreviousNext|"
    r"Previous|Next|Go|Loading locations\.\.\.|Sort By:.*|#### Filter|\[Continue\]\(.*#\) Cancel|"
    r"\*\*Heads up! This link leads to a different website\.\*\*|We only do this when it.s helpful.*|"
    r"Select all (images|squares) with.*|reCAPTCHA|Recaptcha requires verification\.|1x|Tap to unmute)$"
)
_CARD_HEADING = re.compile(r"^#{1,6}\s*(Handpicked [Ff]or You|Recent News)\s*$")


def clean_markdown(md: str, *, cut_cards: bool = True) -> str:
    """Remove crawler furniture (modals, widgets, image data, related-article cards) and escapes."""
    md = md or ""
    md = md.replace("\\\\r\\\\n", "\n").replace("\\r\\n", "\n").replace("\r\n", "\n")
    md = _DATA_URI.sub("()", md)
    md = _IMAGE.sub("", md)
    md = html.unescape(html.unescape(md))
    md = _ZERO_WIDTH.sub("", md).replace("\u00a0", " ")
    out = []
    skipping_cards = False
    for line in md.split("\n"):
        s = line.strip()
        if cut_cards and _CARD_HEADING.match(s):
            skipping_cards = True
            continue
        if skipping_cards:
            # related-article cards run until the next "real" heading (## or #) that is not a card title
            if re.match(r"^#{1,3}\s+[^\[]", s) and not s.startswith("####"):
                skipping_cards = False
            else:
                continue
        if _FLAG_LINE.match(s) or s == "🇺🇸":
            continue
        if s.endswith("\\\\"):
            s = s[:-2].rstrip()
        elif s.endswith("\\"):
            s = s[:-1].rstrip()
        if _DROP_LINES.match(s):
            continue
        if "recaptcha/enterprise" in s or re.match(r"^\|(\s*\|)+$", s):
            continue
        s = _ESCAPE.sub(r"\1", s)
        out.append(s)
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_LINK = re.compile(r"\[([^\]\n]{0,300})\]\(((?:[^()\s]|\([^()\s]{0,100}\)){0,2000})(?:\s+\"[^\"\n]{0,300}\")?\)")


def strip_links(s: str) -> str:
    """'[text](url)' -> 'text' (keeps the visible text only)."""
    return _LINK.sub(lambda m: m.group(1), s)


def links(s: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in _LINK.finditer(s)]


def plain(s: str) -> str:
    """Markdown line -> plain text for display/answers."""
    s = strip_links(s)
    s = re.sub(r"[*_`]{1,3}", "", s)
    s = re.sub(r"^#{1,6}\s*", "", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def norm_dashes(s: str) -> str:
    return s.replace("–", "-").replace("—", "-").replace("‑", "-").replace("’", "'").replace("‘", "'")


# --------------------------------------------------------------------------------------------
# Footnotes glued to values
# --------------------------------------------------------------------------------------------
_PCT_FOOT = re.compile(r"(\d\.\d{2,3}%)\s?[1-9](?!\d)")
_WORD_FOOT = re.compile(r"\b(APR|APY)[1-9]\b")
_LINK_FOOT = re.compile(r"\s?\[\*{0,2}(?:\d|\*)\*{0,2}\]\([^)\s]{0,500}\)")


def strip_footnotes(cell: str) -> str:
    """'4.10%2' -> '4.10%', '5.39% APR1' -> '5.39% APR', '(APY)1' -> '(APY)'."""
    c = _LINK_FOOT.sub("", cell)
    c = _PCT_FOOT.sub(r"\1", c)
    c = _WORD_FOOT.sub(r"\1", c)
    c = re.sub(r"\((APY|APR)\)[1-9]", r"(\1)", c)
    c = re.sub(r"[¹²³]", "", c)
    c = re.sub(r"(?<=[\d%])\*+", "", c)
    return c.strip()


# --------------------------------------------------------------------------------------------
# Numbers
# --------------------------------------------------------------------------------------------
_PCT = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d{1,3})?)\s?%")
_MONEY = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(k|K|million|billion)?")


def pct_values(s: str) -> list[float]:
    return [float(m.group(1)) for m in _PCT.finditer(s or "")]


def first_pct(s: str) -> Optional[tuple[float, str]]:
    m = _PCT.search(s or "")
    if not m:
        return None
    return float(m.group(1)), m.group(1) + "%"


def money_value(s: str) -> Optional[float]:
    m = _MONEY.search(s or "")
    if not m:
        return None
    return _money(m)


def _money(m: re.Match) -> float:
    v = float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
    mult = (m.group(3) or "").lower()
    if mult == "k":
        v *= 1_000
    elif mult == "million":
        v *= 1_000_000
    elif mult == "billion":
        v *= 1_000_000_000
    return v


def money_values(s: str) -> list[float]:
    return [_money(m) for m in _MONEY.finditer(s or "")]


def money_range(s: str) -> Optional[tuple[float, float]]:
    """'$10,000 – $24,999.99' -> (10000, 24999.99); '$25,000+' -> (25000, inf);
    '$832,750 or less' -> (0, 832750); '$10,000-24,999' -> (10000, 24999)."""
    t = norm_dashes(s or "")
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(?:-|to)\s*\$?\s?(\d[\d,]*(?:\.\d+)?)", t)
    if m:
        return float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?\+", t)
    if m:
        return float(m.group(1).replace(",", "")), float("inf")
    m = re.search(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s+or\s+less", t, re.I)
    if m:
        return 0.0, float(m.group(1).replace(",", ""))
    return None


def fmt_money(v: float) -> str:
    if v == int(v):
        return f"${int(v):,}"
    return f"${v:,.2f}"


# --------------------------------------------------------------------------------------------
# Terms, model years
# --------------------------------------------------------------------------------------------
_NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "twenty": 20, "twenty-four": 24, "thirty": 30, "thirty-six": 36,
    "forty-eight": 48, "sixty": 60, "seventy-two": 72, "eighty-four": 84,
}
_TERM = re.compile(r"(?<![\d.$/,])(\d{1,3})\s?-?\s?(months?\b|mos?\b\.?|years?\b|yrs?\b\.?)", re.I)


def words_to_digits(s: str) -> str:
    def rep(m: re.Match) -> str:
        return str(_NUM_WORDS[m.group(0).lower()])
    pat = r"\b(" + "|".join(sorted((re.escape(k) for k in _NUM_WORDS), key=len, reverse=True)) + r")\b"
    return re.sub(pat, rep, s, flags=re.I)


def term_months(s: str) -> Optional[int]:
    """'17 Month' -> 17, '30-Year' -> 360, 'Loan – Standard (60 mo)' -> 60, 'six-month' -> 6."""
    t = words_to_digits(norm_dashes(s or ""))
    m = _TERM.search(t)
    if not m:
        return None
    n = int(m.group(1))
    return n * 12 if m.group(2).lower().startswith("y") else n


def model_year_range(s: str) -> Optional[tuple[int, int]]:
    """'2024-27 Model Year' -> (2024, 2027); 'Model Year 2026-23' -> (2023, 2026);
    '2016 Model Year (and older)' -> (1900, 2016)."""
    t = norm_dashes(s or "")
    if "model year" not in t.lower():
        return None
    m = re.search(r"(20\d\d)\s?-\s?(\d{2,4})", t)
    if m:
        a = int(m.group(1))
        b = int(m.group(2))
        if b < 100:
            b += (a // 100) * 100
        return (min(a, b), max(a, b))
    m = re.search(r"(20\d\d|19\d\d)", t)
    if m:
        y = int(m.group(1))
        if "older" in t.lower():
            return (1900, y)
        if "newer" in t.lower():
            return (y, 2100)
        return (y, y)
    return None


# --------------------------------------------------------------------------------------------
# Dates
# --------------------------------------------------------------------------------------------
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9, "sept": 9,
    "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_NAME = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\.?"
_DATE_LONG = re.compile(_MONTH_NAME + r"\s(\d{1,2})(?:st|nd|rd|th)?,?\s(\d{4})", re.I)
_DATE_SLASH = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})(?![\d/])")
_DATE_ISO = re.compile(r"(?<!\d)(20\d\d)-(\d\d)-(\d\d)(?!\d)")
_MONTH_YEAR = re.compile(_MONTH_NAME + r"\s(?:of\s)?(\d{4})", re.I)


def month_num(name: str) -> int:
    return MONTHS[name.lower().rstrip(".")[:3]]


def _mk(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(s: str) -> Optional[date]:
    """First full date in s ('March 31, 2026', '06/02/2026', '8/13/25', '2026-05-12')."""
    if not s:
        return None
    best = None
    for rx in (_DATE_LONG, _DATE_SLASH, _DATE_ISO):
        m = rx.search(s)
        if not m:
            continue
        if rx is _DATE_LONG:
            d = _mk(int(m.group(3)), month_num(m.group(1)), int(m.group(2)))
        elif rx is _DATE_SLASH:
            y = int(m.group(3))
            y = y + 2000 if y < 100 else y
            d = _mk(y, int(m.group(1)), int(m.group(2)))
        else:
            d = _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d and (best is None or m.start() < best[0]):
            best = (m.start(), d)
    return best[1] if best else None


def all_dates(s: str) -> list[date]:
    out = []
    for m in _DATE_LONG.finditer(s or ""):
        d = _mk(int(m.group(3)), month_num(m.group(1)), int(m.group(2)))
        if d:
            out.append(d)
    for m in _DATE_SLASH.finditer(s or ""):
        y = int(m.group(3))
        d = _mk(y + 2000 if y < 100 else y, int(m.group(1)), int(m.group(2)))
        if d:
            out.append(d)
    return out


def month_year(s: str) -> Optional[tuple[int, int]]:
    m = _MONTH_YEAR.search(s or "")
    if not m:
        return None
    return int(m.group(2)), month_num(m.group(1))


def iso(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def to_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    m = _DATE_ISO.search(s)
    if m:
        return _mk(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return parse_date(s)


# --------------------------------------------------------------------------------------------
# Tokenisation for retrieval
# --------------------------------------------------------------------------------------------
STOP = set(
    "a an the of to in on for and or is are was were be been do does did can could would should will what "
    "whats what's which who whom how when where why your you yours my me i we our us it its this that these "
    "those with at by from as about any there their them they he she his her if than then so not no yes "
    "please tell give get know want like much many some have has had dupaco dupaco's".split()
)
_TOKEN = re.compile(r"[a-z0-9$]+(?:[.'][a-z0-9]+)*%?")


def stem(t: str) -> str:
    """Cheap, deterministic stemmer: plural strip, then truncate long words to 6 characters
    ("recognition"/"recognized" -> "recogn", "employees"/"employee" -> "employ")."""
    if t[0].isdigit() or "$" in t or "%" in t:
        return t
    if len(t) > 4 and t.endswith("ies"):
        t = t[:-3] + "y"
    elif len(t) > 3 and t.endswith("s") and not t.endswith("ss") and not t.endswith("us"):
        t = t[:-1]
    return t[:6] if len(t) > 6 else t


def tokens(s: str, *, keep_stop: bool = False) -> list[str]:
    s = norm_dashes((s or "").lower())
    out = []
    for t in _TOKEN.findall(s):
        t = t.strip("'.")
        if not t or (not keep_stop and t in STOP):
            continue
        out.append(stem(t))
    return out


# --------------------------------------------------------------------------------------------
# Sentences
# --------------------------------------------------------------------------------------------
_ABBR = re.compile(
    r"(?:\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec|St|Ave|Rd|Dr|Blvd|Hwy|Ln|Mt|Ft|No|Inc|Co|Corp|"
    r"Mr|Mrs|Ms|Jr|Sr|vs|Wis|Ill|ext|Sen|Rep|Gov|Ph|approx)\.|\b[A-Z]\.|\b(?:a\.m|p\.m|U\.S|e\.g|i\.e)\.)$"
)
_BOUNDARY = re.compile(r"[.!?][\"”’)]?\s+(?=[A-Z0-9\"“$])")


def sentences(text: str) -> list[str]:
    """Split prose into sentences without breaking 'Oct. 1, 2024', '3299 Hillcrest Rd.' or '8 a.m. Monday'."""
    out = []
    for para in re.split(r"\n+", text or ""):
        para = para.strip()
        if not para:
            continue
        start = 0
        for m in _BOUNDARY.finditer(para):
            head = para[start:m.start() + 1]
            if _ABBR.search(head[-12:]):
                continue
            seg = para[start:m.end()].strip()
            if seg:
                out.append(seg)
            start = m.end()
        tail = para[start:].strip()
        if tail:
            out.append(tail)
    return out


def prose_sentences(md: str) -> list[str]:
    """Sentences of a markdown document (line by line, table rows skipped, links reduced to text)."""
    out = []
    for line in (md or "").split("\n"):
        if line.lstrip().startswith("|"):
            continue
        p = plain(line)
        if p:
            out.extend(sentences(p))
    return out


def fmt_date(d) -> str:
    """date -> 'March 31, 2026' (portable; no platform-specific strftime flags)."""
    return f"{d:%B} {d.day}, {d.year}"
