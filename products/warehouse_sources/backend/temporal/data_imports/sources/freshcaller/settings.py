"""Freshcaller source settings and endpoint catalog."""

from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Freshcaller allows up to 1000 records per page (default 10). Match Airbyte's connector,
# which pulls the max page size to keep the request count (and thus rate-limit pressure) low.
PER_PAGE = 1000

# Both required together; `by_time` filters Calls / Call Metrics on the stable `created_time`
# field. Absent an incremental watermark we bound the first backfill at this date rather than
# scanning all history — Freshcaller's own connectors default the backfill floor to 2022.
DEFAULT_START_DATETIME = "2022-01-01T00:00:00Z"


@dataclass
class FreshcallerEndpointConfig:
    name: str
    path: str
    # Freshcaller wraps each list response in an object keyed by the plural resource name
    # (e.g. {"users": [...], "meta": {...}}); `data_key` is that key.
    data_key: str
    # `True` only where the list endpoint honors a genuine server-side `by_time` window on
    # `created_time`. `users`/`teams` expose no time filter -> full refresh only.
    supports_incremental: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable datetime field used for partitioning. Always a creation timestamp, never a
    # mutable field (partitions must not rewrite on every sync).
    partition_key: Optional[str] = None
    # Extra static query params (e.g. `include=life_cycle` on call_metrics).
    extra_params: dict[str, str] = field(default_factory=dict)


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


# Freshcaller v1 top-level endpoints.
#
# Incremental support (Calls, Call Metrics via `by_time[from]`/`by_time[to]` on `created_time`)
# follows Freshcaller's shipped Airbyte connector. The public API reference only documents the
# `by_time` filter on Call Metrics, so the Calls filter is unverified against a live account with
# credentials — if a curl smoke test shows Calls silently ignores `by_time`, flip `calls` to full
# refresh. Merge dedupes on `id` either way, so a silently-ignored filter degrades to full-refresh
# cost, never wrong data.
FRESHCALLER_ENDPOINTS: dict[str, FreshcallerEndpointConfig] = {
    "users": FreshcallerEndpointConfig(
        name="users",
        path="/api/v1/users",
        data_key="users",
    ),
    "teams": FreshcallerEndpointConfig(
        name="teams",
        path="/api/v1/teams",
        data_key="teams",
    ),
    "calls": FreshcallerEndpointConfig(
        name="calls",
        path="/api/v1/calls",
        data_key="calls",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("created_time")],
        partition_key="created_time",
    ),
    "call_metrics": FreshcallerEndpointConfig(
        name="call_metrics",
        path="/api/v1/call_metrics",
        data_key="call_metrics",
        supports_incremental=True,
        incremental_fields=[_datetime_incremental_field("created_time")],
        partition_key="created_time",
        # Pull the call lifecycle sub-resource alongside each metric row, matching Airbyte.
        extra_params={"include": "life_cycle"},
    ),
}

ENDPOINTS = tuple(FRESHCALLER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FRESHCALLER_ENDPOINTS.items()
}
