"""Tests for the Brazilian general boards (Vagas.com.br, InfoJobs), source
selection, SEARCH_CITIES and the tolerance for minimal profiles.

The HTML fixtures below are trimmed copies of real Vagas.com.br and InfoJobs
markup (2026-09), keeping only the elements the parsers read.
"""
import pytest

import main
from filters.seniority_filter import detect_level
from config.settings import get_settings
from scrapers.jsonld import extract_job_posting, slugify, clean_text, is_telecommute
from scrapers import vagas_com_br, infojobs


# ── seleção de fontes ────────────────────────────────────────────────────────

def test_sources():
    names = {s.source_name for s in main.get_all_scrapers()}
    assert {"weworkremotely", "gupy", "programathor", "vagas.com.br", "infojobs"} <= names
    assert not {"arbeitnow", "remotive"} & names


# ── nível ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title", [
    "Coordenador Administrativo", "Gerente Financeiro", "Supervisora de Faturamento",
])
def test_management_titles_are_above_target(title):
    assert detect_level(title) == "senior"


def test_assistant_titles_pass_seniority():
    assert detect_level("Assistente Administrativo") == "unknown"


# ── helpers ──────────────────────────────────────────────────────────────────

def test_slugify():
    assert slugify("Auxiliar de Escritório") == "auxiliar-de-escritorio"
    assert slugify("Paraná") == "parana"


def test_extract_job_posting_skips_other_ld_blocks():
    html = """
    <script type="application/ld+json">{"@type": "WebSite", "name": "x"}</script>
    <script type="application/ld+json">not json</script>
    <script type="application/ld+json">{"@type": "JobPosting", "title": "T",
      "description": "<p>Rotinas <b>administrativas</b></p>",
      "jobLocationType": "TELECOMMUTE"}</script>"""
    posting = extract_job_posting(html)
    assert posting["title"] == "T"
    assert clean_text(posting["description"]) == "Rotinas administrativas"
    assert is_telecommute(posting)
    assert extract_job_posting("<html></html>") is None


# ── Vagas.com.br ─────────────────────────────────────────────────────────────

VAGAS_HTML = """
<ul>
<li class="vaga odd">
  <h2 class="cargo"><a class="link-detalhes-vaga" data-id-vaga="2828826"
     href="/vagas/v2828826/assistente-administrativo" title="Assistente Administrativo">
     <mark>Assistente</mark> Administrativo</a></h2>
  <span class="emprVaga">  Universidade Veiga de Almeida </span>
  <div class="nivelQtdVagas"><span class="nivelVaga"> Auxiliar/Operacional </span></div>
  <div class="detalhes"><p>Descrição: Apoiar rotinas administrativas...</p></div>
  <footer><div class="vaga-local"><i class="bx bx-map"></i> Pato Branco / PR
    <div class="tooltip-place" role="tooltip">A empresa aceita candidaturas de Pato Branco</div>
  </div></footer>
</li>
<li class="vaga even">
  <h2 class="cargo"><a class="link-detalhes-vaga" data-id-vaga="2"
     href="/vagas/v2/assistente-financeiro" title="Assistente Financeiro">x</a></h2>
  <div class="detalhes"><p>Descrição: Contas a pagar.</p></div>
  <footer><div class="vaga-local"> Localização não informada </div></footer>
</li>
<li class="vaga"><h2 class="cargo">sem link</h2></li>
</ul>"""


def test_vagas_listing_parsing():
    jobs = vagas_com_br.parse_listing(VAGAS_HTML)
    assert len(jobs) == 2
    first, second = jobs
    assert first.url == "https://www.vagas.com.br/vagas/v2828826/assistente-administrativo"
    assert first.title == "Assistente Administrativo"
    assert first.company == "Universidade Veiga de Almeida"
    assert first.location == "Pato Branco / PR"      # tooltip text removed
    assert first.external_id == "2828826"
    assert first.description.startswith("Nível: Auxiliar/Operacional. Apoiar")
    assert first.is_remote is False
    assert second.location == ""


def test_vagas_remote_pass_marks_jobs_remote():
    jobs = vagas_com_br.parse_listing(VAGAS_HTML, remote_pass=True)
    assert all(j.is_remote for j in jobs)
    assert jobs[1].location == "Remoto"


# ── InfoJobs ─────────────────────────────────────────────────────────────────

def _ij_card(job_id, title, location, modality, href=True):
    attr = f'data-href="/vaga-de-x__{job_id}.aspx"' if href else ""
    return f"""
    <div class="pt-24 px-24 js_rowCard js_cardLink" id="vacancy{job_id}" data-id="{job_id}" {attr}>
      <div class="d-flex gap-8"><a href="/vaga"><h2 class="h3 js_vacancyTitle"> {title} </h2></a>
        <div class="text-medium small">Hoje</div></div>
      <div class="d-flex align-items-baseline"><div class="text-body">
        <a class="text-body" href="https://www.infojobs.com.br/empresa-x">EMPRESA X <span>S.A.</span></a>
      </div></div>
      <div class="mb-8"> {location} <span class="js_divUserVagaDistance" hidden=""> , 0 Km de você.</span></div>
      <div class="d-inline-flex flex-wrap mb-8 text-medium"><div>R$ 2.500,00</div><div>{modality}</div></div>
      <div class="text-medium"> Rotinas administrativas e financeiras... </div>
    </div>"""


INFOJOBS_HTML = (
    _ij_card("1", "Assistente Administrativo", "Pato Branco - PR", "Presencial")
    + _ij_card("1", "Assistente Administrativo", "Pato Branco - PR", "Presencial")  # duplicata mobile
    + _ij_card("2", "Auxiliar de Escritório", "Curitiba - PR", "Home office")
    + _ij_card("3", "Assistente de Compras", "Londrina - PR", "Híbrido")
    + _ij_card("4", "Sem href", "Curitiba - PR", "Presencial", href=False)
)


def test_infojobs_listing_parsing():
    jobs = infojobs.parse_listing(INFOJOBS_HTML)
    assert [j.external_id for j in jobs] == ["1", "2", "3"]
    first = jobs[0]
    assert first.url == "https://www.infojobs.com.br/vaga-de-x__1.aspx"
    assert first.title == "Assistente Administrativo"
    assert first.company == "EMPRESA X S.A."
    assert first.location == "Pato Branco - PR"
    assert "Presencial" in first.description and "Rotinas administrativas" in first.description
    assert [j.is_remote for j in jobs] == [False, True, False]   # híbrido não é remoto


@pytest.mark.asyncio
async def test_enrich_fetches_regional_jobs_first_and_skips_the_rest(monkeypatch):
    from scrapers import jsonld
    from filters import location_filter
    monkeypatch.setattr(get_settings(), "local_region_cities", "Pato Branco")
    location_filter._region_regex.cache_clear()
    monkeypatch.setattr(jsonld.asyncio, "sleep", lambda s: _noop())
    monkeypatch.setattr(jsonld, "MAX_DETAIL_FETCHES", 1)
    fetched = []

    async def fake_fetch(session, url):
        fetched.append(url)
        return ('<script type="application/ld+json">{"@type": "JobPosting",'
                '"description": "<p>Descrição completa</p>"}</script>')

    # Ordem da listagem: remoto antes do regional. Com orçamento de 1 detalhe,
    # o regional (mais raro) tem prioridade; Londrina presencial nunca é buscada.
    regional, remote, other = infojobs.parse_listing(INFOJOBS_HTML)
    try:
        await jsonld.enrich_descriptions(None, [remote, other, regional], print, fetch=fake_fetch)
    finally:
        location_filter._region_regex.cache_clear()

    assert fetched == [regional.url]
    assert regional.description == "Descrição completa"
    assert remote.description != "Descrição completa"


async def _noop():
    return None


# ── perfil mínimo: sem projetos/GitHub/certificações ────────────────────────

MINIMAL_PROFILE = {
    "name": "Candidato",
    "role_tag": {"pt": "Assistente Administrativo", "en": "Administrative Assistant"},
    "contact": {"location": {"pt": "Pato Branco, PR", "en": "Pato Branco, PR"},
                "phone": "+55 46 0000-0000", "email": "a@b.com"},
    "headings": {k: {"pt": k.upper(), "en": k.upper()} for k in
                 ["summary", "skills", "experience", "projects", "education",
                  "certifications", "languages"]},
    "summary": {"pt": "Rotinas administrativas.", "en": "Admin routines."},
    "skills": {"Ferramentas": ["Excel", "ERP"]},
    "skill_group_labels": {"Ferramentas": {"pt": "Ferramentas", "en": "Tools"}},
    "experience": [{
        "id": "e1", "company": "Empresa", "role": {"pt": "Auxiliar", "en": "Assistant"},
        "period": {"pt": "2024 - atual", "en": "2024 - present"},
        "location": {"pt": "Pato Branco", "en": "Pato Branco"},
        "org_note": {"pt": "", "en": ""},
        "bullets": [{"id": "e1-b1", "pt": "Contas a pagar.", "en": "Accounts payable."}],
    }],
    "education": [{"degree": {"pt": "Administração", "en": "Business"},
                   "school": {"pt": "UTFPR", "en": "UTFPR"}, "period": "2023 - 2027"}],
    "languages": {"pt": "Português (nativo)", "en": "Portuguese (native)"},
}


def test_profile_without_projects_or_certifications():
    from profile import candidate_profile_text
    text = candidate_profile_text("pt", MINIMAL_PROFILE)
    assert "Skills:\nExcel, ERP" in text
    assert "Projects:" not in text and "Certifications:" not in text


def test_cv_renders_without_projects_github_or_linkedin():
    from generators.tailored_cv import _validate_and_resolve
    from documents.renderer import cv_to_pdf
    cv = _validate_and_resolve({}, MINIMAL_PROFILE, "pt")
    assert cv["projects"] == [] and cv["certifications"] == []
    assert cv["contact"]["github"] == "" and cv["contact"]["linkedin"] == ""
    assert cv_to_pdf(cv).getvalue().startswith(b"%PDF")


# ── SEARCH_CITIES ────────────────────────────────────────────────────────────

def test_infojobs_regional_paths_per_city_or_state():
    assert infojobs.regional_paths("assistente+administrativo", "Paraná",
                                   ["Pato Branco", "Francisco Beltrão"]) == [
        ("/vagas-de-emprego-assistente+administrativo-em-pato-branco,-pr.aspx", "Pato Branco"),
        ("/vagas-de-emprego-assistente+administrativo-em-francisco-beltrao,-pr.aspx", "Francisco Beltrão"),
    ]
    assert infojobs.regional_paths("x", "Paraná", []) == [
        ("/vagas-de-emprego-x-em-parana.aspx", "Paraná")]


@pytest.mark.asyncio
async def test_gupy_queries_each_configured_city(monkeypatch):
    from scrapers import gupy
    monkeypatch.setattr(get_settings(), "search_cities", "Pato Branco, Francisco Beltrão")
    monkeypatch.setattr(get_settings(), "allow_onsite_in_region", True)
    calls = []

    async def fake_search(self, keyword, workplace_types=None, state=None, city=None):
        calls.append((workplace_types, city))
        return []

    monkeypatch.setattr(gupy.GupyScraper, "_search_api", fake_search)
    monkeypatch.setattr(gupy.asyncio, "sleep", lambda s: _noop())
    await gupy.GupyScraper(keywords=["Auxiliar"]).scrape()
    assert calls == [("remote", None), (None, "Pato Branco"), (None, "Francisco Beltrão")]
