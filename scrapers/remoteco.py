import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import List

from scrapers.base import BaseScraper, RawJob


class RemoteCo(BaseScraper):

    @property
    def source_name(self) -> str:
        return "remote.co"

    async def scrape(self) -> List[RawJob]:
        jobs = []
        for keyword in self.keywords:
            results = await self._search(keyword)
            jobs.extend(results)
            await asyncio.sleep(2)

        seen = set()
        unique = []
        for job in jobs:
            if job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} unique jobs")
        return unique

    async def _search(self, keyword: str) -> List[RawJob]:
        search_term = keyword.lower().replace(" ", "+")
        url = f"https://remote.co/remote-jobs/search/?search_keywords={search_term}"

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        }

        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for '{keyword}'")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select(".job_listings .job_listing")

            for card in cards:
                try:
                    title_el = card.select_one(".position h3")
                    company_el = card.select_one(".company strong")
                    link_el = card.select_one("a")

                    if not title_el or not link_el:
                        continue

                    job_url = link_el.get("href", "")
                    if job_url.startswith("/"):
                        job_url = "https://remote.co" + job_url

                    job = RawJob(
                        source=self.source_name,
                        url=job_url,
                        title=title_el.get_text(strip=True),
                        company=company_el.get_text(strip=True) if company_el else "",
                        location="Remote",
                        is_remote=True,
                    )
                    jobs.append(job)
                except Exception as e:
                    self.log(f"Error parsing card: {e}")
                    continue

        except Exception as e:
            self.log(f"Error fetching Remote.co: {e}")

        self.log(f"'{keyword}' → {len(jobs)} jobs")
        return jobs
