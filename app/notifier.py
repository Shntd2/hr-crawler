import httpx
from app.config import get_settings
from app.schemas import Vacancy

TG_API = "https://api.telegram.org/bot{token}/sendMessage"


async def notify(vacancy: Vacancy) -> None:
    s = get_settings()
    text = (
        f"Job Title: {vacancy.title}\n"
        f"Location: {vacancy.location}\n"
        f"Link to Vacancy: {vacancy.link}"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(
            TG_API.format(token=s.telegram_bot_token),
            json={"chat_id": s.telegram_chat_id, "text": text},
        )
