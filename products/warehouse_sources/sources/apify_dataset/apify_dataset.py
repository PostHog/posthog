from datetime import UTC, date, datetime
from typing import Any, Optional
from urllib.parse import quote

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.settings import (
    APIFY_BASE_URL,
    DATASET_ITEMS_ENDPOINT,
    PLATFORM_ENDPOINTS,
    PRIMARY_KEYS,
    USAGE_MONTHLY_ENDPOINT,
    ApifyPlatformEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source import (
    RESTAPIConfig,
    rest_api_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    OffsetPaginator,
    SinglePagePaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import EndpointResource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.source_helpers import validate_via_probe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceResponse

# Rows per request. Both /datasets/{id}/items and the platform list endpoints cap `limit` at 1000,
# and they carry a high rate limit (~400 req/s), so a full page keeps the round-trip count down.
PAGE_SIZE = 1000
# Apify reports the dataset's total item count in this response header (the body is a bare JSON array).
APIFY_TOTAL_HEADER = "X-Apify-Pagination-Total"


@frozen
class ApifyResumeConfig:
    # Absolute offset of the next row to fetch. Dataset items are append-only and returned in stable
    # storage order, and the platform lists are sorted ascending by a creation timestamp, so an
    # offset points at the same row across requests — making it a safe resume cursor.
    offset: int = 0


def _items_path(dataset_id: str) -> str:
    # Encode the dataset_id as a single path segment so a crafted value can't inject extra path
    # segments or query params.
    return f"/datasets/{quote(dataset_id, safe='')}/items"


def _to_iso8601(value: Any) -> Optional[str]:
    """Format an incremental cursor value for Apify's `startedAfter` filter, which takes an ISO 8601
    UTC datetime. Truncating to whole seconds only ever widens the window, so a row on the boundary
    is re-fetched and deduped on merge rather than skipped."""
    if value is None:
        return None
    if isinstance(value, datetime):
        utc = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%dT00:00:00Z")
    return str(value)


def _explode_usage_cycle(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn the monthly usage response into one row per day of the usage cycle.

    The endpoint answers with a single object: the cycle's totals plus a `dailyServiceUsages` array.
    Day is the grain that makes spend queryable over time, so each day carries the cycle it belongs
    to and that cycle's credit totals.
    """
    cycle = row.get("usageCycle") or {}
    return [
        {
            **day,
            "usageCycleStartAt": cycle.get("startAt"),
            "usageCycleEndAt": cycle.get("endAt"),
            "totalUsageCreditsUsdBeforeVolumeDiscount": row.get("totalUsageCreditsUsdBeforeVolumeDiscount"),
            "totalUsageCreditsUsdAfterVolumeDiscount": row.get("totalUsageCreditsUsdAfterVolumeDiscount"),
        }
        for day in row.get("dailyServiceUsages") or []
        if isinstance(day, dict)
    ]


def _platform_resource(name: str, config: ApifyPlatformEndpointConfig, use_incremental: bool) -> EndpointResource:
    params: dict[str, Any] = dict(config.params)
    if use_incremental and config.incremental_param:
        params[config.incremental_param] = {
            "type": "incremental",
            "cursor_path": config.incremental_cursor,
            "initial_value": None,
            "convert": _to_iso8601,
        }

    paginator = (
        OffsetPaginator(limit=PAGE_SIZE, total_path=config.total_path) if config.paginated else SinglePagePaginator()
    )

    resource: EndpointResource = {
        "name": name,
        "table_name": name,
        "write_disposition": {"disposition": "merge", "strategy": "upsert"} if use_incremental else "replace",
        "endpoint": {
            "path": config.path,
            "params": params,
            "paginator": paginator,
            "data_selector": config.data_selector,
            # Apify documents the envelope key as always present, so a response without it is a
            # shape change — fail loud instead of syncing zero rows.
            "data_selector_required": True,
        },
        "table_format": "delta",
    }

    if name == USAGE_MONTHLY_ENDPOINT:
        resource["data_map"] = _explode_usage_cycle

    return resource


def _dataset_items_resource(name: str, dataset_id: str) -> EndpointResource:
    return {
        "name": name,
        "endpoint": {
            "path": _items_path(dataset_id),
            "params": {"format": "json"},
            # Total lives in a response header, not the body; the bare JSON array is the row list.
            "paginator": OffsetPaginator(limit=PAGE_SIZE, total_path=None, total_header=APIFY_TOTAL_HEADER),
            # The body is a bare JSON array; require it to be a list so a misrouted request
            # returning an error object fails loud instead of syncing the object as a row.
            "data_selector_required": True,
        },
    }


def apify_dataset_source(
    api_token: str,
    dataset_id: str,
    endpoint: str,
    team_id: int,
    job_id: str,
    resumable_source_manager: ResumableSourceManager[ApifyResumeConfig],
    db_incremental_field_last_value: Optional[Any] = None,
    should_use_incremental_field: bool = False,
) -> SourceResponse:
    platform_config = PLATFORM_ENDPOINTS.get(endpoint)
    if platform_config is not None:
        use_incremental = should_use_incremental_field and platform_config.incremental_param is not None
        resource_config = _platform_resource(endpoint, platform_config, use_incremental)
        # A single-page endpoint has no cursor to come back to.
        resumable = platform_config.paginated
    elif endpoint == DATASET_ITEMS_ENDPOINT:
        use_incremental = False
        resource_config = _dataset_items_resource(endpoint, dataset_id)
        resumable = True
    else:
        raise ValueError(f"Unknown Apify endpoint: {endpoint}")

    rest_config: RESTAPIConfig = {
        "client": {
            "base_url": APIFY_BASE_URL,
            "auth": {"type": "bearer", "token": api_token},
        },
        "resource_defaults": {},
        "resources": [resource_config],
    }

    initial_paginator_state: Optional[dict[str, Any]] = None
    if resumable and resumable_source_manager.can_resume():
        resume = resumable_source_manager.load_state()
        if resume is not None:
            initial_paginator_state = {"offset": resume.offset}

    def save_checkpoint(state: Optional[dict[str, Any]]) -> None:
        if state and state.get("offset") is not None:
            resumable_source_manager.save_state(ApifyResumeConfig(offset=int(state["offset"])))

    resource = rest_api_resource(
        rest_config,
        team_id,
        job_id,
        db_incremental_field_last_value if use_incremental else None,
        resume_hook=save_checkpoint if resumable else None,
        initial_paginator_state=initial_paginator_state,
    )

    partition_key = platform_config.partition_key if platform_config else None
    return SourceResponse(
        name=endpoint,
        items=lambda: resource,
        primary_keys=PRIMARY_KEYS.get(endpoint),
        column_hints=resource.column_hints,
        # Every platform list endpoint sorts ascending by its creation timestamp unless `desc=1` is
        # passed, and dataset items come back in storage (append) order.
        sort_mode="asc",
        partition_count=1 if partition_key else None,
        partition_size=1 if partition_key else None,
        partition_mode="datetime" if partition_key else None,
        partition_format="month" if partition_key else None,
        partition_keys=[partition_key] if partition_key else None,
    )


def validate_credentials(api_token: str, dataset_id: str) -> tuple[bool, str | None]:
    """Probe the dataset itself so a bad token (401/403) and a wrong/inaccessible dataset (404) are both caught."""
    ok, status = validate_via_probe(
        lambda: make_tracked_session(redact_values=(api_token,)),
        f"{APIFY_BASE_URL}/datasets/{quote(dataset_id, safe='')}",
        headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
    )
    if ok:
        return True, None
    if status in (401, 403):
        return False, "Invalid Apify API token, or the token cannot access this dataset."
    if status == 404:
        return False, "Dataset not found. Check the dataset ID and that the token can access it."
    if status is None:
        return False, "Could not reach the Apify API. Please try again."
    return False, f"Unexpected response from Apify (status {status})."
