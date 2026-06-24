from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from app.config import get_settings
from app.pipeline import run_pipeline

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    scheduler.add_job(
        run_pipeline,
        CronTrigger(hour=get_settings().scrape_hours, minute=0),
        id="scrape",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def shutdown_scheduler() -> None:
    scheduler.shutdown(wait=False)
