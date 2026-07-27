"""Brazil-eligibility filter for remote postings.

Global boards (RemoteOK, Remotive, WWR, Jobicy, Arbeitnow) list many "remote"
roles restricted to a country/region the candidate cannot legally work from
(US-only, EU-only, etc.). Scoring those wastes an LLM call and produces
notifications for jobs that can never be applied to.

Strategy: cheap regex pass over location + description.

  - Explicit DENY patterns ("USA only", "must be located in the US",
    "EU timezones only", ...) exclude the job outright.
  - Everything else passes. Ambiguity is resolved in favour of keeping the
    job, because a false exclusion is worse than one wasted LLM call; the fit
    scorer also receives the location and weighs eligibility.
"""
import re
import unicodedata
from functools import lru_cache

from scrapers.base import RawJob

_DENY_PATTERNS = [
    # Country/region-restricted remote
    r"\busa?\s+only\b",
    r"\bu\.s\.?a?\.?\s+only\b",
    r"\bunited\s+states\s+only\b",
    r"\bus[\s-]+based\s+(only|candidates|applicants)\b",
    r"\bmust\s+(be\s+)?(located|based|reside)\s+in\s+the\s+(us|usa|u\.s\.|united\s+states)\b",
    r"\bus\s+citizens?(hip)?\s+(only|required)\b",
    r"\bauthorized\s+to\s+work\s+in\s+the\s+(us|usa|united\s+states)\b",
    r"\bgreen\s+card\b",
    r"\bcanada\s+only\b",
    r"\buk\s+only\b",
    r"\beurope(an)?\s+(union\s+)?only\b",
    r"\beu\s+only\b",
    r"\bemea\s+only\b",
    r"\bapac\s+only\b",
    r"\bmust\s+(be\s+)?(located|based|reside)\s+in\s+(europe|the\s+eu|the\s+uk|canada|australia)\b",
    r"\b(us|usa|eu|european|uk|canadian)\s+work\s+(permit|authorization|visa)\b",
    # Remotive-style "candidate_required_location" values
    r"^\s*(usa|united\s+states|canada|uk|united\s+kingdom|germany|france|spain|portugal|poland|netherlands|australia|india)\s*$",
]

_DENY_RE = re.compile("|".join(_DENY_PATTERNS), re.IGNORECASE)

# Positive signals; used only to short-circuit past a deny hit in the
# description when the location field itself is welcoming (e.g. location says
# "LATAM" but the description mentions "our US only benefits" boilerplate).
_ALLOW_LOCATION_RE = re.compile(
    r"\b(worldwide|anywhere|global|latam|latin\s+america|south\s+america"
    r"|americas|brazil|brasil|international)\b",
    re.IGNORECASE,
)


def is_brazil_eligible(job: RawJob) -> bool:
    """True if nothing indicates the posting excludes Brazil-based candidates."""
    location = (job.location or "").strip()

    if location and _DENY_RE.search(location):
        return False

    if location and _ALLOW_LOCATION_RE.search(location):
        return True

    # No conclusive location field: check description for hard restrictions.
    description = (job.description or "")[:4000]
    if description and _DENY_RE.search(description):
        return False

    return True


# ── Southwest-Paraná region check (onsite/hybrid acceptance) ─────────────────

@lru_cache(maxsize=1)
def _region_regex() -> re.Pattern:
    """One word-boundary regex over the configured city list.

    Accents are made optional (Ampére also matches Ampere) because job boards
    are inconsistent about them.
    """
    from config.settings import get_settings

    def _accent_insensitive(city: str) -> str:
        table = {
            "a": "[aáàâã]", "e": "[eéê]", "i": "[ií]",
            "o": "[oóôõ]", "u": "[uú]", "c": "[cç]",
        }
        out = []
        for ch in _strip_accents(city.lower()):
            out.append(table.get(ch, re.escape(ch)))
        return "".join(out)

    parts = [rf"\b{_accent_insensitive(c)}\b" for c in get_settings().local_cities_list]
    if not parts:
        return re.compile(r"(?!x)x")  # matches nothing
    return re.compile("|".join(parts), re.IGNORECASE)


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def is_local_region(location: str) -> bool:
    """True when the location names a city in the configured local region.

    Matches both the accented and unaccented spellings ("São João" and
    "Sao Joao"), since boards normalise inconsistently.
    """
    if not location:
        return False
    regex = _region_regex()
    return bool(regex.search(location) or regex.search(_strip_accents(location)))

# ── Affirmative-action PCD postings (reserved for disabled candidates) ──────

_PCD_PATTERNS = [
    r"\bvaga\s+afirmativa\s+(?:para\s+)?pcd\b",
    r"\bafirmativa\s+(?:para\s+)?pcd\b",
    r"\bexclusiv[ao]\s+(?:para\s+)?pcd\b",
    r"\bpcd\b.{0,20}\bexclusiv",
    r"\bvaga\s+(?:afirmativa\s+)?(?:para\s+)?pessoas?\s+com\s+defici[êe]ncia\b",
    r"\breservad[ao]\s+(?:para\s+)?(?:pessoas?\s+com\s+defici[êe]ncia|pcd)\b",
]
_PCD_RE = re.compile("|".join(_PCD_PATTERNS), re.IGNORECASE)


def is_pcd_reserved(title: str, description: str = "") -> bool:
    """True when a posting is an affirmative-action opening reserved for PCD
    (pessoa com deficiência) candidates.

    Requires explicit "vaga afirmativa / reservada / exclusiva" framing so
    that generic diversity boilerplate ("encorajamos candidaturas de pessoas
    com deficiência") does not produce false positives.
    """
    text = f"{title} {description[:500]}"
    return bool(_PCD_RE.search(text))
