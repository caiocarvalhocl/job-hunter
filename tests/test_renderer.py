from io import BytesIO

from pypdf import PdfReader

from documents.renderer import text_to_pdf, cv_to_pdf
from generators.tailored_cv import _validate_and_resolve
from profile import load_profile


def _read(buf: BytesIO) -> str:
    buf.seek(0)
    reader = PdfReader(buf)
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_text_to_pdf_produces_valid_doc():
    buf = text_to_pdf("Cover Letter", "Hello world.\n\nSecond paragraph.")
    text = _read(buf)
    assert "Hello world." in text
    assert "Second paragraph." in text


def test_cv_to_pdf_renders_name_and_sections(a_real_skill):
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_pdf(cv)
    text = _read(buf)
    assert profile["name"] in text
    # Cabeçalho e skill vêm do próprio perfil: fixar o texto literal do
    # heading ou "Java" quebraria em qualquer fork com perfil diferente.
    assert profile["headings"]["experience"]["en"] in text
    assert a_real_skill in text


def test_cv_pdf_has_filename():
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_pdf(cv, filename="cv_test.pdf")
    assert buf.name == "cv_test.pdf"


def test_cv_pdf_section_order_is_summary_experience_education():
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_pdf(cv)
    text = _read(buf)
    h = profile["headings"]
    summary_pos = text.find(h["summary"]["en"])
    exp_pos = text.find(h["experience"]["en"])
    edu_pos = text.find(h["education"]["en"])
    skills_pos = text.find(h["skills"]["en"])
    assert -1 not in (summary_pos, exp_pos, edu_pos, skills_pos)
    assert summary_pos < exp_pos < edu_pos < skills_pos


def test_cv_pdf_shows_role_tag_under_name():
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_pdf(cv)
    text = _read(buf)
    assert profile["role_tag"]["en"].upper() in text
    assert text.find(profile["name"]) < text.find(profile["role_tag"]["en"].upper())


def test_cv_pdf_shows_extracurricular_experience_after_education(a_real_extracurricular_experience):
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_pdf(cv)
    text = _read(buf)
    h = profile["headings"]
    edu_pos = text.find(h["education"]["en"])
    extra_heading_pos = text.find(h["extracurricular"]["en"])
    skills_pos = text.find(h["skills"]["en"])
    company_pos = text.find(a_real_extracurricular_experience["company"])
    assert -1 not in (edu_pos, extra_heading_pos, skills_pos, company_pos)
    assert edu_pos < extra_heading_pos < company_pos < skills_pos


def test_cv_pdf_fits_on_a_single_page():
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_pdf(cv)
    buf.seek(0)
    assert len(PdfReader(buf).pages) == 1
