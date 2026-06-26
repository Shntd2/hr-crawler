import asyncio
import logging
from playwright.async_api import async_playwright
from app.config import load_keywords
from app.db import SessionLocal
from app.models import SeenVacancy
from app.filtering import filter_vacancies
from app.notifier import notify
from app.scrapers import build_scrapers
from app.scrapers.llm import LLMScraper, LAUNCH_ARGS

log = logging.getLogger("pipeline")


async def run_pipeline() -> None:
    keywords = load_keywords()
    scrapers = build_scrapers()

    llm_scrapers = [s for s in scrapers if isinstance(s, LLMScraper)]
    generic_scrapers = [s for s in scrapers if not isinstance(s, LLMScraper)]

    vacancies = []

    generic_results = await asyncio.gather(
        *(s.fetch() for s in generic_scrapers), return_exceptions=True
    )
    for s, res in zip(generic_scrapers, generic_results):
        if isinstance(res, Exception):
            log.warning("scraper %s failed: %s", getattr(s, "name", s), res)
            continue
        vacancies.extend(res)

    if llm_scrapers:
        async with async_playwright() as p:
            browser = await p.chromium.launch(**LAUNCH_ARGS)
            try:
                for s in llm_scrapers:
                    try:
                        res = await s.fetch(browser)
                        vacancies.extend(res)
                    except Exception as exc:
                        log.warning("scraper %s failed: %s", s.name, exc)
            finally:
                await browser.close()

    matched = filter_vacancies(vacancies, keywords)

    with SessionLocal() as db:
        for v in matched:
            if db.get(SeenVacancy, v.uid):
                continue
            await notify(v)
            db.add(SeenVacancy(uid=v.uid, title=v.title, link=v.link))
            db.commit()
            log.info("notified: %s [%s]", v.title, v.source)
