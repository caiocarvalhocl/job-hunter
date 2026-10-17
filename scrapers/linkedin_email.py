"""LinkedIn job e-mails (recommendations and saved-search alerts) read from
the candidate's own Gmail over IMAP.

This never touches linkedin.com. Title, company and location come from the
e-mail itself; the public job page answers HTTP 429 to the server, and
fetching it would be automated access LinkedIn's terms forbid anyway. Jobs
are scored without a description, the same way as any posting that has none.

The mailbox is opened read-only and messages are fetched with BODY.PEEK, so
nothing is marked as read, moved or labelled. Already-seen jobs are dropped
by the pipeline (same URL), so re-reading the last few days every run is
harmless.

Needs a Gmail app password (Google account → Security → 2-Step Verification
→ App passwords) in IMAP_APP_PASSWORD; the normal account password does not
work over IMAP.
"""
import asyncio
import email
import imaplib
import re
from datetime import datetime, timedelta, timezone
from email.policy import default as default_policy
from typing import List

from config.settings import get_settings
from scrapers.base import BaseScraper, RawJob

IMAP_HOST = "imap.gmail.com"
SENDERS = ("jobs-noreply@linkedin.com", "jobalerts-noreply@linkedin.com")

# "Visualizar vaga: https://www.linkedin.com/comm/jobs/view/4471940499/?tracking..."
_VIEW_RE = re.compile(
    r"^(?:visualizar vaga|ver vaga|view job):\s*"
    r"https://www\.linkedin\.com/(?:comm/)?jobs/view/(\d+)",
    re.IGNORECASE,
)
_COUNTRY_ONLY = {"brasil", "brazil"}
# Labels LinkedIn may print between the location and the link
# ("Candidate-se com currículo e perfil" is its Easy Apply).
_EXTRA_LINE_RE = re.compile(
    r"candidat|simplificad|easy apply|promovid|promoted|recrutando|"
    r"actively|ex-alun|alumni|conex|connection|applicant",
    re.IGNORECASE,
)


def parse_job_email(text: str) -> List[RawJob]:
    """Extract the job cards from the plain-text part of a LinkedIn job e-mail.

    Each card is "title / company / location / [label] / Visualizar vaga:
    <url>". The first card of an e-mail comes right after the header text, so
    the card is read backwards from the link: drop trailing labels, then the
    last three lines are title, company and location. URL and dash lines reset
    the buffer.
    """
    jobs, card = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _VIEW_RE.match(line)
        if match:
            while card and _EXTRA_LINE_RE.search(card[-1]):
                card.pop()
            if len(card) >= 3:
                job_id = match.group(1)
                title, company, location = card[-3], card[-2], card[-1]
                lowered = f"{title} {location}".lower()
                jobs.append(RawJob(
                    source="linkedin",
                    url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                    title=title,
                    company=company,
                    location=location,
                    # Country-level location ("Brasil") is how LinkedIn lists
                    # remote openings; a city means on-site or hybrid.
                    is_remote=location.lower() in _COUNTRY_ONLY or "remot" in lowered,
                    external_id=job_id,
                ))
            card = []
        elif "http" in line or line.startswith("---"):
            card = []
        else:
            card.append(line)
    return jobs


def _fetch_texts(user: str, password: str, days: int) -> List[str]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
    texts = []
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)
        ids = set()
        for sender in SENDERS:
            _, data = imap.search(None, "FROM", f'"{sender}"', "SINCE", since)
            ids.update(data[0].split())
        for msg_id in sorted(ids):
            _, data = imap.fetch(msg_id, "(BODY.PEEK[])")
            message = email.message_from_bytes(data[0][1], policy=default_policy)
            body = message.get_body(preferencelist=("plain",))
            if body is not None:
                texts.append(body.get_content())
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return texts


class LinkedInEmailScraper(BaseScraper):

    @property
    def source_name(self) -> str:
        return "linkedin"

    async def scrape(self) -> List[RawJob]:
        settings = get_settings()
        if not (settings.imap_user and settings.imap_app_password):
            self.log("IMAP_USER/IMAP_APP_PASSWORD not set, skipping")
            return []
        try:
            texts = await asyncio.to_thread(
                _fetch_texts, settings.imap_user, settings.imap_app_password,
                settings.linkedin_email_days)
        except Exception as e:
            self.log(f"IMAP error: {e}")
            return []

        unique = {}
        for text in texts:
            for job in parse_job_email(text):
                unique.setdefault(job.url, job)
        self.log(f"{len(texts)} e-mails → {len(unique)} unique jobs")
        return list(unique.values())
