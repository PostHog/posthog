"""The summary prompt, the output contract and the normalization of the model's answer.

`summary_text` is the text the embeddings asset embeds, so its format is part of the contract with
every vector already written. Bump `PROMPT_VERSION` when the prompt, the normalization or
`summary_text` changes.
"""

import json
import datetime
from typing import Any

PROMPT_VERSION = 1

SUMMARY_MAX_WORDS = 60
MAX_FOCUS_AREAS = 6
MAX_PRODUCTS = 10
STRENGTHS = ("high", "medium", "low")
DEFAULT_STRENGTH = "low"
# Strings a model writes in place of a JSON null.
_NULL_STRINGS = frozenset({"", "none", "null", "n/a", "na", "nil"})

SYSTEM_PROMPT = """You maintain a short summary of what one person has been working on in one PostHog project.
You get their previous summary, if any, and a sample of their recent activity in up to three sections: tasks they gave to PostHog AI or the Slack agent, sessions of their own coding agent over MCP, and things they created or changed in PostHog.
Update the summary to reflect what they are focused on now. Keep what is still true, drop what has gone quiet, and add what is new. Weigh themes that repeat across sections above one-off items. Treat bulk changes of the same kind as one theme, not a list.
Name concrete products, features, metrics, pipelines and workflows. Never write generic phrases like "data analysis".
Write about the work, not the person: no names, emails, IDs, secrets, or quotes from the input. Open with the work itself.
Return JSON: `summary` (at most 60 words), `focus_areas` (up to 6, each with `topic`, `strength` high, medium or low, and `last_seen` as YYYY-MM-DD), `products`, and `recent_shift` (one sentence, or null).
Set `recent_shift` only when there is a previous summary and the activity shows a real change from it. Otherwise it is null."""

# Strict structured output. The normalization below still checks every rule, because a provider
# behind the gateway may not enforce the schema.
RESPONSE_FORMAT: Any = {
    "type": "json_schema",
    "json_schema": {
        "name": "activity_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "focus_areas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"},
                            "strength": {"type": "string", "enum": list(STRENGTHS)},
                            "last_seen": {"type": "string"},
                        },
                        "required": ["topic", "strength", "last_seen"],
                        "additionalProperties": False,
                    },
                },
                "products": {"type": "array", "items": {"type": "string"}},
                "recent_shift": {"type": ["string", "null"]},
            },
            "required": ["summary", "focus_areas", "products", "recent_shift"],
            "additionalProperties": False,
        },
    },
}


class MalformedSummaryError(ValueError):
    """The model's answer cannot be turned into a summary. The message never quotes the answer."""


def user_message(rendered_input: str, previous_summary: dict[str, Any] | None, as_of: datetime.date) -> str:
    """The user turn: the day the activity ends, the previous summary and the rendered input.

    The rendered input comes from `activity_summary_inputs` as is, and the previous summary is this
    asset's own output, so no other text reaches the model."""
    previous = (
        json.dumps(
            {key: previous_summary.get(key) for key in ("summary", "focus_areas", "products")},
            ensure_ascii=False,
            sort_keys=True,
        )
        if previous_summary
        else "None"
    )
    return f"Today is {as_of.isoformat()}.\n\nPrevious summary:\n{previous}\n\nRecent activity:\n{rendered_input}"


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return None if text.lower() in _NULL_STRINGS else text


def cap_words(text: str, max_words: int = SUMMARY_MAX_WORDS) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words])


def _last_seen(value: Any) -> str | None:
    text = _clean(value)
    if text is None:
        return None
    try:
        return datetime.date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _focus_areas(value: Any) -> list[dict[str, str | None]]:
    if not isinstance(value, list):
        return []
    areas: list[dict[str, str | None]] = []
    for item in value:
        if not isinstance(item, dict) or (topic := _clean(item.get("topic"))) is None:
            continue
        strength = (_clean(item.get("strength")) or "").lower()
        areas.append(
            {
                "topic": topic,
                "strength": strength if strength in STRENGTHS else DEFAULT_STRENGTH,
                "last_seen": _last_seen(item.get("last_seen")),
            }
        )
        if len(areas) == MAX_FOCUS_AREAS:
            break
    return areas


def _products(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    products: list[str] = []
    for item in value:
        product = _clean(item)
        if product is not None and product not in products:
            products.append(product)
    return products[:MAX_PRODUCTS]


def normalize_summary(content: str | None, *, had_previous_summary: bool) -> dict[str, Any]:
    """The model's JSON answer under the output rules, or `MalformedSummaryError`.

    Only a missing or empty `summary` makes an answer malformed. Every other field degrades to an
    empty or null value, so one bad focus area does not cost the row."""
    if not content:
        raise MalformedSummaryError("empty response")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise MalformedSummaryError("response is not JSON") from error
    if not isinstance(parsed, dict):
        raise MalformedSummaryError("response is not a JSON object")
    summary = _clean(parsed.get("summary"))
    if summary is None:
        raise MalformedSummaryError("response has no summary")
    recent_shift = _clean(parsed.get("recent_shift")) if had_previous_summary else None
    return {
        "summary": cap_words(summary),
        "focus_areas": _focus_areas(parsed.get("focus_areas")),
        "products": _products(parsed.get("products")),
        "recent_shift": recent_shift,
    }


def summary_text(summary: dict[str, Any]) -> str:
    """The text that gets embedded: the summary, then the focus area topics in the model's order."""
    topics = [area["topic"] for area in summary.get("focus_areas", [])]
    return f"{summary['summary']}\nFocus areas: {'; '.join(topics)}" if topics else summary["summary"]
