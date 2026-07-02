from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Twilio Segment exposes two regional hosts for the same workspace-scoped Public API. The token is
# bound to one region, so the user picks it at connect time (Airbyte models this as `region: api|eu1`).
REGION_BASE_URLS: dict[str, str] = {
    "api": "https://api.segmentapis.com",
    "eu1": "https://eu1.api.segmentapis.com",
}
DEFAULT_REGION = "api"


@dataclass
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
    # timestamps, so only audit events (immutable `timestamp`) set this.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True
    # Top-level fields stripped from every row before it's persisted. Segment's config endpoints
    # embed credential-like blobs — destination/warehouse connection `settings` (third-party API
    # keys, DB passwords) and source `writeKeys`. These are free-form per integration, so there's
    # no reliable allowlist of safe sub-keys; we drop the whole field rather than risk leaking
    # secrets into a queryable warehouse table.
    redacted_fields: frozenset[str] = field(default_factory=frozenset)


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
}

ENDPOINTS = tuple(SEGMENT_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SEGMENT_ENDPOINTS.items()
}
