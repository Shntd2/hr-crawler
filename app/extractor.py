import asyncio
import time
from collections import deque
from urllib.parse import urljoin
from anthropic import AsyncAnthropic
from selectolax.parser import HTMLParser
from app.config import get_settings
from app.schemas import Vacancy

_client: AsyncAnthropic | None = None
_rate_limiter: "RateLimiter | None" = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


class RateLimiter:
    def __init__(self, max_per_minute: int, max_tokens_per_minute: int):
        self._max_per_minute = max_per_minute
        self._max_tokens_per_minute = max_tokens_per_minute
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()
        self._token_usage: deque[tuple[float, int]] = deque()

    async def acquire(self, estimated_tokens: int) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                while self._timestamps and now - self._timestamps[0] >= 60:
                    self._timestamps.popleft()
                while self._token_usage and now - self._token_usage[0][0] >= 60:
                    self._token_usage.popleft()

                tokens_in_window = sum(t for _, t in self._token_usage)
                request_ok = len(self._timestamps) < self._max_per_minute
                token_ok = tokens_in_window + estimated_tokens <= self._max_tokens_per_minute

                if request_ok and token_ok:
                    self._timestamps.append(now)
                    self._token_usage.append((now, estimated_tokens))
                    return

                wait_for = []
                if not request_ok:
                    wait_for.append(self._timestamps[0] + 60 - now)
                if not token_ok:
                    wait_for.append(self._token_usage[0][0] + 60 - now)
                await asyncio.sleep(max(wait_for))


def _get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        s = get_settings()
        _rate_limiter = RateLimiter(s.anthropic_rpm, s.anthropic_tpm)
    return _rate_limiter


def _estimate_tokens(*texts: str, max_tokens: int) -> int:
    return sum(len(t) for t in texts) // 4 + max_tokens


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
    truncated = content[: s.max_chars]
    await _get_rate_limiter().acquire(
        _estimate_tokens(SELECTOR_SYSTEM, truncated, max_tokens=512)
    )
    resp = await _get_client().messages.create(
        model=s.anthropic_model,
        max_tokens=512,
        system=[{"type": "text", "text": SELECTOR_SYSTEM}],
        tools=[SELECTOR_TOOL],
        tool_choice={"type": "tool", "name": "emit_selectors"},
        messages=[{"role": "user", "content": truncated}],
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


def _element_fragments(node, max_chars: int) -> list[str]:
    fragments: list[str] = []
    for child in node.iter():
        html = child.html or ""
        if len(html) <= max_chars:
            fragments.append(html)
        else:
            sub = _element_fragments(child, max_chars)
            fragments.extend(sub if sub else [html])
    return fragments


def _pack_fragments(fragments: list[str], max_chars: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for frag in fragments:
        if len(frag) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(frag)
        elif len(current) + len(frag) > max_chars:
            chunks.append(current)
            current = frag
        else:
            current += frag
    if current:
        chunks.append(current)
    return chunks


def _chunk_content(content: str, max_chars: int) -> list[str]:
    if len(content) <= max_chars:
        return [content]
    root = HTMLParser(content).body
    fragments = _element_fragments(root, max_chars) if root is not None else []
    if not fragments:
        return [content[i: i + max_chars] for i in range(0, len(content), max_chars)]
    return _pack_fragments(fragments, max_chars)


async def _extract_chunk(content: str, source: str, base_url: str) -> list[Vacancy]:
    s = get_settings()
    await _get_rate_limiter().acquire(
        _estimate_tokens(SYSTEM, content, max_tokens=2048)
    )
    resp = await _get_client().messages.create(
        model=s.anthropic_model,
        max_tokens=2048,
        cache_control={"type": "ephemeral"},
        system=[{"type": "text", "text": SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "emit_vacancies"},
        messages=[{"role": "user", "content": content}],
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


async def extract_vacancies(content: str, source: str, base_url: str) -> list[Vacancy]:
    s = get_settings()
    seen_links: set[str] = set()
    out: list[Vacancy] = []
    for chunk in _chunk_content(content, s.max_chars):
        for v in await _extract_chunk(chunk, source, base_url):
            if v.link in seen_links:
                continue
            seen_links.add(v.link)
            out.append(v)
    return out
