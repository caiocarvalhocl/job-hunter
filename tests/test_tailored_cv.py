"""Tests for the CV tailoring resolver.

The critical invariant: the LLM plan can only *select and reorder* real
content. Anything not present in master_profile.yaml must be dropped, and no
real company may be silently removed.
"""
from profile import load_profile
from generators.tailored_cv import _validate_and_resolve, _canonical_skill_map


def test_unknown_skill_is_dropped(a_real_skill):
    profile = load_profile()
    plan = {"skill_order": [a_real_skill, "COBOL on Mainframe"], "experience": [], "project_ids": []}
    resolved = _validate_and_resolve(plan, profile, "en")
    all_skills = [s for _, items in resolved["skills"] for s in items]
    assert a_real_skill in all_skills
    assert "COBOL on Mainframe" not in all_skills


def test_real_skill_never_lost_even_if_llm_forgets_it(a_real_skill):
    profile = load_profile()
    plan = {"skill_order": [a_real_skill], "experience": [], "project_ids": []}
    resolved = _validate_and_resolve(plan, profile, "en")
    resolved_skills = {s for _, items in resolved["skills"] for s in items}
    known = set(_canonical_skill_map(profile).values())
    assert known.issubset(resolved_skills)


def test_every_company_is_kept(a_real_experience):
    profile = load_profile()
    # Plan tries to keep only one company; resolver must still emit all.
    # Empresa e bullet vêm do perfil em uso, não fixos, para funcionar em
    # qualquer fork.
    plan = {"skill_order": [], "experience": [{
        "company": a_real_experience["company"],
        "bullet_ids": [a_real_experience["bullets"][0]["id"]],
    }], "project_ids": []}
    resolved = _validate_and_resolve(plan, profile, "en")
    headers = " ".join(e["header"] for e in resolved["experience"])
    for e in profile["experience"]:
        assert e["company"] in headers


def test_empty_bullet_selection_falls_back_to_all():
    profile = load_profile()
    plan = {"skill_order": [], "experience": [], "project_ids": []}
    resolved = _validate_and_resolve(plan, profile, "en")
    for exp in resolved["experience"]:
        assert len(exp["bullets"]) >= 1


def test_invalid_project_id_falls_back_to_all():
    profile = load_profile()
    plan = {"skill_order": [], "experience": [], "project_ids": ["does_not_exist"]}
    resolved = _validate_and_resolve(plan, profile, "en")
    assert len(resolved["projects"]) == len(profile["projects"])


def test_summary_falls_back_when_missing():
    profile = load_profile()
    resolved = _validate_and_resolve({}, profile, "pt")
    assert resolved["summary"] == profile["summary"]["pt"]


def test_extracurricular_experience_kept_separate_from_work_history(a_real_extracurricular_experience):
    profile = load_profile()
    resolved = _validate_and_resolve({}, profile, "en")
    prof_headers = " ".join(e["header"] for e in resolved["experience"])
    assert a_real_extracurricular_experience["company"] not in prof_headers
    extra_headers = " ".join(e["header"] for e in resolved["extracurricular_experience"])
    assert a_real_extracurricular_experience["company"] in extra_headers


def test_role_tag_falls_back_to_profile_when_plan_omits_it():
    profile = load_profile()
    resolved = _validate_and_resolve({}, profile, "en")
    assert resolved["role_tag"] == profile["role_tag"]["en"]


def test_role_tag_uses_plan_value_when_provided():
    profile = load_profile()
    resolved = _validate_and_resolve({"role_tag": "Custom Title"}, profile, "en")
    assert resolved["role_tag"] == "Custom Title"
