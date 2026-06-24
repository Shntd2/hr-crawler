import hashlib
from pydantic import BaseModel


class Vacancy(BaseModel):
    title: str
    location: str
    link: str
    source: str

    @property
    def uid(self) -> str:
        return hashlib.sha256(self.link.encode()).hexdigest()[:32]
