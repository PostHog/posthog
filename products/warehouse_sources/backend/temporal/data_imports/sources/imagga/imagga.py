from datetime import UTC, datetime
from typing import Any

from requests.auth import HTTPBasicAuth

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.settings import IMAGGA_ENDPOINTS

BASE_URL = "https://api.imagga.com/v2"

# The /usage result carries two histogram objects keyed by period -> count (`daily`, `monthly`).
# Their key set changes every period, so folding them into the flat snapshot row would drift the
# column width sync to sync. They're kept out of the `usage` snapshot; the per-day series is exposed
# through the dedicated `daily_usage` table instead.
_HISTOGRAM_KEYS = frozenset({"daily", "monthly"})


def _usage_snapshot_row(result: dict[str, Any]) -> dict[str, Any]:
    """Flatten the /usage result into one row of stable, flat-width scalar fields.

    The histogram objects (`daily`, `monthly`) are excluded — their keys change every period. Nested
    scalar objects such as ``concurrency`` are flattened with a ``<key>_`` prefix (e.g.
    ``concurrency_max``); anything still nested is dropped so the snapshot stays a flat row.
    """
    row: dict[str, Any] = {}
    for key, value in result.items():
        if key in _HISTOGRAM_KEYS:
            continue
        if isinstance(value, dict):
            for sub_key, sub_value in value.items():
                if not isinstance(sub_value, dict | list):
                    row[f"{key}_{sub_key}"] = sub_value
        elif not isinstance(value, list):
            row[key] = value
    return row


def _daily_usage_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Explode the `daily` usage histogram into one row per day.

    Imagga keys the histogram by unix-second timestamp (as a string) mapped to the day's usage count.
    Rows are sorted ascending by day to match ``sort_mode="asc"``. Unparseable keys are skipped
    rather than failing the sync.
    """
    daily = result.get("daily")
    if not isinstance(daily, dict):
        return []

    rows: list[dict[str, Any]] = []
    for ts_key, count in daily.items():
        try:
            timestamp = int(ts_key)
        except (TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(timestamp, tz=UTC).date().isoformat()
        rows.append({"date": day, "timestamp": timestamp, "count": count})

    rows.sort(key=lambda r: r["date"])
    return rows


def _usage_data_map(result: dict[str, Any]) -> dict[str, Any] | list[dict[str, Any]]:
    """Reshape the /usage result into the flat snapshot row, or drop it (empty list) when unusable.

    An empty result, or a non-empty one missing the ``billing_period_start`` merge key, is dropped:
    the `usage` table merges on that key, so yielding a row without it would fail the warehouse merge
    permanently. Degrading to an empty sync keeps a malformed response non-fatal.
    """
    row = _usage_snapshot_row(result)
    if not row:
        return []
    missing_keys = [key for key in IMAGGA_ENDPOINTS["usage"].primary_keys if key not in row]
    if missing_keys:
        return []
    return row


def validate_credentials(api_key: str, api_secret: str) -> bool:
    """Confirm the key/secret pair is genuine with a single GET /usage. 200 = valid; 401/403 = not."""
    ok, _status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_secret,) if api_secret else ()),
        f"{BASE_URL}/usage",
        headers={"Accept": "application/json"},
        auth=HTTPBasicAuth(api_key, api_secret),
    )
    return ok


# Both tables are built from the same GET /usage response, differing only in how the `result` object
# is reshaped: `usage` flattens it into a one-row snapshot, `daily_usage` explodes the per-day
# histogram into one row per day. Credentials ride in the Basic-auth header (redacted from errors),
# never the URL. `concurrency=1` asks Imagga to include the concurrency block in the result.
_ENDPOINT_DATA_MAPS: dict[str, Any] = {
    "usage": _usage_data_map,
    "daily_usage": lambda result: _daily_usage_rows(result),
}


def imagga_source(
    api_key: str,
    api_secret: str,
    endpoint: str,
    team_id: int,
    job_id: str,
) -> SourceResponse:
    if endpoint not in _ENDPOINT_DATA_MAPS:
        raise ValueError(f"Unknown Imagga endpoint: {endpoint}")

    config = IMAGGA_ENDPOINTS[endpoint]

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": BASE_URL,
            "headers": {"Accept": "application/json"},
            "auth": {"type": "http_basic", "username": api_key, "password": api_secret},
        },
        "resource_defaults": {},
        "resources": [
            {
                "name": endpoint,
                "endpoint": {
                    "path": "usage",
                    "params": {"concurrency": "1"},
                    # The rows live under `result`; a missing/null `result` (or a non-dict body)
                    # yields no rows rather than failing, matching the old empty-degradation behavior.
                    "data_selector": "result",
                },
                "data_map": _ENDPOINT_DATA_MAPS[endpoint],
            }
        ],
    }

    resource = rest_api_resource(rest_config, team_id, job_id, None)

    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=config.primary_keys,
        partition_count=1,
        partition_size=1,
        partition_keys=config.partition_keys,
        partition_mode=config.partition_mode,
        partition_format=config.partition_format,
        sort_mode="asc",
    )
