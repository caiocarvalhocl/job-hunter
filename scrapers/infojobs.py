import asyncio
import re
from typing import List

import aiohttp
from bs4 import BeautifulSoup

from config.settings import get_settings
from scrapers.base import BaseScraper, RawJob
from scrapers.jsonld import STATE_UF, enrich_descriptions, fetch_html, slugify

BASE_URL = "https://www.infojobs.com.br"

_MODALITY_REMOTE_RE = re.compile(r"\b(home\s*office|remoto|teletrabalho)\b", re.I)
_MODALITY_HYBRID_RE = re.compile(r"\bh[íi]brido\b", re.I)
_LOCATION_RE = re.compile(r"^[^\d|]+ - [A-Z]{2}$")


class InfoJobsScraper(BaseScraper):
    """
    InfoJobs Brasil: large general board, including small and mid-sized
    companies outside capitals.

    Search pages are server-rendered SEO URLs; robots.txt disallows only
    static/legal pages. Per keyword: a home-office pass nationwide, then one
    pass per SEARCH_CITIES city (or a single SEARCH_STATE pass when no city is
    configured); the pipeline keeps only LOCAL_REGION_CITIES.
    """

    @property
    def source_name(self) -> str:
        return "infojobs"

    async def scrape(self) -> List[RawJob]:
        settings = get_settings()
        jobs: dict[str, RawJob] = {}
        async with aiohttp.ClientSession() as session:
            for keyword in self.keywords:
                kw = slugify(keyword).replace("-", "+")
                passes = [(f"/vagas-de-emprego-{kw}-trabalho-home-office.aspx", "home office")]
                if settings.allow_onsite_in_region:
                    passes += regional_paths(kw, settings.search_state, settings.search_cities_list)
                for path, scope in passes:
                    for job in await self._search(session, keyword, path, scope):
                        jobs.setdefault(job.url, job)
                    await asyncio.sleep(1.5)
            await enrich_descriptions(session, list(jobs.values()), self.log)

        self.log(f"Found {len(jobs)} unique jobs")
        return list(jobs.values())

    async def _search(self, session, keyword: str, path: str, scope: str) -> List[RawJob]:
        try:
            html = await fetch_html(session, BASE_URL + path)
        except Exception as e:  # noqa: BLE001
            self.log(f"Error for '{keyword}': {e}")
            return []
        if html is None:
            self.log(f"HTTP error for '{keyword}'")
            return []
        # The home-office URL still lists some on-site jobs, so a card only
        # counts as remote when its own modality says so.
        jobs = [j for j in parse_listing(html)
                if self.matches_keywords(j.title, j.description)]
        self.log(f"'{keyword}' ({scope}) → {len(jobs)} jobs")
        return jobs


def regional_paths(kw: str, state: str, cities: List[str]) -> List[tuple[str, str]]:
    """Search paths for the on-site pass: one per city (".../-em-pato-branco,-pr.aspx")
    when cities are configured, otherwise the whole state."""
    state_slug = slugify(state)
    uf = STATE_UF.get(state_slug)
    if cities and uf:
        return [(f"/vagas-de-emprego-{kw}-em-{slugify(c)},-{uf}.aspx", c) for c in cities]
    return [(f"/vagas-de-emprego-{kw}-em-{state_slug}.aspx", state)]


def parse_listing(html: str) -> List[RawJob]:
    """Parse InfoJobs search cards. The page repeats each card (desktop and
    mobile variants), so cards are deduplicated by data-id."""
    soup = BeautifulSoup(html, "lxml")
    seen, jobs = set(), []
    for card in soup.select("div.js_rowCard[data-href]"):
        job_id = card.get("data-id", "")
        if job_id in seen:
            continue
        seen.add(job_id)

        title_el = card.select_one(".js_vacancyTitle")
        company_el = card.select_one("a[href^='https://www.infojobs.com.br/']")
        # Direct child <div>s hold location (e.g. "Londrina - PR"), the
        # salary/education/modality row and the description snippet.
        location, modality, snippet = "", "", ""
        for div in card.find_all("div", recursive=False):
            text = re.sub(r"\s+", " ", div.get_text(" ", strip=True))
            if div.select_one(".js_divUserVagaDistance") is not None:
                location = text.split(",")[0].strip()
            elif "text-medium" in (div.get("class") or []) and "d-inline-flex" not in (div.get("class") or []):
                snippet = text
            elif "d-inline-flex" in (div.get("class") or []):
                modality = text
        if location and not _LOCATION_RE.match(location):
            location = ""

        is_remote = bool(_MODALITY_REMOTE_RE.search(modality)) and not _MODALITY_HYBRID_RE.search(modality)
        jobs.append(RawJob(
            source="infojobs",
            url=BASE_URL + card["data-href"],
            title=title_el.get_text(" ", strip=True) if title_el else "",
            company=re.sub(r"\s+", " ", company_el.get_text(" ", strip=True)) if company_el else "",
            location=location or ("Remoto" if is_remote else ""),
            description=(f"{modality}. " if modality else "") + snippet,
            is_remote=is_remote,
            external_id=job_id,
        ))
    return jobs
