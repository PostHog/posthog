"""Metadata suggestions for insights and dashboards, ranked by TypeSafe's Jev classifier.

Jev does not write text. It picks one option from a list and returns a calibrated probability, so
every suggestion here has two halves: this module builds the candidates deterministically from the
query, the tile names, and the existing metadata, and Jev picks the candidate that best fits. The
same shape covers a title, a description, which of the team's tags apply, and which dashboard is
the best home for an insight.

User text (the current name, description, tag names, tile names) always lives in the ``state``
document and is referenced from the question by path. It is never interpolated into instructions,
so a person's title cannot steer the question.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Literal

from django.conf import settings

import structlog
import posthoganalytics

from posthog.schema import ActorsQuery, EventsQuery, GroupsQuery, InsightVizNode

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.client import ChoiceAnswer, ChoiceQuestion, NoulAnswer, NoulQuestion, system_one
from posthog.models import Team

logger = structlog.get_logger(__name__)

# Shared with FEATURE_FLAGS in frontend/src/lib/constants.tsx.
SUGGESTIONS_FLAG = "product-analytics-typesafe-suggestions"
EGRESS_SOURCE = "product_analytics_suggestions"

Subject = Literal["insight", "dashboard"]
MetadataQuery = InsightVizNode | ActorsQuery | EventsQuery | GroupsQuery

# A tag with a lower probability is more likely wrong than right for the person to have to remove.
TAG_THRESHOLD = 0.6
# TypeSafe caps a choice question at 255 options; one option stays free for "none".
MAX_TAG_QUESTIONS = 100
MAX_DASHBOARD_OPTIONS = 254
MAX_TEXT_CANDIDATES = 16


@frozen
class SubjectContext:
    """What Jev is told about the insight or dashboard. Everything here is state, not instruction.
    The query itself never reaches Jev: ``_query_summary`` turns it into lines without filter values."""

    subject: Subject
    name: str = ""
    description: str = ""
    query: MetadataQuery | None = None
    tile_names: tuple[str, ...] = ()


@frozen
class TextSuggestion:
    value: str
    confidence: float
    candidates: tuple[str, ...]


@frozen
class TagSuggestion:
    tags: tuple[str, ...]
    scores: Mapping[str, float]


@frozen
class DashboardCandidate:
    id: int
    name: str
    description: str = ""


@frozen
class DashboardSuggestion:
    dashboard_id: int | None
    confidence: float


def suggestions_enabled(team: Team) -> bool:
    """Whether this team may send metadata to TypeSafe. Fails closed on a flag-eval blip, because
    TypeSafe is not a listed subprocessor and the flag is the only thing that keeps data in-house."""
    if not settings.TYPESAFE_API_KEY:
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                SUGGESTIONS_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        logger.warning("typesafe_suggestions.flag_check_failed", team_id=team.id, exc_info=True)
        return False


def validate_metadata_query(query_data: Mapping[str, object]) -> MetadataQuery:
    """Parse the same query shapes the OpenAI metadata endpoint accepts. Raises ``ValueError``."""
    kind = query_data.get("kind")
    try:
        if kind == "ActorsQuery":
            return ActorsQuery.model_validate(query_data)
        if kind == "EventsQuery":
            return EventsQuery.model_validate(query_data)
        if kind == "GroupsQuery":
            return GroupsQuery.model_validate(query_data)
        return InsightVizNode.model_validate(query_data)
    except Exception as error:
        raise ValueError("Invalid query format") from error


# ---------------------------------------------------------------------------
# Humanizing query parts
# ---------------------------------------------------------------------------

_EVENT_LABELS: dict[str, str] = {
    "$pageview": "pageviews",
    "$pageleave": "pageleaves",
    "$screen": "screen views",
    "$autocapture": "autocaptured interactions",
    "$identify": "identifies",
    "$rageclick": "rage clicks",
    "$exception": "exceptions",
    "$web_vitals": "web vitals",
    "$feature_flag_called": "feature flag calls",
}

_MATH_LABELS: dict[str, str] = {
    "dau": "unique users",
    "weekly_active": "weekly active users",
    "monthly_active": "monthly active users",
    "unique_session": "unique sessions",
    "first_time_for_user": "first-time users",
    "avg_count_per_actor": "average per user",
    "median_count_per_actor": "median per user",
    "avg": "average",
    "sum": "sum",
    "min": "minimum",
    "max": "maximum",
    "median": "median",
    "p90": "p90",
    "p95": "p95",
    "p99": "p99",
}

_INTERVAL_ADJECTIVES: dict[str, str] = {
    "minute": "Per-minute",
    "hour": "Hourly",
    "day": "Daily",
    "week": "Weekly",
    "month": "Monthly",
    "quarter": "Quarterly",
    "year": "Yearly",
}

_RELATIVE_RANGE = re.compile(r"^-(\d+)([hdwmqy])$")
_RANGE_UNITS: dict[str, str] = {"h": "hour", "d": "day", "w": "week", "m": "month", "q": "quarter", "y": "year"}
_PERIOD_ADJECTIVES: dict[str, str] = {"hour": "Hourly", "day": "Daily", "week": "Weekly", "month": "Monthly"}
_START_RANGES: dict[str, str] = {
    "dStart": "today",
    "wStart": "this week",
    "mStart": "this month",
    "qStart": "this quarter",
    "yStart": "this year",
    "all": "all time",
}


def humanize_event(name: str) -> str:
    if name in _EVENT_LABELS:
        return _EVENT_LABELS[name]
    return re.sub(r"[_\-]+", " ", name.lstrip("$")).strip() or "all events"


def humanize_date_range(date_from: str | None) -> str | None:
    if not date_from:
        return None
    if date_from in _START_RANGES:
        return _START_RANGES[date_from]
    match = _RELATIVE_RANGE.match(date_from)
    if match:
        count, unit = int(match.group(1)), _RANGE_UNITS[match.group(2)]
        return f"the last {unit}" if count == 1 else f"the last {count} {unit}s"
    return f"since {date_from[:10]}"


def sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def join_words(parts: Sequence[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + f" and {parts[-1]}"


def _series_label(item: object) -> str:
    custom_name = getattr(item, "custom_name", None)
    if custom_name:
        return str(custom_name)
    event = getattr(item, "event", None)
    if event:
        return humanize_event(str(event))
    name = getattr(item, "name", None)
    if name:
        return str(name)
    table_name = getattr(item, "table_name", None)
    if table_name:
        return str(table_name)
    return "all events"


def _series_math(item: object) -> str | None:
    math = getattr(item, "math", None)
    if not math:
        return None
    label = _MATH_LABELS.get(str(math))
    math_property = getattr(item, "math_property", None)
    if label and math_property:
        return f"{label} of {math_property}"
    return label


# How a series reads when its math has to be spelled out to tell it apart from a sibling series.
_MATH_PHRASES: dict[str, str] = {
    "total": "total {label}",
    "dau": "unique users for {label}",
    "weekly_active": "weekly active users for {label}",
    "monthly_active": "monthly active users for {label}",
    "unique_session": "unique sessions with {label}",
    "first_time_for_user": "first-time users for {label}",
}

# What one unit of a series is called when another series is divided by it.
_PER_UNITS: dict[str, str] = {
    "dau": "user",
    "weekly_active": "weekly active user",
    "monthly_active": "monthly active user",
    "unique_session": "session",
    "first_time_for_user": "new user",
}

_BINARY_FORMULA = re.compile(r"^\s*([A-Z])\s*([/*+\-])\s*([A-Z])\s*(\*\s*100)?\s*$")


def _series_labels(source: object) -> list[str]:
    """Labels for every series. Two series on the same event get their math spelled out so a title
    never reads 'pageviews and pageviews'."""
    items = list(getattr(source, "series", None) or [])
    labels = [_series_label(item) for item in items]
    duplicates = {label for label in labels if labels.count(label) > 1}
    if not duplicates:
        return labels
    distinct: list[str] = []
    for item, label in zip(items, labels):
        if label in duplicates:
            math = str(getattr(item, "math", None) or "total")
            phrase = _MATH_PHRASES.get(math)
            math_label = _series_math(item)
            if phrase:
                label = phrase.format(label=label)
            elif math_label:
                label = f"{math_label} of {label}"
        distinct.append(label)
    return distinct


@frozen
class FormulaReading:
    """A trends formula turned into words: what it computes and how to say it in a title."""

    formula: str
    custom_name: str | None
    titles: tuple[str, ...]
    descriptions: tuple[str, ...]


def _formulas(source: object) -> list[tuple[str, str | None]]:
    trends_filter = getattr(source, "trendsFilter", None)
    if trends_filter is None:
        return []
    found: list[tuple[str, str | None]] = []
    for node in getattr(trends_filter, "formulaNodes", None) or []:
        found.append((str(node.formula), node.custom_name or None))
    if not found:
        for formula in getattr(trends_filter, "formulas", None) or []:
            found.append((str(formula), None))
    if not found and getattr(trends_filter, "formula", None):
        found.append((str(trends_filter.formula), None))
    return found


def _read_formula(source: object, formula: str, custom_name: str | None, range_text: str | None) -> FormulaReading:
    items = list(getattr(source, "series", None) or [])
    labels = [_series_label(item) for item in items]
    over_range = f" over {range_text}" if range_text else ""
    titles: list[str] = [custom_name] if custom_name else []
    descriptions: list[str] = []
    match = _BINARY_FORMULA.match(formula)
    if match:
        left, operator, right, percent = match.groups()
        left_index, right_index = ord(left) - ord("A"), ord(right) - ord("A")
        if 0 <= left_index < len(items) and 0 <= right_index < len(items):
            x, y = labels[left_index], labels[right_index]
            y_math = str(getattr(items[right_index], "math", None) or "total")
            unit = _PER_UNITS.get(y_math)
            if operator == "/" and percent:
                titles += [f"{sentence_case(x)} as a percentage of {y}", f"{sentence_case(x)} rate"]
                descriptions += [f"Shows {x} as a percentage of {y}{over_range}."]
            elif operator == "/" and unit:
                titles += [f"Total {x} per {unit}", f"{sentence_case(x)} per {unit}", f"Average {x} per {unit}"]
                descriptions += [
                    f"Divides total {x} by the number of unique {unit}s to show {x} per {unit}{over_range}.",
                    f"Shows how many {x} each {unit} generates{over_range}.",
                ]
            elif operator == "/":
                titles += [f"{sentence_case(x)} per {y}", f"Ratio of {x} to {y}"]
                descriptions += [f"Divides {x} by {y}{over_range}."]
            elif operator == "-":
                titles += [f"{sentence_case(x)} minus {y}", f"Difference between {x} and {y}"]
                descriptions += [f"Subtracts {y} from {x}{over_range}."]
            elif operator == "+":
                titles += [f"{sentence_case(x)} plus {y}", f"Combined {x} and {y}"]
                descriptions += [f"Adds {x} and {y} together{over_range}."]
            elif operator == "*":
                titles += [f"{sentence_case(x)} times {y}"]
                descriptions += [f"Multiplies {x} by {y}{over_range}."]
    if not titles:
        titles.append(f"Formula {formula}")
    if not descriptions:
        descriptions.append(f"Plots the formula {formula} over the series{over_range}.")
    return FormulaReading(
        formula=formula, custom_name=custom_name, titles=tuple(titles), descriptions=tuple(descriptions)
    )


def _entity_label(entity: object) -> str:
    if entity is None:
        return "an event"
    custom_name = getattr(entity, "custom_name", None) or getattr(entity, "name", None)
    if custom_name:
        return humanize_event(str(custom_name))
    identifier = getattr(entity, "id", None)
    return humanize_event(str(identifier)) if identifier else "an event"


def _breakdown_label(source: object) -> str | None:
    breakdown_filter = getattr(source, "breakdownFilter", None)
    if breakdown_filter is None:
        return None
    if breakdown_filter.breakdowns:
        return join_words([str(b.property) for b in breakdown_filter.breakdowns])
    if breakdown_filter.breakdown:
        return str(breakdown_filter.breakdown)
    return None


def _dedupe(candidates: Iterable[str | None], limit: int = MAX_TEXT_CANDIDATES) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for candidate in candidates:
        cleaned = " ".join((candidate or "").split())
        if cleaned and cleaned.lower() not in {key.lower() for key in seen}:
            seen[cleaned] = None
        if len(seen) >= limit:
            break
    return tuple(seen)


# ---------------------------------------------------------------------------
# Candidates
# ---------------------------------------------------------------------------


def _viz_title_candidates(query: InsightVizNode) -> list[str | None]:
    source = query.source
    kind = source.kind
    series = _series_labels(source)
    maths = [_series_math(item) for item in getattr(source, "series", None) or []]
    breakdown = _breakdown_label(source)
    date_range = getattr(source, "dateRange", None)
    range_text = humanize_date_range(getattr(date_range, "date_from", None)) if date_range else None
    interval = getattr(source, "interval", None)
    joined = join_words(series)

    if kind == "FunnelsQuery" and series:
        first, last = series[0], series[-1]
        return [
            f"{sentence_case(first)} → {last} conversion",
            f"{sentence_case(first)} to {last} funnel",
            f"Conversion: {' → '.join(series)}" if len(series) <= 4 else None,
            f"How many users get from {first} to {last}",
            f"{sentence_case(first)} → {last} conversion over {range_text}" if range_text else None,
        ]
    if kind == "RetentionQuery":
        retention_filter = getattr(source, "retentionFilter", None)
        target = _entity_label(getattr(retention_filter, "targetEntity", None))
        returning = _entity_label(getattr(retention_filter, "returningEntity", None))
        period = str(getattr(retention_filter, "period", None) or "week").lower()
        return [
            f"Retention after {target}",
            f"{_PERIOD_ADJECTIVES.get(period, period.capitalize())} retention: {target} → {returning}",
            f"Users who return to {returning} after {target}",
            f"{sentence_case(target)} retention",
        ]
    if kind == "StickinessQuery" and series:
        return [
            f"{sentence_case(joined)} stickiness",
            f"How often users repeat {joined}",
            f"{sentence_case(joined)} frequency",
        ]
    if kind == "LifecycleQuery" and series:
        return [
            f"{sentence_case(joined)} lifecycle",
            f"New, returning and dormant users for {joined}",
            f"User lifecycle: {joined}",
        ]
    if kind == "PathsQuery":
        paths_filter = getattr(source, "pathsFilter", None)
        start = getattr(paths_filter, "startPoint", None)
        end = getattr(paths_filter, "endPoint", None)
        return [
            "User paths",
            f"Paths from {start}" if start else None,
            f"Paths to {end}" if end else None,
            f"Paths from {start} to {end}" if start and end else None,
            "Where users go next",
        ]
    if series:
        notable_math = join_words([math for math in maths if math])
        formula_titles = [
            title
            for formula, custom_name in _formulas(source)
            for title in _read_formula(source, formula, custom_name, range_text).titles
        ]
        return [
            *formula_titles,
            sentence_case(joined),
            f"{sentence_case(joined)} by {breakdown}" if breakdown else None,
            f"{_INTERVAL_ADJECTIVES[str(interval)]} {joined}"
            if interval and str(interval) in _INTERVAL_ADJECTIVES
            else None,
            f"{sentence_case(joined)} over {range_text}" if range_text else None,
            f"{sentence_case(notable_math)} for {joined}" if notable_math and len(series) == 1 else None,
            f"{sentence_case(joined)} over time",
            f"{sentence_case(joined)} by {breakdown} over {range_text}" if breakdown and range_text else None,
        ]
    return [sentence_case(kind.replace("Query", "")) + " insight"]


def _viz_description_candidates(query: InsightVizNode) -> list[str | None]:
    source = query.source
    kind = source.kind
    series = _series_labels(source)
    maths = [_series_math(item) for item in getattr(source, "series", None) or []]
    breakdown = _breakdown_label(source)
    date_range = getattr(source, "dateRange", None)
    range_text = humanize_date_range(getattr(date_range, "date_from", None)) if date_range else None
    interval = getattr(source, "interval", None)
    joined = join_words(series)
    over_range = f" over {range_text}" if range_text else ""
    by_breakdown = f", broken down by {breakdown}" if breakdown else ""

    if kind == "FunnelsQuery" and series:
        first, last = series[0], series[-1]
        return [
            f"Measures how many users go from {first} to {last}{over_range}.",
            f"Conversion funnel through {' → '.join(series)}{by_breakdown}.",
            f"Shows where users drop off between {first} and {last}.",
        ]
    if kind == "RetentionQuery":
        retention_filter = getattr(source, "retentionFilter", None)
        target = _entity_label(getattr(retention_filter, "targetEntity", None))
        returning = _entity_label(getattr(retention_filter, "returningEntity", None))
        period = str(getattr(retention_filter, "period", None) or "week").lower()
        return [
            f"Shows how many users who did {target} come back to do {returning} in the following {period}s.",
            f"{_PERIOD_ADJECTIVES.get(period, period.capitalize())} retention of users after {target}.",
            f"Tracks whether users keep coming back after {target}.",
        ]
    if kind == "StickinessQuery" and series:
        return [
            f"Shows how many distinct {str(interval or 'day')}s users did {joined}{over_range}.",
            f"Measures how habitually users come back for {joined}.",
        ]
    if kind == "LifecycleQuery" and series:
        return [
            f"Splits users who did {joined} into new, returning, resurrecting and dormant{over_range}.",
            f"Shows whether growth in {joined} comes from new or returning users.",
        ]
    if kind == "PathsQuery":
        paths_filter = getattr(source, "pathsFilter", None)
        start = getattr(paths_filter, "startPoint", None)
        end = getattr(paths_filter, "endPoint", None)
        return [
            f"Shows the sequences users take{f' starting at {start}' if start else ''}{f' before reaching {end}' if end else ''}.",
            "Shows the most common routes users take through the product.",
        ]
    if series:
        notable_math = join_words([math for math in maths if math])
        adverb = f" {str(interval)} by {str(interval)}" if interval else ""
        formula_descriptions = [
            description
            for formula, custom_name in _formulas(source)
            for description in _read_formula(source, formula, custom_name, range_text).descriptions
        ]
        return [
            *formula_descriptions,
            f"Shows {joined}{adverb}{over_range}{by_breakdown}.",
            f"Tracks how {joined} changes over time{f' for each {breakdown}' if breakdown else ''}.",
            f"Counts {notable_math} for {joined}{by_breakdown}." if notable_math and len(series) == 1 else None,
            f"Compares {joined} across {breakdown}." if breakdown and len(series) == 1 else None,
        ]
    return [f"A {kind.replace('Query', '').lower()} insight."]


def _table_title_candidates(query: ActorsQuery | EventsQuery | GroupsQuery) -> list[str | None]:
    if isinstance(query, EventsQuery):
        event = humanize_event(query.event) if query.event else "events"
        return [f"Recent {event}", sentence_case(event), f"{sentence_case(event)} list", "Event list"]
    if isinstance(query, GroupsQuery):
        return ["Groups", "Group list", "All groups"]
    return ["Persons", "Person list", "Matching persons"]


def _table_description_candidates(query: ActorsQuery | EventsQuery | GroupsQuery) -> list[str | None]:
    if isinstance(query, EventsQuery):
        event = humanize_event(query.event) if query.event else "events"
        return [f"A table of {event} matching the current filters.", f"Lists recent {event} one row per event."]
    if isinstance(query, GroupsQuery):
        return ["A table of groups matching the current filters."]
    return ["A table of persons matching the current filters.", "Lists the people this insight selects."]


# Broad dashboard themes give Jev a fixed vocabulary to choose a dashboard title from. Tile names
# alone rarely make a good title, so each theme becomes an "overview" candidate.
_DASHBOARD_THEMES: dict[str, str] = {
    "acquisition": "how people find and sign up for the product",
    "activation": "whether new users reach their first value",
    "engagement": "how much and how often people use the product",
    "retention": "whether people keep coming back",
    "revenue": "money, plans, and payments",
    "growth": "top-line growth across the funnel",
    "marketing": "campaigns, channels, and website traffic",
    "product usage": "which features people use",
    "performance": "speed, errors, and reliability",
    "operations": "internal team or business operations",
}


def _dashboard_title_candidates(context: SubjectContext) -> list[str | None]:
    tiles = [name for name in context.tile_names if name]
    return [
        *[f"{theme.capitalize()} overview" for theme in _DASHBOARD_THEMES],
        join_words([sentence_case(tiles[0]), *tiles[1:3]]) if 0 < len(tiles) <= 3 else None,
        f"{sentence_case(tiles[0])} and related metrics" if tiles else None,
    ]


def _dashboard_description_candidates(context: SubjectContext) -> list[str | None]:
    tiles = [name for name in context.tile_names if name]
    count = len(tiles)
    examples = join_words(tiles[:3])
    including = f", including {examples}" if examples else ""
    return [
        *[f"Tracks {focus} across {count} insights{including}." for focus in _DASHBOARD_THEMES.values()],
        f"Brings together {count} insights{including}." if count else None,
    ]


def title_candidates(context: SubjectContext) -> tuple[str, ...]:
    if context.subject == "dashboard":
        generated = _dashboard_title_candidates(context)
    elif isinstance(context.query, InsightVizNode):
        generated = _viz_title_candidates(context.query)
    elif context.query is not None:
        generated = _table_title_candidates(context.query)
    else:
        generated = []
    return _dedupe([context.name, *generated])


def description_candidates(context: SubjectContext) -> tuple[str, ...]:
    if context.subject == "dashboard":
        generated = _dashboard_description_candidates(context)
    elif isinstance(context.query, InsightVizNode):
        generated = _viz_description_candidates(context.query)
    elif context.query is not None:
        generated = _table_description_candidates(context.query)
    else:
        generated = []
    return _dedupe([context.description, *generated])


# ---------------------------------------------------------------------------
# Asking Jev
# ---------------------------------------------------------------------------


def _filter_keys(properties: object) -> list[str]:
    """Property filter keys and operators, never values. Values are what people type into filters
    (emails, ids, URLs), and they must not leave PostHog for a title suggestion."""
    keys: list[str] = []
    stack: list[object] = [properties]
    while stack:
        current = stack.pop()
        if current is None:
            continue
        if isinstance(current, list | tuple):
            stack.extend(current)
            continue
        nested = getattr(current, "values", None)
        if nested is not None and not isinstance(nested, str):
            stack.append(nested)
            continue
        key = getattr(current, "key", None)
        if getattr(current, "type", None) == "cohort":
            keys.append("cohort membership")
        elif key:
            operator = getattr(current, "operator", None)
            keys.append(f"{key} {str(operator).split('.')[-1]}" if operator else str(key))
    return keys


def _query_summary(query: MetadataQuery) -> list[str]:
    """Plain-language lines about the query. This is all Jev sees of the query: the raw JSON stays
    in PostHog because it carries filter values, HogQL and identifiers a person typed."""
    if not isinstance(query, InsightVizNode):
        lines = [f"Type: {query.kind}"]
        keys = _filter_keys(getattr(query, "properties", None))
        if keys:
            lines.append(f"Filtered on: {join_words(keys)}")
        return lines
    source = query.source
    lines = [f"Type: {source.kind.replace('Query', '')}"]
    items = list(getattr(source, "series", None) or [])
    labels = _series_labels(source)
    step_word = "Step" if source.kind == "FunnelsQuery" else "Series"
    for index, (item, label) in enumerate(zip(items, labels)):
        math = _series_math(item) or ("total count" if getattr(item, "math", None) in (None, "total") else None)
        item_filters = _filter_keys(getattr(item, "properties", None))
        line = f"{step_word} {chr(ord('A') + index)}: {label}"
        if math and source.kind not in ("FunnelsQuery", "PathsQuery"):
            line += f" ({math})"
        if item_filters:
            line += f", filtered on {join_words(item_filters)}"
        lines.append(line)
    for formula, custom_name in _formulas(source):
        reading = _read_formula(source, formula, custom_name, None)
        lines.append(f"Formula: {formula}, which means {reading.titles[0].lower()}. Only the formula is plotted.")
    funnels_filter = getattr(source, "funnelsFilter", None)
    if funnels_filter is not None and getattr(funnels_filter, "funnelWindowInterval", None):
        unit = str(getattr(funnels_filter, "funnelWindowIntervalUnit", None) or "day").split(".")[-1].lower()
        lines.append(f"Conversion window: {funnels_filter.funnelWindowInterval} {unit}s")
    retention_filter = getattr(source, "retentionFilter", None)
    if retention_filter is not None:
        period = str(getattr(retention_filter, "period", None) or "Week").lower()
        lines.append(
            f"Retention: users who did {_entity_label(getattr(retention_filter, 'targetEntity', None))} and came "
            f"back to do {_entity_label(getattr(retention_filter, 'returningEntity', None))}, measured per {period}"
        )
    paths_filter = getattr(source, "pathsFilter", None)
    if paths_filter is not None:
        types = getattr(paths_filter, "includeEventTypes", None)
        if types:
            lines.append(f"Path steps: {join_words([str(t).split('.')[-1].lower() for t in types])}")
        if getattr(paths_filter, "startPoint", None):
            lines.append(f"Paths start at: {paths_filter.startPoint}")
        if getattr(paths_filter, "endPoint", None):
            lines.append(f"Paths end at: {paths_filter.endPoint}")
    breakdown = _breakdown_label(source)
    if breakdown:
        lines.append(f"Broken down by: {breakdown}")
    group_index = getattr(source, "aggregation_group_type_index", None)
    if group_index is not None:
        lines.append(f"Counted per group (group type {group_index}), not per person")
    keys = _filter_keys(getattr(source, "properties", None))
    if keys:
        lines.append(f"Filtered on: {join_words(keys)}")
    if getattr(source, "filterTestAccounts", None):
        lines.append("Internal and test accounts are excluded")
    interval = getattr(source, "interval", None)
    if interval:
        lines.append(f"Interval: {str(interval).split('.')[-1].lower()}")
    date_range = getattr(source, "dateRange", None)
    range_text = humanize_date_range(getattr(date_range, "date_from", None)) if date_range else None
    if range_text:
        lines.append(f"Date range: {range_text}")
    trends_filter = getattr(source, "trendsFilter", None)
    display = getattr(trends_filter, "display", None) if trends_filter is not None else None
    if display:
        lines.append(f"Chart: {str(display).split('.')[-1].replace('Actions', '').replace('_', ' ').lower()}")
    return lines


def _state(context: SubjectContext) -> dict[str, object]:
    subject: dict[str, object] = {"kind": context.subject, "name": context.name, "description": context.description}
    if context.query is not None:
        subject["summary"] = _query_summary(context.query)
    if context.tile_names:
        subject["tiles"] = list(context.tile_names)
    return {"subject": subject}


def _choose_text(context: SubjectContext, candidates: Sequence[str], *, field: str, guidance: str) -> TextSuggestion:
    if len(candidates) == 1:
        return TextSuggestion(value=candidates[0], confidence=1.0, candidates=tuple(candidates))
    criteria = {f"c{index}": candidate for index, candidate in enumerate(candidates)}
    question = ChoiceQuestion(
        instructions=(
            f"`subject` describes a saved {context.subject} in a product analytics tool: its current name and "
            f"description, a plain-language `summary` of what it plots, or the names of the insights on it. "
            f"Which option is the best {field} "
            f"for it? {guidance} Judge only on how well the option fits `subject`; do not prefer an option "
            "because it is longer or because it is the current value."
        ),
        criteria=criteria,
    )
    result = system_one(
        state=_state(context), questions={field: question}, source=EGRESS_SOURCE, priority=Priority.NORMAL
    )
    answer = result.answers[field]
    if not isinstance(answer, ChoiceAnswer):
        raise TypeError("Expected a choice answer")
    return TextSuggestion(value=criteria[answer.choice], confidence=answer.confidence, candidates=tuple(candidates))


def suggest_title(context: SubjectContext) -> TextSuggestion:
    return _choose_text(
        context,
        title_candidates(context),
        field="title",
        guidance=(
            "A good title is short and specific: a teammate scanning a list should know what it shows "
            "without opening it. When the summary has a formula, only the formula's result is plotted, so "
            "the title must name that result (a rate, a ratio, an amount per user) and must not list the "
            "series it is built from. Prefer the specific metric or step names over a generic theme when the "
            "query supports them, and prefer a theme overview only when the tiles clearly share one theme."
        ),
    )


def suggest_description(context: SubjectContext) -> TextSuggestion:
    return _choose_text(
        context,
        description_candidates(context),
        field="description",
        guidance=(
            "A good description is one plain sentence that says what the numbers measure and, when it "
            "matters, over what period or by what breakdown. It must not claim anything the query does not do."
        ),
    )


def suggest_tags(context: SubjectContext, available_tags: Sequence[str]) -> TagSuggestion:
    tags = _dedupe(available_tags, limit=MAX_TAG_QUESTIONS)
    if not tags:
        return TagSuggestion(tags=(), scores={})
    state = _state(context)
    state["tags"] = {f"t{index}": tag for index, tag in enumerate(tags)}
    questions: dict[str, ChoiceQuestion | NoulQuestion] = {
        f"t{index}": NoulQuestion(
            instructions=(
                f"`subject` describes a saved {context.subject} in a product analytics tool. `tags.t{index}` is one "
                f"of the tags the team already uses to organize its work. Does that tag apply to this {context.subject}?"
            ),
            true=(
                "The tag names a theme, product area, team, metric family, or status that the subject clearly "
                "belongs to, so a teammate filtering by that tag would expect to find it."
            ),
            false=(
                "The tag is about something else, is too specific to a different feature, or there is not "
                "enough in the subject to say it applies."
            ),
        )
        for index in range(len(tags))
    }
    result = system_one(state=state, questions=questions, source=EGRESS_SOURCE, priority=Priority.NORMAL)
    scores: dict[str, float] = {}
    for index, tag in enumerate(tags):
        answer = result.answers[f"t{index}"]
        if isinstance(answer, NoulAnswer):
            scores[tag] = answer.probability
    chosen = tuple(sorted((tag for tag, score in scores.items() if score >= TAG_THRESHOLD), key=lambda t: -scores[t]))
    return TagSuggestion(tags=chosen, scores=scores)


def suggest_dashboard(context: SubjectContext, dashboards: Sequence[DashboardCandidate]) -> DashboardSuggestion:
    options = list(dashboards)[:MAX_DASHBOARD_OPTIONS]
    if not options:
        return DashboardSuggestion(dashboard_id=None, confidence=1.0)
    state = _state(context)
    state["dashboards"] = {
        f"d{index}": {"name": dashboard.name, "description": dashboard.description}
        for index, dashboard in enumerate(options)
    }
    criteria = {f"d{index}": f"The dashboard described at `dashboards.d{index}`." for index in range(len(options))}
    criteria["none"] = "No listed dashboard is a clear home for this insight."
    question = ChoiceQuestion(
        instructions=(
            "`subject` describes a saved insight in a product analytics tool. `dashboards` lists the team's "
            "dashboards with their names and descriptions. On which dashboard would a teammate expect to find "
            "this insight? Pick `none` when no dashboard clearly matches the insight's topic."
        ),
        criteria=criteria,
    )
    result = system_one(state=state, questions={"dashboard": question}, source=EGRESS_SOURCE, priority=Priority.NORMAL)
    answer = result.answers["dashboard"]
    if not isinstance(answer, ChoiceAnswer):
        raise TypeError("Expected a choice answer")
    if answer.choice == "none":
        return DashboardSuggestion(dashboard_id=None, confidence=answer.confidence)
    return DashboardSuggestion(dashboard_id=options[int(answer.choice[1:])].id, confidence=answer.confidence)
