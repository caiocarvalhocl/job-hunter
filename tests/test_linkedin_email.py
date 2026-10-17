"""Tests for the LinkedIn e-mail source. The fixture is the plain-text part of
a real recommendation e-mail (2026-09) with tracking parameters cut."""
import asyncio
from email.message import EmailMessage

import pytest

import main
from config.settings import get_settings
from scrapers import linkedin_email
from scrapers.linkedin_email import LinkedInEmailScraper, parse_job_email

EMAIL_TEXT = """Amplie sua pesquisa

Recomendações com base nas suas atividades.

Vagas de Remota
https://www.linkedin.com/comm/jobs/search-results/?keywords=Desenvolvedor+java+junior&geoId=106057199

Desenvolvedor Java Junior - Trabalho Remoto
BairesDev
Brasil
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4471940499/?trackingId=bke9w48r&refId=ppzu

---------------------------------------------------------

Analista Desenvolvedor Full Stack JR (Java | Cloud | Angular) - REMOTO
Foursys
Brasil
Candidate-se com currículo e perfil
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4468684460/?trackingId=4PoKpLWe&refId=ppzu

---------------------------------------------------------

Veja todas as vagas: https://www.linkedin.com/comm/jobs/search-results/?keywords=Desenvolvedor+java+junior

Vagas de Fim
https://www.linkedin.com/comm/jobs/search-results/?keywords=Desenvolvedor+java+junior&f_SAL=f_SA_id_230001

Junior Software Developer
Enghouse Systems
São Paulo
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4461985437/?trackingId=ZpOHWQq6&refId=JEkV

----------------------------------------

Este e-mail foi enviado a Caio Carvalho (Desenvolvedor Java & Spring Boot | Angular | Fullstack)
Gerenciar recomendações: https://www.linkedin.com/comm/jobs/alerts?lipi=urn
"""


def test_parse_job_email():
    jobs = parse_job_email(EMAIL_TEXT)
    assert [j.external_id for j in jobs] == ["4471940499", "4468684460", "4461985437"]
    first, second, third = jobs
    assert first.url == "https://www.linkedin.com/jobs/view/4471940499/"
    assert first.title == "Desenvolvedor Java Junior - Trabalho Remoto"
    assert first.company == "BairesDev"
    assert first.location == "Brasil"
    assert second.title.startswith("Analista Desenvolvedor Full Stack JR")
    assert second.company == "Foursys"            # extra line after location ignored
    assert [j.is_remote for j in jobs] == [True, True, False]
    assert third.location == "São Paulo"
    assert all(j.source == "linkedin" and j.description == "" for j in jobs)


def test_first_card_right_after_header():
    # Single-company e-mails (2026-09) start the first card under the header
    # text, with no search URL in between.
    jobs = parse_job_email(
        "Amplie sua pesquisa\n\nRecomendações com base nas suas atividades.\n\n"
        "SOFTWARE ENGINEER III MOBILE\nStone\nBrasil\n"
        "Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4460383295/?trackingId=x\n")
    assert [(j.title, j.company, j.location) for j in jobs] == [
        ("SOFTWARE ENGINEER III MOBILE", "Stone", "Brasil")]


def test_english_view_job_label():
    jobs = parse_job_email("Backend Engineer\nAcme\nBrazil\n"
                           "View job: https://www.linkedin.com/comm/jobs/view/123/?x=1\n")
    assert jobs[0].url == "https://www.linkedin.com/jobs/view/123/"
    assert jobs[0].is_remote is True


def _raw_email(text):
    msg = EmailMessage()
    msg["From"] = "jobs-noreply@linkedin.com"
    msg["Subject"] = "Vagas"
    msg.set_content(text)
    msg.add_alternative("<html><body>html</body></html>", subtype="html")
    return msg.as_bytes()


class _FakeIMAP:
    instances = []

    def __init__(self, host):
        self.calls = []
        _FakeIMAP.instances.append(self)

    def login(self, user, password):
        self.calls.append(("login", user))

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))

    def search(self, charset, *criteria):
        self.calls.append(("search",) + criteria)
        # Same message matched for both senders: must be read only once.
        return "OK", [b"7"]

    def fetch(self, msg_id, parts):
        self.calls.append(("fetch", msg_id, parts))
        return "OK", [(b"7 (BODY[] {1})", _raw_email(EMAIL_TEXT))]

    def logout(self):
        self.calls.append(("logout",))


@pytest.fixture
def imap(monkeypatch):
    _FakeIMAP.instances = []
    monkeypatch.setattr(linkedin_email.imaplib, "IMAP4_SSL", _FakeIMAP)
    monkeypatch.setattr(get_settings(), "imap_user", "me@gmail.com")
    monkeypatch.setattr(get_settings(), "imap_app_password", "app-pass")
    return _FakeIMAP


def test_scrape_reads_mailbox_read_only(imap):
    jobs = asyncio.run(LinkedInEmailScraper(keywords=[]).scrape())

    assert len(jobs) == 3
    calls = imap.instances[0].calls
    assert ("select", "INBOX", True) in calls
    fetches = [c for c in calls if c[0] == "fetch"]
    assert fetches == [("fetch", b"7", "(BODY.PEEK[])")]
    assert calls[-1] == ("logout",)


def test_scrape_without_credentials_does_nothing(imap, monkeypatch):
    monkeypatch.setattr(get_settings(), "imap_app_password", "")
    assert asyncio.run(LinkedInEmailScraper(keywords=[]).scrape()) == []
    assert imap.instances == []


def test_source_is_wired_only_when_enabled(monkeypatch):
    monkeypatch.setattr(get_settings(), "linkedin_email_enabled", False)
    assert "linkedin" not in {s.source_name for s in main.get_all_scrapers()}
    monkeypatch.setattr(get_settings(), "linkedin_email_enabled", True)
    assert "linkedin" in {s.source_name for s in main.get_all_scrapers()}
