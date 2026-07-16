"""Pure helpers: text cleaning, summaries, date parsing, hashing. No I/O."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import re
from typing import Optional

from bs4 import BeautifulSoup
from dateutil import parser as dateparser


def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def short_summary(text: str, max_sentences: int = 3, max_chars: int = 400) -> str:
    text = clean_text(text)
    if not text:
        return "(No summary provided — open the link for the full text.)"
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentences[:max_sentences]).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0] + "…"
    return summary


def parse_date(value) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dateparser.parse(str(value))
        if parsed and parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, OverflowError, TypeError):
        return None


def iso_date(value) -> str:
    """Normalise any date-ish value to 'YYYY-MM-DD' (sortable) or ''."""
    d = parse_date(value)
    return d.strftime("%Y-%m-%d") if d else ""


def matched_keywords(text, keywords):
    low=text.lower(); hits=[]
    for kw in keywords:
        k=kw.lower()
        if len(kw)<=4 or kw.isupper():
            if re.search(r""+re.escape(k)+r"", low): hits.append(kw)
        elif k in low: hits.append(kw)
    return hits

_EXCLUDE=[re.compile(p) for p in [r"inflation",r"monetary policy",r"policy rate",r"interest rate",r"unemployment",r"gdp",r"moldova",r"ukraine",r"enlargement",r"accession",r"western balkans",r"skills coalition",r"traineeship",r"trainees?",r"call for expression of interest"]]

def is_excluded(text):
    low=(text or '').lower()
    return any(p.search(low) for p in _EXCLUDE)


def content_hash(*parts: str) -> str:
    joined = "\u241f".join(p or "" for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds")


# CELEX descriptor letters → human document type.
# CELEX layout: sector(1) + year(4) + descriptor(letters) + number.
CELEX_TYPES = {
    "R": "Regulation", "L": "Directive", "D": "Decision",
    "F": "Framework Decision", "H": "Recommendation", "G": "Resolution",
    "A": "Act/Opinion", "J": "Judgment", "O": "Guideline",
    "C": "Notice/Communication", "M": "Merger Decision", "X": "Other",
    "Y": "Notice/Communication",
    "PC": "Commission proposal", "DC": "Commission communication",
    "SC": "Staff working document", "JC": "Joint communication",
}


def celex_type(celex: str) -> str:
    """Map a CELEX id to a readable document type. '' if not parseable."""
    if not celex:
        return ""
    m = re.match(r"^\d(\d{4})([A-Z]+)\d", celex.strip())
    if not m:
        return ""
    letters = m.group(2)
    return CELEX_TYPES.get(letters) or CELEX_TYPES.get(letters[0]) or "EU legal act"


def doc_type(row: dict) -> str:
    """Document type for any item: CELEX-derived for legislation, else generic."""
    t = celex_type(row.get("celex", ""))
    if t:
        return t
    return "Legislation" if row.get("prefiltered") else "News / publication"


_ACRONYMS = {
    "EU", "EEA", "ICT", "AI", "AML", "CFT", "GDPR", "DORA", "NIS", "NIS2",
    "ESRB", "EIOPA", "EBA", "ESMA", "ECB", "SSM", "SREP", "ICAAP", "CRR",
    "CRD", "RTS", "ITS", "CTPP", "SOC", "P2R", "RWA", "IT", "EDIC", "CSC",
    "US", "UK", "CFSP", "FI", "FFFS",
}
_FEED_NOISE = [
    r"Anonymous \(not verified\)",
    r"\b\w{3},\s*\d{2}/\d{2}/\d{4}\s*-\s*\d{1,2}:\d{2}",
    r"\bDate\s*\d{2}/\d{2}/\d{4}",
    r"News\s*&\s*Press",
    r"Careers\b.*$",
    r"Call for expression of interest\b.*$",
]
_ACT_TYPE_SENTENCE = {
    "Regulation": "A binding EU regulation — directly applicable in all member states.",
    "Directive": "An EU directive — member states must transpose it into national law.",
    "Decision": "An EU decision — binding on those it is addressed to.",
    "Framework Decision": "An EU framework decision.",
    "Recommendation": "A non-binding EU recommendation.",
    "Resolution": "A non-binding EU resolution.",
    "Commission proposal": "A legislative proposal from the European Commission (not yet in force).",
    "Commission communication": "A Commission communication setting out policy or plans (non-binding).",
    "Staff working document": "A Commission staff working document — background/analysis, non-binding.",
    "Joint communication": "A joint communication setting out policy (non-binding).",
    "Notice/Communication": "An official EU notice or communication.",
    "Guideline": "An EU guideline.",
    "Act/Opinion": "An EU act or opinion.",
    "Merger Decision": "A merger-control decision.",
}
def deshout(title: str) -> str:
    small = {"a","an","the","and","or","of","to","for","in","on","with","from","by","at","as","into"}
    out = []
    for i, w in enumerate(title.split()):
        core = re.sub(r"[^A-Za-z]", "", w)
        if not core or not core.isupper():
            out.append(w)
        elif core.lower() in small and i != 0:
            out.append(w.lower())
        elif core in _ACRONYMS or "-" in w or len(core) < 3:
            out.append(w)
        else:
            out.append(w.capitalize())
    return " ".join(out)
def clean_eurlex_title(title: str) -> str:
    t = clean_text(title)
    if "#" in t:
        t = t.split("#")[0].strip()
    t = re.sub(r"\s*\(Text with EEA relevance\)\s*$", "", t, flags=re.I)
    return deshout(t).strip()
def eurlex_summary(doc_type_label: str) -> str:
    return _ACT_TYPE_SENTENCE.get(doc_type_label, "An EU legal act.")
def clean_feed_summary(raw: str, title: str = "") -> str:
    text = clean_text(raw).replace("\u200b", "")
    for pat in _FEED_NOISE:
        text = re.sub(pat, "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -–—|·:")
    if title:
        tnorm = re.sub(r"\s+", " ", clean_text(title)).strip()
        if tnorm and text.lower().startswith(tnorm.lower()):
            text = text[len(tnorm):].strip(" -–—|·:")
    return short_summary(text)
