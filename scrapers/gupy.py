import asyncio
import aiohttp
from typing import List
from urllib.parse import urlencode

from scrapers.base import BaseScraper, RawJob
from config.settings import get_settings

# Public endpoint that the portal.gupy.io front-end itself calls.
# Verified live (2026-07): returns {"data": [...], "pagination": {...}}.
# Supported params: jobName, offset, limit (max 100), workplaceTypes
# (comma list: remote,hybrid,on-site), state, country, jobTypes.
API_URL = "https://employability-portal.gupy.io/api/v1/jobs"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Origin": "https://portal.gupy.io",
    "Referer": "https://portal.gupy.io/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}


class GupyScraper(BaseScraper):
    """
    Gupy job board via the public portal API (employability-portal.gupy.io).

    The old portal.api.gupy.io host now returns 404, and the listing page at
    vagas.gupy.io is a client-rendered SPA whose server HTML has no job cards,
    so both previous strategies found nothing. This endpoint is the one the
    portal front-end calls and needs no authentication.
    """

    @property
    def source_name(self) -> str:
        return "gupy"

    async def scrape(self) -> List[RawJob]:
        settings = get_settings()
        jobs = []
        for keyword in self.keywords:
            # Remote pass (nationwide)
            jobs.extend(await self._search_api(keyword, workplace_types="remote"))

            # Regional pass: onsite/hybrid in Paraná. The pipeline keeps only
            # the configured sudoeste-do-PR cities, so an over-broad state
            # result set cannot leak through.
            if settings.allow_onsite_in_region:
                jobs.extend(await self._search_api(
                    keyword, workplace_types=None, state="Paraná"))

            await asyncio.sleep(2)

        seen = set()
        unique = []
        for job in jobs:
            if job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} unique jobs")
        return unique

    async def _search_api(self, keyword: str, workplace_types: str = None,
                          state: str = None) -> List[RawJob]:
        params = {"jobName": keyword, "offset": 0, "limit": 50}
        if workplace_types:
            params["workplaceTypes"] = workplace_types
        if state:
            params["state"] = state
        url = f"{API_URL}?{urlencode(params)}"

        jobs = []
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS,
                                       timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for keyword '{keyword}'")
                        return []
                    payload = await resp.json(content_type=None)

            for item in payload.get("data", []):
                job_url = item.get("jobUrl", "")
                if not job_url:
                    continue

                title = item.get("name", "").strip()
                description = item.get("description", "") or ""

                # Defensive client-side checks, since we cannot fully trust
                # server-side filtering (Remotive taught us that lesson):
                # the job must actually mention the keyword, and must match
                # the scope (remote pass → remote jobs; state pass → that
                # state). Otherwise a silently-ignored param would flood the
                # pipeline with unrelated postings from the whole portal.
                if not self.matches_keywords(title, description):
                    continue

                workplace = (item.get("workplaceType") or "").lower()
                is_remote = workplace == "remote" or bool(item.get("isRemoteWork"))
                if workplace_types == "remote" and not is_remote:
                    continue
                if state and (item.get("state") or "").strip().lower() != state.lower():
                    continue

                location_parts = [item.get("city") or "", item.get("state") or ""]
                location = ", ".join(p for p in location_parts if p)
                if not location and is_remote:
                    location = "Remoto"

                jobs.append(RawJob(
                    source=self.source_name,
                    url=job_url,
                    title=title,
                    company=item.get("careerPageName", ""),
                    location=location,
                    description=description,
                    is_remote=is_remote,
                    external_id=str(item.get("id", "")),
                ))
        except Exception as e:
            self.log(f"API error for '{keyword}': {e}")
            return []

        scope = f"state={state}" if state else (workplace_types or "all")
        self.log(f"'{keyword}' ({scope}) → {len(jobs)} jobs")
        return jobs
