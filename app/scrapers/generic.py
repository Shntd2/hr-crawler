import httpx
from urllib.parse import urljoin
from selectolax.parser import HTMLParser
from app.schemas import Vacancy
from app.scrapers.base import BaseScraper
from app.state import get_conditional_headers, save_validators
from app.selectors import invalidate_selectors

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0)"}


class GenericScraper(BaseScraper):
    def __init__(self, source: dict):
        self.s = source

    async def fetch(self) -> list[Vacancy]:
        url = self.s["url"]
        cond = get_conditional_headers(url)
        async with httpx.AsyncClient(timeout=20, headers={**HEADERS, **cond}) as client:
            r = await client.get(url, follow_redirects=True)

        if r.status_code == 304:
            return []
        r.raise_for_status()
        save_validators(url, r.headers)

        tree = HTMLParser(r.text)
        try:
            items = tree.css(self.s["item_selector"])
        except Exception:
            invalidate_selectors(url)
            raise

        out: list[Vacancy] = []
        for item in items:
            t = item.css_first(self.s["title_selector"])
            link = item.css_first(self.s["link_selector"])
            if not (t and link):
                continue
            loc_sel = self.s.get("location_selector")
            loc = item.css_first(loc_sel) if loc_sel else None
            href = link.attributes.get("href", "") or ""
            out.append(
                Vacancy(
                    title=t.text(strip=True),
                    location=loc.text(strip=True) if loc else "N/A",
                    link=urljoin(self.s.get("base_url", url), href),
                    source=self.s["name"],
                )
            )
        return out
