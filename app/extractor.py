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


SELECTOR_SYSTEM = (
    "You write minimal, robust CSS selectors that a simple HTML parser can use "
    "to extract the same job vacancy listings you just identified on this page, "
    "without needing an LLM. Selectors for title/link/location are relative to "
    "the item element."
)

SELECTOR_TOOL = {
    "name": "emit_selectors",
    "description": "Return CSS selectors that locate the job vacancy listings on this page.",
    "input_schema": {
        "type": "object",
        "properties": {
            "item_selector": {
                "type": "string",
                "description": "Selector matching each repeated vacancy item container.",
            },
            "title_selector": {
                "type": "string",
                "description": "Selector, relative to the item, for the title/link element.",
            },
            "link_selector": {
                "type": "string",
                "description": "Selector, relative to the item, for the anchor with the href.",
            },
            "location_selector": {
                "type": ["string", "null"],
                "description": "Selector, relative to the item, for the location text, or null if none.",
            },
        },
        "required": ["item_selector", "title_selector", "link_selector"],
    },
}


async def infer_selectors(content: str) -> dict | None:
    s = get_settings()
    resp = await _get_client().messages.create(
        model=s.anthropic_model,
        max_tokens=512,
        system=[{"type": "text", "text": SELECTOR_SYSTEM}],
        tools=[SELECTOR_TOOL],
        tool_choice={"type": "tool", "name": "emit_selectors"},
        messages=[{"role": "user", "content": content[: s.max_chars]}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "emit_selectors":
            data = block.input
            if not (data.get("item_selector") and data.get("title_selector") and data.get("link_selector")):
                return None
            return {
                "item_selector": data["item_selector"],
                "title_selector": data["title_selector"],
                "link_selector": data["link_selector"],
                "location_selector": data.get("location_selector") or None,
            }
    return None


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
