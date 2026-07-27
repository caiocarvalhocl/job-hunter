"""Tests for the config-driven GenericJSONScraper (no real network)."""
import asyncio

from scrapers.generic_json import GenericJSONScraper, SourceConfig, _dig


def test_dig_reads_nested_paths():
    obj = {"data": {"items": [{"title": "A"}, {"title": "B"}]}}
    assert _dig(obj, "data.items.1.title") == "B"
    assert _dig(obj, "data.missing") == ""
    assert _dig(obj, "data.items.9.title") == ""


CONFIG = SourceConfig(
    name="testboard",
    url_template="https://x.com/api?q={keyword}",
    list_path="data",
    field_map={
        "url": "link", "title": "title", "company": "employer.name",
        "location": "location", "description": "desc", "is_remote": "remote",
        "external_id": "id",
    },
    remote_param="remote=true",
)

PAYLOAD = {
    "data": [
        {   # matches keyword "Java"
            "id": 1, "link": "https://x.com/jobs/1", "title": "Java Developer",
            "employer": {"name": "Acme"}, "location": "Worldwide",
            "desc": "Backend Java role.", "remote": True,
        },
        {   # does NOT match "Java" — must be dropped client-side
            "id": 2, "link": "https://x.com/jobs/2", "title": "Cozinheiro",
            "employer": {"name": "Restaurante"}, "location": "SP",
            "desc": "Cozinha industrial.", "remote": False,
        },
        {   # missing url — must be dropped
            "id": 3, "link": "", "title": "Java Engineer",
            "employer": {"name": "NoUrl"}, "desc": "Java.", "remote": True,
        },
    ]
}


def _run(monkeypatch, payload=PAYLOAD, keywords=("Java",)):
    import scrapers.generic_json as gj

    class _Resp:
        status = 200
        async def json(self, content_type=None): return payload
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Session:
        def get(self, *a, **k): return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(gj.aiohttp, "ClientSession", lambda: _Session())
    scraper = GenericJSONScraper(CONFIG, keywords=list(keywords))
    return asyncio.run(scraper.scrape())


def test_maps_fields_and_filters_by_keyword(monkeypatch):
    jobs = _run(monkeypatch)
    assert len(jobs) == 1
    job = jobs[0]
    assert job.url == "https://x.com/jobs/1"
    assert job.title == "Java Developer"
    assert job.company == "Acme"          # nested employer.name resolved
    assert job.is_remote is True
    assert job.source == "testboard"


def test_unrelated_and_urlless_jobs_are_dropped(monkeypatch):
    jobs = _run(monkeypatch)
    urls = {j.url for j in jobs}
    assert "https://x.com/jobs/2" not in urls   # keyword mismatch
    assert all(j.url for j in jobs)             # no empty-url jobs


def test_bad_list_path_returns_empty(monkeypatch):
    bad = SourceConfig(name="b", url_template="https://x.com?q={keyword}",
                       list_path="nope", field_map={"url": "u", "title": "t"})
    import scrapers.generic_json as gj

    class _Resp:
        status = 200
        async def json(self, content_type=None): return {"data": []}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _Session:
        def get(self, *a, **k): return _Resp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(gj.aiohttp, "ClientSession", lambda: _Session())
    jobs = asyncio.run(GenericJSONScraper(bad, keywords=["Java"]).scrape())
    assert jobs == []
