"""Tests for generate.py job resolution (pure DB logic, no LLM calls)."""
import pytest

from db.models import Job
from generate import resolve_job, raw_from_job, Ambiguous


def _mk(db, **kw):
    base = dict(source="test", url=f"https://x.com/{kw.get('id','a')}",
                title="Dev Júnior", company="ACME")
    base.update(kw)
    job = Job(**base)
    db.add(job)
    db.commit()
    return job


def test_resolve_by_url(db_session):
    job = _mk(db_session, id="aaaa1111-0000-0000-0000-000000000000")
    assert resolve_job(db_session, job.url).id == job.id


def test_resolve_by_full_id(db_session):
    job = _mk(db_session, id="bbbb2222-0000-0000-0000-000000000000")
    assert resolve_job(db_session, job.id).id == job.id


def test_resolve_by_short_prefix(db_session):
    job = _mk(db_session, id="cccc3333-0000-0000-0000-000000000000")
    assert resolve_job(db_session, "cccc3333").id == job.id


def test_prefix_too_short_is_rejected(db_session):
    _mk(db_session, id="dddd4444-0000-0000-0000-000000000000")
    with pytest.raises(LookupError):
        resolve_job(db_session, "dddd")


def test_ambiguous_prefix_lists_matches(db_session):
    _mk(db_session, id="eeee5555-0000-0000-0000-000000000001", url="https://x.com/1")
    _mk(db_session, id="eeee5555-0000-0000-0000-000000000002", url="https://x.com/2")
    with pytest.raises(Ambiguous) as exc:
        resolve_job(db_session, "eeee5555")
    assert len(exc.value.matches) == 2


def test_unknown_reference_raises(db_session):
    with pytest.raises(LookupError):
        resolve_job(db_session, "ffffffff-9999")


def test_raw_from_job_roundtrip(db_session):
    job = _mk(db_session, id="abcd1234-0000-0000-0000-000000000000",
              location="Remoto", description="Vaga de Java.", is_remote=True)
    raw = raw_from_job(job)
    assert (raw.url, raw.title, raw.company) == (job.url, job.title, job.company)
    assert raw.is_remote is True and raw.description == "Vaga de Java."
