"""Offline scraper tests: keyword filtering behaviour via the base helper.

Full fetch paths need the network, so these cover the shared filtering logic
that every scraper relies on, using a throwaway concrete scraper.
"""
from typing import List

from scrapers.base import BaseScraper, RawJob


class _Dummy(BaseScraper):
    @property
    def source_name(self) -> str:
        return "dummy"

    async def scrape(self) -> List[RawJob]:
        return []


def _scraper(keywords):
    return _Dummy(keywords=keywords)


def test_base_matcher_uses_word_boundaries():
    s = _scraper(["Java", "Spring Boot"])
    assert s.matches_keywords("Java Developer")
    assert not s.matches_keywords("JavaScript Developer")


def test_base_matcher_scans_multiple_fields():
    s = _scraper(["Backend Developer"])
    assert s.matches_keywords("Copywriter", "Looking for a Backend Developer")
    assert not s.matches_keywords("Copywriter", "Looking for a designer")


def test_rawjob_defaults():
    job = RawJob(source="s", url="u", title="t")
    assert job.company == "" and job.is_remote is False
    assert job.found_at is not None
