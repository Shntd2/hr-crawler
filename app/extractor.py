from urllib.parse import urljoin
from anthropic import AsyncAnthropic
from app.config import get_settings
from app.schemas import Vacancy

_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


SYSTEM = (
    "You extract job vacancies from raw web page content. "
    "Return only genuine job postings via the emit_vacancies tool. "
    "Use 'N/A' when a location is missing. Always include the href/URL "
    "for each posting exactly as it appears on the page."
)

TOOL = {
    "name": "emit_vacancies",
    "description": "Return every job vacancy found on the page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "vacancies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "location": {"type": "string"},
                        "link": {"type": "string"},
                    },
                    "required": ["title", "link"],
                },
            }
        },
        "required": ["vacancies"],
    },
}


async def extract_vacancies(content: str, source: str, base_url: str) -> list[Vacancy]:
    s = get_settings()
    resp = await _get_client().messages.create(
        model=s.anthropic_model,
        max_tokens=2048,
        cache_control={"type": "ephemeral"},
        system=[{"type": "text", "text": SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "emit_vacancies"},
        messages=[{"role": "user", "content": content[: s.max_chars]}],
    )

    items: list[dict] = []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "emit_vacancies":
            items = block.input.get("vacancies", [])
            break

    out: list[Vacancy] = []
    for v in items:
        link = (v.get("link") or "").strip()
        if not link:
            continue
        out.append(
            Vacancy(
                title=(v.get("title") or "").strip(),
                location=(v.get("location") or "N/A").strip(),
                link=urljoin(base_url, link),
                source=source,
            )
        )
    return out
