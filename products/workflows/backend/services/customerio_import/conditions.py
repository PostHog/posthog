"""Customer.io conditions as PostHog property filters.

Customer.io stores action conditions as a flat array, double encoded: JSON, then URL-encoded, then base64.
Entry filters and exit conditions use a nested `and`/`or` tree instead. Both read the same leaf operators.
"""

import json
import base64
import binascii
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from posthog.dataclasses import frozen

_OPERATORS = {
    "eq": "exact",
    "!eq": "is_not",
    "contains": "icontains",
    "!contains": "not_icontains",
    "gt": "gt",
    "lt": "lt",
    "exists": "is_set",
    "!exists": "is_not_set",
}
_NEGATED = {
    "exact": "is_not",
    "is_not": "exact",
    "icontains": "not_icontains",
    "not_icontains": "icontains",
    "is_set": "is_not_set",
    "is_not_set": "is_set",
    "gt": "lte",
    "lt": "gte",
}
_UNARY = {"is_set", "is_not_set"}
_SECONDS_PER_DAY = 86400


@frozen
class Condition:
    """One Customer.io condition array, translated."""

    # Person and event property filters, all of which must match.
    properties: tuple[dict[str, Any], ...] = ()
    # Events to wait for. Each is a PostHog event filter that can carry its own properties.
    events: tuple[dict[str, Any], ...] = ()
    # Readable descriptions of the parts that have no PostHog equivalent and were left out.
    skipped: tuple[str, ...] = ()


def decode(encoded: str | None) -> list[dict[str, Any]] | None:
    """The condition array behind an encoded string, or None when it does not decode."""
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    # Conditions saved through the app are URL-encoded before base64, older ones are not. Plain JSON is read
    # first, so a value that holds a percent escape, like a URL, keeps it.
    for candidate in (raw, unquote(raw)):
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            parsed = [parsed]
        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return parsed
    return None


def translate_condition(conditions: list[dict[str, Any]], segment_cohorts: dict[str, int]) -> Condition:
    properties: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    skipped: list[str] = []
    for condition in conditions:
        kind = condition.get("type")
        if kind in ("attribute", "event_attribute"):
            filters = property_filters(condition, "person" if kind == "attribute" else "event")
            if filters is None:
                skipped.append(describe(condition))
            else:
                properties.extend(filters)
        elif kind in ("segments_negatable", "segments"):
            cohort_filters = _cohort_filters(condition, segment_cohorts)
            if cohort_filters is None:
                skipped.append(describe(condition))
            else:
                properties.extend(cohort_filters)
        elif kind == "foreign_event" and condition.get("event_name") and not condition.get("event_type"):
            name = str(condition["event_name"])
            events.append({"id": name, "name": name, "type": "events", "order": len(events), "properties": []})
        elif kind == "foreign_event_attribute" and events:
            filters = property_filters(condition, "event")
            if filters is None:
                skipped.append(describe(condition))
            else:
                events[-1]["properties"].extend(filters)
        else:
            skipped.append(describe(condition))
    return Condition(properties=tuple(properties), events=tuple(events), skipped=tuple(skipped))


def translate_filter_tree(tree: Any, property_type: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Flattens an `and` tree of `{field, operator, value}` leaves into property filters.

    PostHog event and trigger filters are a flat AND list, so an `or` is left out and described instead.
    """
    if not isinstance(tree, dict) or not tree:
        return [], []
    if "and" in tree and isinstance(tree["and"], list):
        properties: list[dict[str, Any]] = []
        skipped: list[str] = []
        for child in tree["and"]:
            child_properties, child_skipped = translate_filter_tree(child, property_type)
            properties.extend(child_properties)
            skipped.extend(child_skipped)
        return properties, skipped
    if "field" in tree:
        filters = property_filters(tree, property_type, negate=bool(tree.get("inverse")))
        return (filters, []) if filters is not None else ([], [describe(tree)])
    return [], [describe(tree)]


def property_filters(leaf: dict[str, Any], property_type: str, *, negate: bool = False) -> list[dict[str, Any]] | None:
    """PostHog property filters for one Customer.io leaf, or None when the operator has no equivalent."""
    field, operator, value, value2 = leaf.get("field"), leaf.get("operator"), leaf.get("value"), leaf.get("value2")
    if not isinstance(field, str) or not field or not isinstance(operator, str):
        return None

    def build(posthog_operator: str, posthog_value: Any) -> dict[str, Any]:
        if negate:
            posthog_operator = _NEGATED.get(posthog_operator, posthog_operator)
        result: dict[str, Any] = {"key": field, "operator": posthog_operator, "type": property_type}
        if posthog_operator not in _UNARY:
            result["value"] = posthog_value
        return result

    if negate and operator in ("bw", "timestamp_bw", "timestamp_gt", "timestamp_lt", "timestamp_gta", "timestamp_lta"):
        # A negated range is an OR of two filters, which a flat AND list cannot hold.
        return None
    if operator in _OPERATORS:
        posthog_operator = _OPERATORS[operator]
        if posthog_operator not in _UNARY and value is None:
            return None
        return [build(posthog_operator, value)]
    if operator == "bw" and value is not None and value2 is not None:
        return [build("gte", value), build("lte", value2)]
    if operator in ("timestamp_gt", "timestamp_lt"):
        relative = _relative_duration(value)
        if relative is None:
            return None
        return [build("is_date_after" if operator == "timestamp_gt" else "is_date_before", relative)]
    if operator in ("timestamp_gta", "timestamp_lta"):
        absolute = _absolute_date(value)
        if absolute is None:
            return None
        return [build("is_date_after" if operator == "timestamp_gta" else "is_date_before", absolute)]
    if operator == "timestamp_bw":
        start, end = _absolute_date(value), _absolute_date(value2)
        if start is None or end is None:
            return None
        return [build("is_date_after", start), build("is_date_before", end)]
    return None


def describe(condition: Any) -> str:
    if not isinstance(condition, dict):
        return json.dumps(condition, sort_keys=True)[:200]
    kind = condition.get("type")
    if "field" in condition:
        value = condition.get("value")
        prefix = "not " if condition.get("inverse") else ""
        return (
            f"{prefix}{condition['field']} {condition.get('operator', '')} {value if value is not None else ''}".strip()
        )
    if kind in ("segments_negatable", "segments"):
        verb = "not in" if condition.get("negate") else "in"
        return f"{verb} segment {', '.join(str(segment) for segment in condition.get('segments') or [])}"
    if kind == "foreign_event":
        return f"event {condition.get('event_name')}"
    if kind == "message":
        event = condition.get("event")
        if not isinstance(event, dict):
            event = {}
        prefix = "has not " if condition.get("inverse") else ""
        return f"{prefix}{event.get('type', 'message event')} ({event.get('name', '*')})"
    if isinstance(condition.get("segment"), dict):
        return f"in segment {condition['segment'].get('id')}"
    if isinstance(condition.get("event_name"), dict):
        return f"event {condition['event_name'].get('name')}"
    if isinstance(condition.get("attribute"), dict):
        return describe(condition["attribute"])
    return json.dumps(condition, sort_keys=True)[:200]


def _cohort_filters(condition: dict[str, Any], segment_cohorts: dict[str, int]) -> list[dict[str, Any]] | None:
    segments = [str(segment) for segment in condition.get("segments") or []]
    if len(segments) != 1 or segments[0] not in segment_cohorts:
        # Membership in any of several segments is an OR, which a flat AND list cannot hold.
        return None
    operator = "not_in" if condition.get("negate") else "in"
    return [{"key": "id", "type": "cohort", "operator": operator, "value": segment_cohorts[segments[0]]}]


def _relative_duration(value: Any) -> str | None:
    try:
        seconds = int(str(value))
    except ValueError:
        return None
    if seconds >= 0:
        return None
    if seconds % _SECONDS_PER_DAY == 0:
        return f"-{-seconds // _SECONDS_PER_DAY}d"
    return f"-{max(1, round(-seconds / 3600))}h"


def _absolute_date(value: Any) -> str | None:
    try:
        moment = datetime.fromtimestamp(int(str(value)), tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None
    if moment.hour == moment.minute == moment.second == 0:
        return moment.strftime("%Y-%m-%d")
    return moment.isoformat()
