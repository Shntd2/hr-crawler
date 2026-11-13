from playwright.async_api import Browser
from selectolax.parser import HTMLParser
from app.config import load_keywords
from app.scrapers.base import BaseScraper
from app.scrapers.generic import parse_with_selectors
from app.extractor import compact_html, extract_vacancies
from app.state import content_changed
from app.selectors import (
    confirm_selectors,
    get_stored_selectors,
    record_inferred_selectors,
    validate_selectors,
)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

LAUNCH_ARGS = {
    "headless": True,
    "args": ["--no-sandbox", "--disable-dev-shm-usage"],
}


class LLMScraper(BaseScraper):
    def __init__(self, source: dict):
        super().__init__(source)
        self.name = source["name"]
        self.url = source["url"]

    async def fetch(self, browser: Browser | None = None):
        if browser is None:
            raise ValueError("LLMScraper.fetch requires a Playwright browser")
        stored = get_stored_selectors(self.url)
        page = await browser.new_page(user_agent=UA)
        try:
            await page.goto(self.url, wait_until="load", timeout=45000)
            if stored:
                try:
                    await page.wait_for_selector(stored["item_selector"], timeout=15000)
                except Exception:
                    await page.wait_for_timeout(3000)
            else:
                await page.wait_for_timeout(3000)
            html = await page.content()
            final_url = page.url
        finally:
            await page.close()

        # Hashing, selector matching and the LLM all work on the same compact
        # HTML, so attribute churn (tracking ids, inline styles) no longer counts
        # as a page change and the LLM sees far fewer tokens.
        cleaned = compact_html(html)
        if not cleaned:
            return []

        if not content_changed(self.url, cleaned):
            return []

        if stored and validate_selectors(cleaned, stored):
            confirm_selectors(self.url)
            items = HTMLParser(cleaned).css(stored["item_selector"])
            return parse_with_selectors(items, stored, self.name, final_url)

        include = load_keywords().get("include", [])
        vacancies, selectors = await extract_vacancies(
            cleaned, self.name, final_url, include_keywords=include
        )
        if vacancies and selectors and validate_selectors(cleaned, selectors):
            record_inferred_selectors(self.url, selectors)
        return vacancies
