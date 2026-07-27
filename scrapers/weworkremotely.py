import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import List

from scrapers.base import BaseScraper, RawJob

RSS_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]


class WeWorkRemotelyScraper(BaseScraper):

    @property
    def source_name(self) -> str:
        return "weworkremotely"

    async def scrape(self) -> List[RawJob]:
        all_jobs = []
        for feed_url in RSS_FEEDS:
            jobs = await self._fetch_rss(feed_url)
            all_jobs.extend(jobs)
            await asyncio.sleep(1)

        seen = set()
        filtered = []
        for job in all_jobs:
            if job.url in seen:
                continue
            if self.matches_keywords(job.title, job.description):
                seen.add(job.url)
                filtered.append(job)

        self.log(f"Found {len(filtered)} matching jobs")
        return filtered

    async def _fetch_rss(self, feed_url: str) -> List[RawJob]:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(feed_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for {feed_url}")
                        return []
                    xml = await resp.text()

            soup = BeautifulSoup(xml, "xml")
            for item in soup.find_all("item"):
                try:
                    title_raw = item.find("title").get_text(strip=True)
                    link = item.find("link").get_text(strip=True) if item.find("link") else ""
                    description = item.find("description").get_text(strip=True) if item.find("description") else ""
                    parts = title_raw.split(": ", 1)
                    company = parts[0] if len(parts) == 2 else ""
                    title = parts[1] if len(parts) == 2 else title_raw
                    job = RawJob(
                        source=self.source_name,
                        url=link,
                        title=title,
                        company=company,
                        location="Remote",
                        description=description,
                        is_remote=True,
                    )
                    jobs.append(job)
                except Exception:
                    continue
        except Exception as e:
            self.log(f"Error: {e}")
        return jobs