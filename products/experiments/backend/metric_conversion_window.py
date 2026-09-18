"""Conversion window rules shared by the experiment and the saved metric write paths."""

from collections.abc import Mapping, Sequence
from typing import Any

# The units conversion_window_to_seconds understands (hogql_queries/base_query_utils.py).
CONVERSION_WINDOW_UNITS = ("second", "minute", "hour", "day", "week", "month")

UNITLESS_CONVERSION_WINDOW_ERROR = (
    "conversion_window is set but conversion_window_unit is missing. A window without a unit is "
    "ignored, so the metric counts events until the experiment ends. Set conversion_window_unit to "
    f"one of {', '.join(repr(unit) for unit in CONVERSION_WINDOW_UNITS)}, or remove conversion_window."
)


def _has_unitless_conversion_window(metric: Any) -> bool:
    if not isinstance(metric, Mapping):
        return False
    return metric.get("conversion_window") is not None and not metric.get("conversion_window_unit")


def first_unitless_conversion_window(
    metrics: Sequence[Any] | None,
    stored_metrics_by_uuid: Mapping[str, Any],
) -> int | None:
    """Index of the first metric that sets a conversion window without a unit, or None.

    A metric that matches a stored one by uuid and carries the same unit-less window is skipped.
    Metric lists are whole-array fields, so an update that changes one metric resends them all,
    and experiments written before this rule hold unit-less windows that must stay editable.
    """
    for index, metric in enumerate(metrics or []):
        if not _has_unitless_conversion_window(metric):
            continue
        uuid = metric.get("uuid")
        stored = stored_metrics_by_uuid.get(uuid) if isinstance(uuid, str) else None
        if (
            stored is not None
            and _has_unitless_conversion_window(stored)
            and stored.get("conversion_window") == metric.get("conversion_window")
        ):
            continue
        return index
    return None
