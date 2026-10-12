from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class VantageEndpointConfig:
    name: str
    # API path relative to the v2 base URL (e.g. "/cost_reports").
    path: str
    # Key under which the response nests the row array (e.g. {"links": ..., "cost_reports": [...]}).
    data_key: str
    # Columns that uniquely identify a row table-wide, used for merge dedup. Vantage identifies
    # every top-level object with a globally-unique `token`, so that's the default.
    primary_keys: list[str] = field(default_factory=lambda: ["token"])
    # Stable datetime field to partition by. Must never change once a row is created, so we use
    # `created_at` (never `updated_at`). None for objects the API doesn't stamp with a creation time.
    partition_key: Optional[str] = None
    # Whether the table is selected for sync by default in the UI.
    should_sync_default: bool = True
    # Vantage exposes no generic `updated_after` cursor on these config/report resources, so every
    # endpoint is full-refresh only. Kept for parity with other sources / future incremental support.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Every endpoint below is a top-level GET list endpoint that returns
# `{"links": {...}, "<data_key>": [...]}` and paginates through `links.next`. All are full refresh:
# Vantage's config/report objects have no server-side timestamp filter to drive incremental sync
# (only the cost/usage data endpoints accept date-range windows, and those are intentionally left
# out of this initial version - see the source docstring / PR notes).
VANTAGE_ENDPOINTS: dict[str, VantageEndpointConfig] = {
    "cost_reports": VantageEndpointConfig(
        name="cost_reports", path="/cost_reports", data_key="cost_reports", partition_key="created_at"
    ),
    "budgets": VantageEndpointConfig(name="budgets", path="/budgets", data_key="budgets", partition_key="created_at"),
    "folders": VantageEndpointConfig(name="folders", path="/folders", data_key="folders", partition_key="created_at"),
    "dashboards": VantageEndpointConfig(
        name="dashboards", path="/dashboards", data_key="dashboards", partition_key="created_at"
    ),
    "cost_alerts": VantageEndpointConfig(
        name="cost_alerts", path="/cost_alerts", data_key="cost_alerts", partition_key="created_at"
    ),
    "anomaly_alerts": VantageEndpointConfig(
        name="anomaly_alerts", path="/anomaly_alerts", data_key="anomaly_alerts", partition_key="created_at"
    ),
    "resource_reports": VantageEndpointConfig(
        name="resource_reports", path="/resource_reports", data_key="resource_reports", partition_key="created_at"
    ),
    "financial_commitment_reports": VantageEndpointConfig(
        name="financial_commitment_reports",
        path="/financial_commitment_reports",
        data_key="financial_commitment_reports",
        partition_key="created_at",
    ),
    "network_flow_reports": VantageEndpointConfig(
        name="network_flow_reports",
        path="/network_flow_reports",
        data_key="network_flow_reports",
        partition_key="created_at",
    ),
    "kubernetes_efficiency_reports": VantageEndpointConfig(
        name="kubernetes_efficiency_reports",
        path="/kubernetes_efficiency_reports",
        data_key="kubernetes_efficiency_reports",
        partition_key="created_at",
    ),
    "segments": VantageEndpointConfig(
        name="segments", path="/segments", data_key="segments", partition_key="created_at"
    ),
    "saved_filters": VantageEndpointConfig(
        name="saved_filters", path="/saved_filters", data_key="saved_filters", partition_key="created_at"
    ),
    "recommendations": VantageEndpointConfig(
        name="recommendations", path="/recommendations", data_key="recommendations", partition_key="created_at"
    ),
    "billing_rules": VantageEndpointConfig(
        name="billing_rules", path="/billing_rules", data_key="billing_rules", partition_key="created_at"
    ),
    "access_grants": VantageEndpointConfig(
        name="access_grants", path="/access_grants", data_key="access_grants", partition_key="created_at"
    ),
    "integrations": VantageEndpointConfig(
        name="integrations", path="/integrations", data_key="integrations", partition_key="created_at"
    ),
    "workspaces": VantageEndpointConfig(
        name="workspaces", path="/workspaces", data_key="workspaces", partition_key="created_at"
    ),
    # No `created_at` on these objects, so they're synced without partitioning.
    "report_notifications": VantageEndpointConfig(
        name="report_notifications", path="/report_notifications", data_key="report_notifications"
    ),
    "teams": VantageEndpointConfig(name="teams", path="/teams", data_key="teams"),
    "users": VantageEndpointConfig(name="users", path="/users", data_key="users"),
}

ENDPOINTS = tuple(VANTAGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VANTAGE_ENDPOINTS.items()
}
