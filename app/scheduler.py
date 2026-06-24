from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config import get_settings
from app.pipeline import run_pipeline

scheduler = AsyncIOScheduler()


def start_scheduler() -> None:
    scheduler.add_job(
        run_pipeline,
        "interval",
        minutes=get_settings().scrape_interval_minutes,
        id="scrape",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def shutdown_scheduler() -> None:
    scheduler.shutdown(wait=False)
