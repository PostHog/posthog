"""Build URL query params for deep-linking to the logs scene.

The logs scene (logsSceneLogic.tsx) parses URL search params to restore
filters. This module serializes alert filters into that format so
notification links open the logs view with the right context.

URL format:
  severityLevels  — JSON array: '["error","warn"]'
  serviceNames    — JSON array: '["api","worker"]'
  filterGroup     — JSON object (PropertyGroupFilter)
  dateRange       — JSON object: '{"date_from":"2026-04-06T14:50:00+00:00","date_to":"2026-04-06T15:00:00+00:00"}'
"""

import json
from datetime import datetime
from urllib.parse import urlencode


def build_logs_url_params(
    filters: dict,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> str:
    """Convert alert filters into a URL query string for the logs scene.

    Args:
        filters: Alert filter dict with optional keys: severityLevels,
                 serviceNames, filterGroup.
        date_from: Start of the time range (absolute).
        date_to: End of the time range (absolute).

    Returns:
        URL-encoded query string (without leading '?'), or empty string
        if no params to encode.
    """
    params: dict[str, str] = {}

    severity_levels = filters.get("severityLevels", [])
    if severity_levels:
        params["severityLevels"] = json.dumps(severity_levels)

    service_names = filters.get("serviceNames", [])
    if service_names:
        params["serviceNames"] = json.dumps(service_names)

    filter_group = filters.get("filterGroup")
    if filter_group and _has_filter_values(filter_group):
        params["filterGroup"] = json.dumps(filter_group)

    if date_from is not None or date_to is not None:
        date_range: dict[str, str] = {}
        if date_from is not None:
            date_range["date_from"] = date_from.isoformat()
        if date_to is not None:
            date_range["date_to"] = date_to.isoformat()
        params["dateRange"] = json.dumps(date_range)

    if not params:
        return ""

    return urlencode(params)


def _has_filter_values(filter_group: dict) -> bool:
    """True if the filter group contains at least one non-empty property filter."""
    for group in filter_group.get("values", []):
        if group.get("values"):
            return True
    return False
