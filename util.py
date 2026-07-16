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
    low = text.lower()
    return [kw for kw in keywords if kw.lower() in low]


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
