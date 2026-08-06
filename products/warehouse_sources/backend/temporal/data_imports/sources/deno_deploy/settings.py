from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How the transport should page and shape a given endpoint's response:
# - "list":      a plain paginated list (Link: <url>; rel="next" header), rows used as-is.
# - "logs":      the runtime-logs endpoint — cursor lives in the body (`next_cursor`), rows carry
#                no natural id, so the transport synthesizes a stable one for merge dedup.
# - "analytics": the columnar {fields, values} usage payload, reshaped into one row per time bucket.
EndpointKind = Literal["list", "logs", "analytics"]


@dataclass
class DenoDeployEndpointConfig:
    name: str
    path: str  # Path template; fan-out endpoints carry a {app} placeholder.
    kind: EndpointKind
    incremental_fields: list[IncrementalField]
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    # Primary key columns for dedup. A list declares a composite key, required for fan-out children
    # whose row id is only unique within a parent app.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Fan out over every app in the org, substituting each app's id into the {app} path placeholder.
    fan_out_over_apps: bool = False
    page_size: Optional[int] = None
    # First-sync/full-refresh floor for the time-windowed endpoints (logs, analytics): only pull the
    # last N days instead of the whole (potentially unbounded) history. `start`/`since` are the only
    # way to bound these, and the logs endpoint requires `start`, so a default window is mandatory.
    default_lookback_days: Optional[int] = None
    # Safety overlap subtracted from the incremental watermark on every run. Because each run fetches
    # every app up to `now`, consecutive [start, now] windows already overlap and leave no gap; this
    # just re-pulls a small trailing window to absorb boundary-second and clock-skew effects. Merge
    # dedupes the re-pulled rows on the primary key.
    incremental_lookback: Optional[timedelta] = None
    should_sync_default: bool = True


DENO_DEPLOY_ENDPOINTS: dict[str, DenoDeployEndpointConfig] = {
    # Every app in the organization the access token is scoped to. Small catalog, no server-side
    # updated-since filter, so full refresh; created_at is immutable and partitions stably.
    "apps": DenoDeployEndpointConfig(
        name="apps",
        path="/v2/apps",
        kind="list",
        partition_key="created_at",
        incremental_fields=[],
    ),
    # Deployment/build history per app. Fans out over apps. The list endpoint exposes only a `status`
    # filter (no updated-since), so full refresh; created_at is immutable. The row id is globally
    # addressable (/v2/revisions/{id}) but we keep app_id in the key defensively so a fan-out child
    # is unique table-wide regardless.
    "revisions": DenoDeployEndpointConfig(
        name="revisions",
        path="/v2/apps/{app}/revisions",
        kind="list",
        partition_key="created_at",
        primary_keys=["app_id", "id"],
        fan_out_over_apps=True,
        incremental_fields=[],
    ),
    # Custom domains for the organization. Small catalog, no updated-since filter, full refresh.
    "domains": DenoDeployEndpointConfig(
        name="domains",
        path="/v2/domains",
        kind="list",
        partition_key="created_at",
        incremental_fields=[],
    ),
    # Per-app usage metrics in 15-minute buckets. Fans out over apps. `since`/`until` are genuine
    # server-side RFC 3339 time filters, so this syncs incrementally on the bucket start `time`.
    # Merge on [app_id, time] dedupes the re-pulled boundary bucket.
    "analytics": DenoDeployEndpointConfig(
        name="analytics",
        path="/v2/apps/{app}/analytics",
        kind="analytics",
        partition_key="time",
        primary_keys=["app_id", "time"],
        fan_out_over_apps=True,
        default_incremental_field="time",
        default_lookback_days=30,
        incremental_lookback=timedelta(minutes=30),  # one bucket of slack
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.DateTime,
                "field": "time",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Time-ranged runtime logs per app. Fans out over apps. `start` is a required server-side ISO 8601
    # filter (and `end` must be passed or the endpoint switches to real-time streaming), so this syncs
    # incrementally on `timestamp`. Runtime log lines carry no natural id, so the transport synthesizes
    # a content hash `id` and merges on it — re-pulled boundary lines dedupe instead of duplicating.
    "logs": DenoDeployEndpointConfig(
        name="logs",
        path="/v2/apps/{app}/logs",
        kind="logs",
        partition_key="timestamp",
        primary_keys=["id"],
        fan_out_over_apps=True,
        page_size=1000,  # logs endpoint max
        default_incremental_field="timestamp",
        default_lookback_days=7,
        incremental_lookback=timedelta(minutes=5),
        incremental_fields=[
            {
                "label": "timestamp",
                "type": IncrementalFieldType.DateTime,
                "field": "timestamp",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        # Logs are high volume; leave them deselected by default so a fresh connection doesn't backfill
        # a week of every app's logs unless the user opts in.
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(DENO_DEPLOY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DENO_DEPLOY_ENDPOINTS.items()
}
