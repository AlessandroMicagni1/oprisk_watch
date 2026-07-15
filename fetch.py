"""I/O layer. Pulls raw items from RSS feeds and the EUR-Lex SPARQL endpoint and
returns them as normalized dicts. Knows nothing about Streamlit or the database,
so it can run from the app OR from a scheduled job."""

from __future__ import annotations

import re
import time

from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from config import (EURLEX_PAGE, EURLEX_SPARQL, REQUEST_TIMEOUT, SPARQL_TIMEOUT,
                    USER_AGENT)
from util import clean_text

HEADERS = {"User-Agent": USER_AGENT}


def discover_feed_url(page_url: str):
    """Find a page's declared RSS/Atom feed. Returns (url, error)."""
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")
    except Exception as exc:
        return None, str(exc)
    for link in soup.find_all("link", attrs={"rel": True}):
        rel = " ".join(link.get("rel", [])).lower()
        ltype = (link.get("type") or "").lower()
        if "alternate" in rel and ("rss" in ltype or "atom" in ltype or "xml" in ltype):
            if link.get("href"):
                return urljoin(page_url, link["href"]), None
    for a in soup.find_all("a", href=True):
        if re.search(r"(/rss\b|/feed\b|\.xml$|\.rss$)", a["href"], re.I):
            return urljoin(page_url, a["href"]), None
    return None, "no feed link advertised on page"


def _item(source, region, title, url, published, raw_summary, celex="", prefiltered=False):
    return {
        "source": source, "region": region, "title": title, "url": url,
        "published": published, "raw_summary": raw_summary,
        "celex": celex, "prefiltered": prefiltered,
    }


def fetch_rss(url: str, name: str, region: str):
    """Return (items, error). error is None on success."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as exc:
        return [], str(exc)

    items = []
    for e in parsed.entries:
        items.append(_item(
            source=name, region=region,
            title=clean_text(getattr(e, "title", "(untitled)")),
            url=getattr(e, "link", ""),
            published=getattr(e, "published", None) or getattr(e, "updated", None),
            raw_summary=getattr(e, "summary", None) or getattr(e, "description", "") or "",
        ))
    return items, None


def _build_eurlex_query(terms, since_year, limit, offset):
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


def fetch_eurlex_sparql(terms, since_year: int, max_results: int, retries: int = 2):
    """Paginate the EUR-Lex SPARQL endpoint. Returns (items, error, last_query)."""
    items, error, last_query, offset = [], None, "", 0
    terms = list(terms)
    try:
        while len(items) < max_results:
            page = min(EURLEX_PAGE, max_results - len(items))
            last_query = _build_eurlex_query(terms, since_year, page, offset)
            bindings = None
            for attempt in range(retries + 1):
                try:
                    resp = requests.get(
                        EURLEX_SPARQL,
                        params={"query": last_query,
                                "format": "application/sparql-results+json"},
                        headers={**HEADERS, "Accept": "application/sparql-results+json"},
                        timeout=SPARQL_TIMEOUT,
                    )
                    resp.raise_for_status()
                    bindings = resp.json().get("results", {}).get("bindings", [])
                    break
                except Exception as exc:
                    if attempt == retries:
                        raise
                    time.sleep(1.5 * (attempt + 1))  # backoff
            if not bindings:
                break
            for b in bindings:
                celex = b.get("celex", {}).get("value", "")
                title = clean_text(b.get("title", {}).get("value", ""))
                date = b.get("date", {}).get("value", "")
                if not celex:
                    continue
                items.append(_item(
                    source="EUR-Lex (legislation)", region="EU",
                    title=title or celex,
                    url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                    published=date,
                    raw_summary=f"CELEX {celex}. {title}",
                    celex=celex, prefiltered=True,
                ))
            if len(bindings) < page:
                break
            offset += page
    except Exception as exc:
        error = f"EUR-Lex SPARQL: {exc}"
    return items, error, last_query


def fetch_all(sources, eurlex_on, eurlex_terms, eurlex_year, eurlex_max):
    """Fetch everything. Returns (items, health, eurlex_info).

    health: {source_name: {"ok": bool, "error": str|None, "count": int}}
    """
    items, health = [], {}

    for src in sources:
        if not src.enabled:
            continue
        feed_url, derr = src.url, None
        if getattr(src, "kind", "rss") == "discover":
            feed_url, derr = discover_feed_url(src.url)
        if derr or not feed_url:
            health[src.name] = {"ok": False, "error": derr or "no feed", "count": 0}
            continue
        got, err = fetch_rss(feed_url, src.name, src.region)
        health[src.name] = {"ok": err is None, "error": err, "count": len(got)}
        items.extend(got)

    eurlex_info = {"count": 0, "error": None, "query": ""}
    if eurlex_on:
        got, err, query = fetch_eurlex_sparql(eurlex_terms, eurlex_year, eurlex_max)
        eurlex_info = {"count": len(got), "error": err, "query": query}
        health["EUR-Lex (legislation)"] = {"ok": err is None, "error": err,
                                           "count": len(got)}
        items.extend(got)

    return items, health, eurlex_info
