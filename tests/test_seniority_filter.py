import pytest
from filters.seniority_filter import is_senior_or_above, is_above_target, detect_level


@pytest.mark.parametrize("title", [
    "Senior Backend Developer",
    "Desenvolvedor Sênior Java",
    "Sr. Software Engineer",
    "Staff Engineer",
    "Principal Engineer",
    "Tech Lead",
    "Líder Técnico",
    "Head of Engineering",
    "Engineering Director",
    "Diretor de Tecnologia",
    "Arquiteto de Software",
    "Especialista Java",
])
def test_senior_titles_are_flagged(title):
    assert is_senior_or_above(title)


@pytest.mark.parametrize("title", [
    "Backend Developer",
    "Desenvolvedor Java Júnior",
    "Desenvolvedor Pleno",
    "Software Engineer",
    "Full Stack Developer",
    "QA Automation Engineer",
    "Estágio em Desenvolvimento",
])
def test_non_senior_titles_pass(title):
    assert not is_senior_or_above(title)


@pytest.mark.parametrize("title", [
    # Mixed-tier postings are pleno-eligible and must pass through.
    "Desenvolvedor Pleno/Sênior",
    "Mid/Senior Software Engineer",
    "Desenvolvedor Java Júnior/Pleno",
])
def test_mixed_tier_titles_are_allowed(title):
    assert not is_senior_or_above(title)


@pytest.mark.parametrize("title,expected", [
    ("Estágio em Desenvolvimento Backend", "estagio"),
    ("Trainee QA", "estagio"),
    ("Software Engineering Intern", "estagio"),
    ("Desenvolvedor Java Júnior", "junior"),
    ("Jr. Backend Developer", "junior"),
    ("Desenvolvedor Pleno", "pleno"),
    ("Mid-level QA Engineer", "pleno"),
    ("Desenvolvedor Pleno/Sênior", "pleno"),
    ("Senior Backend Developer", "senior"),
    ("Backend Developer", "unknown"),
    ("", "unknown"),
])
def test_detect_level(title, expected):
    assert detect_level(title) == expected


def test_empty_title_is_not_senior():
    assert not is_senior_or_above("")


def test_javascript_is_not_flagged_as_senior():
    # "Sr" boundary check: must not fire on unrelated substrings.
    assert not is_senior_or_above("JavaScript Developer")


# ── Target gate: estágio/júnior only (pleno blocked unless configured) ───

@pytest.mark.parametrize("title", [
    "Desenvolvedor Pleno",
    "Mid-level QA Engineer",
    "Desenvolvedor Pleno/Sênior",
    "Senior Backend Developer",
    "Tech Lead",
])
def test_above_target_blocks_pleno_and_senior(title):
    assert is_above_target(title)


@pytest.mark.parametrize("title", [
    "Desenvolvedor Java Júnior",
    "Estágio em Desenvolvimento",
    "Trainee QA",
    "Backend Developer",
    "Desenvolvedor Júnior/Pleno",
])
def test_target_range_passes(title):
    assert not is_above_target(title)


def test_accept_pleno_flag_readmits_pleno_only():
    assert not is_above_target("Desenvolvedor Pleno", accept_pleno=True)
    assert is_above_target("Senior Developer", accept_pleno=True)
