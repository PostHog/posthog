"""Customer product context for scanner prompts: Max core memory + event definition descriptions.

Both sources are customer-authored text rendered into the trusted preamble, so everything is
sanitized (control chars stripped, backticks replaced, whitespace collapsed, length-capped)
before it is stored.
"""

import re
from collections import Counter
from collections.abc import Mapping
from functools import cache
from typing import Any

from django.db.models import Q

from posthog.llm.semantic_enrichment import get_team_business_context
from posthog.models import Team
from posthog.settings import EE_AVAILABLE

# CoreMemory.text is model-capped at 10k chars; cap lower since the preamble is resent on every scan step.
_MAX_PRODUCT_CONTEXT_LEN = 4000
_MAX_EVENT_DESCRIPTIONS = 50
_MAX_EVENT_DESCRIPTION_LEN = 500
# Bound the name list sent to Postgres when a session emits a pathological number of distinct events.
_MAX_LOOKUP_NAMES = 300

# \x0a (newline) is excluded so `keep_newlines` callers can preserve line structure.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")


@cache
def _core_event_names() -> frozenset[str]:
    """Built-in event names, which the model already knows and the preamble explains by hand."""
    # Deferred: the taxonomy module is a ~4000-line dict this worker otherwise never loads.
    from posthog.taxonomy.taxonomy import CORE_FILTER_DEFINITIONS_BY_GROUP  # noqa: PLC0415

    return frozenset(CORE_FILTER_DEFINITIONS_BY_GROUP["events"])


def _sanitize(text: str, max_len: int, *, keep_newlines: bool = False) -> str:
    # Backticks become apostrophes because the preamble fences these values as inline code.
    stripped = _CONTROL_CHARS_RE.sub(" ", text).replace("`", "'")
    if keep_newlines:
        lines = [" ".join(line.split()) for line in stripped.split("\n")]
        cleaned = "\n".join(line for line in lines if line)
    else:
        cleaned = " ".join(stripped.split())
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len] + "…"
    return cleaned


def sanitize_product_context(text: str) -> str:
    # Core memory is one fact per line; keep the newlines so the model sees a list, not a wall of text.
    return _sanitize(text, _MAX_PRODUCT_CONTEXT_LEN, keep_newlines=True)


def fetch_product_context(team: Team) -> str:
    """The team's Max core memory, falling back to the project's (deprecated) product description; "" when neither exists."""
    text = get_team_business_context(team)
    if not text:
        text = (team.project.product_description or "").strip()
    return sanitize_product_context(text)


def _event_names_by_frequency(columns: list[str], rows: list[list[Any]]) -> list[str]:
    """Distinct event names, most frequent first (counted over deduplicated rows), alphabetical tie-break."""
    if "event" not in columns:
        return []
    event_index = columns.index("event")
    counts = Counter(row[event_index] for row in rows if isinstance(row[event_index], str) and row[event_index])
    return [name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def session_custom_event_names(columns: list[str], rows: list[list[Any]]) -> list[str]:
    """This session's custom event names, most frequent first, capped for the description lookup."""
    # A backtick in a name would escape the prompt's inline-code fencing; drop such names rather than rewrite an identifier.
    return [
        name for name in _event_names_by_frequency(columns, rows) if name not in _core_event_names() and "`" not in name
    ][:_MAX_LOOKUP_NAMES]


def select_event_descriptions(custom_names: list[str], found: Mapping[str, str | None]) -> dict[str, str]:
    """Sanitize and cap the looked-up descriptions, preserving the frequency order of `custom_names`."""
    described: dict[str, str] = {}
    for name in custom_names:
        if sanitized := _sanitize(found.get(name) or "", _MAX_EVENT_DESCRIPTION_LEN):
            described[name] = sanitized
            if len(described) >= _MAX_EVENT_DESCRIPTIONS:
                break
    return described


def fetch_event_descriptions(team: Team, columns: list[str], rows: list[list[Any]]) -> dict[str, str]:
    """Customer-written descriptions for this session's custom events, keyed by name, most frequent first.

    Descriptions only exist on the enterprise EventDefinition model, so this is a no-op on OSS builds.
    """
    if not EE_AVAILABLE:
        return {}
    from ee.models.event_definition import EnterpriseEventDefinition  # noqa: PLC0415 — absent from OSS builds

    custom_names = session_custom_event_names(columns, rows)
    found = dict(
        EnterpriseEventDefinition.objects.filter(
            # Definitions are project-scoped with a team-scoped legacy fallback; mirrors posthog/api/event_definition.py.
            Q(project_id=team.project_id) | Q(project_id__isnull=True, team_id=team.project_id),
            name__in=custom_names,
        )
        .exclude(description__isnull=True)
        .exclude(description="")
        .values_list("name", "description")
    )
    return select_event_descriptions(custom_names, found)
