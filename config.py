"""Central configuration. Nothing here imports Streamlit, so it's usable from
both the app and the standalone fetch job."""

from pathlib import Path

USER_AGENT = "Cardinal-OpRisk-Monitor/0.2 (regulatory monitoring; ops@getcardinal.io)"
REQUEST_TIMEOUT = 30           # seconds for a normal HTTP request
SPARQL_TIMEOUT = 60            # EUR-Lex SPARQL can be slow
DEFAULT_LOOKBACK_DAYS = 90

# SQLite lives next to the code. NOTE: on Streamlit Community Cloud the disk is
# ephemeral (wiped on restart/redeploy); persistence there comes in Phase 6 via
# a scheduled job + external store. Locally it persists fine.
DB_PATH = Path(__file__).resolve().parent / "oprisk.db"

# EUR-Lex public SPARQL endpoint (CELLAR). No authentication required.
EURLEX_SPARQL = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX_PAGE = 100              # rows per SPARQL request; we loop OFFSET to the max
EURLEX_DEFAULT_YEAR = 2018
EURLEX_DEFAULT_MAX = 1000

# Title phrases that filter EUR-Lex legislation. Multi-word / specific on purpose,
# to avoid substring false positives ("ict" -> "predict", "ai" -> "maintenance").
# Editable live from the sidebar; this is just the default set.
EURLEX_QUERY_TERMS = [
    # core operational risk / resilience
    "operational risk", "operational resilience", "digital operational resilience",
    "business continuity", "operational continuity", "crisis management",
    # ICT / cyber / technology
    "information and communication technology", "ict-related", "ict third",
    "ict risk", "ict service", "ict security", "ict provider",
    "cyber resilience", "cybersecurity", "network and information systems",
    "penetration testing", "threat-led", "data breach", "critical infrastructure",
    # third parties / outsourcing / concentration
    "outsourcing", "third-party",  "critical third", "cloud",
    # financial crime / conduct
    "money laundering", "terrorist financing", "terrorism financing",
     "payment fraud", "payment fraud", "market abuse",
    # prudential capital / governance for operational risk
    "own funds", "business indicator", "internal governance", "internal control",
    "risk management framework", "model risk",
    # emerging
    "artificial intelligence", "machine learning", "distributed ledger",
]

# Keyword universe for filtering the RSS items (English + Swedish). EUR-Lex items
# are pre-filtered by the SPARQL query, so they bypass this at view time.
DEFAULT_KEYWORDS = [
    "operational risk", "operativ risk", "operationell risk",
    "operational resilience", "operativ motståndskraft", "beredskap",
    "DORA", "ICT", "IKT", "third-party", "tredjepart", "outsourcing", "utlagd",
    "CRR3", "CRD6", "business indicator", "ICAAP", "SREP",
    "incident", "incidentrapportering", "cyber resilience", "cybersäkerhet",
    "resilience", "business continuity", "kontinuitet",
    "payment fraud", "bedrägeri", "AML", "penningtvätt",  "sanktion",
    "payment fraud", "betalningsbedrägeri", "Basel", "own funds", "RWA",
    "model risk", "artificial intelligence",
]
