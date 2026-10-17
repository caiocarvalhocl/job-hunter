import asyncio
import re
from typing import List
from urllib.parse import urlencode

import aiohttp
from bs4 import BeautifulSoup

from config.settings import get_settings
from scrapers.base import BaseScraper, RawJob
from scrapers.jsonld import enrich_descriptions, fetch_html, slugify

BASE_URL = "https://www.vagas.com.br"

# Values of the board's own "modalidade" filter (m[]=...).
REMOTE = "100% Home Office"


class VagasComBrScraper(BaseScraper):
    """
    Vagas.com.br, one of the largest general-purpose Brazilian boards, with
    many openings at companies that never post on tech boards.

    Listing pages (/vagas-de-<cargo>) are server-rendered; robots.txt only
    disallows /api, /vagas/pesquisas and account areas. Per keyword we do two
    passes, newest first: 100% home office nationwide, and every modality in
    SEARCH_STATE (the pipeline then keeps only LOCAL_REGION_CITIES).
    """

    @property
    def source_name(self) -> str:
        return "vagas.com.br"

    async def scrape(self) -> List[RawJob]:
        settings = get_settings()
        jobs: dict[str, RawJob] = {}
        async with aiohttp.ClientSession() as session:
            for keyword in self.keywords:
                passes = [{"m[]": REMOTE}]
                if settings.allow_onsite_in_region:
                    passes.append({"e[]": settings.search_state})
                for params in passes:
                    for job in await self._search(session, keyword, params):
                        jobs.setdefault(job.url, job)
                    await asyncio.sleep(1.5)
            await enrich_descriptions(session, list(jobs.values()), self.log)

        self.log(f"Found {len(jobs)} unique jobs")
        return list(jobs.values())

    async def _search(self, session, keyword: str, params: dict) -> List[RawJob]:
        query = urlencode({**params, "ordenar_por": "mais_recentes"})
        url = f"{BASE_URL}/vagas-de-{slugify(keyword)}?{query}"
        try:
            html = await fetch_html(session, url)
        except Exception as e:  # noqa: BLE001
            self.log(f"Error for '{keyword}': {e}")
            return []
        if html is None:
            self.log(f"HTTP error for '{keyword}'")
            return []
        jobs = [j for j in parse_listing(html, remote_pass=REMOTE in params.values())
                if self.matches_keywords(j.title, j.description)]
        scope = "home office" if REMOTE in params.values() else params.get("e[]")
        self.log(f"'{keyword}' ({scope}) → {len(jobs)} jobs")
        return jobs


def parse_listing(html: str, remote_pass: bool = False) -> List[RawJob]:
    """Parse the <li class="vaga"> cards of a Vagas.com.br search page."""
    soup = BeautifulSoup(html, "lxml")
    jobs = []
    for card in soup.select("li.vaga"):
        link = card.select_one("a.link-detalhes-vaga")
        if not link or not link.get("href"):
            continue
        local = card.select_one(".vaga-local")
        location = ""
        if local:
            tip = local.select_one(".tooltip-place")
            if tip:
                tip.decompose()
            location = re.sub(r"\s+", " ", local.get_text(" ", strip=True))
        if location.lower().startswith("localização não informada"):
            location = ""
        company = card.select_one(".emprVaga")
        level = card.select_one(".nivelVaga")
        detail = card.select_one(".detalhes")
        description = re.sub(r"^Descrição:\s*", "", detail.get_text(" ", strip=True)) if detail else ""
        is_remote = remote_pass or bool(re.search(r"home\s*office|remot", location, re.I))
        jobs.append(RawJob(
            source="vagas.com.br",
            url=BASE_URL + link["href"],
            title=link.get("title") or link.get_text(" ", strip=True),
            company=company.get_text(strip=True) if company else "",
            location=location or ("Remoto" if is_remote else ""),
            description=(f"Nível: {level.get_text(strip=True)}. " if level else "") + description,
            is_remote=is_remote,
            external_id=link.get("data-id-vaga", ""),
        ))
    return jobs
