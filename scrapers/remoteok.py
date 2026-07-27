import asyncio
import aiohttp
from typing import List

from scrapers.base import BaseScraper, RawJob


class RemoteOKScraper(BaseScraper):

    @property
    def source_name(self) -> str:
        return "remoteok"

    async def scrape(self) -> List[RawJob]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
        }
        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://remoteok.com/api",
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status}")
                        return []
                    data = await resp.json(content_type=None)

            for item in data:
                if not isinstance(item, dict) or not item.get("position"):
                    continue
                tags = " ".join(item.get("tags", []))
                if not self.matches_keywords(item.get("position", ""), tags):
                    continue
                job = RawJob(
                    source=self.source_name,
                    url=item.get("url", f"https://remoteok.com/l/{item.get('id')}"),
                    title=item.get("position", ""),
                    company=item.get("company", ""),
                    location="Remote",
                    description=item.get("description", ""),
                    salary=item.get("salary", ""),
                    is_remote=True,
                    external_id=str(item.get("id", "")),
                )
                jobs.append(job)
        except Exception as e:
            self.log(f"Error: {e}")

        self.log(f"Found {len(jobs)} jobs")
        return jobs