import asyncio
import logging
from app.config import load_keywords
from app.db import SessionLocal
from app.models import SeenVacancy
from app.filtering import filter_vacancies
from app.notifier import notify
from app.scrapers import build_scrapers

log = logging.getLogger("pipeline")


async def run_pipeline() -> None:
    keywords = load_keywords()
    scrapers = build_scrapers()

    results = await asyncio.gather(
        *(s.fetch() for s in scrapers), return_exceptions=True
    )

    vacancies = []
    for s, res in zip(scrapers, results):
        if isinstance(res, Exception):
            log.warning("scraper %s failed: %s", getattr(s, "name", s), res)
            continue
        vacancies.extend(res)

    matched = filter_vacancies(vacancies, keywords)

    with SessionLocal() as db:
        for v in matched:
            if db.get(SeenVacancy, v.uid):
                continue
            await notify(v)
            db.add(SeenVacancy(uid=v.uid, title=v.title, link=v.link))
            db.commit()
            log.info("notified: %s [%s]", v.title, v.source)
