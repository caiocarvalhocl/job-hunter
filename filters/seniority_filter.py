"""Seniority detection and filtering.

The target range is estágio/trainee → júnior → pleno (mid). Anything that is
*only* senior or above gets excluded before spending an AI call on scoring.

Two levels of API:

  - detect_level(title) -> one of "estagio", "junior", "pleno", "senior",
    "unknown". Useful for storing/displaying the level and for future
    prioritisation.
  - is_senior_or_above(title) -> bool, the gate used by the pipeline.

Mixed-tier titles ("Desenvolvedor Pleno/Sênior", "Mid/Senior Engineer") are
treated as pleno-eligible and ALLOWED: the posting can be filled at pleno
level, and the AI fit score plus the recruiter decide the rest. This is a
deliberate change from the previous behaviour, which excluded them.

Detection is language-agnostic by pattern (PT + EN), running on raw titles.
"""
import re

_SENIOR_PATTERNS = [
    r"\bsenior\b",
    r"\bs[êe]nior\b",        # sênior / senior (PT accented/unaccented)
    r"\bsr\.?\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\bespecialista\b",     # PT "specialist" tier (usually above pleno)
    r"\bspecialist\b",
    r"\blead\b",
    r"\bl[íi]der\b",         # líder (PT)
    r"\bhead\s+of\b",
    r"\bdirector\b",
    r"\bdiretor(a)?\b",      # diretor/diretora (PT)
    r"\barquitet[oa]\b",     # arquiteto de software
    r"\barchitect\b",
]

_PLENO_PATTERNS = [
    r"\bpleno\b",
    r"\bpl\.?\b",
    r"\bmid[\s-]?level\b",
    r"\bmid\b",
    r"\bintermediate\b",
    r"\bn[íi]vel\s+2\b",
    r"\bii\b",               # "Developer II"
]

_JUNIOR_PATTERNS = [
    r"\bj[úu]nior\b",
    r"\bjr\.?\b",
    r"\bentry[\s-]?level\b",
    r"\biniciante\b",
    r"\bn[íi]vel\s+1\b",
]

_INTERN_PATTERNS = [
    r"\best[áa]gio\b",
    r"\best[áa]gi[áa]ri[oa]\b",
    r"\btrainee\b",
    r"\bintern(ship)?\b",
    r"\baprendiz\b",
]

_SENIOR_RE = re.compile("|".join(_SENIOR_PATTERNS), re.IGNORECASE)
_PLENO_RE = re.compile("|".join(_PLENO_PATTERNS), re.IGNORECASE)
_JUNIOR_RE = re.compile("|".join(_JUNIOR_PATTERNS), re.IGNORECASE)
_INTERN_RE = re.compile("|".join(_INTERN_PATTERNS), re.IGNORECASE)


def detect_level(title: str) -> str:
    """Classify a job title into a seniority level.

    Returns "estagio", "junior", "pleno", "senior" or "unknown". When a title
    mixes tiers, the LOWEST eligible tier wins (a "Pleno/Sênior" opening can
    be filled at pleno), except that intern/junior signals always dominate.
    """
    if not title:
        return "unknown"
    if _INTERN_RE.search(title):
        return "estagio"
    if _JUNIOR_RE.search(title):
        return "junior"
    if _PLENO_RE.search(title):
        return "pleno"
    if _SENIOR_RE.search(title):
        return "senior"
    return "unknown"


def is_above_target(title: str, accept_pleno: bool = False) -> bool:
    """True when the title is above the target range (blocked pre-scoring).

    Target range is estágio/trainee → júnior. Pleno is blocked by default,
    configurable via accept_pleno (ACCEPT_PLENO=true in .env).
    """
    level = detect_level(title)
    if level == "senior":
        return True
    if level == "pleno" and not accept_pleno:
        return True
    return False


def is_senior_or_above(title: str) -> bool:
    """True only when the title signals senior+ with no lower-tier signal.

    "unknown" titles (no explicit level, e.g. "Backend Developer") pass
    through, since many junior-friendly postings omit the level and the AI
    fit score handles them downstream.
    """
    return detect_level(title) == "senior"
