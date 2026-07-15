# OpRisk Watch — Phased Build Plan

From working script → product external users can rely on.
Each phase has a **Done when** block. Don't start the next phase until the checks pass.

Guiding order: **data correctness → storage → enrichment → UI → export → access.**
UI before the data layer means building the UI twice.

---

## Phase 0 · Baseline & safety net

**Goal:** freeze what works, make future changes safe.

- Tag the current working version: `git tag v0.1-working && git push --tags`
- Move tunables (sources, terms, limits) out of `app.py` into `config.py`
- Add `.streamlit/secrets.toml` to `.gitignore` (already there) and a `secrets.example.toml`
- Add a `sources.py` module — one place defining every source
- Split `app.py`: `fetch.py` (I/O), `store.py`, `enrich.py`, `ui.py`, `app.py` (thin entry)

**Done when:** app still runs identically, but `app.py` is < 100 lines and no URL or keyword is hardcoded in it.

---

## Phase 1 · Data layer (SQLite) — *the unlock*

**Goal:** stop re-fetching on every page load. Persist history beyond the RSS window.

- SQLite schema: `items` (id, source, celex, title, url, published, fetched_at, raw, hash), `sources` (name, url, last_ok, last_error), `runs`
- Idempotent upsert keyed on `celex` or `url` — re-running never duplicates
- `fetch_all()` as a standalone function callable from CLI: `python -m oprisk fetch`
- UI reads **only** from SQLite; a "Refresh" button triggers a fetch
- "New since last visit" flag per item

**Done when:** the app loads in < 1 second with the network off, and running the fetcher twice adds zero duplicates. History accumulates past the RSS cap.

---

## Phase 2 · Fetch correctness & coverage

**Goal:** get *everything relevant*, not everything with a keyword in the title.

**2a — EUR-Lex, properly**
- Replace title-string matching with **EuroVoc subject descriptors + directory codes**, keeping title match as an *additional* clause, not the only one
- Capture per document: type (Regulation / Directive / RTS / ITS / Decision / Corrigendum), **date of document, date of entry into force, date of application**, in-force status
- Handle SPARQL timeouts: retry with backoff, shrink page size on failure

**2b — Coverage gaps**
- Add: EU Official Journal L-series, Commission consultations, ESAs Joint Committee, ESRB, ENISA/NIS2, EPC (payments), BIS/Basel
- Add Nordics: Finanstilsynet (NO/DK), FIN-FSA — the regional story Cardinal sells
- Add FI *consultations* + Riksbank speeches

**2c — Deduplication**
- Cluster items describing the same instrument (CELEX where present, fuzzy title otherwise)
- One card per instrument, with its sources nested underneath

**Done when:** a spot-check of 10 known op-risk acts (DORA, CRR3, the EBA op-risk RTS, PSD2 SCA RTS, NIS2…) finds all 10 in the DB with correct type + application date; DORA appears **once**, not four times.

---

## Phase 3 · Enrichment — *the differentiator*

**Goal:** every item answers *what changed, who it binds, from when, what it requires.*

- **Real summaries:** fetch the act's preamble/abstract, then LLM-summarise to a fixed 4-field shape. Store the summary — never re-generate on view
- **Structured extraction:** instrument type, issuing body, affected entities (bank / insurer / payment firm / CTPP), key dates, obligations
- **Op-risk taxonomy tagging:** classify each item against the Basel/CRR3 event-type taxonomy + EBA attribute flags (cyber, third-party). *Nobody else's tracker speaks the CRO's taxonomy — this is the moat*
- **Relevance scoring:** term weight × title-vs-body position × source authority × recency → sort by relevance, not just date
- **Firm profile:** user sets ("Swedish bank, payments, DORA in scope"); score items against it

**Done when:** every item in the DB has a summary, ≥1 taxonomy tag, an entity list and a score; a CRO can read one card and know if it binds them without opening the source.

---

## Phase 4 · UI/UX polish

**Goal:** looks and feels like a Cardinal product, not a script.

- **Timeline as hero:** chronological rail with entry-into-force and application dates *ahead of today* — regulation is about deadlines
- **Faceted filters** in the main pane (source, type, risk category, status, date) with active-filter chips
- **Clustered cards** + expandable detail drawer: summary → key dates → obligations → sources
- **Full-text search** with highlighted matches
- **Source health strip:** green/red per feed, last successful fetch
- **Brand styling:** typography, colour, real header; saved views and pinning

**Done when:** someone who has never seen it can find "what binds a Swedish payment firm in the next 6 months" in under 30 seconds.

---

## Phase 5 · Export & distribution

**Goal:** the artefact leaves the app.

- **PDF regulatory brief** (single item) and **weekly digest PDF** — branded, with summary, key dates, links
- **CSV / Excel export** for the spreadsheet-native compliance crowd
- **Email / Slack digest** on a schedule — the app comes to people
- **Outbound RSS/JSON feed** of *your* curated, tagged items
- **Per-item permalink**

> **Copyright guardrail:** export Cardinal's *own summaries + citations + links*. EU legal text from EUR-Lex is broadly reusable; agency news copy is **not**. Never ship scraped full text of others' articles.

**Done when:** a weekly digest PDF can be generated in one click and is good enough to send to a prospect unedited.

---

## Phase 6 · External users & operations

**Goal:** safe for people outside Cardinal.

- **Scheduled backend fetch** (GitHub Actions cron or a small worker) writing to the DB — page loads never hit regulators' servers
- **Auth:** email allowlist or SSO; rate-limited read-only mode if public
- **Secrets** in Streamlit secrets / env vars (needed once the LLM key lands)
- **Monitoring:** alert when a feed breaks — a silently dead source is worse than a visible error
- **Legal/UX honesty:** "automated summaries, not legal advice, verify against source" + attribution

**Done when:** the app runs unattended for 7 days, the DB grows daily, and a broken feed pages you instead of failing silently.

---

## Phase 7 · The things that make it *special*

Ship at least two of these — they're what no competitor has.

- **"Draft the article" button** — turn a regulatory item into the Thursday regulatory-update piece in Cardinal's house structure. The monitor and the content pipeline become one system
- **Obligation timeline by firm profile** — "what binds a Swedish payment institution in the next 18 months," as a Gantt rail
- **The quantification hook** — for each item, surface the op-risk loss category it touches and the public loss/capital data attached to it. Cardinal's whole argument, embedded in a weekly tool
- **Regulatory pressure index** — new binding obligation per quarter, per risk category. A publishable data asset that feeds the research flow

**Done when:** one of these is demoable to a prospect and makes them ask "how do I get this?"

---

## Suggested sequencing

| Sprint | Phases | Outcome |
|--------|--------|---------|
| 1 | 0 + 1 | Refactored, persistent, fast |
| 2 | 2 | Coverage you can trust |
| 3 | 3 | Summaries + taxonomy — the moat |
| 4 | 4 + 5 | Looks like a product, exports PDFs |
| 5 | 6 | External users |
| 6 | 7 | The special thing |
