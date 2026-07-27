import asyncio
import re
import aiohttp
from bs4 import BeautifulSoup
from typing import List, Optional

from scrapers.base import BaseScraper, RawJob

BASE = "https://programathor.com.br"

# Programathor filters by technology using PATH-style URLs (/jobs-java,
# /jobs-java/remoto). The old query form (?technology=Java) returns the page
# unfiltered/empty, which is why every keyword yielded zero. Only real
# technology slugs exist as pages, so non-tech keywords are mapped or skipped.
_SLUG_MAP = {
    "java": "java",
    "spring boot": "spring",
    "react": "react",
    "typescript": "typescript",
    "angular": "angular",
    "flutter": "flutter",
    "selenium": "selenium",
    "cypress": "cypress",
    "playwright": "playwright",
    "qa": "qa",
}


class ProgramathorScraper(BaseScraper):
    """
    Programathor — Brazilian dev jobs (remote and onsite).

    Parsing is anchor-based (links matching /jobs/<id>-<slug>) instead of
    relying on CSS class names, which have rotted before. Card metadata
    (city, Remoto/Híbrido/Presencial) is read from the anchor's card text.
    """

    @property
    def source_name(self) -> str:
        return "programathor"

    def _slugs(self) -> List[str]:
        slugs = []
        for kw in self.keywords:
            slug = _SLUG_MAP.get(kw.strip().lower())
            if slug and slug not in slugs:
                slugs.append(slug)
        return slugs

    async def scrape(self) -> List[RawJob]:
        jobs = []
        for slug in self._slugs():
            jobs.extend(await self._fetch_page(f"{BASE}/jobs-{slug}"))
            await asyncio.sleep(2)

        seen = set()
        unique = []
        for job in jobs:
            if job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} unique jobs")
        return unique

    async def _fetch_page(self, url: str) -> List[RawJob]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for {url}")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            for anchor in soup.select("a[href*='/jobs/']"):
                href = anchor.get("href", "")
                if not re.search(r"/jobs/\d+-", href):
                    continue
                job = self._parse_card(anchor, href)
                if job:
                    jobs.append(job)
        except Exception as e:
            self.log(f"Error fetching {url}: {e}")

        self.log(f"{url.rsplit('/', 1)[-1]} → {len(jobs)} jobs")
        return jobs

    def _parse_card(self, anchor, href: str) -> Optional[RawJob]:
        job_url = href if href.startswith("http") else BASE + href
        # Ascend to the smallest ancestor that still contains only THIS job's
        # anchor. Ascending a fixed number of levels risks swallowing sibling
        # cards' text (e.g. a neighbour's "Remoto"), corrupting the modality.
        card = anchor
        job_link = re.compile(r"/jobs/\d+-")
        while card.parent is not None:
            candidate = card.parent
            anchors_inside = [
                a for a in candidate.find_all("a", href=True)
                if job_link.search(a["href"])
            ]
            if len(anchors_inside) > 1:
                break
            card = candidate
        text = " ".join(card.get_text(" ", strip=True).split())

        title_el = anchor.select_one("h2, h3") or anchor
        title = title_el.get_text(strip=True)
        if not title:
            # Fallback: derive from the URL slug
            slug = href.rsplit("-", 1)[0].split("/")[-1]
            title = slug.replace("-", " ").title()

        lowered = text.lower()
        is_remote = "remoto" in lowered
        location = ""
        m = re.search(r"([A-Za-zÀ-ú][\wÀ-ú .,'/-]{2,60})\s*\((Presencial|Híbrido|Hibrido)\)", text)
        if m:
            location = m.group(1).strip()
        elif is_remote:
            location = "Remoto"

        return RawJob(
            source=self.source_name,
            url=job_url,
            title=title,
            location=location,
            is_remote=is_remote,
        )
