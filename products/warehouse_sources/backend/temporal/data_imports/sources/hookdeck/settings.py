from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Hookdeck pins the API version as the first path segment. Omitting it resolves to the OLDEST
# supported version, so the version is always part of the base URL.
HOOKDECK_API_HOST = "https://api.hookdeck.com"

# `limit` is documented as max 250 (the OpenAPI schema allows 255).
PAGE_SIZE = 250

# Hookdeck restates a delivery record as retries land: `status`, `attempts`, `response_status`,
# `error_code` and the `*_at` timestamps all move after the row was created. Incremental runs
# re-read a trailing day of `created_at` so those updates merge in instead of freezing at the
# value they had when first imported.
_RESTATED_RECORD_LOOKBACK_SECONDS = 24 * 60 * 60


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class HookdeckEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Sent as `order_by` when the endpoint is synced without an incremental field. Every value here
    # (and every incremental field below) must be in the endpoint's documented `order_by` enum, so
    # rows arrive in the order `sort_mode="asc"` promises.
    default_order_by: str = "created_at"
    # Only fields Hookdeck accepts BOTH as a date filter and as an `order_by` value. A field that
    # can be filtered but not sorted (e.g. `last_attempt_at` on events) would leave the request
    # sort and the pipeline watermark on different columns, which corrupts the watermark.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: Optional[str] = "created_at"
    default_incremental_lookback_seconds: Optional[int] = None
    description: Optional[str] = None
    # Rows from this endpoint can carry auth/verification secrets (destination auth, source
    # verification, transformation `env`, and the source/destination objects connections embed).
    # When set, those nested fields are masked before rows are written to the warehouse so a reader
    # of the table can't recover credentials they don't have the Hookdeck key for.
    contains_credentials: bool = False


HOOKDECK_ENDPOINTS: dict[str, HookdeckEndpointConfig] = {
    "events": HookdeckEndpointConfig(
        name="events",
        path="/events",
        incremental_fields=[_datetime_field("created_at")],
        default_incremental_lookback_seconds=_RESTATED_RECORD_LOOKBACK_SECONDS,
        description="Delivery records: one row per event Hookdeck queued for a connection, with its status, attempt count, error code and retry timestamps",
    ),
    "attempts": HookdeckEndpointConfig(
        name="attempts",
        path="/attempts",
        # Full refresh only: `/attempts` filters by `event_id` and `id`, and has no date filter, so
        # there is no server-side cursor to sync from.
        description="Individual delivery attempts for events, including the response status, latency and error code of each try",
    ),
    "requests": HookdeckEndpointConfig(
        name="requests",
        path="/requests",
        incremental_fields=[_datetime_field("created_at"), _datetime_field("ingested_at")],
        default_incremental_lookback_seconds=_RESTATED_RECORD_LOOKBACK_SECONDS,
        description="Raw inbound HTTP requests received by your sources, including requests that were ignored and produced no event",
    ),
    "issues": HookdeckEndpointConfig(
        name="issues",
        path="/issues",
        incremental_fields=[
            _datetime_field("created_at"),
            _datetime_field("first_seen_at"),
            _datetime_field("last_seen_at"),
        ],
        default_incremental_lookback_seconds=_RESTATED_RECORD_LOOKBACK_SECONDS,
        description="Grouped delivery, transformation, backpressure and request failures raised by your issue triggers",
    ),
    "connections": HookdeckEndpointConfig(
        name="connections",
        path="/connections",
        description="Routes that tie a source to a destination, with the rules (retry, filter, transform, delay) applied in between",
        # Embeds the full source and destination objects, including their auth/verification config.
        contains_credentials=True,
    ),
    "sources": HookdeckEndpointConfig(
        name="sources",
        path="/sources",
        description="Inbound endpoints that receive webhooks from a provider, with their URL, type and verification config",
        contains_credentials=True,
    ),
    "destinations": HookdeckEndpointConfig(
        name="destinations",
        path="/destinations",
        description="Endpoints Hookdeck delivers events to, with their type and delivery config",
        contains_credentials=True,
    ),
    "transformations": HookdeckEndpointConfig(
        name="transformations",
        path="/transformations",
        description="JavaScript transformations that rewrite an event before it is delivered",
        contains_credentials=True,
    ),
    "issue_triggers": HookdeckEndpointConfig(
        name="issue_triggers",
        path="/issue-triggers",
        description="Rules that decide when a delivery, transformation, backpressure or request failure is raised as an issue, and where it is notified",
        contains_credentials=True,
    ),
    "bookmarks": HookdeckEndpointConfig(
        name="bookmarks",
        path="/bookmarks",
        description="Saved event payloads kept for replaying against a connection",
    ),
}

ENDPOINTS = tuple(HOOKDECK_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: endpoint.incremental_fields for name, endpoint in HOOKDECK_ENDPOINTS.items()
}
