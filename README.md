# hr-crawler (Job Radar)

FastAPI + APScheduler service that scrapes career pages, keeps vacancies that
match `config/keywords.json`, and sends new ones to Telegram.

## Setup

1. Copy `.env.example` to `.env` and fill in the Telegram and Gemini keys.
2. Put `sources.json` and `keywords.json` in `config/`.
3. `docker compose up -d --build`

`POST /run` triggers a scrape manually; `GET /health` is a liveness check.

## Source types

- `generic`: plain HTTP fetch, parsed with the CSS selectors in `sources.json`.
- `llm`: rendered with Playwright. Gemini (Flash-Lite) extracts vacancies the
  first time and proposes CSS selectors; once the selectors validate on two
  runs they are used without any LLM call until they stop matching.

## Keeping Gemini token usage low

| Measure | Where | Effect |
| --- | --- | --- |
| Compact HTML (keep tags, text, `href`, `id`, first 3 classes; drop scripts, styles, nav, footer, media, comments, other attributes, empty elements, whitespace) | `extractor.compact_html` | Roughly half the input tokens or less; also stops attribute churn from counting as a page change |
| Skip unchanged pages (content hash, ETag / Last-Modified) | `state.py` | No call when nothing changed |
| Learned selectors replace the LLM after 2 stable runs | `selectors.py` | Most runs make zero LLM calls |
| One call returns vacancies **and** selectors | `extractor._extract_chunk` | Removes the second "infer selectors" request |
| Keyword gate: chunks without an include keyword are not sent | `LLM_KEYWORD_GATE` | Large pages send only the relevant chunk |
| `thinking_level=minimal` | `GEMINI_THINKING_LEVEL` | Thinking tokens are billed as output; extraction needs none |
| JSON schema output instead of tool definitions; capped `max_output_tokens`; no automatic continuation | `_generation_config` | Short, bounded output |
| Optional `flex` service tier | `GEMINI_SERVICE_TIER` | Lower price for non-urgent runs |

Every call logs `gemini usage source=… prompt=… cached=… output=… thinking=…`,
so `docker compose logs | grep "gemini usage"` shows exactly where tokens go.
