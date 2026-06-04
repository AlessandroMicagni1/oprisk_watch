"""
Operational-Risk Regulatory Monitor
------------------------------------
Aggregates EU and Swedish regulatory updates relevant to operational risk.

Two kinds of source:
  1. RSS feeds (FI, EBA, ESMA, ECB, EIOPA, Riksbank) -> the *latest* news.
     RSS only ever carries a site's most recent items (no history), so it is
     used for fresh updates, not bulk.
  2. EUR-Lex SPARQL (publications.europa.eu) -> the *legislation database*.
     This is queried directly so it can return thousands of legal acts and
     backfill years, filtered to operational-risk terms in the title.

Run locally:
    pip install -r requirements.txt
    streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass
from typing import Optional

import feedparser
import requests
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

USER_AGENT = "Cardinal-OpRisk-Monitor/1.0 (regulatory monitoring; ops@getcardinal.io)"
REQUEST_TIMEOUT = 30
DEFAULT_LOOKBACK_DAYS = 90

# EUR-Lex public SPARQL endpoint (CELLAR). No authentication required.
EURLEX_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX_PAGE = 100  # rows per SPARQL request; we loop OFFSET to reach the max.

# Title phrases used to filter EUR-Lex legislation. These are deliberately
# multi-word/specific to avoid substring false positives (e.g. "ict" would
# otherwise match "predict", "ai" would match "maintenance"). Edit freely.
EURLEX_QUERY_TERMS = [
    # core operational risk / resilience
    "operational risk", "operational resilience", "digital operational resilience",
    "business continuity", "operational continuity", "crisis management",
    # ICT / cyber / technology
    "information and communication technology", "ict-related", "ict third",
    "ict risk", "ict service", "ict security", "ict provider",
    "cyber", "cybersecurity", "network and information systems",
    "penetration testing", "threat-led", "data breach", "critical infrastructure",
    # third parties / outsourcing / concentration
    "outsourcing", "third-party", "third party", "critical third", "cloud",
    # financial crime / conduct
    "money laundering", "terrorist financing", "terrorism financing",
    "sanction", "fraud", "payment fraud", "market abuse",
    # prudential capital / governance for operational risk
    "own funds", "business indicator", "internal governance", "internal control",
    "risk management framework", "model risk",
    # emerging
    "artificial intelligence", "machine learning", "distributed ledger",
]


@dataclass
class Source:
    name: str
    url: str
    kind: str = "rss"          # "rss" only here; EUR-Lex handled separately
    region: str = "EU"
    enabled: bool = True


SOURCES: list[Source] = [
    # --- Sweden: Finansinspektionen (append /rss to any listing page) ----- #
    Source("FI – All published material",
           "https://www.fi.se/en/published/all-published-material/rss", region="SE"),
    Source("FI – Proposed new regulations (FFFS)",
           "https://www.fi.se/sv/publicerat/forslag-nya-fffs/rss", region="SE"),
    Source("FI – Sanctions & interventions",
           "https://www.fi.se/en/published/sanctions/financial-firms/rss", region="SE"),
    # --- Sweden: Riksbank (real feeds under /en-gb/rss/...) --------------- #
    Source("Riksbank – Press releases",
           "https://www.riksbank.se/en-gb/rss/press-releases/", region="SE"),
    Source("Riksbank – Notices",
           "https://www.riksbank.se/en-gb/rss/notices/", region="SE"),
    # --- EU agencies ------------------------------------------------------ #
    Source("EBA – News & press", "https://www.eba.europa.eu/rss.xml", region="EU"),
    Source("ESMA – News", "https://www.esma.europa.eu/rss.xml", region="EU"),
    Source("ECB Banking Supervision – Press",
           "https://www.bankingsupervision.europa.eu/rss/press.html", region="EU"),
    Source("EIOPA – News", "https://www.eiopa.europa.eu/node/4816/rss_en", region="EU"),
    # NOTE: EUR-Lex legislation is NOT an RSS source — it is fetched in bulk
    # via SPARQL (see fetch_eurlex_sparql). RSS for EUR-Lex is capped and
    # cannot return history.
]

# Keyword universe for filtering the RSS items (English + Swedish). EUR-Lex
# items are pre-filtered by the SPARQL query, so they bypass this.
DEFAULT_KEYWORDS: list[str] = [
    "operational risk", "operativ risk", "operationell risk",
    "operational resilience", "operativ motståndskraft", "beredskap",
    "DORA", "ICT", "IKT", "third-party", "tredjepart", "outsourcing", "utlagd",
    "CRR3", "CRD6", "business indicator", "ICAAP", "SREP",
    "incident", "incidentrapportering", "cyber", "cybersäkerhet",
    "resilience", "business continuity", "kontinuitet",
    "fraud", "bedrägeri", "AML", "penningtvätt", "sanction", "sanktion",
    "payment fraud", "betalningsbedrägeri", "Basel", "own funds", "RWA",
    "model risk", "artificial intelligence",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

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


def parse_date(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dateparser.parse(str(value))
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

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_rss(url: str, source_name: str, region: str) -> list[dict]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        return [{"_error": f"{source_name}: {exc}"}]

    items = []
    for entry in parsed.entries:
        items.append({
            "source": source_name,
            "region": region,
            "title": clean_text(getattr(entry, "title", "(untitled)")),
            "link": getattr(entry, "link", ""),
            "published": getattr(entry, "published", None) or getattr(entry, "updated", None),
            "raw_summary": getattr(entry, "summary", None) or getattr(entry, "description", "") or "",
            "prefiltered": False,
        })
    return items


def _build_eurlex_query(terms: list[str], since_year: int, limit: int, offset: int) -> str:
    title_filter = " || ".join(
        f'CONTAINS(LCASE(STR(?title)), "{t.lower()}")' for t in terms
    )
    return f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
SELECT DISTINCT ?celex ?title ?date WHERE {{
  ?work cdm:work_date_document ?date .
  ?work cdm:resource_legal_id_celex ?celex .
  ?expr cdm:expression_belongs_to_work ?work .
  ?expr cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
  ?expr cdm:expression_title ?title .
  FILTER(?date >= "{since_year}-01-01"^^xsd:date)
  FILTER({title_filter})
}}
ORDER BY DESC(?date)
LIMIT {limit} OFFSET {offset}
""".strip()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_eurlex_sparql(terms: tuple, since_year: int, max_results: int) -> dict:
    """Query EUR-Lex legislation by title keyword + date via SPARQL, paginating.

    Returns {"items": [...], "error": str|None, "query": str, "count": int}.
    """
    items: list[dict] = []
    error = None
    last_query = ""
    offset = 0
    try:
        while len(items) < max_results:
            page = min(EURLEX_PAGE, max_results - len(items))
            last_query = _build_eurlex_query(list(terms), since_year, page, offset)
            resp = requests.get(
                EURLEX_SPARQL,
                params={"query": last_query, "format": "application/sparql-results+json"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
                timeout=60,
            )
            resp.raise_for_status()
            bindings = resp.json().get("results", {}).get("bindings", [])
            if not bindings:
                break
            for b in bindings:
                celex = b.get("celex", {}).get("value", "")
                title = b.get("title", {}).get("value", "")
                date = b.get("date", {}).get("value", "")
                if not celex:
                    continue
                items.append({
                    "source": "EUR-Lex (legislation)",
                    "region": "EU",
                    "title": clean_text(title) or celex,
                    "link": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                    "published": date,
                    "raw_summary": f"CELEX {celex}. {clean_text(title)}",
                    "prefiltered": True,
                })
            if len(bindings) < page:
                break
            offset += page
    except Exception as exc:
        error = f"EUR-Lex SPARQL: {exc}"
    return {"items": items, "error": error, "query": last_query, "count": len(items)}


def collect(sources, keywords, lookback_days, eurlex_on, eurlex_year, eurlex_max, eurlex_terms):
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=lookback_days)
    raw: list[dict] = []
    errors: list[str] = []
    eurlex_info = {"count": 0, "query": "", "error": None}

    # 1) RSS sources (latest news), keyword + date filtered.
    for src in sources:
        if not src.enabled:
            continue
        for r in fetch_rss(src.url, src.name, src.region):
            if "_error" in r:
                errors.append(r["_error"])
            else:
                raw.append(r)

    # 2) EUR-Lex legislation in bulk (pre-filtered by query; no date cutoff).
    if eurlex_on:
        res = fetch_eurlex_sparql(tuple(eurlex_terms), eurlex_year, eurlex_max)
        eurlex_info = {"count": res["count"], "query": res["query"], "error": res["error"]}
        if res["error"]:
            errors.append(res["error"])
        raw.extend(res["items"])

    seen = set()
    items = []
    for r in raw:
        key = r["link"] or r["title"]
        if key in seen:
            continue
        seen.add(key)
        published = parse_date(r["published"])
        if r.get("prefiltered"):
            terms = []  # already matched by SPARQL
        else:
            haystack = f"{r['title']} {clean_text(r['raw_summary'])}"
            terms = matched_keywords(haystack, keywords)
            if not terms:
                continue
            if published and published < cutoff:
                continue
        items.append({
            "source": r["source"], "region": r["region"], "title": r["title"],
            "link": r["link"], "published": published,
            "summary": short_summary(r["raw_summary"]), "terms": terms,
        })

    items.sort(key=lambda i: (i["published"] or dt.datetime.min), reverse=True)
    return items, errors, eurlex_info


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #

st.set_page_config(page_title="Operational-Risk Regulatory Monitor",
                   page_icon="📡", layout="wide")
st.title("Operational-Risk Regulatory Monitor")
st.caption("EU & Swedish operational-risk regulation — agency news (RSS) plus the "
           "full EUR-Lex legislation database (SPARQL).")

with st.sidebar:
    st.header("Agency news (RSS)")
    lookback = st.slider("Look-back window (days)", 7, 365, DEFAULT_LOOKBACK_DAYS, 7)
    regions = st.multiselect("Regions", ["EU", "SE"], default=["EU", "SE"])
    names = [s.name for s in SOURCES]
    chosen = st.multiselect("Feeds", names, default=names)
    kw_text = st.text_area("Keywords (one per line)", "\n".join(DEFAULT_KEYWORDS), height=180)
    keywords = [k.strip() for k in kw_text.splitlines() if k.strip()]

    st.divider()
    st.header("EUR-Lex legislation")
    eurlex_on = st.checkbox("Include EUR-Lex (bulk)", value=True)
    eurlex_year = st.number_input("Backfill from year", 1990, dt.date.today().year, 2018)
    eurlex_max = st.slider("Max EUR-Lex documents", 100, 5000, 1000, 100)
    eurlex_terms_text = st.text_area(
        "EUR-Lex topics (one phrase per line — matched in the title)",
        value="\n".join(EURLEX_QUERY_TERMS), height=220,
    )
    eurlex_terms = [t.strip() for t in eurlex_terms_text.splitlines() if t.strip()]
    st.caption("Use specific multi-word phrases (e.g. 'operational risk', 'money "
               "laundering'). Avoid very short terms like 'ai' or 'ict' alone — they "
               "match unrelated words. Larger pulls take longer; results cache 1h.")

    st.divider()
    if st.button("🔄 Refresh (clear cache)"):
        st.cache_data.clear()
        st.rerun()

active = [s for s in SOURCES if s.name in chosen and s.region in regions]

with st.spinner("Fetching feeds and querying EUR-Lex…"):
    items, errors, eurlex_info = collect(active, keywords, lookback,
                                         eurlex_on, int(eurlex_year), int(eurlex_max),
                                         eurlex_terms)

c1, c2, c3 = st.columns(3)
c1.metric("Total updates", len(items))
c2.metric("EUR-Lex documents", eurlex_info["count"])
c3.metric("Agency feeds", len(active))

if errors:
    with st.expander(f"⚠️ {len(errors)} source(s) reported an issue", expanded=False):
        for e in errors:
            st.write(f"- {e}")

if eurlex_on:
    with st.expander("EUR-Lex query diagnostics", expanded=(eurlex_info["count"] == 0)):
        st.write(f"Documents returned: **{eurlex_info['count']}**")
        if eurlex_info["error"]:
            st.error(eurlex_info["error"])
        st.code(eurlex_info["query"] or "(no query issued)", language="sparql")
        st.caption("If this returns 0 with no error, the title filter matched nothing — "
                   "broaden EURLEX_QUERY_TERMS or lower the 'from year'. If it errors, "
                   "paste this query text back for tuning.")

st.divider()

if not items:
    st.info("No matching updates. Widen the look-back, add keywords, lower the EUR-Lex "
            "year, or check the diagnostics above.")
else:
    for it in items:
        date_str = it["published"].strftime("%Y-%m-%d") if it["published"] else "undated"
        badge = "🇸🇪 SE" if it["region"] == "SE" else "🇪🇺 EU"
        with st.container(border=True):
            top = st.columns([0.7, 0.3])
            top[0].markdown(f"### {it['title']}")
            top[1].markdown(
                f"<div style='text-align:right;color:#888'>{badge} · {date_str}<br>"
                f"<b>{it['source']}</b></div>", unsafe_allow_html=True)
            st.write(it["summary"])
            if it["terms"]:
                st.markdown("**Matched:** " + " ".join(f"`{t}`" for t in it["terms"][:6]))
            if it["link"]:
                st.markdown(f"[↗ Open primary source]({it['link']})")

st.divider()
st.caption("Agency items come from RSS (latest only). EUR-Lex items come from the "
           "SPARQL legislation database and can backfill years. Always verify against "
           "the primary source; summaries are extractive, not legal interpretation.")
