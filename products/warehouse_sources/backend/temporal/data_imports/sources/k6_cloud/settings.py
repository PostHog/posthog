from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class K6CloudEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField]
    # Stable datetime field used for partitioning. Must never change for a row
    # (so `created`, never `updated`). `None` disables partitioning.
    partition_key: Optional[str] = None
    # Name of the server-side timestamp filter query param (e.g. `created_after`).
    # Only set when the API genuinely filters on it — this is what enables
    # incremental sync. `None` => full refresh only.
    time_filter_param: Optional[str] = None
    # Value sent as `$orderby` for a stable ascending page order. Only set on
    # endpoints that document the field — the top-level `test_runs` endpoint
    # rejects `$orderby`, so it stays `None` there.
    order_by: Optional[str] = None
    # Whether the endpoint uses `$skip`/`$top` offset pagination (followed via the
    # `@nextLink` URL in the response). `load_zones` returns every row in one page.
    paginated: bool = True
    should_sync_default: bool = True


def _created_incremental_field() -> list[IncrementalField]:
    return [
        {
            "label": "created",
            "type": IncrementalFieldType.DateTime,
            "field": "created",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Streams mirror the canonical Grafana Cloud k6 v6 resources a user actually wants in a
# warehouse: Projects, Load tests, Test runs, Schedules, and Load zones. Metrics/scripts/
# limits are per-run detail endpoints that require fan-out and are left out of this alpha.
K6_CLOUD_ENDPOINTS: dict[str, K6CloudEndpointConfig] = {
    # Test runs are the natural incremental stream: `/cloud/v6/test_runs` exposes
    # `created_after` (inclusive) as a server-side filter on the immutable `created`
    # timestamp. The endpoint offers no `$orderby`, but it is offset-paginated
    # ($skip/$top), which requires a deterministic server order; k6 assigns
    # monotonically increasing ids at creation and the documented sibling endpoint
    # `/cloud/v6/load_tests/{id}/test_runs` defaults to ascending `created`, so we
    # treat the collection as ascending-by-creation and advance the cursor on `created`.
    "test_runs": K6CloudEndpointConfig(
        name="test_runs",
        path="/test_runs",
        primary_keys=["id"],
        partition_key="created",
        time_filter_param="created_after",
        incremental_fields=_created_incremental_field(),
    ),
    # Projects and Load tests both carry a stable `created` timestamp but expose no
    # server-side time filter (only `$orderby`/`name`), so they are full refresh only.
    # `$orderby=created` keeps offset pagination stable across pages.
    "projects": K6CloudEndpointConfig(
        name="projects",
        path="/projects",
        primary_keys=["id"],
        partition_key="created",
        order_by="created",
        incremental_fields=[],
    ),
    "load_tests": K6CloudEndpointConfig(
        name="load_tests",
        path="/load_tests",
        primary_keys=["id"],
        partition_key="created",
        order_by="created",
        incremental_fields=[],
    ),
    # Schedules have no `created` timestamp (only `starts`/`next_run`, both mutable), so
    # partitioning is disabled. Offset-paginated, no time filter -> full refresh.
    "schedules": K6CloudEndpointConfig(
        name="schedules",
        path="/schedules",
        primary_keys=["id"],
        incremental_fields=[],
    ),
    # Load zones is a small reference table returned in a single page (no $skip/$top,
    # no @nextLink) with no timestamps. Full refresh, off by default as lookup data.
    "load_zones": K6CloudEndpointConfig(
        name="load_zones",
        path="/load_zones",
        primary_keys=["id"],
        incremental_fields=[],
        paginated=False,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(K6_CLOUD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in K6_CLOUD_ENDPOINTS.items()
}
