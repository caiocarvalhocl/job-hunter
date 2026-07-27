"""Fetch a single, already-known job posting page and extract title, company,
location and description.

This is deliberately NOT a scraper: it never searches, lists, or crawls
LinkedIn. It fetches exactly one URL the person already found by browsing
LinkedIn themselves and pasted into the bot. LinkedIn serves the public
`/jobs/view/<id>` page mostly unauthenticated (that's how the posting gets
indexed by search engines), so a single fetch of a URL you already have is a
materially different, much lower-risk action than automated search/crawling,
which this project does not do. It is still automated access to LinkedIn and
not officially sanctioned by their Terms, so failures (login wall, layout
change, block) are expected and handled by falling back to whatever the
person pastes manually.

Support for other ATS-hosted postings (Gupy, Greenhouse, etc.) is included
opportunistically since the same "paste a URL" flow is useful there too; the
LinkedIn-specific selectors are the ones that need the most maintenance.
"""
import re
import aiohttp
from bs4 import BeautifulSoup
from dataclasses import dataclass
from typing import Optional

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class FetchedPosting:
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    is_remote: bool = False
    ok: bool = False          # True if we got enough to be useful
    error: str = ""


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _parse_linkedin(soup: BeautifulSoup) -> FetchedPosting:
    title = _text(
        soup.select_one("h1.top-card-layout__title, h1.topcard__title, h1")
    )
    company = _text(
        soup.select_one(
            "a.topcard__org-name-link, span.topcard__flavor, "
            "a.top-card-layout__second-subline, .topcard__org-name-link"
        )
    )
    location = _text(
        soup.select_one("span.topcard__flavor--bullet, .top-card-layout__second-subline span")
    )
    description = _text(
        soup.select_one("div.description__text, div.show-more-less-html__markup")
    )
    return FetchedPosting(
        title=title, company=company, location=location, description=description,
        is_remote="remote" in (location or "").lower() or "remoto" in (location or "").lower(),
        ok=bool(title and (description or company)),
    )


def _parse_generic(soup: BeautifulSoup) -> FetchedPosting:
    """Best-effort fallback for non-LinkedIn URLs (Gupy, Greenhouse, etc.)."""
    title_el = soup.select_one("h1") or soup.select_one("title")
    description_el = soup.select_one("main") or soup.select_one("article") or soup.body
    title = _text(title_el)
    description = _text(description_el)[:6000]
    return FetchedPosting(
        title=title, description=description,
        ok=bool(title and len(description) > 100),
    )


async def fetch_posting(url: str) -> FetchedPosting:
    """Fetch and parse exactly one job posting URL. Never retries or paginates."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return FetchedPosting(error=f"HTTP {resp.status}")
                html = await resp.text()
    except Exception as e:
        return FetchedPosting(error=str(e))

    soup = BeautifulSoup(html, "html.parser")
    is_linkedin = "linkedin.com" in url.lower()
    result = _parse_linkedin(soup) if is_linkedin else _parse_generic(soup)

    if not result.ok:
        result.error = result.error or (
            "Página retornou pouco conteúdo (provável login wall ou layout "
            "diferente do esperado)."
        )
    return result
