"""Standalone fetcher: pull everything and write to SQLite. Run manually or on a
schedule (cron / GitHub Actions) so the app never has to fetch live.

    python fetch_job.py
"""

from config import EURLEX_DEFAULT_MAX, EURLEX_DEFAULT_YEAR, EURLEX_QUERY_TERMS, EURLEX_TEXT_MAX
from fetch import enrich_eurlex_batch, fetch_all
from sources import SOURCES
from store import init_db, record_health, record_run, stats, upsert_items


def run():
    init_db()
    items, health, eurlex_info = fetch_all(
        SOURCES, eurlex_on=True, eurlex_terms=EURLEX_QUERY_TERMS,
        eurlex_year=EURLEX_DEFAULT_YEAR, eurlex_max=EURLEX_DEFAULT_MAX,
    )
    new = upsert_items(items)
    record_health(health)
    s = stats()
    record_run(new, s["total"])

    print(f"Fetched {len(items)} items; {new} new. DB now holds {s['total']} "
          f"({s['eurlex']} EUR-Lex).")
    if eurlex_info["error"]:
        print("EUR-Lex error:", eurlex_info["error"])
    for name, h in health.items():
        flag = "ok " if h["ok"] else "ERR"
        print(f"  [{flag}] {name}: {h['count']}" + (f" — {h['error']}" if h["error"] else ""))

    print(f"Enriching up to {EURLEX_TEXT_MAX} EUR-Lex items with full text…")
    enriched = enrich_eurlex_batch(EURLEX_TEXT_MAX)
    print(f"  enriched {enriched} EUR-Lex items with real preamble text.")


if __name__ == "__main__":
    run()
