"""The properties of the internal events that drive logs alert HogFunctions.

The logs stack emits these for the alerts it owns, and the platform emits them for the alerts it
owns on the HogFunction path. A HogFunction reads them by name, so both build them here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from products.logs.backend.logs_url_params import build_logs_url_params


def threshold_event_properties(
    *,
    alert_id: str,
    alert_name: str,
    team_id: int,
    threshold_count: int,
    threshold_operator: str,
    window_minutes: int,
    result_count: int | None,
    filters: dict[str, Any],
    date_from: datetime,
    date_to: datetime,
    triggered_at: datetime,
) -> dict[str, Any]:
    """A firing, a resolve, or an opened incident."""
    return {
        "alert_id": alert_id,
        "alert_name": alert_name,
        "team_id": team_id,
        "threshold_count": threshold_count,
        "threshold_operator": threshold_operator,
        "window_minutes": window_minutes,
        "result_count": result_count,
        "filters": filters,
        "service_names": filters.get("serviceNames", []),
        "severity_levels": filters.get("severityLevels", []),
        "logs_url_params": build_logs_url_params(filters, date_from=date_from, date_to=date_to),
        "triggered_at": triggered_at.isoformat(),
    }


def failure_event_properties(
    *,
    alert_id: str,
    alert_name: str,
    team_id: int,
    consecutive_failures: int,
    filters: dict[str, Any],
    triggered_at: datetime,
) -> dict[str, Any]:
    """An errored or an auto-disabled alert, without the error, whose key differs between the two."""
    return {
        "alert_id": alert_id,
        "alert_name": alert_name,
        "team_id": team_id,
        "consecutive_failures": consecutive_failures,
        "service_names": filters.get("serviceNames", []),
        "severity_levels": filters.get("severityLevels", []),
        "triggered_at": triggered_at.isoformat(),
    }


def incident_closed_event_properties(
    *, alert_id: str, alert_name: str, team_id: int, reason: str, triggered_at: datetime
) -> dict[str, Any]:
    return {
        "alert_id": alert_id,
        "alert_name": alert_name,
        "team_id": team_id,
        "reason": reason,
        "triggered_at": triggered_at.isoformat(),
    }
