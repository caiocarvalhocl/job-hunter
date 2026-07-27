"""Classify a posting into a career track and decide if its location is allowed.

The candidate's policy:
  - dev (backend/fullstack): apply anywhere — Brazil or abroad.
  - qa (test automation / QA): only abroad (fora do Brasil).
  - support (technical support / help desk): only abroad.

"Abroad" is decided from the posting's location/description signals. Because
a Brazilian posting is the case we must reliably exclude for qa/support, the
Brazil test is deliberately broad (PT-language board, Brazilian cities/states,
"Brasil"/"Brazil", LATAM-restricted-to-Brazil phrasing). When a qa/support
posting is genuinely ambiguous about country, it is DROPPED, the opposite of
the dev-track bias, since the whole point is to avoid Brazilian qa/support.

Track detection runs on the title first (most reliable), then description.
A posting can match dev and qa keywords at once (e.g. "SDET" mentions coding);
dev wins, because a dev-track posting is always acceptable regardless of
country, so classifying it as dev never wrongly excludes it.
"""
import re
import unicodedata

from scrapers.base import RawJob
from config.settings import get_settings

# ── Track keyword sets ──────────────────────────────────────────────────────

_DEV_PATTERNS = [
    r"\bdesenvolvedor(a)?\b", r"\bdeveloper\b", r"\bengenheir[oa]\s+de\s+software\b",
    r"\bsoftware\s+engineer\b", r"\bprogramador(a)?\b", r"\bfullstack\b",
    r"\bfull[\s-]?stack\b", r"\bbackend\b", r"\bback[\s-]?end\b",
    r"\bfrontend\b", r"\bfront[\s-]?end\b", r"\bspring\s+boot\b",
    r"\bengenharia\s+de\s+software\b", r"\bdev\b",
]

_QA_PATTERNS = [
    r"\bqa\b", r"\bquality\s+assurance\b", r"\btest\s+automation\b",
    r"\bautomation\s+test", r"\bsdet\b", r"\banalista\s+de\s+testes\b",
    r"\btest(er|ing)\b", r"\bqualidade\s+de\s+software\b",
    r"\bengenheir[oa]\s+de\s+qualidade\b", r"\bquality\s+engineer\b",
]

_SUPPORT_PATTERNS = [
    r"\btechnical\s+support\b", r"\bsuporte\s+t[ée]cnico\b", r"\bhelp\s?desk\b",
    r"\bservice\s+desk\b", r"\bsupport\s+engineer\b", r"\bsupport\s+analyst\b",
    r"\banalista\s+de\s+suporte\b", r"\bsupport\s+specialist\b",
    r"\bcustomer\s+support\s+engineer\b",
]

_DEV_RE = re.compile("|".join(_DEV_PATTERNS), re.IGNORECASE)
_QA_RE = re.compile("|".join(_QA_PATTERNS), re.IGNORECASE)
_SUPPORT_RE = re.compile("|".join(_SUPPORT_PATTERNS), re.IGNORECASE)

# ── Brazil-location signals ─────────────────────────────────────────────────

_BR_BOARDS = {"gupy", "programathor", "catho", "infojobs"}

_BR_LOCATION_PATTERNS = [
    r"\bbrasil\b", r"\bbrazil\b",
    r"\b(pr|sp|rj|mg|rs|sc|ba|pe|ce|go|df|es|pa|am|mt|ms|pb|rn|al|se|pi|ro|to|ac|ap|rr|ma)\b",
    # common Brazilian cities that appear in remote-BR postings
    r"\bs[ãa]o\s+paulo\b", r"\bcuritiba\b", r"\brio\s+de\s+janeiro\b",
    r"\bbelo\s+horizonte\b", r"\bporto\s+alegre\b", r"\bflorian[óo]polis\b",
    r"\bcampinas\b", r"\bdois\s+vizinhos\b", r"\bpato\s+branco\b",
    r"\bfrancisco\s+beltr[ãa]o\b",
]
_BR_LOCATION_RE = re.compile("|".join(_BR_LOCATION_PATTERNS), re.IGNORECASE)


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def detect_track(job: RawJob) -> str:
    """Return 'dev', 'qa', 'support' or 'unknown'.

    dev takes precedence over qa/support on ties, because dev is allowed
    everywhere and so can never be wrongly excluded by this label.
    """
    title = job.title or ""
    if _DEV_RE.search(title):
        return "dev"
    if _QA_RE.search(title):
        return "qa"
    if _SUPPORT_RE.search(title):
        return "support"

    # Title inconclusive: fall back to description (first chunk only).
    text = (job.description or "")[:1500]
    if _DEV_RE.search(text):
        return "dev"
    if _QA_RE.search(text):
        return "qa"
    if _SUPPORT_RE.search(text):
        return "support"
    return "unknown"


def is_brazil_located(job: RawJob) -> bool:
    """True when the posting appears to be in/for Brazil.

    Used to EXCLUDE qa/support postings located in Brazil. Deliberately broad,
    since a missed Brazilian qa job is exactly what we're trying to avoid.
    """
    if (job.source or "").lower() in _BR_BOARDS:
        return True

    haystack = _strip_accents(f"{job.location or ''} {job.url or ''}").lower()
    if _BR_LOCATION_RE.search(haystack):
        return True

    # Description mentions Brazil-restricted hiring.
    desc = _strip_accents((job.description or "")[:1500]).lower()
    if re.search(r"\b(based\s+in\s+brazil|located\s+in\s+brazil|brazil\s+only|"
                 r"apenas\s+brasil|somente\s+brasil|residir\s+no\s+brasil)\b", desc):
        return True

    return False


def is_track_location_allowed(job: RawJob) -> tuple[bool, str]:
    """Apply the per-track geographic policy definida em settings.track_rules.

    Returns (allowed, reason). reason is "" when allowed, otherwise a short
    Portuguese explanation for logging/persistence.

    A regra por track (anywhere / abroad_only / domestic_only) vem de
    settings.track_rules_dict, não é mais fixa em código. 'unknown' sempre
    passa: melhor deixar uma vaga não classificada seguir para o scoring da
    IA do que descartar por engano uma vaga de dev.
    """
    track = detect_track(job)
    if track == "unknown":
        return True, ""

    rule = get_settings().track_rules_dict.get(track, "anywhere")

    if rule == "anywhere":
        return True, ""

    if rule == "abroad_only":
        if is_brazil_located(job):
            return False, f"Filtrado: {track} no Brasil (configurado para aceitar {track} só no exterior)"
        return True, ""

    if rule == "domestic_only":
        if not is_brazil_located(job):
            return False, f"Filtrado: {track} fora do Brasil (configurado para aceitar {track} só no Brasil)"
        return True, ""

    # Regra desconhecida no .env: não bloqueia, só avisa no log.
    return True, ""
