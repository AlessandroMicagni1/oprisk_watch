"""Streamlit UI. Reads from SQLite only; the Refresh button is the single place
that triggers live fetching. Loads instantly (and offline) once the DB is warm."""

from __future__ import annotations

import datetime as dt

import streamlit as st

from config import (DEFAULT_KEYWORDS, DEFAULT_LOOKBACK_DAYS, EURLEX_DEFAULT_MAX,
                    EURLEX_DEFAULT_YEAR, EURLEX_QUERY_TERMS)
from fetch import fetch_all
from sources import SOURCES
from store import (get_items, get_meta, init_db, new_since, record_health,
                   record_run, set_meta, source_health, stats, upsert_items)
from util import doc_type, matched_keywords, now_iso


def _run_fetch(eurlex_on, eurlex_terms, eurlex_year, eurlex_max):
    with st.spinner("Fetching feeds and querying EUR-Lex…"):
        items, health, eurlex_info = fetch_all(
            SOURCES, eurlex_on, eurlex_terms, eurlex_year, eurlex_max)
        new = upsert_items(items)
        record_health(health)
        record_run(new, stats()["total"])
    st.session_state["last_fetch_new"] = new
    st.session_state["last_eurlex_info"] = eurlex_info
    return new, eurlex_info


def render():
    st.set_page_config(page_title="OpRisk Watch", page_icon="📡", layout="wide")
    init_db()

    st.title("OpRisk Watch")
    st.caption("EU & Swedish operational-risk regulation — agency news plus the "
               "full EUR-Lex legislation database, stored and searchable.")

    # ---------------- Sidebar ---------------- #
    with st.sidebar:
        st.header("View filters")
        lookback = st.slider("Look-back (days, agency news)", 7, 365,
                             DEFAULT_LOOKBACK_DAYS, 7)
        regions = st.multiselect("Regions", ["EU", "SE", "NO", "DK", "FI"],
                                 default=["EU", "SE", "NO", "DK", "FI"])
        names = [s.name for s in SOURCES] + ["EUR-Lex (legislation)"]
        chosen = st.multiselect("Sources", names, default=names)
        include_eurlex = "EUR-Lex (legislation)" in chosen
        query = st.text_input("Search title/summary", "")
        kw_text = st.text_area("Op-risk keywords (RSS filter)",
                               "\n".join(DEFAULT_KEYWORDS), height=150)
        keywords = [k.strip() for k in kw_text.splitlines() if k.strip()]

        st.divider()
        st.header("Fetch")
        eurlex_on = st.checkbox("Include EUR-Lex on fetch", value=True)
        eurlex_year = st.number_input("Backfill from year", 1990,
                                      dt.date.today().year, EURLEX_DEFAULT_YEAR)
        eurlex_max = st.slider("Max EUR-Lex docs per fetch", 100, 5000,
                               EURLEX_DEFAULT_MAX, 100)
        eurlex_terms_text = st.text_area("EUR-Lex topics (title match)",
                                         "\n".join(EURLEX_QUERY_TERMS), height=180)
        eurlex_terms = [t.strip() for t in eurlex_terms_text.splitlines() if t.strip()]

        if st.button("⤓ Fetch now", type="primary"):
            _run_fetch(eurlex_on, eurlex_terms, int(eurlex_year), int(eurlex_max))
            st.rerun()

    # ---------------- Data ---------------- #
    db = stats()
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=lookback)).strftime("%Y-%m-%d")

    if db["total"] == 0:
        st.info("The database is empty. Click **Fetch now** in the sidebar to pull "
                "the first batch. After that, the app loads instantly from storage.")
        return

    rss_sources = [s for s in chosen if s != "EUR-Lex (legislation)"]
    rows = get_items(regions=regions or None, sources=rss_sources or None,
                     cutoff_iso=cutoff, include_eurlex=include_eurlex)

    # Keyword filter (RSS rows only; EUR-Lex rows are pre-filtered).
    shown = []
    for r in rows:
        if r["prefiltered"]:
            r["_terms"] = []
        else:
            terms = matched_keywords(f"{r['title']} {r['raw_summary']}", keywords)
            if not terms:
                continue
            r["_terms"] = terms
        if query and query.lower() not in f"{r['title']} {r['summary']}".lower():
            continue
        r["_type"] = doc_type(r)
        shown.append(r)

    # Document-type facet (built from what's currently in view).
    all_types = sorted({r["_type"] for r in shown})
    if all_types:
        with st.sidebar:
            st.divider()
            st.subheader("Document type")
            chosen_types = st.multiselect("Show types", all_types, default=all_types,
                                          label_visibility="collapsed")
        shown = [r for r in shown if r["_type"] in chosen_types]

    # "New since last visit"
    last_visit = get_meta("last_visit", "")
    new_count = new_since(last_visit)

    # ---------------- Header metrics ---------------- #
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Showing", len(shown))
    c2.metric("New since last visit", new_count)
    c3.metric("In database", db["total"])
    c4.metric("EUR-Lex stored", db["eurlex"])

    meta_bits = []
    if db["last_run"]:
        meta_bits.append(f"Last fetch: {db['last_run']} UTC")
    if st.session_state.get("last_fetch_new") is not None:
        meta_bits.append(f"Last fetch added {st.session_state['last_fetch_new']} new")
    if meta_bits:
        st.caption(" · ".join(meta_bits))

    top = st.columns([0.25, 0.75])
    if top[0].button("Mark all as read"):
        set_meta("last_visit", now_iso())
        st.rerun()

    # Source health strip
    with st.expander("Source health", expanded=False):
        for h in source_health():
            ok = h["last_ok"] is not None and not h["last_error"]
            dot = "🟢" if ok else "🔴"
            line = f"{dot} **{h['name']}** — {h['last_count'] or 0} items"
            if h["last_error"]:
                line += f" — {h['last_error']}"
            st.markdown(line)

    ei = st.session_state.get("last_eurlex_info")
    if ei and (ei.get("error") or ei.get("count") == 0):
        with st.expander("EUR-Lex query diagnostics", expanded=True):
            if ei.get("error"):
                st.error(ei["error"])
            st.code(ei.get("query", ""), language="sparql")

    st.divider()

    # ---------------- Item list ---------------- #
    if not shown:
        st.info("Nothing matches the current filters. Widen the look-back, clear the "
                "search, or adjust keywords.")
        return

    fresh_boundary = last_visit
    for it in shown:
        date_str = it["published"] or "undated"
        badge = "🇸🇪 SE" if it["region"] == "SE" else "🇪🇺 EU"
        is_new = fresh_boundary and it["first_seen"] > fresh_boundary
        with st.container(border=True):
            top = st.columns([0.66, 0.34])
            title = ("🆕 " if is_new else "") + it["title"]
            top[0].markdown(f"### {title}")
            type_line = f"`{it['_type']}`" if it.get("_type") else ""
            top[1].markdown(
                f"<div style='text-align:right;color:#888'>{badge} · {date_str}<br>"
                f"<b>{it['source']}</b></div>", unsafe_allow_html=True)
            if type_line:
                top[1].markdown(f"<div style='text-align:right'>{type_line}</div>",
                                unsafe_allow_html=True)
            # For legislation, the raw summary is just "CELEX x. title" — skip it.
            if not it["prefiltered"]:
                st.write(it["summary"])
            meta = []
            if it["celex"]:
                meta.append(f"CELEX **{it['celex']}**")
            if meta:
                st.caption(" · ".join(meta))
            if it["_terms"]:
                st.markdown("**Matched:** " + " ".join(f"`{t}`" for t in it["_terms"][:6]))
            if it["url"]:
                st.markdown(f"[↗ Open primary source]({it['url']})")

    # Record this visit AFTER rendering, so "new" reflects the *previous* visit.
    set_meta("last_visit", now_iso())
