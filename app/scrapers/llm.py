from playwright.async_api import async_playwright
from selectolax.parser import HTMLParser
from app.scrapers.base import BaseScraper
from app.extractor import extract_vacancies
from app.state import content_changed

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class LLMScraper(BaseScraper):
    def __init__(self, source: dict):
        self.name = source["name"]
        self.url = source["url"]

    async def fetch(self):
        launch: dict = {"headless": True}

        async with async_playwright() as p:
            browser = await p.chromium.launch(**launch)
            page = await browser.new_page(user_agent=UA)
            try:
                await page.goto(self.url, wait_until="networkidle", timeout=45000)
                html = await page.content()
            finally:
                await browser.close()

        tree = HTMLParser(html)
        for tag in tree.css("script, style, nav, footer, svg"):
            tag.decompose()
        cleaned = tree.body.html if tree.body else html

        if not content_changed(self.url, cleaned):
            return []
        return await extract_vacancies(cleaned, self.name, self.url)
