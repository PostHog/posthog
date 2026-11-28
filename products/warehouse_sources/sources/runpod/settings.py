from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

RUNPOD_BASE_URL = "https://api.runpod.io/v2"

INVENTORY_PAGE_SIZE = 1000

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


@dataclass(frozen=False)
class RunPodEndpointConfig:
    name: str
    path: str
    response_key: str
    primary_keys: list[str]
    # Billing endpoints return one record per resource per time bucket, windowed by startTime/endTime.
    is_billing: bool = False
    # Stable partition key — the bucket start never changes once emitted. Inventory tables are small
    # full-refresh snapshots, so they are not partitioned.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only True where the API exposes a genuine server-side time filter (the billing endpoints via
    # startTime). Inventory lists have no updated-since filter, so they are full-refresh only.
    supports_incremental: bool = False
    # Response keys holding user-configured secrets — RunPod Pods, endpoints, and templates carry an
    # `env` map and `args`/`cmd`/`entrypoint` container commands that can contain cloud access keys
    # and other credentials. These are stripped recursively before yielding, and HTTP sample
    # capture is disabled for the endpoint (the values are arbitrary user-chosen strings the sample
    # scrubbers can't recognise) so raw bodies with the secrets never land in captured samples.
    sensitive_keys: tuple[str, ...] = ()
    # Billing buckets get restated while open, so append would materialize duplicates; merge-only.
    supports_append: bool = False
    default_incremental_lookback_seconds: Optional[int] = None
    should_sync_default: bool = True


_CONTAINER_SECRET_KEYS = ("env", "args", "cmd", "entrypoint")

RUNPOD_ENDPOINTS: dict[str, RunPodEndpointConfig] = {
    "pods": RunPodEndpointConfig(
        name="pods",
        path="/pods",
        response_key="pods",
        primary_keys=["id"],
        sensitive_keys=_CONTAINER_SECRET_KEYS,
    ),
    "endpoints": RunPodEndpointConfig(
        name="endpoints",
        path="/serverless",
        response_key="endpoints",
        primary_keys=["id"],
        sensitive_keys=_CONTAINER_SECRET_KEYS,
    ),
    "templates": RunPodEndpointConfig(
        name="templates",
        path="/templates",
        response_key="templates",
        primary_keys=["id"],
        sensitive_keys=_CONTAINER_SECRET_KEYS,
    ),
    "network_volumes": RunPodEndpointConfig(
        name="network_volumes",
        path="/network-volumes",
        response_key="networkVolumes",
        primary_keys=["id"],
    ),
    # `id` on the billing tables is synthesized from the bucket start plus the billed resource id
    # (see runpod.py) — a non-null, stable key so merge updates a bucket in place as its amounts get
    # restated.
    "billing_pods": RunPodEndpointConfig(
        name="billing_pods",
        path="/billing/pods",
        response_key="records",
        primary_keys=["id"],
        is_billing=True,
        partition_key="time",
        incremental_fields=_TIME_INCREMENTAL_FIELD,
        supports_incremental=True,
        default_incremental_lookback_seconds=_BILLING_LOOKBACK_SECONDS,
    ),
    # Serverless billing. In v2, `/billing/endpoints` is Public Endpoint billing, a different product.
    "billing_endpoints": RunPodEndpointConfig(
        name="billing_endpoints",
        path="/billing/serverless",
        response_key="records",
        primary_keys=["id"],
        is_billing=True,
        partition_key="time",
        incremental_fields=_TIME_INCREMENTAL_FIELD,
        supports_incremental=True,
        default_incremental_lookback_seconds=_BILLING_LOOKBACK_SECONDS,
    ),
    "billing_network_volumes": RunPodEndpointConfig(
        name="billing_network_volumes",
        path="/billing/network-volumes",
        response_key="records",
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
