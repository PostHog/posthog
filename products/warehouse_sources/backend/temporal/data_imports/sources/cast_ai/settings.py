from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

CASTAI_BASE_URL = "https://api.cast.ai"

# Cost/savings report endpoints have no documented maximum window, and CAST AI accounts are
# usually onboarded well within the last year, so 30 days is a reasonable first-sync backfill
# that won't request an unbounded/huge response.
DEFAULT_LOOKBACK_DAYS = 30

# `/cost` buckets by stepSeconds; hourly keeps a 30 day window to ~720 rows per cluster while
# still being useful for cost trend analysis. Not documented as configurable elsewhere, so this
# is our own choice, not a vendor default.
COST_REPORT_STEP_SECONDS = 3600

# Workload reports return one row per workload with the per-step metrics nested inside it, so a
# daily step keeps each row's nested array to ~30 entries over the default window.
WORKLOAD_REPORT_STEP_SECONDS = 86400

TIMESTAMP_INCREMENTAL: IncrementalField = {
    "label": "timestamp",
    "type": IncrementalFieldType.DateTime,
    "field": "timestamp",
    "field_type": IncrementalFieldType.DateTime,
}

CREATED_AT_INCREMENTAL: IncrementalField = {
    "label": "createdAt",
    "type": IncrementalFieldType.DateTime,
    "field": "createdAt",
    "field_type": IncrementalFieldType.DateTime,
}


@dataclass(frozen=False)
class CastAiEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    partition_key: str | None = None
    # Unused: no endpoint documents a page size limit, so callers always pass page_size_param=None
    # and let the server pick. Kept only to satisfy the shared fan-out helper's protocol.
    page_size: int = 0
    # The incremental reports fan out per cluster, so the rows of a run have no single order.
    sort_mode: Literal["asc", "desc"] | None = None
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None
    # Required report window params, as (start, end).
    window_params: tuple[str, str] | None = None
    step_seconds: int | None = None
    # Workload reports page with `page.cursor` and return the next cursor as `nextCursor`.
    cursor_paginated: bool = False


def _cluster_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="clusters",
        resolve_param="clusterId",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "cluster_id"},
    )


# Workload names are only unique within a namespace and workload type in one cluster.
WORKLOAD_PRIMARY_KEY = ["cluster_id", "namespace", "workloadType", "workloadName"]


CASTAI_ENDPOINTS: dict[str, CastAiEndpointConfig] = {
    # Org-wide entity list. No pagination params documented and no server-side timestamp filter,
    # so this stays a small full-refresh table that fan-out children resolve `clusterId` from.
    "clusters": CastAiEndpointConfig(
        name="clusters",
        path="/v1/kubernetes/external-clusters",
        partition_key="createdAt",
        primary_key="id",
    ),
    "cluster_cost_reports": CastAiEndpointConfig(
        name="cluster_cost_reports",
        path="/v1/cost-reports/clusters/{clusterId}/cost",
        incremental_fields=[TIMESTAMP_INCREMENTAL],
        default_incremental_field="timestamp",
        partition_key="timestamp",
        # The row identifier is only unique within a cluster (one entry per time bucket), and
        # this table aggregates every cluster, so the cluster id is part of the key.
        primary_key=["cluster_id", "timestamp"],
        fanout=_cluster_fanout(),
        window_params=("startTime", "endTime"),
        step_seconds=COST_REPORT_STEP_SECONDS,
    ),
    "cluster_savings_history": CastAiEndpointConfig(
        name="cluster_savings_history",
        path="/v1/cost-reports/clusters/{clusterId}/estimated-savings-history",
        incremental_fields=[CREATED_AT_INCREMENTAL],
        default_incremental_field="createdAt",
        partition_key="createdAt",
        primary_key=["cluster_id", "createdAt"],
        fanout=_cluster_fanout(),
        window_params=("fromDate", "toDate"),
    ),
    "cluster_savings_reports": CastAiEndpointConfig(
        name="cluster_savings_reports",
        path="/v1/cost-reports/clusters/{clusterId}/savings",
        incremental_fields=[TIMESTAMP_INCREMENTAL],
        default_incremental_field="timestamp",
        partition_key="timestamp",
        primary_key=["cluster_id", "timestamp"],
        fanout=_cluster_fanout(),
        window_params=("startTime", "endTime"),
        step_seconds=COST_REPORT_STEP_SECONDS,
    ),
    # The workload reports aggregate each workload over the requested window and carry no
    # row-level timestamp, so they are full refresh over the default lookback window.
    "workload_cost_reports": CastAiEndpointConfig(
        name="workload_cost_reports",
        path="/v1/cost-reports/clusters/{clusterId}/workload-costs",
        primary_key=WORKLOAD_PRIMARY_KEY,
        fanout=_cluster_fanout(),
        window_params=("startTime", "endTime"),
        step_seconds=WORKLOAD_REPORT_STEP_SECONDS,
        cursor_paginated=True,
    ),
    "workload_efficiency_reports": CastAiEndpointConfig(
        name="workload_efficiency_reports",
        path="/v1/cost-reports/clusters/{clusterId}/workload-efficiency",
        primary_key=WORKLOAD_PRIMARY_KEY,
        fanout=_cluster_fanout(),
        window_params=("startTime", "endTime"),
        cursor_paginated=True,
    ),
    "workload_data_transfer_costs": CastAiEndpointConfig(
        name="workload_data_transfer_costs",
        path="/v1/cost-reports/clusters/{clusterId}/datatransfer-costs",
        primary_key=WORKLOAD_PRIMARY_KEY,
        fanout=_cluster_fanout(),
        window_params=("startTime", "endTime"),
        step_seconds=WORKLOAD_REPORT_STEP_SECONDS,
        cursor_paginated=True,
    ),
}

# Fan-out children are synced directly (never the bare "clusters" parent table on its own as a
# schema choice alongside them would double-count); "clusters" is still exposed as its own
# top-level table for users who only want the entity list.
ENDPOINTS = tuple(CASTAI_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CASTAI_ENDPOINTS.items()
}
