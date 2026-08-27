import asyncio
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from config.settings import get_settings
from db.models import init_db, SessionLocal, Job
# scrapers.remoteco.RemoteCo intentionally NOT wired in: remote.co moved
# behind a JavaScript/Cloudflare wall (plain aiohttp gets no usable HTML),
# so the scraper only produced error noise. Re-enable if a headless
# browser is ever added.
# scrapers.remoteok.RemoteOKScraper intentionally NOT wired in: RemoteOK
# charges job seekers to apply, which disqualifies it as a source here.
# The scraper file is kept in case that policy changes.
from scrapers.weworkremotely import WeWorkRemotelyScraper
from scrapers.himalayas import HimalayasScraper
from scrapers.programathor import ProgramathorScraper
from scrapers.gupy import GupyScraper
from scrapers.arbeitnow import ArbeitnowScraper
from scrapers.remotive import RemotiveScraper
from scrapers.jobicy import JobicyScraper
# scrapers.indeed.IndeedScraper intentionally NOT wired in: Indeed added a
# Cloudflare challenge + login wall past page 1 in 2026 and its ToS explicitly
# prohibits automated scraping. A plain aiohttp+BeautifulSoup scraper will
# return empty results without a residential proxy + stealth browser, which
# is disproportionate effort/risk for this project.
from scrapers.base import RawJob
from filters.ai_filter import score_job_fit
from filters.seniority_filter import is_above_target, detect_level
from filters.location_filter import is_brazil_eligible, is_local_region, is_pcd_reserved
from filters.track_filter import is_track_location_allowed
from notifiers.telegram import notify_new_job, notify_run_summary

settings = get_settings()


def get_all_scrapers():
    kwargs = dict(
        keywords=settings.keywords_list,
        location=settings.search_location,
        remote_only=settings.search_remote_only,
    )
    scrapers = [
        WeWorkRemotelyScraper(**kwargs),
        HimalayasScraper(**kwargs),
        ProgramathorScraper(**kwargs),
        GupyScraper(**kwargs),
        ArbeitnowScraper(**kwargs),
        RemotiveScraper(**kwargs),
        JobicyScraper(**kwargs),
    ]
    # Config-driven boards (scrapers/generic_sources.py). Only confirmed
    # endpoints live in ENABLED_SOURCES, so this stays empty until a board is
    # verified rather than adding scrapers that silently return zero.
    from scrapers.generic_json import GenericJSONScraper
    from scrapers.generic_sources import ENABLED_SOURCES
    for cfg in ENABLED_SOURCES:
        scrapers.append(GenericJSONScraper(cfg, **kwargs))

    return scrapers


def job_already_seen(db: Session, url: str) -> bool:
    return db.query(Job).filter(Job.url == url).first() is not None


def save_job(db: Session, raw: RawJob, score: float, summary: str, seniority: str = None,
             run_batch: str = None) -> Job:
    job = Job(
        source=raw.source,
        external_id=raw.external_id,
        url=raw.url,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        description=raw.description,
        salary=raw.salary,
        is_remote=raw.is_remote,
        seniority=seniority,
        fit_score=score,
        fit_summary=summary,
        status="new",
        run_batch=run_batch,
    )
    db.add(job)
    try:
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        return None
    return job


def _record_ignored(db: Session, raw: RawJob, level: str, reason: str,
                     run_batch: str = None) -> bool:
    """Persist a job as ignored with a reason and return False (skipped)."""
    job = Job(
        source=raw.source,
        url=raw.url,
        title=raw.title,
        company=raw.company,
        location=raw.location,
        is_remote=raw.is_remote,
        seniority=level,
        fit_summary=reason,
        status="ignored",
        run_batch=run_batch,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
    return False


async def process_job(raw: RawJob, db: Session, run_batch: str = None) -> bool:
    if job_already_seen(db, raw.url):
        return False

    print(f"  ⏳ Analyzing: {raw.title} @ {raw.company}")

    level = detect_level(raw.title)

    if is_above_target(raw.title, settings.accept_pleno):
        print(f"  🚫 Acima do nível alvo ({level}) — skipping before scoring")
        return _record_ignored(db, raw, level, f"Filtrado: acima do nível alvo ({level})", run_batch)

    if not raw.is_remote and not (settings.allow_onsite_in_region and is_local_region(raw.location)):
        print(f"  🏢 Presencial/híbrido fora da região — skipping before scoring")
        return _record_ignored(db, raw, level, "Filtrado: presencial/híbrido fora do sudoeste do PR", run_batch)

    # PCD affirmative-action postings are reserved for candidates with
    # disabilities; skip before scoring, unless this instance turned the
    # filter off (settings.exclude_pcd_reserved=false) because the person
    # running it is PCD and wants those postings.
    if settings.exclude_pcd_reserved and is_pcd_reserved(raw.title, raw.description):
        print(f"  ♿ Vaga afirmativa reservada para PCD — skipping before scoring")
        return _record_ignored(db, raw, level, "Filtrado: vaga afirmativa reservada para PCD", run_batch)

    # Per-track geographic policy: dev anywhere; QA/support only abroad.
    track_ok, track_reason = is_track_location_allowed(raw)
    if not track_ok:
        print(f"  🌐 {track_reason} — skipping before scoring")
        return _record_ignored(db, raw, level, track_reason, run_batch)

    if not is_brazil_eligible(raw):
        print(f"  🌎 Not open to Brazil-based candidates — skipping before scoring")
        return _record_ignored(db, raw, level, "Filtrado: vaga restrita a outro país/região", run_batch)

    result = await score_job_fit(raw)
    if result is None:
        # Transient failure (rate limit, network, malformed response). Do NOT
        # persist: the URL stays unseen and the next run retries it.
        print(f"  ⚠️  Scoring unavailable — will retry on next run")
        return False
    score, summary = result

    if score < settings.min_fit_score:
        print(f"  ⬇️  Score {score:.0f} below threshold — skipping")
        job = Job(
            source=raw.source,
            url=raw.url,
            title=raw.title,
            company=raw.company,
            seniority=level,
            fit_score=score,
            fit_summary=summary,
            status="ignored",
            run_batch=run_batch,
        )
        db.add(job)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        return False

    # Documents are no longer generated automatically. Use:
    #   python generate.py <id> [--cover] [--cv] [--lang pt|en]
    job = save_job(db, raw, score, summary, seniority=level, run_batch=run_batch)
    if not job:
        return False

    success = await notify_new_job(job)
    if success:
        job.status = "notified"
        job.notified_at = datetime.now(timezone.utc)
        db.commit()
        print(f"  ✅ Notified: {job.title} (score {score:.0f})")

    return success


async def run():
    print(f"\n{'='*50}")
    print(f"🚀 Job Hunter starting at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*50}")

    run_batch = datetime.now(timezone.utc).isoformat()
    db = SessionLocal()
    scrapers = get_all_scrapers()
    total_found = total_new = total_notified = 0

    try:
        for scraper in scrapers:
            print(f"\n📡 Scraping {scraper.source_name}...")
            try:
                raw_jobs = await scraper.scrape()
                total_found += len(raw_jobs)
                for raw in raw_jobs:
                    if not job_already_seen(db, raw.url):
                        total_new += 1
                        if await process_job(raw, db, run_batch):
                            total_notified += 1
                        await asyncio.sleep(1)
            except Exception as e:
                print(f"  ❌ Error with {scraper.source_name}: {e}")
                continue
    finally:
        db.close()

    print(f"\n{'='*50}")
    print(f"✅ Run complete: {total_found} found, {total_new} new, {total_notified} notified")
    print(f"{'='*50}\n")

    await notify_run_summary(total_found, total_new, total_notified)


if __name__ == "__main__":
    init_db()
    asyncio.run(run())