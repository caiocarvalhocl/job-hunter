"""Render documents to PDF in memory (no disk writes).

Two entry points:
  - text_to_pdf: turns a block of text (a cover letter) into a PDF.
  - cv_to_pdf:   turns a *resolved* CV dict (see generators/tailored_cv.py)
                 into an ATS-friendly, single-column, single-page PDF.

Kept intentionally single-column with standard headings: ATS parsers choke on
tables, text boxes and multi-column layouts, so the CV avoids all of them.

The CV must fit on one page. Rendering starts at a comfortable size and, only
if the content overflows, steps down through tighter (but still readable)
font/spacing/margins and trims the least-relevant bullets, re-measuring the
real page count each time with pypdf until it fits (or the tightest step is
reached, whichever comes first).
"""
from io import BytesIO
from xml.sax.saxutils import escape, quoteattr

from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

_DARK = HexColor("#1a1a1a")

# Degrade steps for the CV, from most to least comfortable. Each step is
# tried in order; the first one that renders to a single page wins.
_CV_STEPS = [
    {"font": 9.8, "leading": 12.6, "margin": 15 * mm, "cap_bullets": None},
    {"font": 9.3, "leading": 11.8, "margin": 13 * mm, "cap_bullets": None},
    {"font": 8.8, "leading": 11.0, "margin": 11 * mm, "cap_bullets": 4},
    {"font": 8.5, "leading": 10.4, "margin": 9 * mm, "cap_bullets": 3},
]


def _esc(text: str) -> str:
    return escape(text or "")


def _url(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    return text if text.startswith("http") else f"https://{text}"


def _link(display: str, href: str) -> str:
    return f"<a href={quoteattr(href)}>{_esc(display)}</a>"


def _styles(font: float, leading: float) -> dict:
    return {
        "name": ParagraphStyle(
            "name", fontName="Helvetica-Bold", fontSize=17, leading=19,
            alignment=TA_CENTER, spaceAfter=1,
        ),
        "role_tag": ParagraphStyle(
            "role_tag", fontName="Helvetica-Bold", fontSize=font + 1.5,
            leading=leading + 1.5, alignment=TA_CENTER, textColor=_DARK,
            spaceAfter=3,
        ),
        "contact": ParagraphStyle(
            "contact", fontName="Helvetica", fontSize=8.7, leading=11,
            alignment=TA_CENTER, textColor=_DARK, spaceAfter=1,
        ),
        "heading": ParagraphStyle(
            "heading", fontName="Helvetica-Bold", fontSize=10.6, leading=13,
            textColor=_DARK, spaceBefore=7, spaceAfter=2,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=font, leading=leading,
            spaceAfter=2,
        ),
        "entry_header": ParagraphStyle(
            "entry_header", fontName="Helvetica-Bold", fontSize=font,
            leading=leading, spaceBefore=3, spaceAfter=0,
        ),
        "entry_meta": ParagraphStyle(
            "entry_meta", fontName="Helvetica-Oblique", fontSize=font - 0.5,
            leading=leading - 0.5, textColor=_DARK, spaceAfter=1,
        ),
        "bullet": ParagraphStyle(
            # Hanging indent built by hand (leftIndent + negative firstLineIndent)
            # rather than reportlab's bulletText: that path mis-encodes "•" as a
            # control character in this reportlab version, which both looks wrong
            # and breaks text extraction (ATS parsers read raw text, not glyphs).
            "bullet", fontName="Helvetica", fontSize=font, leading=leading,
            leftIndent=12, firstLineIndent=-12, spaceAfter=1,
        ),
    }


def _page_count(buf: BytesIO) -> int:
    buf.seek(0)
    count = len(PdfReader(buf).pages)
    buf.seek(0)
    return count


def _to_buffer(buf: BytesIO, filename: str) -> BytesIO:
    buf.seek(0)
    buf.name = filename
    return buf


def text_to_pdf(title: str, body: str, filename: str = "documento.pdf") -> BytesIO:
    """Cover-letter style document: a heading plus paragraphs."""
    s = _styles(font=10.5, leading=14.5)
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=22 * mm, rightMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )
    story = [Paragraph(_esc(title), _styles(font=13, leading=16)["heading"]), Spacer(1, 6)]
    for block in body.split("\n\n"):
        block = block.strip()
        if block:
            story.append(Paragraph(_esc(block), s["body"]))
            story.append(Spacer(1, 6))
    doc.build(story)
    return _to_buffer(buf, filename)


def _skills_story(cv: dict, s: dict) -> list:
    story = [Paragraph(cv["headings"]["skills"].upper(), s["heading"])]
    for label, items in cv["skills"]:
        text = f"<b>{_esc(label)}:</b> {_esc(', '.join(items))}"
        story.append(Paragraph(text, s["body"]))
    return story


def _experience_story(cv: dict, s: dict, cap_bullets: int | None) -> list:
    story = [Paragraph(cv["headings"]["experience"].upper(), s["heading"])]
    for exp in cv["experience"]:
        story.append(Paragraph(_esc(exp["header"]), s["entry_header"]))
        if exp.get("meta"):
            story.append(Paragraph(_esc(exp["meta"]), s["entry_meta"]))
        bullets = exp["bullets"][:cap_bullets] if cap_bullets else exp["bullets"]
        for b in bullets:
            story.append(Paragraph(f"- {_esc(b)}", s["bullet"]))
    return story


def _projects_story(cv: dict, s: dict, cap_bullets: int | None) -> list:
    story = [Paragraph(cv["headings"]["projects"].upper(), s["heading"])]
    for proj in cv["projects"]:
        story.append(Paragraph(_esc(proj["header"]), s["entry_header"]))
        bullets = proj["bullets"][:cap_bullets] if cap_bullets else proj["bullets"]
        for b in bullets:
            story.append(Paragraph(f"- {_esc(b)}", s["bullet"]))
    return story


def _education_story(cv: dict, s: dict) -> list:
    story = [Paragraph(cv["headings"]["education"].upper(), s["heading"])]
    for header, meta in cv["education"]:
        story.append(Paragraph(_esc(header), s["entry_header"]))
        if meta:
            story.append(Paragraph(_esc(meta), s["entry_meta"]))
    return story


def _extracurricular_story(cv: dict, s: dict, cap_bullets: int | None) -> list:
    story = [Paragraph(cv["headings"]["extracurricular"].upper(), s["heading"])]
    for exp in cv.get("extracurricular_experience", []):
        story.append(Paragraph(_esc(exp["header"]), s["entry_header"]))
        if exp.get("meta"):
            story.append(Paragraph(_esc(exp["meta"]), s["entry_meta"]))
        bullets = exp["bullets"][:cap_bullets] if cap_bullets else exp["bullets"]
        for b in bullets:
            story.append(Paragraph(f"- {_esc(b)}", s["bullet"]))
    return story


def _certifications_story(cv: dict, s: dict) -> list:
    story = [Paragraph(cv["headings"]["certifications"].upper(), s["heading"])]
    for cert in cv["certifications"]:
        story.append(Paragraph(f"- {_esc(cert)}", s["bullet"]))
    return story


def _contact_story(cv: dict, s: dict) -> list:
    c = cv["contact"]
    line1_parts = [_esc(c["location"]), _esc(c["phone"]),
                   _link(c["email"], f"mailto:{c['email']}")]
    line2_parts = [_link(c["linkedin"], _url(c["linkedin"]))]
    if c.get("github"):
        line2_parts.append(_link(c["github"], _url(c["github"])))
    if c.get("website"):
        line2_parts.append(_link(c["website"], _url(c["website"])))
    return [
        Paragraph(" | ".join(line1_parts), s["contact"]),
        Paragraph(" | ".join(line2_parts), s["contact"]),
    ]


def _build_cv_story(cv: dict, s: dict, cap_bullets: int | None) -> list:
    # Section order: Name, role tag, Contact, Summary, Work History,
    # Education, Extracurricular Experience, Skills, Projects,
    # Certifications, Languages.
    story = [
        Paragraph(_esc(cv["name"]), s["name"]),
    ]
    if cv.get("role_tag"):
        story.append(Paragraph(cv["role_tag"].upper(), s["role_tag"]))
    story += _contact_story(cv, s)

    if cv.get("summary"):
        story.append(Paragraph(cv["headings"]["summary"].upper(), s["heading"]))
        story.append(Paragraph(_esc(cv["summary"]), s["body"]))

    if cv.get("experience"):
        story += _experience_story(cv, s, cap_bullets)

    if cv.get("education"):
        story += _education_story(cv, s)

    if cv.get("extracurricular_experience"):
        story += _extracurricular_story(cv, s, cap_bullets)

    if cv.get("skills"):
        story += _skills_story(cv, s)

    if cv.get("projects"):
        story += _projects_story(cv, s, cap_bullets)

    if cv.get("certifications"):
        story += _certifications_story(cv, s)

    if cv.get("languages"):
        story.append(Paragraph(cv["languages_label"].upper(), s["heading"]))
        story.append(Paragraph(_esc(cv["languages"]), s["body"]))

    return story


def cv_to_pdf(cv: dict, filename: str = "cv.pdf") -> BytesIO:
    """Render a resolved CV dict to a single-page PDF. Expected keys:

    name, role_tag (str), contact (dict: location/phone/email/linkedin/github/website),
    headings (dict), summary (str),
    skills (list[(label, [items])]), experience (list of dicts with
    header/meta/bullets), projects (list of dicts with header/bullets),
    education (list of (header, meta)), certifications (list[str]),
    languages_label, languages.
    """
    best_buf = None
    for step in _CV_STEPS:
        s = _styles(step["font"], step["leading"])
        story = _build_cv_story(cv, s, step["cap_bullets"])

        buf = BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4,
            leftMargin=step["margin"], rightMargin=step["margin"],
            topMargin=step["margin"], bottomMargin=step["margin"],
        )
        doc.build(story)

        pages = _page_count(buf)
        if best_buf is None:
            best_buf = buf
        if pages <= 1:
            best_buf = buf
            break
        best_buf = buf  # keep the tightest attempt so far as the fallback

    return _to_buffer(best_buf, filename)
