import asyncio
import re
import aiohttp
from typing import List

from scrapers.base import BaseScraper, RawJob

API_URL = "https://www.arbeitnow.com/api/job-board-api"


class ArbeitnowScraper(BaseScraper):
    """
    Free public JSON API (no key needed) covering Europe + remote roles,
    sourced from ATSs like Greenhouse, SmartRecruiters, Recruitee, etc.

    The API has no server-side keyword search (confirmed: `?search=` is
    silently ignored), so we fetch a few pages and filter client-side
    against title + description + tags.
    """

    @property
    def source_name(self) -> str:
        return "arbeitnow"

    async def scrape(self) -> List[RawJob]:
        raw_jobs = await self._fetch_pages(max_pages=3)
        matched = [j for j in raw_jobs if self._matches_keywords(j)]

        seen = set()
        unique = []
        for job in matched:
            if job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} matching jobs (of {len(raw_jobs)} fetched)")
        return unique

    def _matches_keywords(self, job: RawJob) -> bool:
        return self.matches_keywords(job.title, job.description)

    async def _fetch_pages(self, max_pages: int) -> List[RawJob]:
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                for page in range(1, max_pages + 1):
                    url = f"{API_URL}?page={page}"
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                        if resp.status != 200:
                            self.log(f"HTTP {resp.status} on page {page}")
                            break
                        payload = await resp.json(content_type=None)

                    items = payload.get("data", [])
                    if not items:
                        break

                    for item in items:
                        description = re.sub(r"<[^>]+>", " ", item.get("description", ""))
                        jobs.append(RawJob(
                            source=self.source_name,
                            url=item.get("url", ""),
                            title=item.get("title", ""),
                            company=item.get("company_name", ""),
                            location=item.get("location", ""),
                            description=description.strip(),
                            is_remote=bool(item.get("remote", False)),
                            external_id=item.get("slug", ""),
                        ))
                    await asyncio.sleep(1)
        except Exception as e:
            self.log(f"Error fetching Arbeitnow: {e}")

        return jobs
