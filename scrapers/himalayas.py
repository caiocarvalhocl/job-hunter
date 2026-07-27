import asyncio
import re
import aiohttp
from typing import List
from urllib.parse import urlencode

from scrapers.base import BaseScraper, RawJob
from utils import is_international_keyword

# Dedicated search endpoint (verified live, 2026-07). The previous code used
# the browse endpoint (/jobs/api) which silently ignores the `q` param, and
# read a `url` field that doesn't exist in the schema — every job was dropped
# by the `if job.url` guard, so the scraper always reported zero results.
SEARCH_URL = "https://himalayas.app/jobs/api/search"

# Values of locationRestrictions that keep the job eligible for a
# Brazil-based candidate. Empty array means worldwide.
_ELIGIBLE_LOCATIONS = {"brazil", "latin america", "south america", "americas"}


class HimalayasScraper(BaseScraper):

    @property
    def source_name(self) -> str:
        return "himalayas"

    async def scrape(self) -> List[RawJob]:
        # PT-only keywords (Estágio, Analista de Testes...) never match on an
        # English-language board; skipping them saves requests and log noise.
        keywords = [k for k in self.keywords if is_international_keyword(k)]

        jobs = []
        for keyword in keywords:
            jobs.extend(await self._search(keyword))
            await asyncio.sleep(1.5)

        seen = set()
        unique = []
        for job in jobs:
            if job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} unique jobs")
        return unique

    async def _search(self, keyword: str) -> List[RawJob]:
        url = f"{SEARCH_URL}?{urlencode({'q': keyword})}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 429:
                        self.log(f"Rate limited on '{keyword}' — skipping rest of keyword")
                        return []
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for '{keyword}'")
                        return []
                    data = await resp.json(content_type=None)

            for item in data.get("jobs", []):
                restrictions = item.get("locationRestrictions") or []
                # Non-empty restrictions without a Brazil-compatible entry
                # mean the candidate can't apply; skip before it costs an
                # LLM call downstream.
                if restrictions and not any(
                    r.lower() in _ELIGIBLE_LOCATIONS for r in restrictions
                ):
                    continue

                description = re.sub(r"<[^>]+>", " ", item.get("description", "")).strip()
                jobs.append(RawJob(
                    source=self.source_name,
                    url=item.get("applicationLink", "") or item.get("guid", ""),
                    title=item.get("title", ""),
                    company=item.get("companyName", ""),
                    location=", ".join(restrictions) if restrictions else "Worldwide",
                    description=description,
                    salary=(f"{item.get('minSalary')}-{item.get('maxSalary')} "
                            f"{item.get('currency', '')}".strip()
                            if item.get("minSalary") else ""),
                    is_remote=True,
                    external_id=item.get("guid", ""),
                ))
        except Exception as e:
            self.log(f"Error: {e}")

        self.log(f"'{keyword}' → {len(jobs)} jobs")
        return [j for j in jobs if j.url]
