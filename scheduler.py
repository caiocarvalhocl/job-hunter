import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import get_settings
from db.models import init_db
from main import run

settings = get_settings()


async def main():
    init_db()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run,
        trigger=IntervalTrigger(hours=settings.scrape_interval_hours),
        id="job_hunter",
        name="Job Hunter Scraper",
        replace_existing=True,
    )
    scheduler.start()

    print(f"⏰ Scheduler started — running every {settings.scrape_interval_hours}h")
    print("🔍 Running first scan now...\n")

    await run()

    try:
        while True:
            await asyncio.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print("\n👋 Shutting down scheduler...")
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
