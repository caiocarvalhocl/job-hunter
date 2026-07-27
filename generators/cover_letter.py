"""Generate a tailored cover letter for a job, in the posting's language."""
from scrapers.base import RawJob
from profile import candidate_profile_text
from utils import detect_language
from llm import chat, LLMUnavailable


def _build_prompt(job: RawJob, lang: str) -> str:
    lang_instruction = (
        "Write in Brazilian Portuguese, professional but warm tone."
        if lang == "pt"
        else "Write in English, professional and confident tone."
    )
    description = job.description[:3000] if job.description else "No description available."
    return f"""You are an expert career coach writing a cover letter on behalf of a candidate.

## CANDIDATE PROFILE
{candidate_profile_text(lang)}

## JOB POSTING
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description:
{description}

## INSTRUCTIONS
{lang_instruction}

Write a cover letter that:
1. Opens with a strong hook (not "My name is..." or "I am writing to...")
2. Connects candidate's specific experience to the job requirements
3. Highlights 2-3 concrete achievements/projects
4. Shows genuine interest in the company/role
5. Closes with a clear call to action
6. Is between 250-350 words
7. Does NOT use clichés like "team player", "hard worker", "passionate"

Return ONLY the cover letter text, no subject line, no date, no address headers.
"""


async def generate_cover_letter(job: RawJob, language: str = "auto") -> str:
    lang = detect_language(job) if language == "auto" else language
    try:
        text = await chat(_build_prompt(job, lang), max_tokens=1024,
                          temperature=0.7, context="GENERATOR")
        return text.strip()
    except LLMUnavailable as e:
        print(f"[GENERATOR] No LLM available for cover letter: {e}")
        return "Could not generate cover letter."
    except Exception as e:
        print(f"[GENERATOR] Error generating cover letter: {e}")
        return "Could not generate cover letter."
