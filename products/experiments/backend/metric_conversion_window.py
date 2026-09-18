"""Conversion window rules shared by the experiment and the saved metric write paths."""

from collections.abc import Mapping, Sequence
from typing import Any

from posthog.schema import FunnelConversionWindowTimeUnit

UNITLESS_CONVERSION_WINDOW_ERROR = (
    "conversion_window is set but conversion_window_unit is missing. A window without a unit is "
    "ignored, so the metric counts events until the experiment ends. Set conversion_window_unit to "
    f"one of {', '.join(repr(unit.value) for unit in FunnelConversionWindowTimeUnit)}, "
    "or remove conversion_window."
)


def _has_unitless_conversion_window(metric: Any) -> bool:
    if not isinstance(metric, Mapping):
        return False
    return metric.get("conversion_window") is not None and not metric.get("conversion_window_unit")


def _is_same_stored_metric(metric: Mapping[str, Any], stored: Any) -> bool:
    """True when `stored` is the same metric, still carrying the same unit-less window.

    Identity is the uuid as sent. Metrics written before uuids were assigned have none, and two
    missing uuids compare equal, so those match on the window alone.
    """
    if not _has_unitless_conversion_window(stored):
        return False
    return stored.get("uuid") == metric.get("uuid") and stored.get("conversion_window") == metric.get(
        "conversion_window"
    )


def first_unitless_conversion_window(
    metrics: Sequence[Any] | None,
    stored_metrics: Sequence[Any],
) -> int | None:
    """Index of the first metric that sets a conversion window without a unit, or None.

    A metric already present in `stored_metrics` with the same unit-less window is skipped.
    Metric lists are whole-array fields, so an update that changes one metric resends them all,
    and experiments written before this rule hold unit-less windows that must stay editable.
    """
    for index, metric in enumerate(metrics or []):
        if not _has_unitless_conversion_window(metric):
            continue
        if any(_is_same_stored_metric(metric, stored) for stored in stored_metrics):
            continue
        return index
    return None
