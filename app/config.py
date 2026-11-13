import json
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str
    telegram_chat_id: str

    # Gemini API (https://ai.google.dev/gemini-api/docs)
    gemini_api_key: str
    # Latest stable Flash-Lite. Set GEMINI_MODEL=gemini-3.1-flash-lite for the
    # cheaper previous generation.
    gemini_model: str = "gemini-3.5-flash-lite"
    # minimal | low | medium | high. Thinking tokens are billed as output, and
    # extraction does not need reasoning, so keep this at "minimal".
    gemini_thinking_level: str = "minimal"
    # standard | flex | priority. "flex" is cheaper but may respond more slowly.
    gemini_service_tier: str = "standard"
    gemini_max_output_tokens: int = 2048

    database_url: str = "sqlite:///./data/seen.db"
    scrape_hours: str = "8,13,18"
    max_chars: int = 12000

    # Client-side throttling for LLM calls (match your Gemini API tier limits).
    llm_rpm: int = 35
    llm_tpm: int = 45000
    # Only send page chunks to the LLM if they mention an "include" keyword.
    llm_keyword_gate: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_sources() -> list[dict]:
    return json.loads((CONFIG_DIR / "sources.json").read_text(encoding="utf-8"))


def load_keywords() -> dict:
    return json.loads((CONFIG_DIR / "keywords.json").read_text(encoding="utf-8"))
