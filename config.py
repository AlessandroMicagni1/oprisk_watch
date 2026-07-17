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
    "business continuity", "operational continuity", "recovery and resolution",
    # ICT / cyber / technology
    "information and communication technology", "ict-related", "ict third",
    "ict risk", "ict service", "ict security", "ict provider",
    "cyber resilience", "cybersecurity", "network and information systems",
    "penetration testing", "threat-led", "security of network",
    # third parties / outsourcing / concentration
    "outsourcing", "third-party risk", "critical third", "cloud outsourcing",
    "concentration risk",
    # financial crime / conduct
    "anti-money laundering", "money laundering", "terrorist financing",
    "market abuse", "market manipulation", "insider dealing",
    "payment fraud", "fraud prevention", "strong customer authentication",
    # execution / market infrastructure / settlement
    "settlement discipline", "central counterparties", "central securities depositor",
    # prudential capital / governance for operational risk
    "own funds requirements", "business indicator", "internal governance",
    "risk management framework", "model risk", "internal control", "remuneration",
    # incident / reporting
    "incident reporting", "major incident", "business disruption",
    # data protection
    "protection of personal data",
]

# Keyword universe for filtering the RSS items (English + Swedish). EUR-Lex items
# are pre-filtered by the SPARQL query, so they bypass this at view time.
DEFAULT_KEYWORDS = [
    # --- core operational risk / resilience ---
    "operational risk", "operativ risk", "operationell risk",
    "operational resilience", "operativ motståndskraft", "beredskap",
    "resilience", "business continuity", "kontinuitet", "contingency",
    # --- Basel event type: internal & external fraud ---
    "fraud", "bedrägeri", "external fraud", "internal fraud", "payment fraud",
    "betalningsbedrägeri", "card fraud", "authorised push payment", "APP fraud",
    "embezzlement", "misappropriation", "forgery", "rogue trading",
    # --- Basel event type: clients, products & business practices / conduct ---
    "conduct", "uppförande", "mis-selling", "market abuse", "marknadsmissbruk",
    "market manipulation", "insider dealing", "fiduciary", "suitability",
    # --- Basel event type: employment practices ---
    "employment practices", "workplace safety", "discrimination", "whistleblow",
    # --- Basel event type: damage to physical assets / disruption ---
    "damage to physical assets", "business disruption", "system failure",
    "system outage", "driftstörning", "IT failure", "service disruption",
    # --- Basel event type: execution, delivery & process management ---
    "execution", "settlement", "avveckling", "transaction processing",
    "reconciliation", "data entry error", "process failure", "human error",
    # --- ICT / cyber / technology ---
    "DORA", "ICT", "IKT", "cyber", "cybersäkerhet", "cybersecurity",
    "incident", "incidentrapportering", "information security", "informationssäkerhet",
    "network and information systems", "NIS2", "penetration testing", "ransomware",
    "data breach", "personuppgiftsincident", "cloud",
    # --- third party / outsourcing / concentration ---
    "third-party", "tredjepart", "outsourcing", "utlagd", "critical third",
    "concentration risk", "koncentrationsrisk", "vendor", "supply chain",
    # --- model risk / AI ---
    "model risk", "modellrisk", "artificial intelligence", "machine learning",
    "algorithm", "algoritm",
    # --- financial crime ---
    "AML", "penningtvätt", "anti-money laundering", "terrorist financing",
    "finansiering av terrorism", "sanction", "sanktion", "KYC", "financial crime",
    # --- prudential capital / governance for op risk ---
    "CRR3", "CRD6", "business indicator", "ICAAP", "SREP", "own funds", "RWA",
    "Basel", "pillar 2", "internal governance", "risk management framework",
    "governance", "internal control", "internkontroll",
    # --- data protection ---
    "GDPR", "data protection", "dataskydd", "privacy breach",
]
