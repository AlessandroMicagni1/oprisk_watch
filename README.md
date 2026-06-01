# Operational-Risk Regulatory Monitor

A small Streamlit dashboard that aggregates **EU and Swedish regulatory updates**
in the operational-risk space, filters them to relevant keywords, shows a short
summary of each, and links straight to the primary source.

## Run it

```bash
cd oprisk_monitor
python -m venv .venv && source .venv/bin/activate   # optional
pip install -r requirements.txt
streamlit run app.py
```

It opens at `http://localhost:8501`.

## How it works (and why it's reliable)

It does **not** screen-scrape brittle HTML. It uses the structured feeds the
regulators already publish:

| Source | Route | Notes |
|--------|-------|-------|
| Finansinspektionen (FI) | RSS | Any fi.se listing page becomes a feed by appending `/rss` (e.g. `…/all-published-material/rss`). |
| EUR-Lex | Atom/RSS | Predefined and saved-search feeds. Confirm the exact feed URL from your EUR-Lex **My RSS feeds** page and paste it into `SOURCES`. |
| EBA / ESMA / EIOPA / ECB-SSM | RSS | This is where most EU operational-risk regulation actually breaks first. |
| Riksbank | RSS | Payments / financial-stability context. |

A generic HTML fallback (`fetch_html`) exists for any future source without a
feed — set `kind="html"` and provide CSS selectors — but feeds are preferred.

## Tuning

- **Add or remove sources:** edit the `SOURCES` list at the top of `app.py`.
- **EUR-Lex feed URL:** sign in to EUR-Lex → run an advanced/expert search scoped
  to operational-risk subject matter → *Create in My RSS feeds* → copy the feed
  URL into the `EUR-Lex` source. (The one shipped is a placeholder pattern.)
- **Keywords:** edit `DEFAULT_KEYWORDS`, or change them live in the sidebar.
  Both English and Swedish terms are included.
- **Look-back, regions, sources:** all adjustable from the sidebar at runtime.
- **Caching:** feeds are cached 30 minutes; use **Refresh now** to force a reload.

## Notes & limits

- Summaries are **extractive** — the first few sentences of the source's own
  abstract — not legal interpretation. Always verify against the primary source.
- If a feed errors (network, changed URL), it's listed in the *errors* expander
  and the rest still load.
- Respect each site's terms of use and reasonable request rates. The default
  30-minute cache and single-request-per-feed design keeps load minimal.

## Optional next steps

- Swap the extractive summary for an LLM summary (add an API key and a
  `summarise()` call in `collect`).
- Persist items to SQLite so you get a deduped history and "new since last run".
- Add a daily digest (email/Slack) by running `collect()` from a cron job.
