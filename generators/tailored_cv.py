"""Generate a job-tailored CV from the master profile.

Design principle: the LLM never writes the CV. It only returns a *plan* that
selects and orders content that already exists in data/master_profile.yaml, plus
a rewritten summary. Bullets are pulled verbatim from the profile, so the model
cannot invent experience. Skills, bullet ids and project ids are validated
against the profile and anything unknown is dropped before rendering.
"""
import json

from scrapers.base import RawJob
from profile import load_profile
from utils import detect_language
from llm import chat


def _canonical_skill_map(profile: dict) -> dict:
    """lowercased skill -> canonical spelling, across all groups."""
    out = {}
    for items in profile["skills"].values():
        for s in items:
            out[s.lower()] = s
    return out


def _selectable_view(profile: dict, lang: str) -> dict:
    """Compact view handed to the LLM: only ids, skills and bullet texts it may pick from."""
    return {
        "all_skills": [s for group in profile["skills"].values() for s in group],
        "experience": [
            {
                "company": e["company"],
                "bullets": [{"id": b["id"], "text": b[lang]} for b in e["bullets"]],
            }
            for e in profile["experience"]
        ],
        "projects": [
            {"id": p["id"], "name": p["name"], "bullets": [{"id": b["id"], "text": b[lang]} for b in p["bullets"]]}
            for p in profile["projects"]
        ],
    }


def _build_prompt(profile: dict, job: RawJob, lang: str) -> str:
    view = _selectable_view(profile, lang)
    lang_name = "Brazilian Portuguese" if lang == "pt" else "English"
    desc = (job.description or "No description available.")[:3000]
    return f"""You tailor an existing CV to a specific job. You must NOT invent anything.
You may only select and reorder content that is provided below, and rewrite the
summary. Never introduce a skill, technology, company, tool, metric or
responsibility that is not present in the provided data.

## AVAILABLE CONTENT (the only things you may use)
{json.dumps(view, ensure_ascii=False, indent=2)}

## CURRENT SUMMARY (rewrite this, same facts, mirror the job's language and priorities)
{profile['summary'][lang]}

## CURRENT ROLE TAG (short title shown under the name, e.g. "Backend Developer")
{profile.get('role_tag', {}).get(lang, '')}

## JOB POSTING
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description:
{desc}

## YOUR TASK
Return ONLY a JSON object (no markdown fences, no commentary) written in {lang_name}:
{{
  "summary": "<rewritten summary, 2-3 concise sentences (no filler, no repeated info), {lang_name}, ONLY facts already present above>",
  "role_tag": "<short role title (2-5 words), {lang_name}, e.g. 'Backend Developer' or 'Full Stack Developer' — pick whichever framing fits this job best, but it must be honestly supported by the skills/experience above>",
  "skill_order": ["<skills copied EXACTLY from all_skills, most relevant first, drop the least relevant>"],
  "experience": [
    {{"company": "<exact company name>", "bullet_ids": ["<ids to keep, most relevant first>"]}}
  ],
  "project_ids": ["<project ids to keep, most relevant first>"]
}}

Rules:
- Copy skills and ids verbatim from the data above. Do not create new ones.
- Keep every real job in experience (do not drop a whole company), but you may
  drop or reorder individual bullets.
- If unsure whether a skill is relevant, keep it rather than invent a new one.
- Never mention "PowerBuilder" anywhere in the summary, even if related facts
  appear in the source data.
- The role tag is a framing choice, not a new fact: don't call yourself
  something the skills/experience above don't support (e.g. no "Data
  Scientist" without ML experience in the data).
- The CV must fit on a single page: keep the summary short and prefer fewer,
  higher-impact bullets over including everything.
"""


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    return json.loads(raw.strip())


def _validate_and_resolve(plan: dict, profile: dict, lang: str) -> dict:
    """Turn the LLM plan into a render dict, dropping anything not in the profile."""
    skill_map = _canonical_skill_map(profile)

    # Skills: keep only known ones, in the requested order, then group them back.
    ordered_known = []
    seen = set()
    for s in plan.get("skill_order", []):
        canon = skill_map.get(str(s).lower())
        if canon and canon not in seen:
            ordered_known.append(canon)
            seen.add(canon)
        elif not canon:
            print(f"[CV] dropped unknown skill from LLM output: {s!r}")
    # Any known skill the LLM forgot: append so nothing real is silently lost.
    for canon in skill_map.values():
        if canon not in seen:
            ordered_known.append(canon)
            seen.add(canon)

    grouped = []
    for group, items in profile["skills"].items():
        label = profile["skill_group_labels"][group][lang]
        chosen = [s for s in ordered_known if s in items]
        if chosen:
            best_rank = min(ordered_known.index(s) for s in chosen)
            grouped.append((best_rank, label, chosen))
    grouped.sort(key=lambda t: t[0])
    grouped = [(label, chosen) for _, label, chosen in grouped]

    # Experience: resolve bullet ids -> verbatim text, keep every company.
    exp_plan = {e["company"]: e.get("bullet_ids", []) for e in plan.get("experience", [])}
    experience = []
    for e in profile["experience"]:
        bullets_by_id = {b["id"]: b[lang] for b in e["bullets"]}
        wanted = [bid for bid in exp_plan.get(e["company"], []) if bid in bullets_by_id]
        if not wanted:  # fallback: keep all real bullets rather than an empty job
            wanted = list(bullets_by_id.keys())
        org = e["org_note"][lang]
        header = f"{e['role'][lang]} | {e['company']}" + (f" - {org}" if org else "")
        meta = " | ".join(x for x in [e["period"][lang], e["location"][lang]] if x)
        experience.append({"header": header, "meta": meta, "bullets": [bullets_by_id[i] for i in wanted]})

    # Extracurricular experience, shown in its own section, separate from
    # Work History. Not subject to LLM tailoring — same as education/
    # certifications, it's always shown in full.
    extracurricular_experience = []
    for e in profile.get("extracurricular_experience", []):
        org = e["org_note"][lang]
        header = f"{e['role'][lang]} | {e['company']}" + (f" - {org}" if org else "")
        meta = " | ".join(x for x in [e["period"][lang], e["location"][lang]] if x)
        extracurricular_experience.append({
            "header": header, "meta": meta,
            "bullets": [b[lang] for b in e["bullets"]],
        })

    # Projects
    valid_project_ids = {p["id"]: p for p in profile["projects"]}
    chosen_pids = [pid for pid in plan.get("project_ids", []) if pid in valid_project_ids]
    if not chosen_pids:
        chosen_pids = list(valid_project_ids.keys())
    projects = []
    for pid in chosen_pids:
        p = valid_project_ids[pid]
        projects.append({
            "header": f"{p['name']} | {', '.join(p['stack'])}",
            "bullets": [b[lang] for b in p["bullets"]],
        })

    c = profile["contact"]
    contact = {
        "location": c["location"][lang],
        "phone": c["phone"],
        "email": c["email"],
        "linkedin": c["linkedin"],
        "github": c["github"],
        "website": c.get("website") or "",
    }

    return {
        "name": profile["name"],
        "role_tag": plan.get("role_tag") or profile.get("role_tag", {}).get(lang, ""),
        "contact": contact,
        "headings": {k: v[lang] for k, v in profile["headings"].items()},
        "summary": plan.get("summary") or profile["summary"][lang],
        "skills": grouped,
        "experience": experience,
        "projects": projects,
        "education": [
            (f"{ed['degree'][lang]}", f"{ed['school'][lang]} | {ed['period']}")
            for ed in profile["education"]
        ],
        "extracurricular_experience": extracurricular_experience,
        "certifications": [cert[lang] for cert in profile["certifications"]],
        "languages_label": profile["headings"]["languages"][lang],
        "languages": profile["languages"][lang],
        "_language": lang,
    }


async def tailor_cv(job: RawJob, profile: dict | None = None,
                    lang: str | None = None) -> dict:
    """Return a resolved, render-ready CV dict for this job (safe to json.dumps).

    lang: force 'pt' or 'en'; None auto-detects from the posting text.
    """
    profile = profile or load_profile()
    lang = lang or detect_language(job)
    try:
        raw = await chat(_build_prompt(profile, job, lang), max_tokens=900,
                         temperature=0.2, context="CV")
        plan = _parse_json(raw)
    except Exception as e:
        print(f"[CV] tailoring failed ({e}); falling back to base profile")
        plan = {}
    return _validate_and_resolve(plan, profile, lang)
