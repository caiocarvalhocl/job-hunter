"""Offline parsing tests for the rewritten scrapers, using fixtures shaped
like the live responses verified against each service (2026-07)."""
import asyncio
from unittest.mock import patch

import pytest

from scrapers.gupy import GupyScraper
from scrapers.programathor import ProgramathorScraper
from utils import is_international_keyword


# ── Gupy: client-side validation over the API payload ────────────────────

GUPY_ITEMS = [
    {   # remote Java job → must pass the remote pass
        "id": 1, "name": "Desenvolvedor Java Júnior",
        "careerPageName": "TechCo", "description": "Vaga de Java com Spring.",
        "workplaceType": "remote", "isRemoteWork": True,
        "city": "", "state": "", "jobUrl": "https://x.gupy.io/jobs/1",
    },
    {   # unrelated job → must be dropped even if the API ignores jobName
        "id": 2, "name": "Atendente de Restaurante",
        "careerPageName": "FastFood", "description": "Atendimento ao cliente.",
        "workplaceType": "on-site", "isRemoteWork": False,
        "city": "São Paulo", "state": "São Paulo", "jobUrl": "https://x.gupy.io/jobs/2",
    },
    {   # onsite Java in Paraná → must pass the state pass, not the remote pass
        "id": 3, "name": "Desenvolvedor Java Pleno",
        "careerPageName": "AgroTech", "description": "Java e SQL.",
        "workplaceType": "hybrid", "isRemoteWork": False,
        "city": "Dois Vizinhos", "state": "Paraná", "jobUrl": "https://x.gupy.io/jobs/3",
    },
]


def _run_gupy(workplace_types=None, state=None):
    scraper = GupyScraper(keywords=["Java"])

    async def go():
        with patch.object(GupyScraper, "_fetch_payload",
                          return_value={"data": GUPY_ITEMS}, create=True):
            # call the parsing path directly through _search_api by patching
            # the HTTP layer via aiohttp is heavier; instead reuse the parse
            # logic through a thin seam below.
            return await scraper._search_api(  # noqa: SLF001
                "Java", workplace_types=workplace_types, state=state)
    return asyncio.run(go())


@pytest.fixture(autouse=True)
def _patch_gupy_http(monkeypatch):
    """Route _search_api's HTTP call to the fixture payload."""
    import scrapers.gupy as gupy_mod

    class _FakeResp:
        status = 200
        async def json(self, content_type=None):
            return {"data": GUPY_ITEMS}
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeSession:
        def get(self, *a, **kw): return _FakeResp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(gupy_mod.aiohttp, "ClientSession", lambda: _FakeSession())


def test_gupy_remote_pass_keeps_only_remote_keyword_matches():
    jobs = _run_gupy(workplace_types="remote")
    urls = {j.url for j in jobs}
    assert urls == {"https://x.gupy.io/jobs/1"}


def test_gupy_state_pass_keeps_only_parana_jobs():
    jobs = _run_gupy(state="Paraná")
    urls = {j.url for j in jobs}
    assert urls == {"https://x.gupy.io/jobs/3"}
    assert jobs[0].location == "Dois Vizinhos, Paraná"
    assert jobs[0].is_remote is False


def test_gupy_unrelated_job_never_passes():
    for kwargs in ({"workplace_types": "remote"}, {"state": "São Paulo"}):
        assert all("Atendente" not in j.title for j in _run_gupy(**kwargs))


# ── Programathor: anchor-based card parsing ──────────────────────────────

PROGRAMATHOR_HTML = """
<html><body>
<div class="listing">
  <div class="card">
    <a href="/jobs/7977-desenvolvedor-java-junior"><h3>Desenvolvedor Java Júnior</h3></a>
    <span>StartupX</span><span>Rio de Janeiro (Presencial)</span>
  </div>
  <div class="card">
    <a href="/jobs/8001-dev-java-pleno"><h3>Dev Java Pleno</h3></a>
    <span>iBlue Consulting</span><span>Remoto</span>
  </div>
  <a href="/jobs">todas as vagas</a>
  <a href="/jobs-java/remoto">vagas remotas</a>
</div>
</body></html>
"""


def test_programathor_parses_job_anchors_only(monkeypatch):
    import scrapers.programathor as pt_mod

    class _FakeResp:
        status = 200
        async def text(self): return PROGRAMATHOR_HTML
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeSession:
        def get(self, *a, **kw): return _FakeResp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(pt_mod.aiohttp, "ClientSession", lambda: _FakeSession())

    scraper = ProgramathorScraper(keywords=["Java"])
    jobs = asyncio.run(scraper.scrape())

    assert len(jobs) == 2
    by_url = {j.url: j for j in jobs}
    onsite = by_url["https://programathor.com.br/jobs/7977-desenvolvedor-java-junior"]
    remote = by_url["https://programathor.com.br/jobs/8001-dev-java-pleno"]
    assert onsite.title == "Desenvolvedor Java Júnior"
    assert onsite.is_remote is False and "Rio de Janeiro" in onsite.location
    assert remote.is_remote is True and remote.location == "Remoto"


def test_programathor_maps_only_known_tech_slugs():
    scraper = ProgramathorScraper(
        keywords=["Java", "Spring Boot", "Backend Developer", "Analista de Testes", "QA"])
    assert scraper._slugs() == ["java", "spring", "qa"]  # noqa: SLF001


# ── Keyword internationalisation helper ──────────────────────────────────

@pytest.mark.parametrize("kw,expected", [
    ("Java", True), ("QA Automation", True), ("Trainee", True),
    ("Estágio", False), ("Estagiário", False), ("Analista de Testes", False),
])
def test_is_international_keyword(kw, expected):
    assert is_international_keyword(kw) == expected
