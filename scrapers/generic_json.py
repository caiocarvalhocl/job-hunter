"""Config-driven scraper for JSON-API job boards.

Most modern job boards (Gupy, Jobicy, Remotive, and the SPA boards on the
candidate's wishlist: BrazilDevs, JobNaGringa, Tecla, BuiltIn, Sólides,
LatamRecruit) render listings client-side from an internal JSON endpoint.
Writing a bespoke scraper file per board means repeating the same fetch +
map + filter logic; the only thing that actually differs is the URL and
which JSON keys hold each field.

This module captures that pattern once. To add a board:

  1. Open the board, F12 → Network → filter XHR/Fetch, run a search.
  2. Find the request that returns the job list as JSON; copy its URL.
  3. Add a SourceConfig (below or in generic_sources.py) describing where the
     list lives in the response and which keys map to title/company/etc.

The heavy lifting (keyword whole-word matching, seniority/location/track/PCD
gates, AI scoring, dedup) all happens downstream in the pipeline, exactly as
for the hand-written scrapers, so a generic source is a first-class citizen.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional
from urllib.parse import urlencode

import aiohttp

from scrapers.base import BaseScraper, RawJob


def _dig(obj: Any, path: str) -> Any:
    """Read a dotted path from nested dict/list JSON, returning '' if absent.

    'data.items' → obj['data']['items']; supports numeric list indexes too:
    'results.0.title'. Kept tiny on purpose; boards rarely nest deeper.
    """
    cur = obj
    for part in path.split("."):
        if cur is None:
            return ""
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return ""
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return ""
    return cur if cur is not None else ""


@dataclass
class SourceConfig:
    name: str                       # source_name stored on each job
    url_template: str               # e.g. "https://x.com/api/jobs?q={keyword}&page=1"
    list_path: str                  # dotted path to the job array, e.g. "data" or "results.jobs"
    field_map: dict                 # RawJob field -> dotted path in each item
    remote_param: Optional[str] = None   # extra querystring appended when remote_only
    headers: dict = field(default_factory=dict)
    # Optional post-processors: RawJob field -> callable(value) -> value
    transforms: dict = field(default_factory=dict)
    international_only: bool = False      # skip PT-only keywords for this board


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}


class GenericJSONScraper(BaseScraper):
    """Instantiated with a SourceConfig; behaves like any other scraper."""

    def __init__(self, config: SourceConfig, keywords, location="Brasil", remote_only=True):
        super().__init__(keywords=keywords, location=location, remote_only=remote_only)
        self.config = config

    @property
    def source_name(self) -> str:
        return self.config.name

    async def scrape(self) -> List[RawJob]:
        from utils import is_international_keyword

        keywords = self.keywords
        if self.config.international_only:
            keywords = [k for k in keywords if is_international_keyword(k)]

        jobs: List[RawJob] = []
        for keyword in keywords:
            jobs.extend(await self._search(keyword))
            await asyncio.sleep(1.5)

        seen, unique = set(), []
        for job in jobs:
            if job.url and job.url not in seen:
                seen.add(job.url)
                unique.append(job)

        self.log(f"Found {len(unique)} unique jobs")
        return unique

    async def _search(self, keyword: str) -> List[RawJob]:
        url = self.config.url_template.format(keyword=urlencode({"": keyword})[1:])
        if self.remote_only and self.config.remote_param:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{self.config.remote_param}"

        headers = {**DEFAULT_HEADERS, **self.config.headers}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers,
                                       timeout=aiohttp.ClientTimeout(total=20)) as resp:
                    if resp.status != 200:
                        self.log(f"HTTP {resp.status} for '{keyword}'")
                        return []
                    payload = await resp.json(content_type=None)
        except Exception as e:
            self.log(f"Error for '{keyword}': {e}")
            return []

        items = _dig(payload, self.config.list_path) if self.config.list_path else payload
        if not isinstance(items, list):
            self.log(f"list_path '{self.config.list_path}' did not resolve to a list "
                     f"for '{keyword}' — check the config")
            return []

        jobs = []
        for item in items:
            job = self._build_job(item)
            # Defensive client-side keyword check: boards often ignore the
            # query param and return everything (the Remotive lesson).
            if job.url and self.matches_keywords(job.title, job.description):
                jobs.append(job)

        self.log(f"'{keyword}' → {len(jobs)} jobs")
        return jobs

    def _build_job(self, item: dict) -> RawJob:
        values = {}
        for field_name, path in self.config.field_map.items():
            val = _dig(item, path)
            if field_name in self.config.transforms:
                val = self.config.transforms[field_name](val)
            values[field_name] = val

        return RawJob(
            source=self.source_name,
            url=str(values.get("url", "") or ""),
            title=str(values.get("title", "") or ""),
            company=str(values.get("company", "") or ""),
            location=str(values.get("location", "") or ""),
            description=str(values.get("description", "") or ""),
            salary=str(values.get("salary", "") or ""),
            is_remote=bool(values.get("is_remote", False)),
            external_id=str(values.get("external_id", "") or ""),
        )
