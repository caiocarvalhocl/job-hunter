"""Score how well a job fits the candidate, using the LLM.

The candidate profile is built from data/master_profile.yaml via
profile.candidate_profile_text, so scoring, cover letter and CV all describe
the same person.

Failure semantics matter here: jobs are deduplicated by URL and persisted
forever, so a transient API error (rate limit, timeout) must NOT translate
into score 0 + status "ignored", or a good job gets buried permanently. On
unrecoverable errors this module returns None and the pipeline skips the job
without persisting it, so the next scheduled run retries it.
"""
import json
from typing import Optional, Tuple

from scrapers.base import RawJob
from profile import candidate_profile_text
from utils import detect_language
from llm import chat, LLMUnavailable

_MAX_PARSE_RETRIES = 2


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    return raw.strip()


def _build_prompt(job: RawJob, profile_text: str) -> str:
    description = job.description[:3000] if job.description else "No description available."
    return f"""You are a career advisor. Analyze how well this job fits the candidate profile.

## CANDIDATE PROFILE
{profile_text}

## CANDIDATE CONSTRAINTS (hard requirements — factor into the score)
- Based in Brazil; can only take remote roles open to Brazil-based candidates
  (worldwide, LATAM, Americas or Brazil). If the posting restricts hiring to
  another country/region (US-only, EU-only, etc.), score it 0-20.
- Target level: internship (estágio), trainee, junior or mid-level (pleno).
  Roles requiring senior-level ownership should score low.
- Two acceptable tracks: (1) Backend/Fullstack development (Java, Spring Boot,
  Angular, TypeScript); (2) QA Automation / SDET / Test Automation, leveraging
  Java and tools like Selenium, Playwright, REST Assured. Score QA Automation
  roles on their own merits, not as a downgrade from development.

## JOB POSTING
Title: {job.title}
Company: {job.company}
Location: {job.location}
Remote: {job.is_remote}
Description:
{description}

## TASK
Return ONLY a JSON object (no markdown, no explanation) with:
{{
  "score": <integer 0-100>,
  "summary": "<2-3 sentence explanation of why this job fits or doesn't fit>",
  "highlights": ["<skill/requirement that matches>", ...],
  "gaps": ["<skill/requirement candidate lacks>", ...]
}}

Score guide:
- 80-100: Excellent fit, apply immediately
- 60-79: Good fit, worth applying
- 40-59: Partial fit, only if low on options
- 0-39: Poor fit, skip
"""


async def score_job_fit(job: RawJob) -> Optional[Tuple[float, str]]:
    """Return (score, summary), or None when scoring could not be completed.

    None means "transient failure, retry on a future run" — the caller must
    not persist the job as ignored in that case. Provider selection (Groq
    with Claude Haiku fallback on rate limits) lives in llm.chat.
    """
    lang = detect_language(job)
    prompt = _build_prompt(job, candidate_profile_text(lang))

    for attempt in range(1, _MAX_PARSE_RETRIES + 1):
        try:
            raw = await chat(prompt, max_tokens=512, temperature=0.2, context="FILTER")
        except LLMUnavailable as e:
            print(f"[FILTER] No LLM available for '{job.title}': {e}")
            return None
        try:
            data = json.loads(_strip_fences(raw))
            return float(data.get("score", 0)), data.get("summary", "")
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[FILTER] Malformed response scoring '{job.title}' "
                  f"(attempt {attempt}/{_MAX_PARSE_RETRIES}): {e}")

    return None
