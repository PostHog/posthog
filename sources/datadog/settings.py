from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

PaginationStyle = Literal["cursor", "page", "offset", "record_id", "none"]
# How a timestamp filter value is rendered for the endpoint's query param. Datadog uses a
# different encoding per family: ISO-8601 with milliseconds for event search, month or hour
# precision for usage metering, and epoch seconds for the metrics and SLO history endpoints.
TimestampFormat = Literal["iso_ms", "month", "hour", "epoch_seconds"]


@frozen
class DatadogFanOutConfig:
    """Wires a child endpoint to the parent endpoint whose ids fill its path placeholder."""

    parent_endpoint: str
    # Field on each parent row holding the id substituted into the child path's ``{parent_id}``.
    parent_id_field: str
    # Field name the parent id is written to on every child row, so the child table joins back.
    child_id_field: str
    # Datadog caps neither the SLO nor the team list, so bound the walk rather than letting a
    # pathological account turn one sync into an unbounded request fan.
    max_parents: int = 2000


@frozen
class DatadogEndpointConfig:
    name: str
    path: str
    # Key in the response body holding the list of records. ``None`` means the body itself is the list.
    data_path: Optional[str] = None
    # The record's key, unique across the whole table. Fan-out children include the parent id.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # ``/api/v1/slo/{slo_id}/history`` answers with one object under ``data`` rather than a list.
    single_object: bool = False
    # Endpoints that answer with bare strings (``/api/v1/metrics``) wrap each one in a row under
    # this column name.
    scalar_field: Optional[str] = None
    pagination: PaginationStyle = "none"
    page_size: int = 100
    # Pagination param names (only the ones relevant to ``pagination`` are set per endpoint).
    page_size_param: Optional[str] = None
    page_index_param: Optional[str] = None  # zero-indexed page number
    offset_param: Optional[str] = None  # row offset
    record_id_param: Optional[str] = None  # opaque next-record cursor echoed back as a param
    # Where the next-record cursor sits in the response body.
    record_id_path: tuple[str, ...] = ("meta", "pagination", "next_record_id")
    # Constant query params the endpoint requires on every request.
    static_params: dict[str, str] = field(default_factory=dict)
    # v2 JSON:API records nest their useful fields under ``attributes``; flatten them to the root.
    flatten_attributes: bool = False
    # Stable, immutable datetime field used for partitioning (never ``modified``/``updated``).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Server-side timestamp filter param (e.g. ``filter[from]``). Only set when the API genuinely
    # filters server-side — leaving it ``None`` keeps the endpoint full-refresh only.
    timestamp_filter_param: Optional[str] = None
    timestamp_filter_format: TimestampFormat = "iso_ms"
    # Closing bound for endpoints that require a window rather than an open-ended start
    # (``/api/v1/slo/{slo_id}/history`` rejects a request without ``to_ts``). Always sent as now.
    window_end_param: Optional[str] = None
    # Parent endpoint to fan out over, for paths carrying a ``{parent_id}`` placeholder.
    parent: Optional[DatadogFanOutConfig] = None
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
        # A server-side time filter alone isn't incremental — the endpoint also has to return a
        # cursor field the pipeline can checkpoint. ``metrics`` filters on ``from`` but every row
        # is just a metric name, so it stays full refresh.
        return self.timestamp_filter_param is not None and bool(self.incremental_fields)


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
# synthetic tests, downtimes), plus the metrics, usage metering, SLO history and teams families.
#
# Incremental vs full refresh: the v2 event-style endpoints (logs / audit_logs / events) expose a
# genuine server-side timestamp filter (``filter[from]``) and an ascending ``timestamp`` sort, and
# the usage-metering endpoints filter on ``filter[timestamp][start]`` / ``start_month``, so those
# are marked incremental. The list/config endpoints have no server-side time filter, so they ship
# as full refresh and dedupe on their primary key.
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
    "usage_hourly": DatadogEndpointConfig(
        name="usage_hourly",
        path="/api/v2/usage/hourly_usage",
        data_path="data",
        # ``id`` is documented only as "unique ID of the response", so key on the grain the
        # endpoint actually reports: one row per org, per product family, per hour.
        primary_keys=["public_id", "product_family", "timestamp"],
        pagination="record_id",
        page_size=500,
        page_size_param="page[limit]",
        record_id_param="page[next_record_id]",
        # ``filter[product_families]`` is required and has no implicit default.
        static_params={"filter[product_families]": "all"},
        flatten_attributes=True,
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields("timestamp"),
        default_incremental_field="timestamp",
        timestamp_filter_param="filter[timestamp][start]",
        timestamp_filter_format="hour",
        default_lookback_days=30,
    ),
    "usage_summary": DatadogEndpointConfig(
        name="usage_summary",
        path="/api/v1/usage/summary",
        data_path="usage",
        primary_keys=["date"],
        pagination="none",
        partition_key="date",
        incremental_fields=_timestamp_incremental_fields("date"),
        default_incremental_field="date",
        timestamp_filter_param="start_month",
        timestamp_filter_format="month",
        # ``start_month`` is required and rejected beyond 15 months back; stay inside that.
        default_lookback_days=400,
    ),
    "usage_historical_cost": DatadogEndpointConfig(
        name="usage_historical_cost",
        path="/api/v2/usage/historical_cost",
        data_path="data",
        primary_keys=["public_id", "date"],
        pagination="none",
        flatten_attributes=True,
        partition_key="date",
        incremental_fields=_timestamp_incremental_fields("date"),
        default_incremental_field="date",
        timestamp_filter_param="start_month",
        timestamp_filter_format="month",
        default_lookback_days=400,
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
        primary_keys=["public_id"],
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
    "metrics": DatadogEndpointConfig(
        name="metrics",
        path="/api/v1/metrics",
        data_path="metrics",
        # The endpoint answers with bare metric-name strings rather than objects.
        scalar_field="metric",
        primary_keys=["metric"],
        pagination="none",
        timestamp_filter_param="from",
        timestamp_filter_format="epoch_seconds",
        default_lookback_days=30,
    ),
    "usage_billable_summary": DatadogEndpointConfig(
        name="usage_billable_summary",
        path="/api/v1/usage/billable-summary",
        data_path="usage",
        # One row per org per billing period; omitting ``month`` returns every available period.
        primary_keys=["public_id", "start_date"],
        pagination="none",
        partition_key="start_date",
    ),
    "usage_estimated_cost": DatadogEndpointConfig(
        name="usage_estimated_cost",
        path="/api/v2/usage/estimated_cost",
        data_path="data",
        primary_keys=["public_id", "date"],
        pagination="none",
        flatten_attributes=True,
        partition_key="date",
        # Datadog only holds estimated cost for the current and previous month, so there is no
        # history to filter into and the whole window is cheap to re-read each sync.
    ),
    "slo_corrections": DatadogEndpointConfig(
        name="slo_corrections",
        # The org-wide list returns the same corrections as ``/api/v1/slo/{slo_id}/corrections``
        # and carries ``slo_id`` on every row, so it needs no fan-out over the SLO list.
        path="/api/v1/slo/correction",
        data_path="data",
        pagination="offset",
        page_size=100,
        page_size_param="limit",
        offset_param="offset",
        flatten_attributes=True,
        # ``created_at`` is epoch seconds rather than an ISO datetime, so it isn't a partition key.
    ),
    "slo_history": DatadogEndpointConfig(
        name="slo_history",
        path="/api/v1/slo/{parent_id}/history",
        data_path="data",
        # The history of one SLO is a single object, not a list of them.
        single_object=True,
        primary_keys=["slo_id", "from_ts"],
        pagination="none",
        parent=DatadogFanOutConfig(parent_endpoint="slos", parent_id_field="id", child_id_field="slo_id"),
        timestamp_filter_param="from_ts",
        timestamp_filter_format="epoch_seconds",
        window_end_param="to_ts",
        default_lookback_days=30,
    ),
    "teams": DatadogEndpointConfig(
        name="teams",
        path="/api/v2/team",
        data_path="data",
        pagination="page",
        page_size=100,
        page_size_param="page[size]",
        page_index_param="page[number]",
        flatten_attributes=True,
        partition_key="created_at",
    ),
    "team_memberships": DatadogEndpointConfig(
        name="team_memberships",
        path="/api/v2/team/{parent_id}/memberships",
        data_path="data",
        # The membership id embeds the team id, but key on both so the table stays unique even if
        # Datadog ever changes that encoding.
        primary_keys=["team_id", "id"],
        pagination="page",
        page_size=100,
        page_size_param="page[size]",
        page_index_param="page[number]",
        parent=DatadogFanOutConfig(parent_endpoint="teams", parent_id_field="id", child_id_field="team_id"),
        flatten_attributes=True,
    ),
}

# Vendor API versions. Datadog serves each resource under a fixed API version, so this source
# already reads logs/audit_logs/events/users/incidents/downtimes at /api/v2 and
# dashboards/monitors/slos/synthetic_tests at /api/v1 (those four have no v2 list endpoint). Both
# labels therefore resolve to the identical request paths; the pin only selects the version a new
# source is stamped with and drives the deprecation warning for v1.
DATADOG_API_VERSION_V1 = "v1"
DATADOG_API_VERSION_V2 = "v2"
DATADOG_SUPPORTED_VERSIONS = (DATADOG_API_VERSION_V1, DATADOG_API_VERSION_V2)
DATADOG_DEFAULT_VERSION = DATADOG_API_VERSION_V2

ENDPOINTS = tuple(DATADOG_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DATADOG_ENDPOINTS.items()
}

# Datadog retains logs / audit logs / events for a limited window, so the first sync can only
# reach back as far as the account's retention allows.
LIMITED_RETENTION_ENDPOINTS = {"logs", "audit_logs", "events"}
