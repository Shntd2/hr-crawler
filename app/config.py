import json
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_chat_id: str
    anthropic_api_key: str
    anthropic_model: str = "claude-haiku-4-5-20251001"
    database_url: str = "sqlite:///./data/seen.db"
    scrape_hours: str = "8,13,18"
    max_chars: int = 12000
    anthropic_rpm: int = 35
    anthropic_tpm: int = 45000


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_sources() -> list[dict]:
    return json.loads((CONFIG_DIR / "sources.json").read_text(encoding="utf-8"))


def load_keywords() -> dict:
    return json.loads((CONFIG_DIR / "keywords.json").read_text(encoding="utf-8"))
