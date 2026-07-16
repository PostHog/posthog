from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

RUNPOD_BASE_URL = "https://rest.runpod.io/v1"

# Billing history is aggregated into time buckets; a fixed size keeps the bucket `time` values (and
# the surrogate ids derived from them) stable across syncs. `day` matches the API default and keeps
# row volume low while still supporting daily cost analytics.
BILLING_BUCKET_SIZE = "day"

# A bucket keeps accumulating charges until it closes, and RunPod doesn't document how long a closed
# bucket can be restated, so every incremental run re-pulls a trailing two days of buckets. Merge
# dedupes the overlap on the surrogate `id`.
_BILLING_LOOKBACK_SECONDS = 60 * 60 * 48

_TIME_INCREMENTAL_FIELD: list[IncrementalField] = [
    {
        "label": "time",
        "type": IncrementalFieldType.DateTime,
        "field": "time",
        "field_type": IncrementalFieldType.DateTime,
    },
]


@dataclass
class RunPodEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    # Billing endpoints return time-bucketed usage records windowed by startTime/endTime; resource
    # list endpoints return the full account inventory in one unpaginated response.
    is_billing: bool = False
    # Billing only: the `grouping` dimension requested so each bucket splits per resource. None keeps
    # the endpoint's aggregate shape (network volume billing has no grouping parameter).
    group_by: Optional[str] = None
    # Stable partition key — the bucket start never changes once emitted. Inventory tables are small
    # full-refresh snapshots, so they are not partitioned.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where the API exposes a genuine server-side time filter (the billing endpoints via
    # startTime). Inventory lists have no updated-since filter, so they are full-refresh only.
    supports_incremental: bool = False
    # Billing buckets get restated while open, so append would materialize duplicates; merge-only.
    supports_append: bool = False
    default_incremental_lookback_seconds: Optional[int] = None
    should_sync_default: bool = True


RUNPOD_ENDPOINTS: dict[str, RunPodEndpointConfig] = {
    "pods": RunPodEndpointConfig(
        name="pods",
        path="/pods",
        primary_keys=["id"],
    ),
    "endpoints": RunPodEndpointConfig(
        name="endpoints",
        path="/endpoints",
        primary_keys=["id"],
    ),
    "templates": RunPodEndpointConfig(
        name="templates",
        path="/templates",
        primary_keys=["id"],
    ),
    "network_volumes": RunPodEndpointConfig(
        name="network_volumes",
        path="/networkvolumes",
        primary_keys=["id"],
    ),
    # `id` on the billing tables is synthesized from the bucket start plus every grouping dimension
    # (see runpod.py) — a non-null, stable key so merge updates a bucket in place as its amounts get
    # restated.
    "billing_pods": RunPodEndpointConfig(
        name="billing_pods",
        path="/billing/pods",
        primary_keys=["id"],
        is_billing=True,
        group_by="podId",
        partition_key="time",
        incremental_fields=_TIME_INCREMENTAL_FIELD,
        supports_incremental=True,
        default_incremental_lookback_seconds=_BILLING_LOOKBACK_SECONDS,
    ),
    "billing_endpoints": RunPodEndpointConfig(
        name="billing_endpoints",
        path="/billing/endpoints",
        primary_keys=["id"],
        is_billing=True,
        group_by="endpointId",
        partition_key="time",
        incremental_fields=_TIME_INCREMENTAL_FIELD,
        supports_incremental=True,
        default_incremental_lookback_seconds=_BILLING_LOOKBACK_SECONDS,
    ),
    # Network volume billing has no grouping parameter — records are account-wide aggregates per
    # bucket, so the surrogate id reduces to the bucket start.
    "billing_network_volumes": RunPodEndpointConfig(
        name="billing_network_volumes",
        path="/billing/networkvolumes",
        primary_keys=["id"],
        is_billing=True,
        partition_key="time",
        incremental_fields=_TIME_INCREMENTAL_FIELD,
        supports_incremental=True,
        default_incremental_lookback_seconds=_BILLING_LOOKBACK_SECONDS,
    ),
}

ENDPOINTS = tuple(RUNPOD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in RUNPOD_ENDPOINTS.items()
}
