from collections.abc import Mapping
from datetime import datetime

from products.metrics.backend.metric_query_runner import _MAX_BUCKET_COUNT, _resolve_interval
from products.metrics.backend.variables import REFERENCE, Variable, reference_name, referenced_names, unresolved_message

_DURATION_INTERVALS = {
    "15s": "second_15",
    "30s": "second_30",
    "1m": "minute",
    "5m": "minute_5",
    "15m": "minute_15",
    "30m": "minute_30",
    "1h": "hour",
    "6h": "hour_6",
    "1d": "day",
    "1w": "week",
}


def resolve_query_interval(
    interval: str | None, variables: Mapping[str, Variable], date_from: datetime, date_to: datetime
) -> str | None:
    if not referenced_names(interval):
        return interval

    match = REFERENCE.fullmatch(interval or "")
    if match is None:
        raise ValueError("The chart interval must be a single variable reference, such as $window.")
    name = reference_name(match)
    variable = variables.get(name)
    if variable is None:
        raise ValueError(unresolved_message([name]))
    if variable.is_all or len(variable.values) != 1:
        raise ValueError(f"Select one duration for ${name} to set the chart interval.")
    value = variable.values[0]
    selected = _DURATION_INTERVALS.get(value)
    if selected is None:
        raise ValueError(
            f"Invalid chart interval for ${name}: {value!r}. Choose one of: {', '.join(_DURATION_INTERVALS)}."
        )
    # Coarsening only the step would separate it from a PromQL lookback using the same variable.
    if _resolve_interval(date_from, date_to, selected) != selected:
        raise ValueError(
            f"The {value} chart interval exceeds the {_MAX_BUCKET_COUNT}-point limit for this date range. "
            f"Choose a larger duration for ${name} or a shorter date range."
        )
    return selected
