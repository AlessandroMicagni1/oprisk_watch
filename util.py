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


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    """Match keywords in text. Short/acronym terms (<=4 chars or ALL-CAPS) must
    match as whole words, so 'RWA' doesn't match 'Norway' and 'AI' doesn't match
    'maintain'. Longer descriptive terms match as substrings (so 'cyber' still
    hits 'cybersecurity')."""
    low = text.lower()
    hits = []
    for kw in keywords:
        k = kw.lower()
        if len(kw) <= 4 or kw.isupper():
            if re.search(r"\b" + re.escape(k) + r"\b", low):
                hits.append(kw)
        elif k in low:
            hits.append(kw)
    return hits


# Off-topic signals — items whose title/summary hit these are dropped as not
# operational-risk-in-finance. Balanced: excludes clear macro/foreign-policy/
# institution-building noise, keeps adjacent supervisory/resilience topics.
_EXCLUDE_PATTERNS = [re.compile(p) for p in [
    # monetary policy / macroeconomic commentary
    r"\binflation\b", r"\bmonetary policy\b", r"\bpolicy rate\b",
    r"\binterest rate\b", r"\bunemployment\b", r"\bgdp\b",
    # foreign policy / geographic aid / enlargement
    r"\bmoldova\b", r"\bukraine\b", r"\benlargement\b", r"\baccession\b",
    r"\bwestern balkans\b",
    # EU institution / skills building (not firm-facing regulation)
    r"\bskills coalition\b", r"\btraineeship\b", r"\btrainees?\b",
    r"\bcall for expression of interest\b",
]]


def is_excluded(text: str) -> bool:
    """True if the item is off-topic for operational risk in finance."""
    low = (text or "").lower()
    return any(p.search(low) for p in _EXCLUDE_PATTERNS)


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


# --------------------------------------------------------------------------- #
# Summary cleaning (deterministic, no AI)
# --------------------------------------------------------------------------- #

# Acronyms to preserve when de-shouting ALL-CAPS titles.
_ACRONYMS = {
    "EU", "EEA", "ICT", "AI", "AML", "CFT", "GDPR", "DORA", "NIS", "NIS2",
    "ESRB", "EIOPA", "EBA", "ESMA", "ECB", "SSM", "SREP", "ICAAP", "CRR",
    "CRD", "RTS", "ITS", "CTPP", "SOC", "P2R", "RWA", "IT", "EDIC", "CSC",
    "US", "UK", "CFSP", "FI", "FFFS",
}

# Boilerplate patterns that leak into RSS descriptions (author lines,
# timestamps, careers/nav fragments). Removed before summarising.
_FEED_NOISE = [
    r"Anonymous \(not verified\)",
    r"\b\w{3},\s*\d{2}/\d{2}/\d{4}\s*-\s*\d{1,2}:\d{2}",   # Thu, 07/09/2026 - 17:00
    r"\bDate\s*\d{2}/\d{2}/\d{4}",
    r"News\s*&\s*Press",
    r"Careers\b.*$",                                        # careers + trailing nav
    r"Call for expression of interest\b.*$",
]

# Plain-English one-liner describing what each instrument type *is*.
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
    """Fix shouting titles. Title-cases ALL-CAPS words unless they're acronyms
    or short joining words; leaves normal mixed-case words untouched."""
    small = {"a", "an", "the", "and", "or", "of", "to", "for", "in", "on",
             "with", "from", "by", "at", "as", "into"}
    out = []
    for i, w in enumerate(title.split()):
        core = re.sub(r"[^A-Za-z]", "", w)
        if not core or not core.isupper():
            out.append(w)                                  # not shouting
        elif core.lower() in small and i != 0:
            out.append(w.lower())                          # joining word
        elif core in _ACRONYMS or "-" in w or len(core) < 3:
            out.append(w)                                  # acronym / compound
        else:
            out.append(w.capitalize())                     # de-shout
    return " ".join(out)


def clean_eurlex_title(title: str) -> str:
    """Strip '#' case-markers, '(Text with EEA relevance)', and de-shout caps."""
    t = clean_text(title)
    if "#" in t:
        t = t.split("#")[0].strip()
    t = re.sub(r"\s*\(Text with EEA relevance\)\s*$", "", t, flags=re.I)
    return deshout(t).strip()


def eurlex_summary(doc_type_label: str) -> str:
    """Plain-English act-type sentence for a EUR-Lex legislation card."""
    return _ACT_TYPE_SENTENCE.get(doc_type_label, "An EU legal act.")


_SIGNAL = [
    "operational", "resilience", "ict", "cyber", "risk", "incident", "outsourc",
    "third-party", "third party", "fraud", "aml", "money laundering", "sanction",
    "dora", "supervis", "report", "requirement", "framework", "control",
    "governance", "capital", "own funds", "model", "continuity", "breach",
    "penetration", "payment", "conduct", "settlement", "guideline", "consultation",
]


def _rank_sentences(sentences: list[str], max_n: int) -> list[str]:
    """Pick the most op-risk-relevant sentences, preserving original order."""
    scored = [(sum(t in s.lower() for t in _SIGNAL), i, s) for i, s in enumerate(sentences)]
    top = sorted(scored, key=lambda x: (-x[0], x[1]))[:max_n]
    top.sort(key=lambda x: x[1])
    return [t[2] for t in top]


def clean_feed_summary(raw: str, title: str = "", max_sentences: int = 5,
                       max_chars: int = 750) -> str:
    """Strip feed boilerplate, drop a leading duplicate title, keep the most
    relevant sentences (up to max_sentences), capped at max_chars."""
    text = clean_text(raw).replace("\u200b", "")
    for pat in _FEED_NOISE:
        text = re.sub(pat, "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip(" -–—|·:")
    if title:
        tnorm = re.sub(r"\s+", " ", clean_text(title)).strip()
        if tnorm and text.lower().startswith(tnorm.lower()):
            text = text[len(tnorm):].strip(" -–—|·:")
    if not text:
        return "(No summary provided — open the link for the full text.)"
    sents = re.split(r"(?<=[.!?])\s+", text)
    if len(sents) > max_sentences:
        sents = _rank_sentences(sents, max_sentences)
    out = " ".join(sents).strip()
    if len(out) > max_chars:
        out = out[:max_chars].rsplit(" ", 1)[0] + "…"
    return out


def describe_eurlex(title: str, doc_type_label: str) -> str:
    """Title-derived description used until the real preamble text is fetched:
    the act-type sentence plus what the act amends/supplements, if stated."""
    out = [eurlex_summary(doc_type_label)]
    m = re.search(
        r"\b(supplement\w*|amend\w*|repeal\w*|implement\w*|correct\w*)\b\s+"
        r"((?:Regulation|Directive|Decision)[^,.;]*)", title, re.I)
    if m:
        verb = {"supplementing": "supplements", "amending": "amends",
                "repealing": "repeals", "implementing": "implements",
                "correcting": "corrects"}.get(m.group(1).lower(), m.group(1).lower())
        rel = re.sub(r"\s+", " ", m.group(2)).strip()
        out.append(f"It {verb} {rel[:120]}.")
    return " ".join(out)
