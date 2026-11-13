import asyncio
import json
import logging
import re
import time
from collections import deque
from urllib.parse import urljoin

from google import genai
from google.genai import types
from selectolax.parser import HTMLParser

from app.config import get_settings
from app.schemas import Vacancy

log = logging.getLogger("extractor")

_client: genai.Client | None = None
_rate_limiter: "RateLimiter | None" = None

# Retry transient Gemini errors (rate limit / overload) inside the SDK.
_RETRY = types.HttpRetryOptions(
    attempts=4,
    initial_delay=2.0,
    max_delay=30.0,
    http_status_codes=[429, 500, 503, 504],
)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=get_settings().gemini_api_key,
            http_options=types.HttpOptions(retry_options=_RETRY, timeout=120_000),
        )
    return _client


class RateLimiter:
    def __init__(self, max_per_minute: int, max_tokens_per_minute: int):
        self._max_per_minute = max_per_minute
        self._max_tokens_per_minute = max_tokens_per_minute
        self._lock = asyncio.Lock()
        self._timestamps: deque[float] = deque()
        self._token_usage: deque[tuple[float, int]] = deque()

    async def acquire(self, estimated_tokens: int) -> None:
        if estimated_tokens > self._max_tokens_per_minute:
            raise ValueError(
                f"estimated_tokens={estimated_tokens} exceeds llm_tpm budget "
                f"({self._max_tokens_per_minute}); request can never be admitted"
            )
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
        _rate_limiter = RateLimiter(s.llm_rpm, s.llm_tpm)
    return _rate_limiter


def _estimate_tokens(*texts: str, max_tokens: int) -> int:
    return sum(len(t) for t in texts) // 4 + max_tokens


# ---------------------------------------------------------------------------
# Token reduction: shrink HTML before it is hashed, parsed or sent to the LLM.
# ---------------------------------------------------------------------------

_KEEP_ATTRS = {"class", "id", "href"}
_MAX_CLASSES = 3
_DROP_TAGS = "script, style, noscript, template, svg, img, picture, video, iframe, link, meta"
# Dropped unless they mention an include keyword (some sites list jobs there).
_CHROME_TAGS = "nav, footer"


def compact_html(html: str, keep_keywords: list[str] | None = None) -> str:
    """Return a much smaller HTML string that keeps only what extraction needs.

    Keeps tags, text, href, id and the first few classes, so CSS selectors
    learned on the compact HTML keep working on it. Drops scripts, styles,
    media, nav/footer blocks that mention none of keep_keywords, comments, all other attributes, empty leaf elements and
    redundant whitespace, which roughly halves the token count or better.
    """
    tree = HTMLParser(html)
    root = tree.body or tree.root
    if root is None:
        return ""
    for node in root.css(_DROP_TAGS):
        node.decompose()
    kw = [k.lower() for k in (keep_keywords or [])]
    for node in root.css(_CHROME_TAGS):
        text = (node.text(separator=" ") or "").lower()
        if not any(k in text for k in kw):
            node.decompose()

    nodes = list(root.traverse(include_text=False))
    for node in reversed(nodes):  # children before parents
        if node.tag == "_comment":
            node.decompose()
            continue
        attrs = node.attrs
        for name in list(node.attributes):
            if name not in _KEEP_ATTRS:
                del attrs[name]
        cls = node.attributes.get("class")
        if cls:
            parts = cls.split()
            if len(parts) > _MAX_CLASSES:
                attrs["class"] = " ".join(parts[:_MAX_CLASSES])
        if (
            node is not root
            and node.child is None
            and not node.attributes.get("href")
            and not (node.text(deep=False) or "").strip()
        ):
            node.decompose()

    out = root.html or ""
    out = re.sub(r"\s+", " ", out)
    return re.sub(r">\s+<", "><", out).strip()


def chunk_has_keyword(chunk: str, include: list[str]) -> bool:
    if not include:
        return True
    text = HTMLParser(chunk).text(separator=" ").lower()
    return any(k.lower() in text for k in include)


# ---------------------------------------------------------------------------
# One Gemini call per chunk returns BOTH the vacancies and reusable selectors,
# so we never pay a second request just to learn selectors.
# ---------------------------------------------------------------------------

SYSTEM = (
    "You extract job vacancies from compact HTML of a careers or job-board page. "
    "Return only genuine job postings, not navigation, filters or blog links. "
    "Copy each posting's href exactly as it appears in the HTML. "
    "Use 'N/A' when a location is missing. "
    "Also return CSS selectors that a plain HTML parser can use on this same HTML "
    "to extract these postings without an LLM: item_selector matches each "
    "repeated posting container; title_selector, link_selector and "
    "location_selector are relative to the item. Use only tag names, classes and "
    "ids that appear in the HTML. Set selectors to null if there are no postings."
)

RESPONSE_SCHEMA = {
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
        },
        "selectors": {
            "type": ["object", "null"],
            "properties": {
                "item_selector": {"type": "string"},
                "title_selector": {"type": "string"},
                "link_selector": {"type": "string"},
                "location_selector": {"type": ["string", "null"]},
            },
            "required": ["item_selector", "title_selector", "link_selector"],
        },
    },
    "required": ["vacancies", "selectors"],
}

_PLACEHOLDER_SELECTOR_VALUES = {"", "<unknown>", "unknown", "n/a", "none", "null"}


def _looks_like_placeholder(value: str) -> bool:
    return value.strip().lower() in _PLACEHOLDER_SELECTOR_VALUES


def _clean_selectors(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    keys = ("item_selector", "title_selector", "link_selector")
    selectors = {k: (data.get(k) or "") for k in keys}
    if not all(selectors.values()):
        return None
    if any(_looks_like_placeholder(v) for v in selectors.values()):
        return None
    return {**selectors, "location_selector": data.get("location_selector") or None}


def _generation_config() -> types.GenerateContentConfig:
    s = get_settings()
    kwargs: dict = {
        "system_instruction": SYSTEM,
        "response_mime_type": "application/json",
        "response_json_schema": RESPONSE_SCHEMA,
        "max_output_tokens": s.gemini_max_output_tokens,
        # Never let the SDK silently re-send the request to finish a long answer.
        "automatic_continuation": False,
    }
    if s.gemini_thinking_level:
        kwargs["thinking_config"] = types.ThinkingConfig(
            thinking_level=s.gemini_thinking_level.upper()
        )
    if s.gemini_service_tier and s.gemini_service_tier.lower() != "standard":
        kwargs["service_tier"] = s.gemini_service_tier.lower()
    return types.GenerateContentConfig(**kwargs)


def _log_usage(source: str, resp) -> None:
    u = getattr(resp, "usage_metadata", None)
    if not u:
        return
    log.info(
        "gemini usage source=%s prompt=%s cached=%s output=%s thinking=%s total=%s",
        source,
        u.prompt_token_count,
        u.cached_content_token_count or 0,
        u.candidates_token_count,
        u.thoughts_token_count or 0,
        u.total_token_count,
    )


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
        chunks = [content[i: i + max_chars] for i in range(0, len(content), max_chars)]
    else:
        chunks = _pack_fragments(fragments, max_chars)

    out: list[str] = []
    for chunk in chunks:
        if len(chunk) <= max_chars:
            out.append(chunk)
        else:
            out.extend(chunk[i: i + max_chars] for i in range(0, len(chunk), max_chars))
    return out


async def _extract_chunk(
    content: str, source: str, base_url: str
) -> tuple[list[Vacancy], dict | None]:
    s = get_settings()
    await _get_rate_limiter().acquire(
        _estimate_tokens(SYSTEM, content, max_tokens=s.gemini_max_output_tokens)
    )
    resp = await _get_client().aio.models.generate_content(
        model=s.gemini_model,
        contents=content,
        config=_generation_config(),
    )
    _log_usage(source, resp)

    try:
        data = json.loads(resp.text or "{}")
    except json.JSONDecodeError:
        log.warning("gemini returned invalid JSON for %s (finish=%s)", source,
                    resp.candidates[0].finish_reason if resp.candidates else None)
        return [], None

    out: list[Vacancy] = []
    for v in data.get("vacancies") or []:
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
    return out, _clean_selectors(data.get("selectors"))


async def extract_vacancies(
    content: str, source: str, base_url: str, include_keywords: list[str] | None = None
) -> tuple[list[Vacancy], dict | None]:
    """Extract vacancies from compact HTML.

    Returns the vacancies and the selectors proposed for the chunk that yielded
    the most vacancies (or None). Chunks that mention none of the include
    keywords are skipped when the keyword gate is on.
    """
    s = get_settings()
    gate = include_keywords if s.llm_keyword_gate else None
    seen_links: set[str] = set()
    out: list[Vacancy] = []
    best_selectors: dict | None = None
    best_count = 0
    skipped = 0
    for chunk in _chunk_content(content, s.max_chars):
        if gate and not chunk_has_keyword(chunk, gate):
            skipped += 1
            continue
        chunk_vacancies, selectors = await _extract_chunk(chunk, source, base_url)
        if selectors and len(chunk_vacancies) > best_count:
            best_selectors = selectors
            best_count = len(chunk_vacancies)
        for v in chunk_vacancies:
            if v.link in seen_links:
                continue
            seen_links.add(v.link)
            out.append(v)
    if skipped:
        log.info("skipped %d chunk(s) without keywords for %s", skipped, source)
    return out, best_selectors
