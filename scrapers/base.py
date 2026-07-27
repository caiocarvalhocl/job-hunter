from abc import ABC, abstractmethod
from typing import List
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RawJob:
    source: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    salary: str = ""
    is_remote: bool = False
    external_id: str = ""
    found_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BaseScraper(ABC):
    def __init__(self, keywords: List[str], location: str = "Brasil", remote_only: bool = True):
        self.keywords = keywords
        self.location = location
        self.remote_only = remote_only

    @property
    @abstractmethod
    def source_name(self) -> str:
        ...

    @abstractmethod
    async def scrape(self) -> List[RawJob]:
        ...

    def matches_keywords(self, *texts: str) -> bool:
        """Whole-word/phrase keyword match (see utils.matches_keywords).

        Deferred import avoids a circular dependency with utils, which imports
        RawJob from this module.
        """
        from utils import matches_keywords
        return matches_keywords(self.keywords, *texts)

    def log(self, message: str):
        print(f"[{self.source_name.upper()}] {message}")
