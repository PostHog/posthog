"""Per-insight criteria a subscription applies at delivery time.

Stored as ``Subscription.delivery_config["insight_criteria"]``. Absent means every
selected insight is sent. The check reads the snapshot that create_export_assets already
builds for each insight, so it costs no extra query.
"""

from typing import Any

from products.subscriptions.backend.models.subscription import Subscription

# Keys that hold the measured values in the result shapes of the query runners:
# trends/lifecycle/stickiness series ("data", "aggregated_value"), funnel steps ("count"),
# retention cohorts ("values"), paths links ("value").
_VALUE_KEYS = ("data", "aggregated_value", "count", "values", "value")


def _has_signal(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        return value != ""
    if isinstance(value, list | tuple):
        return any(_has_signal(item) for item in value)
    if isinstance(value, dict):
        value_keys = [key for key in _VALUE_KEYS if key in value]
        if not value_keys:
            # A row shape we don't know: its presence is the data.
            return True
        return any(_has_signal(value[key]) for key in value_keys)
    return True


def snapshot_has_data(snapshot: dict[str, Any]) -> bool | None:
    """True when the insight returned at least one non-zero, non-empty value.

    None when the query did not produce a result (error, cold cache, missing query),
    so the caller can decide what an unknown result means.
    """
    query_results = snapshot.get("query_results")
    if not isinstance(query_results, dict):
        return None
    return _has_signal(query_results.get("result"))


def insight_matches_criteria(criteria: str | None, snapshot: dict[str, Any]) -> bool:
    if criteria == Subscription.InsightCriteria.HAS_DATA:
        # An insight whose query failed is still sent, so the error shows in the delivery
        # instead of the insight disappearing without a trace.
        return snapshot_has_data(snapshot) is not False
    return True
