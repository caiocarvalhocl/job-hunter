"""Offline parsing tests for scrapers/single_fetch.py (no real network)."""
import asyncio
from unittest.mock import patch

from scrapers.single_fetch import fetch_posting, _parse_linkedin, _parse_generic
from bs4 import BeautifulSoup

LINKEDIN_HTML = """
<html><body>
<h1 class="top-card-layout__title">Java Backend Developer Júnior</h1>
<a class="topcard__org-name-link">Acme Tecnologia</a>
<span class="topcard__flavor--bullet">Remote</span>
<div class="description__text">
  We are looking for a Java developer to join our backend team.
</div>
</body></html>
"""

LOGIN_WALL_HTML = """
<html><body>
<h1 class="top-card-layout__title">Java Backend Developer</h1>
<div id="sign-in-wall">Please sign in to see more.</div>
</body></html>
"""

GENERIC_HTML = """
<html><head><title>Dev Java Pleno — Empresa</title></head>
<body><main><h1>Dev Java Pleno</h1>
<p>""" + ("Descrição da vaga. " * 30) + """</p>
</main></body></html>
"""


def test_parse_linkedin_extracts_fields():
    soup = BeautifulSoup(LINKEDIN_HTML, "html.parser")
    result = _parse_linkedin(soup)
    assert result.ok
    assert result.title == "Java Backend Developer Júnior"
    assert result.company == "Acme Tecnologia"
    assert result.is_remote is True
    assert "Java developer" in result.description


def test_parse_linkedin_login_wall_is_not_ok():
    # No description and no company → not enough to be useful.
    soup = BeautifulSoup(LOGIN_WALL_HTML, "html.parser")
    result = _parse_linkedin(soup)
    assert not result.ok


def test_parse_generic_extracts_title_and_body():
    soup = BeautifulSoup(GENERIC_HTML, "html.parser")
    result = _parse_generic(soup)
    assert result.ok
    assert result.title == "Dev Java Pleno"
    assert "Descrição da vaga" in result.description


def test_fetch_posting_reports_http_error(monkeypatch):
    import scrapers.single_fetch as sf

    class _FakeResp:
        status = 404
        async def text(self): return ""
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeSession:
        def get(self, *a, **kw): return _FakeResp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(sf.aiohttp, "ClientSession", lambda: _FakeSession())

    result = asyncio.run(fetch_posting("https://www.linkedin.com/jobs/view/123"))
    assert not result.ok
    assert "404" in result.error


def test_fetch_posting_never_retries_or_paginates(monkeypatch):
    """One GET call per invocation — this must never turn into crawling."""
    import scrapers.single_fetch as sf

    calls = []

    class _FakeResp:
        status = 200
        async def text(self): return LINKEDIN_HTML
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    class _FakeSession:
        def get(self, url, **kw):
            calls.append(url)
            return _FakeResp()
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False

    monkeypatch.setattr(sf.aiohttp, "ClientSession", lambda: _FakeSession())

    asyncio.run(fetch_posting("https://www.linkedin.com/jobs/view/123"))
    assert len(calls) == 1
