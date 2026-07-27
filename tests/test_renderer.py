from io import BytesIO
from docx import Document

from documents.renderer import text_to_docx, cv_to_docx
from generators.tailored_cv import _validate_and_resolve
from profile import load_profile


def _read(buf: BytesIO) -> str:
    buf.seek(0)
    doc = Document(buf)
    return "\n".join(p.text for p in doc.paragraphs)


def test_text_to_docx_produces_valid_doc():
    buf = text_to_docx("Cover Letter", "Hello world.\n\nSecond paragraph.")
    text = _read(buf)
    assert "Hello world." in text
    assert "Second paragraph." in text


def test_cv_to_docx_renders_name_and_sections(a_real_skill):
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_docx(cv)
    text = _read(buf)
    assert profile["name"] in text
    # Cabeçalho e skill vêm do próprio perfil: fixar "PROFESSIONAL SUMMARY"
    # ou "Java" quebraria em qualquer fork com perfil diferente.
    assert profile["headings"]["summary"]["en"] in text
    assert a_real_skill in text


def test_cv_docx_has_filename():
    profile = load_profile()
    cv = _validate_and_resolve({}, profile, "en")
    buf = cv_to_docx(cv, filename="cv_test.docx")
    assert buf.name == "cv_test.docx"
