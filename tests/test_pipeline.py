"""Pipeline-level tests for main.process_job filter persistence."""
import pytest

from scrapers.base import RawJob
from db.models import Job


def _raw(**over):
    base = dict(
        source="test", url="https://x.com/1", title="Desenvolvedor Java Sênior",
        company="Acme", location="São Paulo, SP", description="Vaga.",
        is_remote=True,
    )
    base.update(over)
    return RawJob(**base)


async def test_senior_job_persisted_ignored_with_context(db_session):
    import main
    ok = await main.process_job(_raw(), db_session)
    assert ok is False
    job = db_session.query(Job).one()
    assert job.status == "ignored"
    assert job.seniority == "senior"
    assert job.location == "São Paulo, SP"   # context preserved by helper
    assert job.is_remote is True
    assert "acima do nível alvo" in job.fit_summary


async def test_onsite_outside_region_persisted_ignored(db_session):
    import main
    raw = _raw(url="https://x.com/2", title="Desenvolvedor Java Júnior",
               location="Curitiba, PR", is_remote=False)
    ok = await main.process_job(raw, db_session)
    assert ok is False
    job = db_session.query(Job).one()
    assert job.status == "ignored"
    assert "fora do sudoeste" in job.fit_summary


async def test_duplicate_url_not_reprocessed(db_session):
    import main
    raw = _raw(url="https://x.com/3")
    await main.process_job(raw, db_session)
    assert await main.process_job(raw, db_session) is False
    assert db_session.query(Job).count() == 1


async def test_ignored_job_tagged_with_run_batch(db_session):
    import main
    ok = await main.process_job(_raw(url="https://x.com/4"), db_session,
                                 run_batch="2026-08-27T10:00:00+00:00")
    assert ok is False
    job = db_session.query(Job).one()
    assert job.run_batch == "2026-08-27T10:00:00+00:00"


async def test_run_batch_defaults_to_none(db_session):
    import main
    await main.process_job(_raw(url="https://x.com/5"), db_session)
    job = db_session.query(Job).one()
    assert job.run_batch is None
