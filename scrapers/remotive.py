import asyncio
import re
import aiohttp
from typing import List
from urllib.parse import urlencode

from scrapers.base import BaseScraper, RawJob

API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveScraper(BaseScraper):
    """
    Free public JSON API. Docs advertise a server-side `search` param, but
    production runs showed it (and `category`) being silently ignored: three
    different keyword queries all returned the identical 31-job set,
    including roles far outside software (Copywriter, Sales Assistant).

    Fix: fetch once (no reliance on server-side filtering) and filter
    client-side against title + description, same defensive pattern as the
    Arbeitnow scraper. This also cuts requests from one-per-keyword to a
    single call per run, which matters here: Remotive's own docs ask for
    at most ~4 polls/day, and looping per keyword was already multiplying
    that by len(keywords) every run.
    """

    @property
    def source_name(self) -> str:
        return "remotive"

    async def scrape(self) -> List[RawJob]:
        raw_jobs = await self._fetch()
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

    async def _fetch(self) -> List[RawJob]:
        url = f"{API_URL}?{urlencode({'category': 'software-dev'})}"
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status}")
                        return []
                    data = await resp.json(content_type=None)

            for item in data.get("jobs", []):
                description = re.sub(r"<[^>]+>", " ", item.get("description", ""))
                jobs.append(RawJob(
                    source=self.source_name,
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=item.get("candidate_required_location", ""),
                    description=description.strip(),
                    salary=item.get("salary", ""),
                    is_remote=True,
                    external_id=str(item.get("id", "")),
                ))
        except Exception as e:
            self.log(f"Error: {e}")

        return jobs
