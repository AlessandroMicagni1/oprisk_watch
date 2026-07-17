"""FastAPI backend for OpRisk Watch. Wraps the existing Python modules
(fetch, store, util) and exposes a small JSON API for the Next.js frontend.

Run:
    pip install -r requirements-api.txt
    uvicorn api:app --reload --port 8000

Endpoints:
    GET  /stats               → counts + last fetch time
    GET  /sources             → per-source health
    GET  /items               → filtered, paginated items
    GET  /facets              → distinct regions / sources / types for filter UI
    POST /refresh             → fetch everything and upsert (blocking)
    POST /mark-read           → set the 'last visit' watermark
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

import store
import util
from config import (DEFAULT_KEYWORDS, DEFAULT_LOOKBACK_DAYS, EURLEX_DEFAULT_MAX,
                    EURLEX_DEFAULT_YEAR, EURLEX_QUERY_TERMS)
from fetch import fetch_all
from sources import SOURCES

app = FastAPI(title="OpRisk Watch API", version="0.1")

# CORS: allow the frontend origin(s). Override via CORS_ORIGINS env (comma-sep).
_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins] or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

store.init_db()


def _serialize(r: dict, keywords: list[str], last_visit: str) -> dict:
    terms = ([] if r["prefiltered"]
             else util.matched_keywords(f"{r['title']} {r['raw_summary']}", keywords))
    return {
        "uid": r["uid"],
        "source": r["source"],
        "region": r["region"],
        "title": r["title"],
        "url": r["url"],
        "published": r["published"] or None,
        "summary": r["summary"],
        "celex": r["celex"] or None,
        "docType": util.doc_type(r),
        "isNew": bool(last_visit and r["first_seen"] > last_visit),
        "firstSeen": r["first_seen"],
        "terms": terms,
        "prefiltered": bool(r["prefiltered"]),
    }


def _query(region, source, doc_type, q, since_days, include_eurlex):
    cutoff = (dt.datetime.utcnow() - dt.timedelta(days=since_days)).strftime("%Y-%m-%d")
    rows = store.get_items(regions=region, sources=source,
                           cutoff_iso=cutoff, include_eurlex=include_eurlex)
    last_visit = store.get_meta("last_visit", "")
    out = []
    ql = q.lower() if q else ""
    for r in rows:
        s = _serialize(r, DEFAULT_KEYWORDS, last_visit)
        if not r["prefiltered"] and not s["terms"]:
            continue
        if util.is_excluded(f"{s['title']} {s['summary'] or ''}"):
            continue
        if ql and ql not in f"{s['title']} {s['summary'] or ''}".lower():
            continue
        if doc_type and s["docType"] not in doc_type:
            continue
        out.append(s)
    return out


@app.get("/stats")
def get_stats():
    return store.stats()


@app.get("/sources")
def get_sources():
    return store.source_health()


@app.get("/items")
def get_items(
    region: Optional[list[str]] = Query(None),
    source: Optional[list[str]] = Query(None),
    type: Optional[list[str]] = Query(None),
    q: str = "",
    since_days: int = DEFAULT_LOOKBACK_DAYS,
    include_eurlex: bool = True,
    limit: int = 50,
    offset: int = 0,
):
    items = _query(region, source, type, q, since_days, include_eurlex)
    return {
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "items": items[offset: offset + limit],
    }


@app.get("/facets")
def get_facets():
    """Distinct values for building filter controls."""
    rows = store.get_items(cutoff_iso="", include_eurlex=True)
    last_visit = store.get_meta("last_visit", "")
    regions, sources, types = set(), set(), set()
    for r in rows:
        regions.add(r["region"])
        sources.add(r["source"])
        types.add(util.doc_type(r))
    return {
        "regions": sorted(regions),
        "sources": sorted(sources),
        "types": sorted(types),
    }


@app.post("/refresh")
def refresh(eurlex: bool = True,
            eurlex_year: int = EURLEX_DEFAULT_YEAR,
            eurlex_max: int = EURLEX_DEFAULT_MAX):
    items, health, eurlex_info = fetch_all(
        SOURCES, eurlex, EURLEX_QUERY_TERMS, eurlex_year, eurlex_max)
    new = store.upsert_items(items)
    store.record_health(health)
    store.record_run(new, store.stats()["total"])
    return {"new": new, "fetched": len(items),
            "eurlex": eurlex_info, "stats": store.stats(), "health": health}


@app.get("/item.pdf")
def item_pdf(uid: str):
    import io

    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                    Spacer, Table, TableStyle)

    r = store.get_by_uid(uid)
    if not r:
        raise HTTPException(status_code=404, detail="item not found")

    dtype = util.doc_type(r)
    C = colors.HexColor("#8f2d3b")
    INK = colors.HexColor("#1a2233")
    M = colors.HexColor("#6b7686")
    ss = getSampleStyleSheet()

    def esc(x):
        return (x or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    brand = ParagraphStyle("br", parent=ss["Normal"], textColor=C, fontSize=10,
                           fontName="Helvetica-Bold", spaceAfter=2)
    kicker = ParagraphStyle("k", parent=ss["Normal"], textColor=M, fontSize=9, spaceAfter=8)
    title = ParagraphStyle("t", parent=ss["Title"], textColor=INK, fontSize=17,
                           leading=21, alignment=0, spaceAfter=10)
    label = ParagraphStyle("lb", parent=ss["Normal"], textColor=M, fontSize=8,
                           fontName="Helvetica-Bold")
    value = ParagraphStyle("v", parent=ss["Normal"], textColor=INK, fontSize=9, leading=12)
    h = ParagraphStyle("h", parent=ss["Normal"], textColor=C, fontSize=10,
                       fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["Normal"], textColor=INK, fontSize=10, leading=15)
    foot = ParagraphStyle("f", parent=ss["Normal"], textColor=M, fontSize=7,
                          spaceBefore=16)

    rows = [
        [Paragraph("TYPE", label), Paragraph(esc(dtype), value)],
        [Paragraph("REGION", label), Paragraph(esc(r["region"]), value)],
        [Paragraph("DATE", label), Paragraph(esc(r["published"] or "undated"), value)],
        [Paragraph("SOURCE", label), Paragraph(esc(r["source"]), value)],
    ]
    if r["celex"]:
        rows.append([Paragraph("CELEX", label), Paragraph(esc(r["celex"]), value)])
    tbl = Table(rows, colWidths=[26 * mm, 140 * mm])
    tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, colors.HexColor("#e5e9f0")),
    ]))

    story = [
        Paragraph("OPRISK WATCH", brand),
        Paragraph("Regulatory brief", kicker),
        HRFlowable(width="100%", thickness=1.6, color=C, spaceAfter=12),
        Paragraph(esc(r["title"]), title),
        tbl,
    ]
    if r["summary"]:
        story += [Paragraph("Summary", h), Paragraph(esc(r["summary"]), body)]
    if r["url"]:
        story += [Paragraph("Primary source", h),
                  Paragraph(f'<link href="{esc(r["url"])}" color="#8f2d3b">{esc(r["url"])}</link>', body)]
    story.append(Paragraph(
        f"Generated by OpRisk Watch on {util.now_iso()} UTC. Automated summary — "
        f"verify against the primary source. Not legal advice.", foot))

    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, topMargin=20 * mm, bottomMargin=18 * mm,
                      leftMargin=20 * mm, rightMargin=20 * mm,
                      title="OpRisk Watch — Regulatory Brief").build(story)
    buf.seek(0)
    fname = (r["celex"] or "brief").replace("/", "-")
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=oprisk-{fname}.pdf"})


@app.post("/mark-read")
def mark_read():
    store.set_meta("last_visit", util.now_iso())
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Exports
# --------------------------------------------------------------------------- #

def _export_rows(region, source, type, q, since_days, include_eurlex, limit):
    items = _query(region, source, type, q, since_days, include_eurlex)
    return items[: limit or len(items)]


@app.get("/export.csv")
def export_csv(
    region: Optional[list[str]] = Query(None),
    source: Optional[list[str]] = Query(None),
    type: Optional[list[str]] = Query(None),
    q: str = "",
    since_days: int = DEFAULT_LOOKBACK_DAYS,
    include_eurlex: bool = True,
    limit: int = 500,
):
    import csv
    import io
    from fastapi.responses import StreamingResponse

    rows = _export_rows(region, source, type, q, since_days, include_eurlex, limit)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Date", "Region", "Type", "Source", "Title", "Summary", "CELEX", "URL"])
    for it in rows:
        w.writerow([it["published"] or "", it["region"], it["docType"], it["source"],
                    it["title"], it["summary"] or "", it["celex"] or "", it["url"] or ""])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=oprisk-watch.csv"},
    )


@app.get("/export.pdf")
def export_pdf(
    region: Optional[list[str]] = Query(None),
    source: Optional[list[str]] = Query(None),
    type: Optional[list[str]] = Query(None),
    q: str = "",
    since_days: int = DEFAULT_LOOKBACK_DAYS,
    include_eurlex: bool = True,
    limit: int = 100,
):
    import io

    from fastapi.responses import StreamingResponse
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, HRFlowable)

    rows = _export_rows(region, source, type, q, since_days, include_eurlex, limit)

    CARDINAL = colors.HexColor("#8f2d3b")
    INK = colors.HexColor("#1a2233")
    MUTED = colors.HexColor("#6b7686")

    ss = getSampleStyleSheet()
    h_title = ParagraphStyle("t", parent=ss["Title"], textColor=CARDINAL,
                             fontSize=20, spaceAfter=2, alignment=TA_LEFT)
    h_sub = ParagraphStyle("s", parent=ss["Normal"], textColor=MUTED, fontSize=9,
                           spaceAfter=10)
    meta = ParagraphStyle("m", parent=ss["Normal"], textColor=MUTED, fontSize=8,
                          spaceAfter=1)
    item_title = ParagraphStyle("it", parent=ss["Normal"], textColor=INK,
                                fontSize=11, leading=14, spaceAfter=2,
                                fontName="Helvetica-Bold")
    body = ParagraphStyle("b", parent=ss["Normal"], textColor=INK, fontSize=9,
                          leading=12, spaceAfter=3)
    link = ParagraphStyle("l", parent=ss["Normal"], textColor=CARDINAL, fontSize=8,
                          spaceAfter=12)

    def esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [
        Paragraph("OpRisk Watch — Regulatory Brief", h_title),
        Paragraph(f"EU &amp; Nordic operational-risk regulation · generated "
                  f"{util.now_iso()} UTC · {len(rows)} items", h_sub),
        HRFlowable(width="100%", thickness=1.4, color=CARDINAL, spaceAfter=10),
    ]
    for it in rows:
        m = f"{it['docType']} · {it['region']} · {it['published'] or 'undated'} · {esc(it['source'])}"
        story.append(Paragraph(m, meta))
        story.append(Paragraph(esc(it["title"]), item_title))
        if it["summary"]:
            story.append(Paragraph(esc(it["summary"]), body))
        tail = (f"CELEX {it['celex']} · " if it["celex"] else "") + esc(it["url"] or "")
        story.append(Paragraph(tail, link))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            title="OpRisk Watch — Regulatory Brief")
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=oprisk-watch-brief.pdf"},
    )
