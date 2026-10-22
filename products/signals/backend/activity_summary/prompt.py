"""The summary prompt, the output contract and the normalization of the model's answer.

`summary_text` is the text that gets embedded, so its format is part of the contract with every
vector already written. Bump `PROMPT_VERSION` when the prompt, the normalization or `summary_text`
changes.
"""

import json
import datetime
from typing import Any

from products.signals.backend.activity_summary.render import PROFILE_MAX_CHARS, cap_line

PROMPT_VERSION = 5

MAX_FOCUS_AREAS = 6
MAX_PRODUCTS = 10
# Per-field caps, so one runaway field cannot make the stored summary large. A cut ends at a word boundary.
MAX_TOPIC_CHARS = 80
MAX_PRODUCT_CHARS = 40
MAX_RECENT_SHIFT_CHARS = 300
MAX_HEADLINE_CHARS = 600
STRENGTHS = ("high", "medium", "low")
DEFAULT_STRENGTH = "low"
# Strings a model writes in place of a JSON null.
_NULL_STRINGS = frozenset({"", "none", "null", "n/a", "na", "nil"})

_SYSTEM_PROMPT = """You write an activity summary: what one person has been doing in one PostHog project, built only from the activity below. People and their agents read it to understand what this person works on and cares about.

The input has up to three sections, plus the previous summary if there is one:
- Tasks: work the person gave to PostHog AI or the Slack agent. Each line has the day, the tags in brackets, and the stated goal.
- Things they created or changed in PostHog: each line has the day, the action, the type and the name of the object. "(xN)" is the number of changes. "agent" is the reason their coding agent gave for the change.
- Things they opened in PostHog: one line per object, or per product for its pages. Each line has the number of distinct days they opened it, the last day, the number of days they edited it if any, and "not theirs" when someone else made it. Treat what they open on many days as part of their work, even when they changed nothing.

Each section shows a different side of the same person, and the evidence can overlap. Use your own judgment about what matters. Stay with what the input shows, and say so when something is unclear.
The activity covers only the time since the previous summary. Keep what the previous summary says unless the new activity changes it.
Give a line to every thread that has repeated evidence. Use the concrete names that the input uses, such as features, dashboards and experiments.

Write about the work, not the person: no names, emails, IDs, secrets, or quotes from the input.

Return JSON:
- `profile`: a one-page markdown profile of the person's work in this project, at most {profile_max_chars} characters. Choose your own sections.
- `headline`: two or three plain sentences that capture the profile.
- `focus_areas`: the main threads, up to 6, each with `topic`, `strength` (high, medium or low) and `last_seen` as YYYY-MM-DD.
- `products`: the PostHog products they use, by name.
- `recent_shift`: one sentence about what changed since the previous summary, or null when there is no previous summary or no real change."""


def system_prompt(profile_max_chars: int = PROFILE_MAX_CHARS) -> str:
    return _SYSTEM_PROMPT.format(profile_max_chars=profile_max_chars)


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
                "profile": {"type": "string"},
                "headline": {"type": "string"},
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
            "required": ["profile", "headline", "focus_areas", "products", "recent_shift"],
            "additionalProperties": False,
        },
    },
}


class MalformedSummaryError(ValueError):
    """The model's answer cannot be turned into a summary. The message never quotes the answer."""


def _profile(value: Any, max_chars: int) -> str | None:
    """The markdown profile with its line breaks, cut at a word boundary when it is longer than `max_chars`."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.lower() in _NULL_STRINGS:
        return None
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1]
    boundary = max(cut.rfind(" "), cut.rfind("\n"))
    return (cut[:boundary] if boundary > 0 else cut).rstrip() + "…"


def _previous(previous_summary: dict[str, Any], profile_max_chars: int) -> dict[str, Any]:
    # A summary stored before prompt version 3 has a `summary` and no `headline` or `profile`.
    # A profile stored under a larger limit gets cut to the current one, so the input stays inside the cost bound.
    return {
        "headline": previous_summary.get("headline") or previous_summary.get("summary"),
        "profile": _profile(previous_summary.get("profile"), profile_max_chars),
        "focus_areas": previous_summary.get("focus_areas"),
        "products": previous_summary.get("products"),
    }


def user_message(
    rendered_input: str,
    previous_summary: dict[str, Any] | None,
    as_of: datetime.date,
    profile_max_chars: int = PROFILE_MAX_CHARS,
) -> str:
    """The user turn: the day the activity ends, the previous summary and the rendered input.

    The rendered input comes from `build_input` as is, and the previous summary is this pipeline's
    own stored output, so no other text reaches the model."""
    previous = (
        json.dumps(_previous(previous_summary, profile_max_chars), ensure_ascii=False, sort_keys=True)
        if previous_summary
        else "None"
    )
    return f"Today is {as_of.isoformat()}.\n\nPrevious summary:\n{previous}\n\nRecent activity:\n{rendered_input}"


def _clean(value: Any, max_chars: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if text.lower() in _NULL_STRINGS:
        return None
    return cap_line(text, max_chars) if max_chars is not None else text


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
        if not isinstance(item, dict) or (topic := _clean(item.get("topic"), MAX_TOPIC_CHARS)) is None:
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
        product = _clean(item, MAX_PRODUCT_CHARS)
        if product is not None and product not in products:
            products.append(product)
    return products[:MAX_PRODUCTS]


def normalize_summary(
    content: str | None, *, had_previous_summary: bool, profile_max_chars: int = PROFILE_MAX_CHARS
) -> dict[str, Any]:
    """The model's JSON answer under the output rules, or `MalformedSummaryError`.

    Only a missing or empty `profile` or `headline` makes an answer malformed. Every other field
    degrades to an empty or null value, so one bad focus area does not cost the row."""
    if not content:
        raise MalformedSummaryError("empty response")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise MalformedSummaryError("response is not JSON") from error
    if not isinstance(parsed, dict):
        raise MalformedSummaryError("response is not a JSON object")
    profile = _profile(parsed.get("profile"), profile_max_chars)
    if profile is None:
        raise MalformedSummaryError("response has no profile")
    headline = _clean(parsed.get("headline"))
    if headline is None:
        raise MalformedSummaryError("response has no headline")
    recent_shift = _clean(parsed.get("recent_shift"), MAX_RECENT_SHIFT_CHARS) if had_previous_summary else None
    return {
        "profile": profile,
        "headline": cap_line(headline, MAX_HEADLINE_CHARS),
        "focus_areas": _focus_areas(parsed.get("focus_areas")),
        "products": _products(parsed.get("products")),
        "recent_shift": recent_shift,
    }


def summary_text(summary: dict[str, Any]) -> str:
    """The text that gets embedded: the headline, then the focus area topics in the model's order."""
    topics = [area["topic"] for area in summary.get("focus_areas", [])]
    return f"{summary['headline']}\nFocus areas: {'; '.join(topics)}" if topics else summary["headline"]
