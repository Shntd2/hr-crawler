from app.config import load_sources
from app.scrapers.base import BaseScraper
from app.scrapers.generic import GenericScraper
from app.scrapers.llm import LLMScraper

_REGISTRY: dict[str, type[BaseScraper]] = {
    "generic": GenericScraper,
    "llm": LLMScraper,
}


def build_scrapers() -> list[BaseScraper]:
    scrapers: list[BaseScraper] = []
    for src in load_sources():
        kind = src.get("type", "generic")
        cls = _REGISTRY.get(kind)
        if cls is None:
            raise ValueError(f"Unknown source type: {kind!r}")
        scrapers.append(cls(src))
    return scrapers
