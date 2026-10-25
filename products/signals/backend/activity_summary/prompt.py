"""The summary prompt, the output contract and the normalization of the model's answer.

`summary_text` is the text that gets embedded, so its format is part of the contract with every
vector already written. Bump `PROMPT_VERSION` when the prompt, the normalization or `summary_text`
changes.
"""

import json
import datetime
from collections.abc import Mapping
from typing import Any

from django.db import models

from products.signals.backend.activity_summary.render import PRODUCT_LABELS, PROFILE_MAX_CHARS, Product, cap_line

PROMPT_VERSION = 6

MAX_THEMES = 6
# Per-field caps, so one runaway field cannot make the stored summary large. A cut ends at a word boundary.
MAX_LABEL_CHARS = 60
MAX_RECENT_SHIFT_CHARS = 300
MAX_HEADLINE_CHARS = 600
# The computed block sits outside the render budget, so it has its own caps. `max_update_cost_usd` counts them.
COMPUTED_LINE_CHARS = 200
COMPUTED_MAX_CHARS = 8000
STRENGTHS = ("high", "medium", "low")
DEFAULT_STRENGTH = "low"
# Strings a model writes in place of a JSON null.
_NULL_STRINGS = frozenset({"", "none", "null", "n/a", "na", "nil"})


class ActivitySummaryMode(models.TextChoices):
    """How a person works on a theme, or in the project overall."""

    BUILDING = "building"
    ANALYZING = "analyzing"
    MONITORING = "monitoring"
    INVESTIGATING = "investigating"
    OPERATING = "operating"
    EXPERIMENTING = "experimenting"


MODES = tuple(str(mode) for mode in ActivitySummaryMode)

_SYSTEM_PROMPT = """You write an activity summary: what one person works on and cares about in one PostHog project, built only from the input below. Other features read it to rank inbox reports, to pick reviewers and to route work. Write for a reader who needs facts they can act on.

The input has these parts:
- Objects and pages: a list that code computed from the last weeks of activity. Each line starts with a ref. An "o" ref is an object. An object they edited shows the number of days with edits, and "created" when they made it. An object they only opened shows the number of days they opened it, and "not theirs" when someone else made it. A "p" ref is the pages of one product. The list ends with the products they work in and the products they only visit.
- Tasks: work the person gave to PostHog AI or the Slack agent. Each line has the day, the tags in brackets and the goal. "(xN)" is the number of runs.
- Things they created or changed in PostHog: each line has the day, the action, the type and the name of the object. "(xN)" is the number of changes. "agent" is the reason their coding agent gave for the change.
- Things they opened in PostHog: one line per object, or per product for its pages, with the number of days they opened it and the last day.
- The previous summary, when there is one.

The tasks and the lines of changes and opens cover only the time since the previous summary. Keep what the previous summary says unless the new activity changes it.

How to write:
- Be concrete. Name the dashboards, insights, flags, experiments, accounts, features and goals that matter. Use the names that the input uses.
- Be selective. Write about the work that repeats and the objects the person owns or opens again and again. Leave out one-time visits and setup chores.
- Summarize a long list by count and topic, such as "12 insights about checkout conversion".
- Write plain statements. Do not hedge, and do not write about what the input does not show.
- Write about the work, not a job title.

Return JSON:
- `headline`: one or two sentences about what they work on and care about in this project.
- `themes`: 3 to 6 threads of work, the strongest first. Give fewer only when the input shows fewer. Each theme has:
  - `label`: the topic of the thread in at most 60 characters, such as "Experiment recalculation reliability". Name the topic, not a list of objects.
  - `mode`: one of {modes}.
  - `strength`: high, medium or low, by how much of the activity is about this thread.
  - `refs`: the refs from the objects and pages list that show this thread. Every theme needs at least one ref.
- `modes`: the modes that describe how they work in this project overall, from the same list, the main one first.
- `profile`: markdown, at most {profile_max_chars} characters, with these sections in this order:
  - `## Working on`: the threads they build or change, with the objects by name.
  - `## Keeps an eye on`: what they open again and again but do not change.
  - `## Recently asked about`: what they asked PostHog AI or the Slack agent. Only when there are tasks.
  - `## Earlier context`: what the previous summary says that the new activity does not repeat. Only when there is a previous summary.
  Leave out a section that has nothing to say. Do not add other sections, such as one for page visits or for evidence.
- `recent_shift`: one sentence about what changed since the previous summary, or null when there is no previous summary or no real change."""


def system_prompt(profile_max_chars: int = PROFILE_MAX_CHARS) -> str:
    return _SYSTEM_PROMPT.format(profile_max_chars=profile_max_chars, modes=", ".join(MODES))


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
                "headline": {"type": "string"},
                "themes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "mode": {"type": "string", "enum": list(MODES)},
                            "strength": {"type": "string", "enum": list(STRENGTHS)},
                            "refs": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["label", "mode", "strength", "refs"],
                        "additionalProperties": False,
                    },
                },
                "modes": {"type": "array", "items": {"type": "string", "enum": list(MODES)}},
                "profile": {"type": "string"},
                "recent_shift": {"type": ["string", "null"]},
            },
            "required": ["headline", "themes", "modes", "profile", "recent_shift"],
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
    # A ref is valid only inside one update, so the themes go without their refs.
    themes = previous_summary.get("themes")
    return {
        "headline": previous_summary.get("headline") or previous_summary.get("summary"),
        "profile": _profile(previous_summary.get("profile"), profile_max_chars),
        "themes": [
            {key: theme.get(key) for key in ("label", "mode", "strength", "last_seen")}
            for theme in themes
            if isinstance(theme, dict)
        ]
        if isinstance(themes, list)
        else None,
        "modes": previous_summary.get("modes"),
    }


def _product_label(key: str) -> str:
    return PRODUCT_LABELS.get(Product(key), key) if key in Product._value2member_map_ else key


def computed_lines(computed: Mapping[str, Any] | None) -> str:
    """The computed lists of `computed.py` with their refs, at most `COMPUTED_MAX_CHARS` long.

    The products come first, then one line per object or product page, so a cut drops the least used ones."""
    if not computed:
        return "None"
    lines: list[str] = []
    products = computed.get("products", {})
    for title, key in (("Products they work in", "works_in"), ("Products they only visit", "visits")):
        if names := [_product_label(product) for product in products.get(key, [])]:
            lines.append(f"{title}: {', '.join(names)}")
    for item in computed.get("owned", []):
        created = ", created" if item["created"] else ""
        lines.append(
            f'- {item["ref"]} {item["type"]} "{item["name"]}": edited on {item["edit_days"]} days, last {item["last_at"]}{created}'
        )
    for item in computed.get("watched", []):
        not_theirs = ", not theirs" if item["not_theirs"] else ""
        lines.append(
            f'- {item["ref"]} {item["type"]} "{item["name"]}": opened on {item["open_days"]} days, last {item["last_at"]}{not_theirs}'
        )
    for item in computed.get("pages", []):
        lines.append(
            f"- {item['ref']} {_product_label(item['product'])} pages: opened on {item['open_days']} days, last {item['last_at']}"
        )
    kept: list[str] = []
    chars = 0
    for line in (cap_line(line, COMPUTED_LINE_CHARS) for line in lines):
        if chars + len(line) + 1 > COMPUTED_MAX_CHARS:
            break
        kept.append(line)
        chars += len(line) + 1
    return "\n".join(kept) or "None"


def user_message(
    rendered_input: str,
    previous_summary: dict[str, Any] | None,
    as_of: datetime.date,
    profile_max_chars: int = PROFILE_MAX_CHARS,
    computed: Mapping[str, Any] | None = None,
) -> str:
    """The user turn: the day the activity ends, the previous summary, the computed lists and the rendered input.

    The rendered input comes from `build_input` as is, the computed lists from `compute_fields`, and the
    previous summary is this pipeline's own stored output, so no other text reaches the model."""
    previous = (
        json.dumps(_previous(previous_summary, profile_max_chars), ensure_ascii=False, sort_keys=True)
        if previous_summary
        else "None"
    )
    return (
        f"Today is {as_of.isoformat()}.\n\nPrevious summary:\n{previous}\n\n"
        f"Objects and pages:\n{computed_lines(computed)}\n\nRecent activity:\n{rendered_input}"
    )


def _clean(value: Any, max_chars: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if text.lower() in _NULL_STRINGS:
        return None
    return cap_line(text, max_chars) if max_chars is not None else text


def ref_days(computed: Mapping[str, Any] | None) -> dict[str, str]:
    """The last day of each ref in the computed lists."""
    if not computed:
        return {}
    return {item["ref"]: item["last_at"] for key in ("owned", "watched", "pages") for item in computed.get(key, [])}


def _mode(value: Any) -> str | None:
    mode = (_clean(value) or "").lower()
    return mode if mode in MODES else None


def _themes(value: Any, days: Mapping[str, str]) -> list[dict[str, Any]]:
    """At most `MAX_THEMES` themes. A theme keeps only the refs in `days`, and a theme with none is dropped."""
    if not isinstance(value, list):
        return []
    themes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or (label := _clean(item.get("label"), MAX_LABEL_CHARS)) is None:
            continue
        raw_refs = item.get("refs")
        refs: list[str] = []
        for raw in raw_refs if isinstance(raw_refs, list) else []:
            if (ref := _clean(raw)) is not None and ref in days and ref not in refs:
                refs.append(ref)
        if not refs:
            continue
        strength = (_clean(item.get("strength")) or "").lower()
        themes.append(
            {
                "label": label,
                "mode": _mode(item.get("mode")),
                "strength": strength if strength in STRENGTHS else DEFAULT_STRENGTH,
                "refs": refs,
                "last_seen": max(days[ref] for ref in refs),
            }
        )
        if len(themes) == MAX_THEMES:
            break
    return themes


def _modes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(mode for item in value if (mode := _mode(item)) is not None))


def normalize_summary(
    content: str | None,
    *,
    had_previous_summary: bool,
    computed: Mapping[str, Any] | None = None,
    profile_max_chars: int = PROFILE_MAX_CHARS,
) -> dict[str, Any]:
    """The model's JSON answer under the output rules, or `MalformedSummaryError`.

    Only a missing or empty `profile` or `headline` makes an answer malformed. Every other field
    degrades to an empty or null value, so one bad theme does not cost the row. A theme ref must be
    in `computed`, and a theme's `last_seen` is the last day of its refs."""
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
        "themes": _themes(parsed.get("themes"), ref_days(computed)),
        "modes": _modes(parsed.get("modes")),
        "recent_shift": recent_shift,
    }


def summary_text(summary: dict[str, Any]) -> str:
    """The text that gets embedded: the headline, then the theme labels in the model's order."""
    labels = [theme["label"] for theme in summary.get("themes", [])]
    return f"{summary['headline']}\nThemes: {'; '.join(labels)}" if labels else summary["headline"]
