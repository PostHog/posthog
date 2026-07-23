from dataclasses import dataclass, field

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SortMode
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

COURIER_BASE_URL = "https://api.courier.com"

# Courier's default page size is small (~10 messages/page per the vendor docs); raising `limit`
# cuts the round-trips a full backfill needs. No documented maximum, so we stay conservative.
COURIER_PAGE_SIZE = 100


@dataclass(frozen=True)
class CourierEndpointConfig:
    path: str
    # The list of records is wrapped under a named key that varies per endpoint ("results" vs
    # "items").
    data_selector: str
    primary_keys: tuple[str, ...] = ("id",)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Request param carrying the server-side lower-bound timestamp filter.
    incremental_param: str | None = None
    # Stable datetime field to partition on; None disables partitioning.
    partition_key: str | None = None
    # Courier's list endpoints document no explicit sort param at all. Treated as newest-first
    # (matching Knock's identical no-sort-param message-log endpoint) rather than assumed
    # ascending, which would silently corrupt the incremental watermark if wrong.
    sort_mode: SortMode = "asc"
    # Where the paginator finds the next-page cursor in the response body: nested under `paging`
    # for every list endpoint except Tenants, which returns `cursor` at the top level.
    cursor_path: str = "paging.cursor"
    # Fields that arrive as epoch-millisecond ints or ISO-8601 strings and are converted to real
    # datetimes before yielding, so partitioning and incremental filtering see proper timestamps
    # instead of raw millis (which the partitioner would otherwise misread as epoch seconds).
    timestamp_fields: tuple[str, ...] = ()


ENDPOINTS_CONFIG: dict[str, CourierEndpointConfig] = {
    # The primary stream: per-message delivery status/history. `enqueued_after` is a documented
    # server-side filter, so incremental sync genuinely reduces pages.
    "Messages": CourierEndpointConfig(
        path="/messages",
        data_selector="results",
        primary_keys=("id",),
        incremental_fields=[incremental_field("enqueued")],
        incremental_param="enqueued_after",
        partition_key="enqueued",
        sort_mode="desc",
        timestamp_fields=("enqueued", "sent", "delivered", "opened", "clicked"),
    ),
    # Account activity log. No server-side timestamp filter is documented, so full refresh only.
    "AuditEvents": CourierEndpointConfig(
        path="/audit-events",
        data_selector="results",
        primary_keys=("auditEventId",),
        partition_key="timestamp",
        timestamp_fields=("timestamp",),
    ),
    # Saved recipient segments. No server-side timestamp filter is documented.
    "Audiences": CourierEndpointConfig(
        path="/audiences",
        data_selector="items",
        primary_keys=("id",),
        partition_key="created_at",
        timestamp_fields=("created_at", "updated_at"),
    ),
    # Branding profiles (templates/colors/logos). No server-side timestamp filter, and the
    # `created`/`updated` unix timestamps are undocumented as to unit, so no partitioning.
    "Brands": CourierEndpointConfig(
        path="/brands",
        data_selector="results",
        primary_keys=("id",),
    ),
    # Multi-tenant scoping objects. No timestamp fields at all, so no partitioning.
    "Tenants": CourierEndpointConfig(
        path="/tenants",
        data_selector="items",
        primary_keys=("id",),
        cursor_path="cursor",
    ),
}

ENDPOINTS = tuple(ENDPOINTS_CONFIG.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ENDPOINTS_CONFIG.items()
}
