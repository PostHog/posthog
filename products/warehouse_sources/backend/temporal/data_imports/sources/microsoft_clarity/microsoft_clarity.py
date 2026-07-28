from datetime import UTC, datetime
from typing import Any, Optional

import requests

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.microsoft_clarity.settings import (
    ENDPOINT_NAME,
    NO_DIMENSION,
)

BASE_URL = "https://www.clarity.ms"
INSIGHTS_PATH = "/export-data/api/v1/project-live-insights"

# Cheapest possible probe to confirm a token is genuine: one day, no breakdown dimensions. Still
# counts against the project's 10-requests/day quota, which is an accepted tradeoff for validating
# credentials at source-create time.
_VALIDATION_NUM_OF_DAYS = "1"

_REQUEST_TIMEOUT = 30


def _build_params(num_of_days: str, dimensions: list[str]) -> dict[str, str]:
    params: dict[str, str] = {"numOfDays": num_of_days}
    for index, dimension in enumerate(dimensions, start=1):
        params[f"dimension{index}"] = dimension
    return params


def _fetch(token: str, num_of_days: str, dimensions: list[str]) -> requests.Response:
    # make_tracked_session already retries 429/5xx with backoff; the daily quota is a hard cap so a
    # 429 that survives those retries is genuine and should surface, not be retried again here.
    session = make_tracked_session(redact_values=(token,))
    return session.get(
        f"{BASE_URL}{INSIGHTS_PATH}",
        params=_build_params(num_of_days, dimensions),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=_REQUEST_TIMEOUT,
    )


def validate_credentials(token: str) -> tuple[bool, str | None]:
    try:
        response = _fetch(token, _VALIDATION_NUM_OF_DAYS, [])
    except requests.RequestException:
        return False, "Could not reach Microsoft Clarity. Please try again."

    if response.ok:
        return True, None
    if response.status_code == 401:
        return False, "Invalid or expired Microsoft Clarity API token."
    if response.status_code == 403:
        return False, "This Microsoft Clarity API token is not authorized for this project."
    if response.status_code == 429:
        # The project's 10-requests/day quota is already exhausted (possibly by other tooling), but
        # that doesn't mean the token itself is invalid — don't block source creation over it.
        return True, None
    return False, f"Microsoft Clarity returned status {response.status_code}."


def _resolve_dimensions(dimension1: Optional[str], dimension2: Optional[str], dimension3: Optional[str]) -> list[str]:
    dimensions: list[str] = []
    for dimension in (dimension1, dimension2, dimension3):
        if dimension and dimension != NO_DIMENSION and dimension not in dimensions:
            dimensions.append(dimension)
    return dimensions


def microsoft_clarity_source(
    token: str,
    num_of_days: str,
    dimension1: Optional[str],
    dimension2: Optional[str],
    dimension3: Optional[str],
) -> SourceResponse:
    dimensions = _resolve_dimensions(dimension1, dimension2, dimension3)
    response = _fetch(token, num_of_days, dimensions)
    response.raise_for_status()
    payload = response.json()

    # Shared across every row from this call so a sync's snapshot rows all land together, and
    # repeated syncs (the only way to accumulate history against this API) append rather than
    # collide on the primary key.
    synced_at = datetime.now(UTC).isoformat()

    def _rows() -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not isinstance(payload, list):
            return rows

        for metric in payload:
            if not isinstance(metric, dict):
                continue
            metric_name = metric.get("metricName")
            information = metric.get("information")
            if not isinstance(information, list):
                continue

            for row_index, item in enumerate(information):
                row: dict[str, Any] = {
                    "metric_name": metric_name,
                    "synced_at": synced_at,
                    "num_of_days": int(num_of_days),
                    # Metric rows carry no vendor-issued id, and which fields identify a row varies
                    # by metric/dimension combination — the index within this call's group is the
                    # only value guaranteed unique table-wide.
                    "row_index": row_index,
                }
                if isinstance(item, dict):
                    row.update(item)
                rows.append(row)
        return rows

    return SourceResponse(
        name=ENDPOINT_NAME,
        items=lambda: _rows(),
        primary_keys=["metric_name", "synced_at", "row_index"],
        partition_mode="datetime",
        partition_format="month",
        partition_keys=["synced_at"],
        sort_mode="asc",
    )
