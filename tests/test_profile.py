"""Tests do carregador de perfil.

Nada aqui fixa fatos de um perfil específico (nome, skill, empresa): as
asserções derivam do master_profile.yaml em uso, para a suíte continuar
verde em qualquer fork.
"""
from profile import load_profile, candidate_profile_text


def test_profile_loads():
    p = load_profile()
    assert p["name"]
    assert "skills" in p and "experience" in p


def test_candidate_text_contains_name_and_stack(a_real_skill):
    p = load_profile()
    text = candidate_profile_text("en", p)
    assert p["name"] in text
    assert a_real_skill in text


def test_candidate_text_language_switch():
    p = load_profile()
    en = candidate_profile_text("en", p)
    pt = candidate_profile_text("pt", p)
    assert en != pt
    # O resumo em pt não pode ser o texto em inglês.
    assert p["summary"]["pt"] in pt


def test_every_experience_company_appears():
    p = load_profile()
    text = candidate_profile_text("en", p)
    for e in p["experience"]:
        assert e["company"] in text
