"""
Operational-Risk Regulatory Monitor
------------------------------------
A Streamlit dashboard that aggregates EU and Swedish regulatory updates relevant
to operational risk, filters them to the operational-risk space, and shows a short
summary plus a direct link to the primary source.

Primary data routes (reliable, no fragile HTML scraping):
  * Finansinspektionen (FI): every fi.se listing page exposes RSS by appending "/rss".
  * EUR-Lex: predefined Atom/RSS feeds for the Official Journal and legislation.
  * Bonus EU sources with clean feeds: EBA, ECB, ESMA, EIOPA (edit SOURCES to taste).

A generic HTML fallback (requests + BeautifulSoup) is included for any source that
has no feed, but feeds are strongly preferred.

Run:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field
from typing import Optional

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

USER_AGENT = (
    "Cardinal-OpRisk-Monitor/1.0 (regulatory monitoring; contact: ops@getcardinal.io)"
)
REQUEST_TIMEOUT = 20  # seconds
DEFAULT_LOOKBACK_DAYS = 90


@dataclass
class Source:
    name: str
    url: str
    kind: str = "rss"          # "rss" or "html"
    region: str = "EU"         # "EU" or "SE"
    enabled: bool = True
    # For html sources only: CSS selectors to extract items.
    item_selector: str = ""
    title_selector: str = ""
    link_selector: str = ""
    date_selector: str = ""
    base_url: str = ""         # to resolve relative links


# Edit this list freely. FI listing pages all support the "/rss" suffix.
# EUR-Lex predefined feeds: https://eur-lex.europa.eu/content/help/my-eurlex/my-rss-feeds.html
SOURCES: list[Source] = [
    # --- Sweden: Finansinspektionen --------------------------------------- #
    Source(
        name="FI – All published material",
        url="https://www.fi.se/en/published/all-published-material/rss",
        region="SE",
    ),
    Source(
        name="FI – Proposed new regulations (FFFS)",
        url="https://www.fi.se/sv/publicerat/forslag-nya-fffs/rss",
        region="SE",
    ),
    Source(
        name="FI – Reports / supervision",
        url="https://www.fi.se/sv/publicerat/rapporter/rss",
        region="SE",
    ),
    Source(
        name="FI – Sanctions & interventions",
        url="https://www.fi.se/en/published/sanctions/rss",
        region="SE",
    ),
    # --- Sweden: Riksbank (payments / stability context) ------------------ #
    Source(
        name="Riksbank – Press & published",
        url="https://www.riksbank.se/en-gb/rss/press-and-published/",
        region="SE",
    ),
    # --- EU: EUR-Lex predefined feeds ------------------------------------- #
    # Predefined feed: latest legislation (Parliament & Council). Confirm/replace
    # the exact predefined-feed URL from your EUR-Lex "My RSS feeds" page if needed.
    Source(
        name="EUR-Lex – Latest legislation",
        url="https://eur-lex.europa.eu/EN/display-feed.rss?myRssId=eP9ezlXEFL%2Fa3GhmFOuJijQDB5Dvm4t9OEC%2FsdEzGHZ%2FQGI%2BFwbjlA%3D%3D",
        region="EU",
    ),
    # --- EU: where operational-risk regulation actually breaks ------------ #
    Source(
        name="EBA – News & press",
        url="https://www.eba.europa.eu/rss.xml",
        region="EU",
    ),
    Source(
        name="ESMA – News",
        url="https://www.esma.europa.eu/rss.xml",
        region="EU",
    ),
    Source(
        name="EIOPA – News",
        url="https://www.eiopa.europa.eu/rss.xml",
        region="EU",
    ),
    Source(
        name="ECB Banking Supervision – Press",
        url="https://www.bankingsupervision.europa.eu/rss/pub.xml",
        region="EU",
    ),
]


# Operational-risk keyword universe. An item is kept if any term appears in its
# title or summary (case-insensitive). Editable from the sidebar at runtime.
DEFAULT_KEYWORDS: list[str] = [
    "operational risk", "operativ risk", "operationell risk",
    "operational resilience", "operativ motståndskraft", "beredskap",
    "DORA", "ICT", "IKT", "third-party", "tredjepart", "outsourcing", "utlagd",
    "CRR3", "CRD6", "business indicator", "ICAAP", "SREP",
    "incident", "incidentrapportering", "cyber", "cybersäkerhet",
    "resilience", "business continuity", "kontinuitet",
    "fraud", "bedrägeri", "AML", "penningtvätt", "sanction", "sanktion",
    "payment fraud", "betalningsbedrägeri", "Basel", "own funds", "RWA",
    "model risk", "AI", "artificial intelligence",
]


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

@dataclass
class Item:
    source: str
    region: str
    title: str
    link: str
    published: Optional[dt.datetime]
    raw_summary: str
    summary: str = field(default="")
    matched_terms: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def clean_text(raw: str) -> str:
    """Strip HTML, collapse whitespace, unescape entities."""
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def short_summary(text: str, max_sentences: int = 3, max_chars: int = 400) -> str:
    """A lightweight extractive summary: first few sentences, capped in length."""
    text = clean_text(text)
    if not text:
        return "(No summary provided by the source — open the link for the full text.)"
    sentences = re.split(r"(?<=[.!?])\s+", text)
    summary = " ".join(sentences[:max_sentences]).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0] + "…"
    return summary


def parse_date(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dateparser.parse(value)
        if parsed and parsed.tzinfo:
            parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return parsed
    except (ValueError, OverflowError, TypeError):
        return None


def matched_keywords(text: str, keywords: list[str]) -> list[str]:
    low = text.lower()
    return [kw for kw in keywords if kw.lower() in low]


# --------------------------------------------------------------------------- #
# Fetchers
# --------------------------------------------------------------------------- #

@st.cache_data(ttl=1800, show_spinner=False)  # cache 30 min
def fetch_rss(url: str, source_name: str, region: str) -> list[dict]:
    """Fetch and parse an RSS/Atom feed. Returns plain dicts (cache-friendly)."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:  # network, parse, etc.
        return [{"_error": f"{source_name}: {exc}"}]

    items = []
    for entry in parsed.entries:
        published = (
            getattr(entry, "published", None)
            or getattr(entry, "updated", None)
            or getattr(entry, "pubDate", None)
        )
        summary = (
            getattr(entry, "summary", None)
            or getattr(entry, "description", None)
            or ""
        )
        items.append(
            {
                "source": source_name,
                "region": region,
                "title": clean_text(getattr(entry, "title", "(untitled)")),
                "link": getattr(entry, "link", ""),
                "published": published,
                "raw_summary": summary,
            }
        )
    return items


@st.cache_data(ttl=1800, show_spinner=False)
def fetch_html(src_dict: dict) -> list[dict]:
    """Generic HTML fallback. Only used for sources with kind='html'."""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(src_dict["url"], headers=headers, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
    except Exception as exc:
        return [{"_error": f"{src_dict['name']}: {exc}"}]

    items = []
    for node in soup.select(src_dict["item_selector"]):
        title_el = node.select_one(src_dict["title_selector"]) if src_dict["title_selector"] else node
        link_el = node.select_one(src_dict["link_selector"]) if src_dict["link_selector"] else node
        date_el = node.select_one(src_dict["date_selector"]) if src_dict["date_selector"] else None
        link = link_el.get("href", "") if link_el else ""
        if link and src_dict.get("base_url") and link.startswith("/"):
            link = src_dict["base_url"].rstrip("/") + link
        items.append(
            {
                "source": src_dict["name"],
                "region": src_dict["region"],
                "title": clean_text(title_el.get_text()) if title_el else "(untitled)",
                "link": link,
                "published": date_el.get_text() if date_el else None,
                "raw_summary": clean_text(node.get_text())[:600],
            }
        )
    return items


def collect(sources: list[Source], keywords: list[str], lookback_days: int):
    """Fetch all enabled sources, filter by keyword + date, dedupe, sort."""
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=lookback_days)
    raw_items: list[dict] = []
    errors: list[str] = []

    for src in sources:
        if not src.enabled:
            continue
        if src.kind == "rss":
            results = fetch_rss(src.url, src.name, src.region)
        else:
            results = fetch_html(src.__dict__)
        for r in results:
            if "_error" in r:
                errors.append(r["_error"])
            else:
                raw_items.append(r)

    seen = set()
    items: list[Item] = []
    for r in raw_items:
        link = r["link"]
        key = link or r["title"]
        if key in seen:
            continue
        seen.add(key)

        published = parse_date(r["published"])
        haystack = f"{r['title']} {clean_text(r['raw_summary'])}"
        terms = matched_keywords(haystack, keywords)
        if not terms:
            continue
        if published and published < cutoff:
            continue

        items.append(
            Item(
                source=r["source"],
                region=r["region"],
                title=r["title"],
                link=link,
                published=published,
                raw_summary=r["raw_summary"],
                summary=short_summary(r["raw_summary"]),
                matched_terms=terms,
            )
        )

    # Newest first; undated items sink to the bottom.
    items.sort(key=lambda i: (i.published or dt.datetime.min), reverse=True)
    return items, errors


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="Operational-Risk Regulatory Monitor",
    page_icon="📡",
    layout="wide",
)

st.title("Operational-Risk Regulatory Monitor")
st.caption(
    "EU and Swedish regulatory updates in the operational-risk space — "
    "summarised, filtered, and linked to the primary source."
)

with st.sidebar:
    st.header("Filters")

    lookback = st.slider(
        "Look-back window (days)",
        min_value=7, max_value=365, value=DEFAULT_LOOKBACK_DAYS, step=7,
    )

    region_choice = st.multiselect(
        "Regions",
        options=["EU", "SE"],
        default=["EU", "SE"],
    )

    source_names = [s.name for s in SOURCES]
    chosen_sources = st.multiselect(
        "Sources",
        options=source_names,
        default=source_names,
    )

    st.subheader("Keywords")
    st.caption("An item is kept if any keyword appears in its title or summary.")
    keyword_text = st.text_area(
        "One keyword per line",
        value="\n".join(DEFAULT_KEYWORDS),
        height=220,
    )
    keywords = [k.strip() for k in keyword_text.splitlines() if k.strip()]

    if st.button("🔄 Refresh now (clear cache)"):
        st.cache_data.clear()
        st.rerun()

    st.caption("Feeds are cached for 30 minutes. Edit SOURCES in app.py to add more.")

# Apply source/region selection
active_sources = [
    s for s in SOURCES
    if s.name in chosen_sources and s.region in region_choice
]

with st.spinner("Fetching regulatory feeds…"):
    items, errors = collect(active_sources, keywords, lookback)

# Headline metrics
col1, col2, col3 = st.columns(3)
col1.metric("Matching updates", len(items))
col2.metric("Sources queried", len(active_sources))
col3.metric("Look-back", f"{lookback} days")

if errors:
    with st.expander(f"⚠️ {len(errors)} source(s) returned an error", expanded=False):
        for e in errors:
            st.write(f"- {e}")

st.divider()

if not items:
    st.info(
        "No matching updates. Widen the look-back window, add keywords, "
        "or check that the selected feeds are reachable."
    )
else:
    for item in items:
        date_str = item.published.strftime("%Y-%m-%d") if item.published else "undated"
        region_badge = "🇸🇪 SE" if item.region == "SE" else "🇪🇺 EU"
        with st.container(border=True):
            top = st.columns([0.7, 0.3])
            top[0].markdown(f"### {item.title}")
            top[1].markdown(
                f"<div style='text-align:right;color:#888'>{region_badge} · "
                f"{date_str}<br><b>{item.source}</b></div>",
                unsafe_allow_html=True,
            )
            st.write(item.summary)
            tags = " ".join(f"`{t}`" for t in item.matched_terms[:6])
            st.markdown(f"**Matched:** {tags}")
            if item.link:
                st.markdown(f"[↗ Open primary source]({item.link})")

st.divider()
st.caption(
    "Built for monitoring public regulatory publications. Always verify against the "
    "primary source before acting. Summaries are extractive (first sentences of the "
    "source abstract), not legal interpretation."
)
