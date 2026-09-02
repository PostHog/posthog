"""Repair legacy insight `filters` that `filter_to_query` cannot convert.

The insights this targets do not work today. `filters` was a plain JSON column with no validation,
so anything could be written to it. The values below were never valid: `/query` validates every
request against the same generated schema `filter_to_query` uses, so an insight carrying them fails
at query time. Repairing them is what makes a stored `query` possible.

Two rules decide each value:

- One clear reading — map it (`unique_users` means daily unique users, so `dau`).
- More than one reading — drop the field so the schema default applies.

Dropping widens an insight: a filter that is gone stops excluding events. That is a real change to
what the insight reports, which is why every repair is named in the returned list, and why the
caller records them.
"""

import copy
from typing import Any

from posthog.schema import PathType

from posthog.schema_enums import (
    BaseMathType,
    CalendarHeatmapMathType,
    CountPerActorMathType,
    ExperimentMetricMathType,
    FunnelConversionWindowTimeUnit,
    FunnelMathType,
    FunnelVizType,
    GroupMathType,
    IntervalType,
    Key,
    PropertyMathType,
    PropertyOperator,
    RetentionPeriod,
    RetentionReference,
    RetentionType,
    StepOrderValue,
)

VALID_MATH: frozenset[str] = frozenset(
    m.value
    for enum in (
        BaseMathType,
        FunnelMathType,
        PropertyMathType,
        CountPerActorMathType,
        GroupMathType,
        ExperimentMetricMathType,
        CalendarHeatmapMathType,
    )
    for m in enum
) | {"hogql"}

# Each alias has exactly one reading. Anything absent from here and from VALID_MATH is dropped.
MATH_ALIASES: dict[str, str] = {
    "unique_users": "dau",
    "unique_user": "dau",
    "unique_sessions": "unique_session",
    "wau": "weekly_active",
    "mau": "monthly_active",
    "average": "avg",
    "avg_property": "avg",
    "avg_per_actor": "avg_count_per_actor",
    "p50": "median",
    "p50_property": "median",
    "p75_property": "p75",
    "p90_property": "p90",
    "p95_property": "p95",
    "p99_property": "p99",
}

# Display types and list views were written into the `insight` slot. They all describe a trends
# series; the chart shape lives in `display`, which `clean_display` validates separately.
INSIGHT_ALIASES: dict[str, str] = {
    "FUNNEL": "FUNNELS",
    "TABLE": "TRENDS",
    "NUMBER": "TRENDS",
    "PIE": "TRENDS",
    "BAR": "TRENDS",
    "HISTOGRAM": "TRENDS",
    "EVENTS": "TRENDS",
    "ACTIONS": "TRENDS",
    "PERSONS": "TRENDS",
}

VIZ_INSIGHT_TYPES: frozenset[str] = frozenset({"TRENDS", "FUNNELS", "RETENTION", "PATHS", "LIFECYCLE", "STICKINESS"})
SQL_INSIGHT_TYPES: frozenset[str] = frozenset({"SQL", "HOGQL"})

OPERATOR_ALIASES: dict[str, str] = {
    "eq": "exact",
    "is": "exact",
    "equals": "exact",
    "contains": "icontains",
    "not_contains": "not_icontains",
}

RETENTION_TYPE_ALIASES: dict[str, str] = {"retention": "retention_recurring"}
RETENTION_REFERENCE_ALIASES: dict[str, str] = {"overall": "total"}
STEP_ORDER_ALIASES: dict[str, str] = {"sequential": "ordered", "strict_order": "strict"}
# Plurals of every unit the schema names in the singular.
TIME_UNIT_ALIASES: dict[str, str] = {f"{u.value}s": u.value for u in FunnelConversionWindowTimeUnit}

_VALID_OPERATORS = frozenset(o.value for o in PropertyOperator)
_VALID_INTERVALS = frozenset(i.value for i in IntervalType)
_VALID_PATH_TYPES = frozenset(p.value for p in PathType)
_VALID_ELEMENT_KEYS = frozenset(k.value for k in Key)
_VALID_TIME_UNITS = frozenset(u.value for u in FunnelConversionWindowTimeUnit)
_VALID_STEP_ORDERS = frozenset(s.value for s in StepOrderValue)
_VALID_FUNNEL_VIZ = frozenset(v.value for v in FunnelVizType)
_VALID_RETENTION_TYPES = frozenset(r.value for r in RetentionType)
_VALID_RETENTION_REFERENCES = frozenset(r.value for r in RetentionReference)
_VALID_RETENTION_PERIODS = frozenset(p.value for p in RetentionPeriod)

# `type` names a property's source table. A value type such as "number" says nothing about the
# source, and event properties are the overwhelming default, so read it as one.
PROPERTY_TYPE_ALIASES: dict[str, str] = {"number": "event", "string": "event", "boolean": "event"}

# `_entities` stamps the type from the list an entity sits in, so `events` holds events whatever
# their own `type` says. Exclusions and retention entities keep their own, and need one to be set.
ENTITY_LIST_TYPES: dict[str, str | None] = {"events": "events", "actions": "actions", "exclusions": None}
SINGLE_ENTITY_KEYS = ("target_entity", "returning_entity")


def _repair_enum(
    filters: dict[str, Any],
    field: str,
    valid: frozenset[str],
    aliases: dict[str, str],
    repairs: list[str],
    *,
    title_case: bool = False,
) -> None:
    if field not in filters:
        return
    value = filters[field]
    if isinstance(value, str):
        if value in valid:
            return
        candidate = value.title() if title_case else value.lower()
        target = aliases.get(value) or aliases.get(candidate) or (candidate if candidate in valid else None)
        if target is not None:
            filters[field] = target
            repairs.append(f"{field}:{value}->{target}")
            return
    filters.pop(field)
    repairs.append(f"{field}:dropped")


def _repair_int(filters: dict[str, Any], field: str, repairs: list[str]) -> None:
    value = filters.get(field)
    if value is None or isinstance(value, int):
        return
    try:
        filters[field] = int(value)
        repairs.append(f"{field}:coerced-int")
    except (TypeError, ValueError):
        filters.pop(field)
        repairs.append(f"{field}:dropped")


def _repair_property(prop: Any, repairs: list[str]) -> dict[str, Any] | None:
    """Repair one leaf property filter, or return None to drop it."""
    if not isinstance(prop, dict):
        repairs.append("property:dropped-not-a-dict")
        return None

    prop = {**prop}

    # `property` is an older spelling of `key`; without the rename the schema rejects it as unknown.
    if "property" in prop and "key" not in prop:
        prop["key"] = prop.pop("property")
        repairs.append("property.property->key")

    # These never belonged on a property filter and the schema forbids unknown keys.
    for extra in ("math", "name", "value_is_regex", "event_type"):
        if extra in prop and prop.get("type") != "behavioral":
            prop.pop(extra)
            repairs.append(f"property.{extra}:dropped")

    ptype = prop.get("type")
    if isinstance(ptype, str) and ptype in PROPERTY_TYPE_ALIASES:
        prop["type"] = PROPERTY_TYPE_ALIASES[ptype]
        repairs.append(f"property.type:{ptype}->{prop['type']}")

    # Behavioral and cohort filters carry required fields we cannot reconstruct once they are absent.
    if prop.get("type") == "behavioral":
        repairs.append("property:dropped-behavioral")
        return None
    if prop.get("type") == "cohort":
        try:
            int(prop.get("value"))
        except (TypeError, ValueError):
            repairs.append("property:dropped-cohort-without-id")
            return None

    operator = prop.get("operator")
    if isinstance(operator, str) and operator not in _VALID_OPERATORS:
        target = OPERATOR_ALIASES.get(operator)
        if target is None:
            prop.pop("operator")
            repairs.append(f"property.operator:{operator}->default")
        else:
            prop["operator"] = target
            repairs.append(f"property.operator:{operator}->{target}")

    # An element filter can only address the four parts of an element the schema names.
    if prop.get("type") == "element" and prop.get("key") not in _VALID_ELEMENT_KEYS:
        repairs.append("property:dropped-unknown-element-key")
        return None

    if prop.get("key") is None:
        repairs.append("property:dropped-without-key")
        return None

    return prop


def _repair_property_container(properties: Any, repairs: list[str]) -> Any:
    """Walk a property list or AND/OR group, repairing leaves and dropping the unrepairable."""
    if isinstance(properties, dict):
        if properties.get("type") in ("AND", "OR"):
            values = properties.get("values")
            if not isinstance(values, list):
                repairs.append("properties:dropped-malformed-group")
                return None
            cleaned = [c for c in (_repair_property_container(v, repairs) for v in values) if c]
            if not cleaned:
                return None
            return {**properties, "values": cleaned}
        if _is_old_style_properties(properties):
            return properties
        return _repair_property(properties, repairs)

    if isinstance(properties, list):
        cleaned = [c for c in (_repair_property_container(p, repairs) for p in properties) if c]
        return cleaned or None

    repairs.append("properties:dropped-unexpected-format")
    return None


def _is_old_style_properties(properties: Any) -> bool:
    """Mirrors clean_properties.is_old_style_properties, which owns this shape."""
    return isinstance(properties, dict) and len(properties) == 1 and properties.get("type") not in ("AND", "OR")


def _flatten_properties(properties: Any) -> list[dict[str, Any]]:
    """Collect every leaf property filter, discarding the AND/OR nesting around them."""
    if isinstance(properties, dict):
        if properties.get("type") in ("AND", "OR"):
            return [leaf for value in properties.get("values") or [] for leaf in _flatten_properties(value)]
        return [properties]
    if isinstance(properties, list):
        return [leaf for item in properties for leaf in _flatten_properties(item)]
    return []


def _repair_entity(entity: Any, repairs: list[str], forced_type: str | None = None) -> dict[str, Any] | None:
    if not isinstance(entity, dict):
        repairs.append("entity:dropped-not-a-dict")
        return None

    entity = {**entity}

    etype = forced_type or entity.get("type")
    if etype not in ("events", "actions", "data_warehouse"):
        if etype is not None:
            repairs.append("entity.type->events")
        etype = "events"
    # An entity reaching LegacyEntity without a type raises, so always state it.
    entity["type"] = etype

    entity_id = entity.get("id")
    if entity["type"] == "actions":
        try:
            entity["id"] = int(entity_id)
        except (TypeError, ValueError):
            repairs.append("entity:dropped-action-without-id")
            return None
    elif isinstance(entity_id, int | float) and not isinstance(entity_id, bool):
        # An event is addressed by name. A number here is a name that lost its quotes.
        entity["id"] = str(entity_id)
        repairs.append("entity.id:coerced-str")
    elif entity_id is not None and not isinstance(entity_id, str):
        repairs.append("entity:dropped-unusable-id")
        return None

    math = entity.get("math")
    if isinstance(math, str) and math not in VALID_MATH:
        target = MATH_ALIASES.get(math)
        if target is None:
            entity.pop("math", None)
            repairs.append(f"math:{math}->default")
        else:
            entity["math"] = target
            repairs.append(f"math:{math}->{target}")
    elif math is not None and not isinstance(math, str):
        entity.pop("math", None)
        repairs.append("math:dropped")

    # `{"utm_medium__icontains": "email"}` is the old one-key shape, which clean_properties expands
    # on its own. Wrapping it in a list would hide it from that check.
    if "properties" in entity and not _is_old_style_properties(entity["properties"]):
        cleaned = _repair_property_container(entity["properties"], repairs)
        # An entity takes a flat list only — clean_entity_properties raises on a nested group.
        if isinstance(cleaned, dict | list):
            flat = _flatten_properties(cleaned)
            if flat != cleaned:
                repairs.append("entity.properties:flattened")
            cleaned = flat or None
        if cleaned is None:
            entity.pop("properties")
        else:
            entity["properties"] = cleaned

    for step_field in ("funnel_from_step", "funnel_to_step"):
        if step_field in entity:
            _repair_int(entity, step_field, repairs)

    return entity


def normalized_insight_type(filters: dict[str, Any]) -> str | None:
    """The insight type after case and alias repair, or None when it is not a recognizable one."""
    raw = filters.get("insight")
    if raw is None:
        return "TRENDS"
    if not isinstance(raw, str):
        return None
    upper = raw.upper()
    resolved = INSIGHT_ALIASES.get(upper, upper)
    if resolved in VIZ_INSIGHT_TYPES or resolved in SQL_INSIGHT_TYPES:
        return resolved
    return None


def repair_filters(filters: Any) -> tuple[dict[str, Any], list[str]]:
    """Return filters `filter_to_query` accepts, plus the name of every repair applied."""
    repairs: list[str] = []
    if not isinstance(filters, dict):
        return {}, ["filters:replaced-non-dict"]

    out = copy.deepcopy(filters)

    raw_insight = out.get("insight")
    resolved = normalized_insight_type(out)
    if resolved is None:
        # `_insight_type` reads the key rather than defaulting when it is present but unusable.
        out["insight"] = "TRENDS"
        repairs.append(f"insight:{raw_insight if isinstance(raw_insight, str) else 'malformed'}->TRENDS")
    elif raw_insight is None and "insight" in out:
        out["insight"] = "TRENDS"
        repairs.append("insight:null->TRENDS")
    elif isinstance(raw_insight, str) and raw_insight != resolved:
        out["insight"] = resolved
        repairs.append(f"insight:{raw_insight}->{resolved}")

    for key, forced_type in ENTITY_LIST_TYPES.items():
        if key not in out:
            continue
        raw = out[key]
        if not isinstance(raw, list):
            out.pop(key)
            repairs.append(f"{key}:dropped-not-a-list")
            continue
        out[key] = [e for e in (_repair_entity(e, repairs, forced_type) for e in raw) if e]

    for key in SINGLE_ENTITY_KEYS:
        if key not in out:
            continue
        raw = out[key]
        # A list here is a single entity that was stored wrapped; take the entity back out.
        if isinstance(raw, list):
            raw = next((item for item in raw if isinstance(item, dict)), None)
        repaired = _repair_entity(raw, repairs) if raw is not None else None
        if repaired is None:
            out.pop(key)
            repairs.append(f"{key}:dropped")
        else:
            out[key] = repaired

    if "properties" in out:
        cleaned = _repair_property_container(out["properties"], repairs)
        if cleaned is None:
            out.pop("properties")
        else:
            out["properties"] = cleaned

    _repair_enum(out, "interval", _VALID_INTERVALS, {}, repairs)
    _repair_enum(out, "funnel_order_type", _VALID_STEP_ORDERS, STEP_ORDER_ALIASES, repairs)
    _repair_enum(out, "funnel_viz_type", _VALID_FUNNEL_VIZ, {}, repairs)
    _repair_enum(out, "funnel_window_interval_unit", _VALID_TIME_UNITS, TIME_UNIT_ALIASES, repairs)
    _repair_enum(out, "retention_type", _VALID_RETENTION_TYPES, RETENTION_TYPE_ALIASES, repairs)
    _repair_enum(out, "retention_reference", _VALID_RETENTION_REFERENCES, RETENTION_REFERENCE_ALIASES, repairs)
    _repair_enum(out, "period", _VALID_RETENTION_PERIODS, {}, repairs, title_case=True)
    # An unusable breakdown type falls back to "event", which is what `_breakdown_filter` assumes
    # whenever a breakdown is set without one.
    _repair_enum(out, "breakdown_type", _valid_breakdown_types(), {}, repairs)

    if "funnel_window_interval" in out:
        _repair_int(out, "funnel_window_interval", repairs)

    if not isinstance(out.get("layout"), str) and "layout" in out:
        out.pop("layout")
        repairs.append("layout:dropped")

    if "compare_to" in out and not isinstance(out["compare_to"], str):
        out.pop("compare_to")
        repairs.append("compare_to:dropped")

    breakdown = out.get("breakdown")
    if breakdown is not None and not isinstance(breakdown, str | int):
        if isinstance(breakdown, list):
            kept = [b for b in breakdown if isinstance(b, str | int)]
            if kept:
                out["breakdown"] = kept
            else:
                out.pop("breakdown")
                repairs.append("breakdown:dropped")
        else:
            out.pop("breakdown")
            repairs.append("breakdown:dropped")

    # filter_to_query only converts a single breakdown; more than one has no query equivalent.
    breakdowns = out.get("breakdowns")
    if isinstance(breakdowns, list) and len(breakdowns) > 1:
        out.pop("breakdowns")
        repairs.append("breakdowns:dropped-multiple")

    include_event_types = out.get("include_event_types")
    if isinstance(include_event_types, list):
        kept = [t for t in include_event_types if t in _VALID_PATH_TYPES]
        if len(kept) != len(include_event_types):
            repairs.append("include_event_types:dropped-unknown")
        if kept:
            out["include_event_types"] = kept
        else:
            out.pop("include_event_types")

    path_groupings = out.get("path_groupings")
    if isinstance(path_groupings, list):
        kept_groupings = [g for g in path_groupings if isinstance(g, str)]
        if len(kept_groupings) != len(path_groupings):
            repairs.append("path_groupings:dropped-non-string")
        if kept_groupings:
            out["path_groupings"] = kept_groupings
        else:
            out.pop("path_groupings")

    for date_field in ("date_from", "date_to"):
        value = out.get(date_field)
        if value is not None and not isinstance(value, str):
            out[date_field] = str(value)
            repairs.append(f"{date_field}:coerced-str")

    return out, repairs


def _valid_breakdown_types() -> frozenset[str]:
    from posthog.schema import BreakdownType  # noqa: PLC0415 — avoids a schema import cycle at module load

    return frozenset(b.value for b in BreakdownType)
