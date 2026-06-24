from abc import ABC, abstractmethod
from app.schemas import Vacancy


class BaseScraper(ABC):
    @abstractmethod
    async def fetch(self) -> list[Vacancy]:
        ...
