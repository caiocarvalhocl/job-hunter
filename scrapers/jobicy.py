import asyncio
import re
import aiohttp
from typing import List
from urllib.parse import urlencode

from scrapers.base import BaseScraper, RawJob
from utils import is_international_keyword

API_URL = "https://jobicy.com/api/v2/remote-jobs"


class JobicyScraper(BaseScraper):
    """
    Free public JSON API. Real server-side `tag` param (searches title +
    description) plus an `industry` filter, we use industry=dev to narrow
    the pool before the keyword pass.

    Jobicy asks for attribution (link back) and infrequent polling, same
    spirit as Remotive; well within our 6h scheduler interval.
    """

    @property
    def source_name(self) -> str:
        return "jobicy"

    async def scrape(self) -> List[RawJob]:
        jobs = []
        keywords = [k for k in self.keywords if is_international_keyword(k)]
        for keyword in keywords:
            results = await self._search(keyword)
            jobs.extend(results)
            await asyncio.sleep(1)

        seen = set()
        unique = []
        for job in jobs:
            if job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} unique jobs")
        return unique

    async def _search(self, keyword: str) -> List[RawJob]:
        params = {"count": 50, "industry": "dev", "tag": keyword}
        url = f"{API_URL}?{urlencode(params)}"
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status in (400, 404):
                        # Jobicy answers 404/400 when a tag has no results;
                        # that's "0 jobs", not an error worth logging loudly.
                        return []
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for '{keyword}'")
                        return []
                    data = await resp.json(content_type=None)

            for item in data.get("jobs", []):
                description = re.sub(r"<[^>]+>", " ", item.get("jobDescription", ""))
                salary = ""
                if item.get("salaryMin") and item.get("salaryMax"):
                    salary = f"{item.get('salaryMin')}-{item.get('salaryMax')} {item.get('salaryCurrency', '')}".strip()
                jobs.append(RawJob(
                    source=self.source_name,
                    url=item.get("url", ""),
                    title=item.get("jobTitle", ""),
                    company=item.get("companyName", ""),
                    location=item.get("jobGeo", "Anywhere"),
                    description=description.strip(),
                    salary=salary,
                    is_remote=True,
                    external_id=str(item.get("id", "")),
                ))
        except Exception as e:
            self.log(f"Error: {e}")

        self.log(f"'{keyword}' → {len(jobs)} jobs")
        return jobs
