from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField

# Twilio Segment exposes two regional hosts for the same workspace-scoped Public API. The token is
# bound to one region, so the user picks it at connect time (Airbyte models this as `region: api|eu1`).
REGION_BASE_URLS: dict[str, str] = {
    "api": "https://api.segmentapis.com",
    "eu1": "https://eu1.api.segmentapis.com",
}
DEFAULT_REGION = "api"


@dataclass(frozen=False)
class SegmentEndpointConfig:
    name: str
    path: str
    # Keys must be unique table-wide. Most resources expose a global `id`; labels have none, so they
    # use the natural (key, value) composite.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # `GET /` (Get Workspace) returns a single object under `data.<object_key>` with no pagination,
    # rather than a paginated list. Such endpoints yield exactly one row.
    single_object_key: Optional[str] = None
    # A stable, immutable datetime field to partition on. Segment's config/admin objects carry no
    # timestamps, so only audit events (`timestamp`) and Reverse ETL syncs (`startedAt`) set this.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    # Top-level fields stripped from every row before it's persisted. Segment's config endpoints
    # embed credential-like blobs — destination/warehouse connection `settings` (third-party API
    # keys, DB passwords) and source `writeKeys`. These are free-form per integration, so there's
    # no reliable allowlist of safe sub-keys; we drop the whole field rather than risk leaking
    # secrets into a queryable warehouse table.
    redacted_fields: frozenset[str] = field(default_factory=frozenset)
    # Child resources read once per parent row. `path` then holds the parent placeholders, and
    # `segment.py` lists the parents and resumes per parent.
    fanout: Optional[Literal["tracking_plan_rules", "delivery_metrics", "reverse_etl_syncs"]] = None


# The Segment Public API is a workspace configuration/admin/usage API (not the event/Profile data
# plane). Every listing endpoint uses cursor pagination (`pagination[count]` / `pagination[cursor]`)
# and wraps its rows in `{"data": {"<resource>": [...], "pagination": {...}}}`.
#
# These resources expose no server-side timestamp filter, so they are full refresh only. Audit events
# document `startTime`/`endTime` filters and so are a future incremental candidate, but that needs a
# live-token smoke test (future-date cutoff) to confirm the filter is honored before we enable it.
SEGMENT_ENDPOINTS: dict[str, SegmentEndpointConfig] = {
    "workspace": SegmentEndpointConfig(
        name="workspace",
        path="/",
        single_object_key="workspace",
    ),
    "sources": SegmentEndpointConfig(name="sources", path="/sources", redacted_fields=frozenset({"writeKeys"})),
    "destinations": SegmentEndpointConfig(
        name="destinations", path="/destinations", redacted_fields=frozenset({"settings"})
    ),
    "warehouses": SegmentEndpointConfig(name="warehouses", path="/warehouses", redacted_fields=frozenset({"settings"})),
    "tracking_plans": SegmentEndpointConfig(name="tracking_plans", path="/tracking-plans"),
    "transformations": SegmentEndpointConfig(name="transformations", path="/transformations"),
    "reverse_etl_models": SegmentEndpointConfig(name="reverse_etl_models", path="/reverse-etl-models"),
    "iam_users": SegmentEndpointConfig(name="iam_users", path="/users"),
    "iam_groups": SegmentEndpointConfig(name="iam_groups", path="/groups"),
    "labels": SegmentEndpointConfig(name="labels", path="/labels", primary_keys=["key", "value"]),
    "audit_events": SegmentEndpointConfig(name="audit_events", path="/audit-events", partition_key="timestamp"),
    # Segment-wide catalogs that resolve the `metadata.id` carried on sources, destinations and warehouses.
    "destinations_catalog": SegmentEndpointConfig(name="destinations_catalog", path="/catalog/destinations"),
    "sources_catalog": SegmentEndpointConfig(name="sources_catalog", path="/catalog/sources"),
    "warehouses_catalog": SegmentEndpointConfig(name="warehouses_catalog", path="/catalog/warehouses"),
    # Rules have no id. A plan holds one rule per (type, key, version), and keyless rule types
    # (identify, group, common) get an empty `key`.
    "tracking_plan_rules": SegmentEndpointConfig(
        name="tracking_plan_rules",
        path="/tracking-plans/{tracking_plan_id}/rules",
        primary_keys=["trackingPlanId", "type", "key", "version"],
        fanout="tracking_plan_rules",
    ),
    # One row per destination and metric, with totals over the last DELIVERY_METRICS_WINDOW_DAYS full days.
    "destination_delivery_metrics": SegmentEndpointConfig(
        name="destination_delivery_metrics",
        path="/destinations/{destination_id}/delivery-metrics",
        primary_keys=["destinationId", "metricName"],
        fanout="delivery_metrics",
    ),
    # A sync can load into several subscriptions of one model, so the sync id is unique only per subscription.
    "reverse_etl_syncs": SegmentEndpointConfig(
        name="reverse_etl_syncs",
        path="/reverse-etl-models/{model_id}/subscriptionId/{subscription_id}/syncs",
        primary_keys=["subscriptionId", "syncId"],
        partition_key="startedAt",
        fanout="reverse_etl_syncs",
    ),
}

# Segment accepts a DAY-granularity range of at most 14 days that starts at most 14 days ago. 12 whole
# days stay inside both limits, also for a resumed run that keeps the window of its first attempt.
DELIVERY_METRICS_WINDOW_DAYS = 12
DELIVERY_METRICS_MAX_LOOKBACK_DAYS = 14

ENDPOINTS = tuple(SEGMENT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SEGMENT_ENDPOINTS.items()
}
