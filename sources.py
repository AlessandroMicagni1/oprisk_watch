"""Every RSS source in one place. EUR-Lex is not here — it's a bulk SPARQL
query (see fetch.py), because RSS can't return legislative history."""

from dataclasses import dataclass


@dataclass
class Source:
    name: str
    url: str
    region: str = "EU"          # "EU" or "SE" or "NO"/"DK"/"FI" (Nordics)
    kind: str = "rss"           # "rss" or "discover" (find the feed on a page)
    enabled: bool = True


SOURCES = [
    # --- Sweden: Finansinspektionen (append /rss to any listing page) ----- #
    Source("FI – All published material",
           "https://www.fi.se/en/published/all-published-material/rss", "SE"),
    Source("FI – Proposed new regulations (FFFS)",
           "https://www.fi.se/sv/publicerat/forslag-nya-fffs/rss", "SE"),
    Source("FI – Sanctions & interventions",
           "https://www.fi.se/en/published/sanctions/financial-firms/rss", "SE"),
    # --- Sweden: Riksbank ------------------------------------------------- #
    Source("Riksbank – Press releases",
           "https://www.riksbank.se/en-gb/rss/press-releases/", "SE"),
    Source("Riksbank – Notices",
           "https://www.riksbank.se/en-gb/rss/notices/", "SE"),
    # --- Norway: Finanstilsynet (verified feeds under /en/rss/...) -------- #
    Source("Finanstilsynet NO – News",
           "https://www.finanstilsynet.no/en/rss/news/", "NO"),
    Source("Finanstilsynet NO – Circulars",
           "https://www.finanstilsynet.no/en/rss/circulars/", "NO"),
    # --- Other Nordics via auto-discovery (feed found on the listing page) - #
    # If a page doesn't advertise a feed, it's skipped with a clean note.
    Source("Finanssivalvonta FI – News",
           "https://www.finanssivalvonta.fi/en/publications-and-press-releases/news-releases/",
           "FI", kind="discover"),
    # Denmark: listing URL not yet verified — disabled so it doesn't 404.
    Source("Finanstilsynet DK – News",
           "https://www.finanstilsynet.dk/",
           "DK", kind="discover", enabled=False),
    # --- EU agencies ------------------------------------------------------ #
    Source("EBA – News & press", "https://www.eba.europa.eu/rss.xml", "EU"),
    Source("ESMA – News", "https://www.esma.europa.eu/rss.xml", "EU"),
    Source("ECB Banking Supervision – Press",
           "https://www.bankingsupervision.europa.eu/rss/press.html", "EU"),
    Source("EIOPA – News", "https://www.eiopa.europa.eu/node/4816/rss_en", "EU"),
]
