from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from app.schemas import Vacancy

if TYPE_CHECKING:
    from playwright.async_api import Browser


class BaseScraper(ABC):
    def __init__(self, source: dict) -> None:
        self.source = source

    @abstractmethod
    async def fetch(self, browser: "Browser | None" = None) -> list[Vacancy]:
        ...
