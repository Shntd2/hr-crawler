import logging
import httpx
from typing import TYPE_CHECKING
from urllib.parse import urljoin
from selectolax.parser import HTMLParser
from app.schemas import Vacancy
from app.scrapers.base import BaseScraper
from app.state import get_conditional_headers, save_validators
from app.selectors import EMPTY_STREAK_LIMIT, invalidate_selectors, record_match_result

if TYPE_CHECKING:
    from playwright.async_api import Browser

log = logging.getLogger("scrapers.generic")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; JobRadar/1.0)"}


def parse_with_selectors(items, selectors: dict, name: str, base_url: str) -> list[Vacancy]:
    out: list[Vacancy] = []
    for item in items:
        t = item.css_first(selectors["title_selector"])
        link = item.css_first(selectors["link_selector"])
        if not (t and link):
            continue
        loc_sel = selectors.get("location_selector")
        loc = item.css_first(loc_sel) if loc_sel else None
        href = link.attributes.get("href", "") or ""
        out.append(
            Vacancy(
                title=t.text(strip=True),
                location=loc.text(strip=True) if loc else "N/A",
                link=urljoin(base_url, href),
                source=name,
            )
        )
    return out


class GenericScraper(BaseScraper):
    def __init__(self, source: dict):
        super().__init__(source)
        self.s = source

    async def fetch(self, browser: "Browser | None" = None) -> list[Vacancy]:
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

        if record_match_result(url, matched=bool(items)):
            log.warning(
                "selector for %s stopped matching after %d consecutive empty scrapes; "
                "invalidated for re-learning",
                url,
                EMPTY_STREAK_LIMIT,
            )

        base_url = self.s.get("base_url") or str(r.url)
        return parse_with_selectors(items, self.s, self.s["name"], base_url)
