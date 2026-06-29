from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["cursor", "page", "offset", "none"]


@dataclass
class DatadogEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. ``None`` means the body itself is the list.
    data_path: Optional[str] = None
    primary_key: str = "id"
    pagination: PaginationStyle = "none"
    page_size: int = 100
    # Pagination param names (only the ones relevant to ``pagination`` are set per endpoint).
    page_size_param: Optional[str] = None
    page_index_param: Optional[str] = None  # zero-indexed page number
    offset_param: Optional[str] = None  # row offset
    # v2 JSON:API records nest their useful fields under ``attributes``; flatten them to the root.
    flatten_attributes: bool = False
    # Stable, immutable datetime field used for partitioning (never ``modified``/``updated``).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Server-side timestamp filter param (e.g. ``filter[from]``). Only set when the API genuinely
    # filters server-side — leaving it ``None`` keeps the endpoint full-refresh only.
    timestamp_filter_param: Optional[str] = None
    # Value for the ``sort`` query param. For incremental endpoints this must be an ascending,
    # monotonic field so the pipeline's watermark advances correctly.
    sort_param: Optional[str] = None
    # First-sync lookback window for endpoints with a server-side timestamp filter. Datadog's
    # event-search endpoints default ``filter[from]`` to ``now-15m`` when it's omitted, so without
    # this the very first sync would only fetch the last 15 minutes. We seed ``filter[from]`` to
    # ``now - default_lookback_days`` instead; Datadog clamps it to the account's retention.
    default_lookback_days: Optional[int] = None

    @property
    def supports_incremental(self) -> bool:
        return self.timestamp_filter_param is not None


def _timestamp_incremental_fields(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


# Endpoint catalog. Coverage mirrors the canonical Datadog streams exposed by the Airbyte and
# Fivetran connectors (logs, audit logs, events, dashboards, monitors, users, incidents, SLOs,
# synthetic tests, downtimes).
#
# Incremental vs full refresh: only the v2 event-style endpoints (logs / audit_logs / events)
# expose a genuine server-side timestamp filter (``filter[from]``) and an ascending ``timestamp``
# sort, so only those are marked incremental. The list/config endpoints have no server-side time
# filter, so they ship as full refresh and dedupe on their primary key.
DATADOG_ENDPOINTS: dict[str, DatadogEndpointConfig] = {
    # --- Append-only, server-side timestamp filter (incremental) ---
    "logs": DatadogEndpointConfig(
        name="logs",
        path="/api/v2/logs/events",
        data_path="data",
        pagination="cursor",
        page_size=1000,
        page_size_param="page[limit]",
        flatten_attributes=True,
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields("timestamp"),
        default_incremental_field="timestamp",
        timestamp_filter_param="filter[from]",
        sort_param="timestamp",
        default_lookback_days=30,
    ),
    "audit_logs": DatadogEndpointConfig(
        name="audit_logs",
        path="/api/v2/audit/events",
        data_path="data",
        pagination="cursor",
        page_size=1000,
        page_size_param="page[limit]",
        flatten_attributes=True,
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields("timestamp"),
        default_incremental_field="timestamp",
        timestamp_filter_param="filter[from]",
        sort_param="timestamp",
        default_lookback_days=30,
    ),
    "events": DatadogEndpointConfig(
        name="events",
        path="/api/v2/events",
        data_path="data",
        pagination="cursor",
        page_size=1000,
        page_size_param="page[limit]",
        flatten_attributes=True,
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields("timestamp"),
        default_incremental_field="timestamp",
        timestamp_filter_param="filter[from]",
        sort_param="timestamp",
        default_lookback_days=30,
    ),
    # --- Full refresh ---
    "dashboards": DatadogEndpointConfig(
        name="dashboards",
        path="/api/v1/dashboard",
        data_path="dashboards",
        pagination="none",
        partition_key="created_at",
    ),
    "monitors": DatadogEndpointConfig(
        name="monitors",
        path="/api/v1/monitor",
        data_path=None,
        pagination="page",
        page_size=100,
        page_size_param="page_size",
        page_index_param="page",
        partition_key="created",
    ),
    "users": DatadogEndpointConfig(
        name="users",
        path="/api/v2/users",
        data_path="data",
        pagination="page",
        page_size=100,
        page_size_param="page[size]",
        page_index_param="page[number]",
        flatten_attributes=True,
        partition_key="created_at",
    ),
    "incidents": DatadogEndpointConfig(
        name="incidents",
        path="/api/v2/incidents",
        data_path="data",
        pagination="offset",
        page_size=100,
        page_size_param="page[size]",
        offset_param="page[offset]",
        flatten_attributes=True,
        partition_key="created",
    ),
    "slos": DatadogEndpointConfig(
        name="slos",
        path="/api/v1/slo",
        data_path="data",
        pagination="offset",
        page_size=100,
        page_size_param="limit",
        offset_param="offset",
        # SLO ``created_at`` is a unix epoch integer rather than an ISO datetime, so it isn't a
        # safe partition key — left unpartitioned.
    ),
    "synthetic_tests": DatadogEndpointConfig(
        name="synthetic_tests",
        path="/api/v1/synthetics/tests",
        data_path="tests",
        pagination="none",
        primary_key="public_id",
    ),
    "downtimes": DatadogEndpointConfig(
        name="downtimes",
        path="/api/v2/downtime",
        data_path="data",
        pagination="offset",
        page_size=100,
        page_size_param="page[limit]",
        offset_param="page[offset]",
        flatten_attributes=True,
    ),
}

ENDPOINTS = tuple(DATADOG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DATADOG_ENDPOINTS.items()
}

# Datadog retains logs / audit logs / events for a limited window, so the first sync can only
# reach back as far as the account's retention allows.
LIMITED_RETENTION_ENDPOINTS = {"logs", "audit_logs", "events"}
