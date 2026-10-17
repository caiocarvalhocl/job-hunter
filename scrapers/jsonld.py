"""Shared helpers for Brazilian HTML boards (Vagas.com.br, InfoJobs).

Both boards render the listing server-side but show only a ~300-char snippet
per card. The full description lives on the detail page as a schema.org
JobPosting JSON-LD block, which is far more stable than scraping the page's
own markup, so the scrapers fetch it for the jobs that can actually survive
the pipeline (remote, or on-site inside LOCAL_REGION_CITIES).
"""
import asyncio
import json
import re
import unicodedata
from typing import Callable, List, Optional

import aiohttp
from bs4 import BeautifulSoup

from scrapers.base import RawJob

HEADERS = {
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
}

STATE_UF = {
    "acre": "ac", "alagoas": "al", "amapa": "ap", "amazonas": "am", "bahia": "ba",
    "ceara": "ce", "distrito-federal": "df", "espirito-santo": "es", "goias": "go",
    "maranhao": "ma", "mato-grosso": "mt", "mato-grosso-do-sul": "ms",
    "minas-gerais": "mg", "para": "pa", "paraiba": "pb", "parana": "pr",
    "pernambuco": "pe", "piaui": "pi", "rio-de-janeiro": "rj",
    "rio-grande-do-norte": "rn", "rio-grande-do-sul": "rs", "rondonia": "ro",
    "roraima": "rr", "santa-catarina": "sc", "sao-paulo": "sp", "sergipe": "se",
    "tocantins": "to",
}

# Detail pages fetched per scraper run. Bounds the extra requests when a
# broad keyword returns many regional hits at once.
MAX_DETAIL_FETCHES = 20


def slugify(text: str) -> str:
    """'Auxiliar de Escritório' → 'auxiliar-de-escritorio' (URL slug form)."""
    ascii_text = "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def clean_text(html_or_text: str) -> str:
    text = BeautifulSoup(html_or_text or "", "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def extract_job_posting(html: str) -> Optional[dict]:
    """Return the first schema.org JobPosting object embedded in the page."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def is_telecommute(posting: dict) -> bool:
    return str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE"


async def fetch_html(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    async with session.get(url, headers=HEADERS,
                           timeout=aiohttp.ClientTimeout(total=20)) as resp:
        if resp.status != 200:
            return None
        return await resp.text()


async def enrich_descriptions(session, jobs: List[RawJob], log: Callable[[str], None],
                              fetch=None) -> None:
    """Swap the listing snippet for the full JobPosting description, only for
    jobs that can pass the location gate downstream. On-site jobs in the
    region come first: they are scarce, while home-office hits are plenty and
    would otherwise use up the MAX_DETAIL_FETCHES budget."""
    from filters.location_filter import is_local_region

    fetch = fetch or fetch_html
    local = [j for j in jobs if not j.is_remote and is_local_region(j.location)]
    remote = [j for j in jobs if j.is_remote]
    for job in (local + remote)[:MAX_DETAIL_FETCHES]:
        try:
            html = await fetch(session, job.url)
        except Exception as e:  # noqa: BLE001
            log(f"Detail error {job.url}: {e}")
            continue
        posting = extract_job_posting(html or "")
        if posting:
            job.description = clean_text(posting.get("description", "")) or job.description
            job.is_remote = job.is_remote or is_telecommute(posting)
        await asyncio.sleep(1)
