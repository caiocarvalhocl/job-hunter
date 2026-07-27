"""Registry of JSON-API job boards handled by GenericJSONScraper.

Each entry is a SourceConfig. Boards are added here as their internal JSON
endpoints are confirmed from the browser (F12 → Network → XHR). Until an
endpoint is confirmed, a board stays commented out rather than shipping a
scraper that silently returns zero — the recurring failure mode this project
has fought throughout.

## How to confirm an endpoint (2 minutes)

1. Open the board and run a search for e.g. "Java".
2. F12 → Network tab → filter "Fetch/XHR".
3. Click the request whose JSON response contains the visible job cards.
4. Copy: the request URL, and note which JSON key holds the array of jobs
   and which keys hold title / company / location / url / description.
5. Fill a SourceConfig below and move it into ENABLED_SOURCES.

`{keyword}` in url_template is URL-encoded and substituted per keyword.

## Candidate boards (from the wishlist) — endpoints TBD

These are SPAs, so the URL below is a *placeholder shape*, not confirmed.
Enable each once you paste me the real endpoint.
"""
from scrapers.generic_json import SourceConfig

# ─────────────────────────────────────────────────────────────────────────────
# ENABLED: confirmed endpoints only. Empty until we verify one together.
# ─────────────────────────────────────────────────────────────────────────────
ENABLED_SOURCES: list[SourceConfig] = [
    # Example of a *confirmed* shape (Gupy already has a dedicated scraper;
    # shown here only to illustrate a filled-in config):
    #
    # SourceConfig(
    #     name="brazildevs",
    #     url_template="https://api.brazildevs.com/jobs?search={keyword}",
    #     list_path="data",
    #     field_map={
    #         "url": "url", "title": "title", "company": "company_name",
    #         "location": "location", "description": "description",
    #         "is_remote": "is_remote", "external_id": "id",
    #     },
    #     remote_param="remote=true",
    #     international_only=False,
    # ),
]


# ─────────────────────────────────────────────────────────────────────────────
# DRAFTS: field maps are guesses; DO NOT enable until the endpoint + keys are
# confirmed from devtools. Left here so wiring is a copy-paste once verified.
# ─────────────────────────────────────────────────────────────────────────────
DRAFT_SOURCES: dict[str, SourceConfig] = {
    "jobnagringa": SourceConfig(
        name="jobnagringa",
        url_template="https://www.jobnagringa.com.br/api/jobs?search={keyword}",
        list_path="data",
        field_map={
            "url": "url", "title": "title", "company": "company",
            "location": "location", "description": "description",
            "is_remote": "remote", "external_id": "id",
        },
        international_only=True,
    ),
    "tecla": SourceConfig(
        name="tecla",
        url_template="https://app.tecla.io/api/jobs?search={keyword}",
        list_path="jobs",
        field_map={
            "url": "url", "title": "title", "company": "company",
            "location": "location", "description": "description",
            "external_id": "id",
        },
        international_only=True,
    ),
    "solides": SourceConfig(
        name="solides",
        url_template="https://vagas.solides.com.br/api/vagas?q={keyword}",
        list_path="data",
        field_map={
            "url": "url", "title": "titulo", "company": "empresa",
            "location": "localizacao", "description": "descricao",
            "external_id": "id",
        },
        international_only=False,
    ),
}
