from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _timestamp_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "timestamp",
            "type": IncrementalFieldType.DateTime,
            "field": "timestamp",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


@dataclass
class SigNozEndpointConfig:
    name: str
    kind: Literal["telemetry", "config"]
    # Telemetry endpoints query POST /api/v5/query_range with a composite query.
    signal: Optional[str] = None  # "logs" | "traces"
    # Stable, monotonic sort keys sent as the query's `order`. The secondary key breaks
    # timestamp ties so limit/offset paging is deterministic.
    order_keys: tuple[str, ...] = ()
    # Config endpoints are plain GET list endpoints without pagination.
    path: Optional[str] = None
    # Key path from the response's `data` payload to the list of records. Empty means
    # `data` itself is the list.
    data_keys: tuple[str, ...] = ()
    # When set, config records are projected down to exactly these fields before they are
    # yielded — a strict allowlist that keeps credential-bearing fields (e.g. a notification
    # channel's receiver config) out of the warehouse. None means keep every field.
    allowed_fields: Optional[tuple[str, ...]] = None
    primary_keys: tuple[str, ...] = ("id",)
    # Stable, immutable datetime field used for partitioning (never an updated-at field).
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    page_size: int = 1000
    # First-sync lookback for telemetry endpoints. The query_range API requires an explicit
    # start, so without a stored watermark we reach back this far; SigNoz simply has no data
    # older than the account's retention, so a generous window is harmless.
    default_lookback_days: Optional[int] = None

    @property
    def supports_incremental(self) -> bool:
        # The query_range `start` param is a genuine server-side timestamp filter; config
        # list endpoints have no time filter and stay full-refresh.
        return self.kind == "telemetry"


# Endpoint catalog. Telemetry rows (logs, traces) come from the v5 query_range API with
# `requestType: "raw"`; config entities (alert rules, dashboards, notification channels)
# come from the versioned management REST API. Metric series are intentionally excluded:
# the raw request type only supports logs and traces, and metrics require a per-metric
# aggregation query, which doesn't map to a generic warehouse table.
SIGNOZ_ENDPOINTS: dict[str, SigNozEndpointConfig] = {
    # --- Telemetry (server-side time window -> incremental) ---
    "logs": SigNozEndpointConfig(
        name="logs",
        kind="telemetry",
        signal="logs",
        # Per the SigNoz logs API docs: order by timestamp with `id` as the tiebreaker.
        order_keys=("timestamp", "id"),
        primary_keys=("id",),
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields(),
        default_lookback_days=30,
    ),
    "traces": SigNozEndpointConfig(
        name="traces",
        kind="telemetry",
        signal="traces",
        order_keys=("timestamp", "span_id"),
        # span_id is only guaranteed unique within a trace, so include the trace id.
        primary_keys=("trace_id", "span_id"),
        partition_key="timestamp",
        incremental_fields=_timestamp_incremental_fields(),
        default_lookback_days=30,
    ),
    # --- Config entities (no server-side time filter -> full refresh) ---
    "alert_rules": SigNozEndpointConfig(
        name="alert_rules",
        kind="config",
        path="/api/v1/rules",
        data_keys=("rules",),
        primary_keys=("id",),
        # `createAt` is SigNoz's (sic) creation timestamp on rules — stable, unlike updateAt.
        partition_key="createAt",
    ),
    "dashboards": SigNozEndpointConfig(
        name="dashboards",
        kind="config",
        path="/api/v1/dashboards",
        primary_keys=("id",),
        partition_key="createdAt",
    ),
    "notification_channels": SigNozEndpointConfig(
        name="notification_channels",
        kind="config",
        path="/api/v1/channels",
        # The `data` field holds each channel's Alertmanager receiver config — Slack webhook
        # URLs, PagerDuty keys, and similar secrets. Allowlist the safe metadata so those
        # credentials are never persisted to a warehouse table other project members can read.
        allowed_fields=("id", "name", "type", "createdAt", "updatedAt"),
        primary_keys=("id",),
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(SIGNOZ_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SIGNOZ_ENDPOINTS.items()
}

# Logs and traces are bounded by the SigNoz account's retention, so the first sync can only
# reach back as far as retention allows.
LIMITED_RETENTION_ENDPOINTS = {"logs", "traces"}
