"""Single source of truth for the candidate profile.

Everything about the candidate lives in data/master_profile.yaml. This module
loads it once and exposes two views:

  - load_profile(): the raw dict, used by the tailored-CV generator.
  - candidate_profile_text(lang): a compact text block built from the YAML,
    handed to the scorer and the cover-letter generator.

Before this existed there were two hand-written profiles (one in ai_filter.py,
one in the YAML) that had already drifted apart. Now scoring, cover letter and
CV all read the same facts.
"""
from functools import lru_cache
from pathlib import Path

import yaml

PROFILE_PATH = Path(__file__).resolve().parent / "data" / "master_profile.yaml"


@lru_cache(maxsize=1)
def load_profile() -> dict:
    with open(PROFILE_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def candidate_profile_text(lang: str = "en", profile: dict | None = None) -> str:
    """Build the text profile used for scoring and cover letters from the YAML.

    Kept deliberately close to the old hard-coded block so prompts behave the
    same, but now derived from the single source so it can never drift again.
    """
    p = profile or load_profile()

    def line(label, value):
        return f"{label}: {value}" if value else ""

    skills_flat = ", ".join(s for group in p["skills"].values() for s in group)

    exp_lines = []
    for e in p["experience"]:
        role = e["role"][lang]
        org = e["org_note"][lang]
        head = f"- {role} at {e['company']}" + (f" ({org})" if org else "")
        exp_lines.append(head)
        for b in e["bullets"]:
            exp_lines.append(f"    {b[lang]}")

    proj_lines = []
    for pr in p["projects"]:
        proj_lines.append(f"- {pr['name']} ({', '.join(pr['stack'])})")
        for b in pr["bullets"]:
            proj_lines.append(f"    {b[lang]}")

    edu_lines = [f"- {ed['degree'][lang]}, {ed['school'][lang]} ({ed['period']})" for ed in p["education"]]
    cert_lines = [f"- {c[lang]}" for c in p["certifications"]]

    return "\n".join(filter(None, [
        line("Name", p["name"]),
        line("Location", p["contact"]["location"][lang]),
        "",
        "Summary:",
        p["summary"][lang],
        "",
        "Tech stack:",
        skills_flat,
        "",
        "Experience:",
        *exp_lines,
        "",
        "Projects:",
        *proj_lines,
        "",
        "Education:",
        *edu_lines,
        "",
        "Certifications:",
        *cert_lines,
        "",
        line("Languages", p["languages"][lang]),
    ]))
