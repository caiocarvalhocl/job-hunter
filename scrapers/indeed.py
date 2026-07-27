import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import List
from urllib.parse import urlencode
import re

from scrapers.base import BaseScraper, RawJob


class IndeedScraper(BaseScraper):

    @property
    def source_name(self) -> str:
        return "indeed"

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
        params = {
            "q": keyword,
            "l": "Brazil" if "brasil" in self.location.lower() else self.location,
            "fromage": "7",
        }
        if self.remote_only:
            params["remotejob"] = "032b3046-06a3-4876-8dfd-474eb5e7ed11"

        url = f"https://br.indeed.com/jobs?{urlencode(params)}"
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }

        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for keyword '{keyword}'")
                        return []
                    html = await resp.text()

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.select("div.job_seen_beacon")

            for card in cards:
                try:
                    title_el = card.select_one("h2.jobTitle span")
                    company_el = card.select_one("[data-testid='company-name']")
                    location_el = card.select_one("[data-testid='text-location']")
                    salary_el = card.select_one("[data-testid='attribute_snippet_testid']")
                    link_el = card.select_one("h2.jobTitle a")

                    if not title_el or not link_el:
                        continue

                    job_url = "https://br.indeed.com" + link_el.get("href", "")
                    external_id = re.search(r"jk=([a-z0-9]+)", job_url)

                    job = RawJob(
                        source=self.source_name,
                        url=job_url,
                        title=title_el.get_text(strip=True),
                        company=company_el.get_text(strip=True) if company_el else "",
                        location=location_el.get_text(strip=True) if location_el else "",
                        salary=salary_el.get_text(strip=True) if salary_el else "",
                        is_remote="remot" in (location_el.get_text(strip=True) if location_el else "").lower(),
                        external_id=external_id.group(1) if external_id else "",
                    )
                    jobs.append(job)
                except Exception as e:
                    self.log(f"Error parsing card: {e}")
                    continue

        except Exception as e:
            self.log(f"Error fetching Indeed: {e}")

        self.log(f"'{keyword}' → {len(jobs)} jobs")
        return jobs
