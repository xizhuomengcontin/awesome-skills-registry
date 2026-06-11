#!/usr/bin/env python3
"""Classify skills into a category + tags via the TrueFoundry AI Gateway.

Reuses the canonical category set from lint_registry.py so the gateway can only
ever emit a schema-valid `category`. Tags are normalized to the schema.cue `#Tag`
shape (^[a-z0-9]+(-[a-z0-9]+)*$). Used by both the backfill script and update.py.
"""

from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from lint_registry import VALID_CATEGORIES

load_dotenv()

CATEGORIES = sorted(VALID_CATEGORIES - {"none"})
_MODEL = "bedrock/global.anthropic.claude-sonnet-4-6"
_BASE_URL = "https://gateway.truefoundry.ai"
_TAG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_BATCH_SIZE = 20
_MAX_TAGS = 8

_SYSTEM = f"""You classify AI agent "skills" for a public registry.

For each skill you receive, return:
- "category": exactly ONE of: {", ".join(CATEGORIES)}. Pick the single best fit; use "miscellaneous" only when nothing else applies.
- "tags": 3-8 freeform discovery labels, lowercase and dash-separated (e.g. "web-ui", "code-review", "rna-seq"). Granular topic/tool/skill-type keywords.
- "display_name": a clean, human-readable title (e.g. "XLSX Spreadsheets", not "Xlsx").

Respond with ONLY a JSON array, one object per input skill, each:
{{"id": <id>, "category": <category>, "tags": [<tag>, ...], "display_name": <name>}}
No prose, no markdown fences."""


_LLM: ChatOpenAI | None = None


def _client() -> ChatOpenAI:
    global _LLM
    if _LLM is None:
        api_key = os.environ.get("TFY_API_KEY")
        if not api_key:
            raise SystemExit("TFY_API_KEY is not set (expected in .env).")
        _LLM = ChatOpenAI(
            model=_MODEL,
            base_url=_BASE_URL,
            api_key=api_key,
            max_tokens=4000,
            temperature=0,
            default_headers={
                "X-TFY-METADATA": "{}",
                "X-TFY-LOGGING-CONFIG": '{"enabled": true}',
            },
        )
    return _LLM


def _normalize_tag(raw: str) -> str | None:
    tag = re.sub(r"[^a-z0-9]+", "-", str(raw).lower()).strip("-")
    return tag if tag and _TAG_RE.match(tag) else None


def _clean(obj: dict, fallback_name: str) -> dict:
    category = obj.get("category")
    if category not in CATEGORIES:
        category = "miscellaneous"

    seen: list[str] = []
    for raw in obj.get("tags", []) or []:
        tag = _normalize_tag(raw)
        if tag and tag not in seen:
            seen.append(tag)
    tags = seen[:_MAX_TAGS]

    display_name = str(obj.get("display_name") or "").strip() or fallback_name
    return {"category": category, "tags": tags, "display_name": display_name}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, max=30))
def _invoke_batch(llm: ChatOpenAI, batch: list[dict]) -> list[dict]:
    payload = [
        {"id": it["id"], "display_name": it.get("display_name", ""), "description": it.get("description", "")}
        for it in batch
    ]
    resp = llm.invoke([
        SystemMessage(content=_SYSTEM),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ])
    text = str(resp.content).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)  # strip accidental fences
    return json.loads(text)


def classify(items: list[dict]) -> dict[str, dict]:
    """Classify skills. Returns {id: {category, tags, display_name}}.

    items: list of {id, display_name, description}.
    """
    if not items:
        return {}

    llm = _client()
    results: dict[str, dict] = {}

    for start in range(0, len(items), _BATCH_SIZE):
        batch = items[start : start + _BATCH_SIZE]
        try:
            raw = _invoke_batch(llm, batch)
        except Exception as exc:  # one bad batch shouldn't abort the run
            print(f"  ! batch {start}-{start + len(batch)} failed: {exc}")
            continue
        by_id = {str(o.get("id")): o for o in raw if isinstance(o, dict)}
        for it in batch:
            obj = by_id.get(it["id"], {})
            results[it["id"]] = _clean(obj, it.get("display_name", ""))
        print(f"  classified {min(start + _BATCH_SIZE, len(items))}/{len(items)}")

    return results
