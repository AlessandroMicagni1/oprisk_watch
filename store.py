"""SQLite persistence. The UI reads only from here; fetching writes here.
Upserts are idempotent (keyed on CELEX or URL), so re-running never duplicates."""

from __future__ import annotations

import json
import sqlite3

from config import DB_PATH
from util import (clean_eurlex_title, clean_feed_summary, content_hash, doc_type,
                 eurlex_summary, iso_date, now_iso, short_summary)

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    uid          TEXT PRIMARY KEY,   -- celex or url
    source       TEXT,
    region       TEXT,
    celex        TEXT,
    title        TEXT,
    url          TEXT,
    published    TEXT,               -- 'YYYY-MM-DD' or ''
    summary      TEXT,
    raw_summary  TEXT,
    prefiltered  INTEGER DEFAULT 0,
    content_hash TEXT,
    first_seen   TEXT,               -- when we first stored it
    last_fetched TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published);
CREATE INDEX IF NOT EXISTS idx_items_region ON items(region);

CREATE TABLE IF NOT EXISTS sources (
    name       TEXT PRIMARY KEY,
    last_ok    TEXT,
    last_error TEXT,
    last_count INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    finished_at TEXT,
    new_items   INTEGER,
    total_items INTEGER
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_items(items) -> int:
    """Insert new items, refresh existing ones. Returns count of NEW items."""
    new_count = 0
    stamp = now_iso()
    with connect() as conn:
        for it in items:
            uid = it.get("celex") or it.get("url") or it.get("title")
            if not uid:
                continue
            prefiltered = 1 if it.get("prefiltered") else 0
            celex = it.get("celex", "")
            title = it.get("title", "")
            if prefiltered:
                title = clean_eurlex_title(title)
                summary = eurlex_summary(doc_type({"celex": celex, "prefiltered": True}))
            else:
                summary = clean_feed_summary(it.get("raw_summary", ""), title)
            chash = content_hash(title, it.get("raw_summary", ""))
            row = conn.execute("SELECT uid FROM items WHERE uid = ?", (uid,)).fetchone()
            if row is None:
                conn.execute(
                    """INSERT INTO items (uid, source, region, celex, title, url,
                       published, summary, raw_summary, prefiltered, content_hash,
                       first_seen, last_fetched)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, it.get("source", ""), it.get("region", ""),
                     celex, title, it.get("url", ""),
                     iso_date(it.get("published")),
                     summary,
                     it.get("raw_summary", ""),
                     prefiltered,
                     chash, stamp, stamp),
                )
                new_count += 1
            else:
                conn.execute(
                    "UPDATE items SET last_fetched = ?, content_hash = ? WHERE uid = ?",
                    (stamp, chash, uid),
                )
    return new_count


def record_health(health: dict):
    stamp = now_iso()
    with connect() as conn:
        for name, h in health.items():
            conn.execute(
                """INSERT INTO sources (name, last_ok, last_error, last_count)
                   VALUES (?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                     last_ok = excluded.last_ok,
                     last_error = excluded.last_error,
                     last_count = excluded.last_count""",
                (name, stamp if h["ok"] else None, h.get("error"), h.get("count", 0)),
            )


def record_run(new_items: int, total_items: int):
    with connect() as conn:
        conn.execute(
            "INSERT INTO runs (finished_at, new_items, total_items) VALUES (?,?,?)",
            (now_iso(), new_items, total_items),
        )


def get_meta(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_meta(key, value):
    with connect() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_items(regions=None, sources=None, cutoff_iso="", include_eurlex=True):
    """Return item rows as dicts. RSS items obey the date cutoff; EUR-Lex
    (prefiltered) items ignore it so history is preserved."""
    where_parts, params = [], []
    # Order matters: params must line up with the '?' order in the final SQL.
    if cutoff_iso:
        where_parts.append("(prefiltered = 1 OR published = '' OR published >= ?)")
        params.append(cutoff_iso)
    if regions:
        where_parts.append(f"region IN ({','.join('?' * len(regions))})")
        params += regions
    if sources:
        where_parts.append(f"source IN ({','.join('?' * len(sources))})")
        params += sources
    if not include_eurlex:
        where_parts.append("prefiltered = 0")
    where = " AND ".join(where_parts) if where_parts else "1=1"
    sql = (f"SELECT * FROM items WHERE {where} "
           "ORDER BY (published = '') ASC, published DESC, first_seen DESC")
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def new_since(iso: str) -> int:
    if not iso:
        return 0
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM items WHERE first_seen > ?", (iso,)
        ).fetchone()
        return row["n"]


def stats() -> dict:
    with connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]
        eurlex = conn.execute(
            "SELECT COUNT(*) AS n FROM items WHERE prefiltered = 1").fetchone()["n"]
        last_run = conn.execute(
            "SELECT finished_at FROM runs ORDER BY id DESC LIMIT 1").fetchone()
        return {
            "total": total,
            "eurlex": eurlex,
            "last_run": last_run["finished_at"] if last_run else None,
        }


def source_health() -> list[dict]:
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM sources ORDER BY name").fetchall()]
