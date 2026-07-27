"""Shared helpers used across scrapers and generators.

Two responsibilities, kept here so every part of the pipeline behaves the same:
  - language detection for a posting (cover letter and CV must agree);
  - keyword matching with word boundaries (so "Java" never matches
    "JavaScript", the classic substring bug).
"""
import re
from functools import lru_cache
from typing import List, Tuple

from scrapers.base import RawJob

_BR_SIGNALS = ["gupy", "catho", "infojobs", "programathor", "brasil", "brazil", " br", "br "]

_PT_MARKERS = [
    "você", "voce", "não", "nao", "vaga", "experiência", "experiencia",
    "conhecimento", "desenvolvimento", "equipe", "requisitos", "benefícios",
    "beneficios", "diferenciais", "atividades", "atuar", "conosco", "área",
    "area", "será", "sera", "para", "como", "nossa", "nosso",
]
_EN_MARKERS = [
    "you", "we", "the", "and", "with", "our", "will", "team", "work",
    "experience", "skills", "requirements", "development", "years",
    "looking", "join", "role", "responsibilities",
]

_PT_RE = re.compile(r"\b(" + "|".join(_PT_MARKERS) + r")\b", re.IGNORECASE)
_EN_RE = re.compile(r"\b(" + "|".join(_EN_MARKERS) + r")\b", re.IGNORECASE)


def detect_language(job: RawJob) -> str:
    """Return 'pt' or 'en' — the language the APPLICATION should be in.

    Priority 1: the language of the posting text itself. Priority 2
    (fallback, short text): board/location signals.
    """
    text = f"{job.title} {job.description or ''}"
    pt_hits = len(_PT_RE.findall(text))
    en_hits = len(_EN_RE.findall(text))

    if pt_hits + en_hits >= 5 and pt_hits != en_hits:
        return "pt" if pt_hits > en_hits else "en"

    haystack = f" {job.source} {job.location} {job.url} ".lower()
    return "pt" if any(sig in haystack for sig in _BR_SIGNALS) else "en"


_PT_ONLY_KEYWORDS = {"analista de testes", "estágio", "estagio", "estagiário", "estagiario"}


def is_international_keyword(keyword: str) -> bool:
    """False for PT-only terms that will never match on English-only boards."""
    kw = keyword.strip().lower()
    if kw in _PT_ONLY_KEYWORDS:
        return False
    return kw == kw.encode("ascii", errors="ignore").decode()


@lru_cache(maxsize=64)
def _compile_keywords(keywords: Tuple[str, ...]) -> re.Pattern:
    """Compile keywords into a single word-boundary regex.

    Each keyword becomes a \\b...\\b alternative. Multi-word keywords such as
    "Spring Boot" are matched as a whole phrase with flexible internal
    whitespace. Matching is case-insensitive.
    """
    parts = []
    for kw in keywords:
        kw = kw.strip()
        if not kw:
            continue
        tokens = re.split(r"\s+", kw)
        pattern = r"\s+".join(re.escape(t) for t in tokens)
        parts.append(rf"\b{pattern}\b")
    if not parts:
        return re.compile(r"(?!x)x")  # matches nothing
    return re.compile("|".join(parts), re.IGNORECASE)


def matches_keywords(keywords: List[str], *texts: str) -> bool:
    """True if any keyword occurs as a whole word/phrase in any of the texts.

    Fixes the substring false positives that let "javascript", "guardian",
    etc. through a naive `keyword in text` check.
    """
    regex = _compile_keywords(tuple(keywords))
    haystack = " ".join(t for t in texts if t)
    return bool(regex.search(haystack))


_PT_ONLY_KEYWORDS = {"analista de testes", "estágio", "estagio", "estagiário", "estagiario"}


def is_international_keyword(keyword: str) -> bool:
    """False for PT-only terms that will never match on English-only boards.

    Skipping them on international sources (Jobicy, Himalayas) saves one HTTP
    request per keyword per run and removes misleading 404 log lines.
    """
    kw = keyword.strip().lower()
    if kw in _PT_ONLY_KEYWORDS:
        return False
    # Accented words are a strong PT signal for our keyword set.
    return kw == kw.encode("ascii", errors="ignore").decode()
