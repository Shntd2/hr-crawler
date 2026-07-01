from playwright.async_api import Browser
from selectolax.parser import HTMLParser
from app.scrapers.base import BaseScraper
from app.extractor import extract_vacancies, infer_selectors
from app.state import content_changed
from app.selectors import record_inferred_selectors, validate_selectors

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
        self.name = source["name"]
        self.url = source["url"]

    async def fetch(self, browser: Browser):
        page = await browser.new_page(user_agent=UA)
        try:
            await page.goto(self.url, wait_until="load", timeout=45000)
            await page.wait_for_timeout(3000)
            html = await page.content()
        finally:
            await page.close()

        tree = HTMLParser(html)
        for tag in tree.css("script, style, nav, footer, svg"):
            tag.decompose()
        cleaned = tree.body.html if tree.body else html

        if not content_changed(self.url, cleaned):
            return []

        vacancies, matched_chunk = await extract_vacancies(cleaned, self.name, self.url)
        if vacancies:
            selectors = await infer_selectors(matched_chunk or cleaned)
            if selectors and validate_selectors(cleaned, selectors):
                record_inferred_selectors(self.url, selectors)
        return vacancies
