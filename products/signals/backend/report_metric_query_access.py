"""Query shapes the report metric read policy can inspect for viewer access."""

from collections.abc import Callable, Mapping

ORDINARY_PROPERTY_FILTER_TYPES = frozenset({"element", "event", "group", "person", "person_metadata", "session"})
MAX_PROPERTY_FILTER_DEPTH = 20


def property_filters_allow_read(filters: object, *, may_read_cohort: Callable[[int], bool] | None = None) -> bool:
    if filters is None:
        return True
    pending: list[tuple[object, int]]
    if isinstance(filters, list):
        pending = [(item, 0) for item in filters]
    elif isinstance(filters, Mapping) and filters.get("type") in ("AND", "OR"):
        pending = [(filters, 0)]
    else:
        return False

    while pending:
        item, depth = pending.pop()
        if not isinstance(item, Mapping) or depth > MAX_PROPERTY_FILTER_DEPTH:
            return False
        filter_type = item.get("type")
        if filter_type in ("AND", "OR"):
            values = item.get("values")
            if not isinstance(values, list):
                return False
            pending.extend((value, depth + 1) for value in values)
        elif filter_type == "cohort":
            cohort_id = item.get("value")
            if (
                item.get("key") != "id"
                or not isinstance(cohort_id, int)
                or isinstance(cohort_id, bool)
                or cohort_id <= 0
                or (may_read_cohort is not None and not may_read_cohort(cohort_id))
            ):
                return False
        elif not isinstance(filter_type, str) or filter_type not in ORDINARY_PROPERTY_FILTER_TYPES:
            return False
    return True


def conversion_goal_has_readable_shape(goal: object) -> bool:
    if goal is None:
        return True
    if not isinstance(goal, Mapping):
        return False
    if "actionId" in goal:
        action_id = goal["actionId"]
        return (
            set(goal) == {"actionId"}
            and isinstance(action_id, int)
            and not isinstance(action_id, bool)
            and action_id > 0
        )
    return (
        set(goal) == {"customEventName"}
        and isinstance(goal.get("customEventName"), str)
        and bool(goal["customEventName"])
    )


def query_filter_shape_allows_read(query: Mapping[str, object]) -> bool:
    source = query.get("source")
    if not isinstance(source, Mapping):
        return False
    series = source.get("series")
    if not isinstance(series, list) or any(not isinstance(item, Mapping) for item in series):
        return False
    for item in series:
        for field in ("properties", "fixedProperties"):
            if field in item and not property_filters_allow_read(item[field]):
                return False
    for field in ("properties", "fixedProperties"):
        if field in source and not property_filters_allow_read(source[field]):
            return False
    return conversion_goal_has_readable_shape(source.get("conversionGoal"))
