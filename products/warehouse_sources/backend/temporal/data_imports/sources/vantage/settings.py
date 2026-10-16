from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# The Vantage API caps `limit` at 1000 on most list endpoints; use the max to minimise the number of
# paginated requests (and thus stay well under the ~1,000 requests/hour and ~20 requests/minute
# per-key rate limits).
PAGE_SIZE = 1000
# `/costs` documents a higher cap than the other list endpoints.
COSTS_PAGE_SIZE = 5000


@frozen
class VantageEndpointConfig:
    name: str
    # API path relative to the v2 base URL (e.g. "/cost_reports").
    path: str
    # Key under which the response nests the row array (e.g. {"links": ..., "cost_reports": [...]}).
    data_key: str
    # Columns that uniquely identify a row table-wide, used for merge dedup. Vantage identifies
    # every top-level object with a globally-unique `token`, so that's the default. None for
    # full-refresh rows that carry no identifier at all.
    primary_keys: Optional[list[str]] = field(default_factory=lambda: ["token"])
    # Stable datetime field to partition by. Must never change once a row is created, so we use
    # `created_at` (never `updated_at`). None for objects the API doesn't stamp with a creation time.
    partition_key: Optional[str] = None
    # Whether the table is selected for sync by default in the UI.
    should_sync_default: bool = True
    # Vantage exposes no generic `updated_after` cursor on these config/report resources, so every
    # endpoint is full-refresh only. Kept for parity with other sources / future incremental support.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE
    # Set for endpoints that need a parent row (a report token or a tag key) to build each request.
    fanout: Optional[DependentEndpointConfig] = None
    # Child-request params that are not page size, e.g. a fixed sort order.
    params: dict[str, str] = field(default_factory=dict)


# Every endpoint below is a GET list endpoint that returns `{"links": {...}, "<data_key>": [...]}`
# and paginates through `links.next`. All are full refresh: Vantage's config/report objects have no
# server-side timestamp filter to drive incremental sync, and cost rows are restated by the
# providers after they accrue and carry no key to merge on.
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
    "tags": VantageEndpointConfig(name="tags", path="/tags", data_key="tags", primary_keys=["tag_key"]),
    # Commitment rows carry no token or other identifier, so the table is replaced on every sync.
    "financial_commitments": VantageEndpointConfig(
        name="financial_commitments",
        path="/financial_commitments",
        data_key="financial_commitments",
        primary_keys=None,
        partition_key="created_at",
    ),
    # The fan-out tables below make one request series per parent row. They are off by default
    # because a large account can have many reports or tag keys, and the cost endpoints have
    # stricter rate limits than the config endpoints.
    "tag_values": VantageEndpointConfig(
        name="tag_values",
        path="/tags/{tag_key}/values",
        data_key="tag_values",
        primary_keys=["tag_key", "tag_value"],
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="tags",
            resolve_param="tag_key",
            # Tag keys can contain `/` (e.g. `kubernetes.io/name`), so the path uses a
            # percent-encoded copy that the transport adds to each parent row.
            resolve_field="tag_key_path",
            include_from_parent=["tag_key"],
            parent_field_renames={"tag_key": "tag_key"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # Cost rows have no identifier and their dimensions depend on each report's saved groupings,
    # so the table is replaced on every sync. Each report's saved date range and settings apply.
    "costs": VantageEndpointConfig(
        name="costs",
        path="/costs?cost_report_token={cost_report_token}",
        data_key="costs",
        primary_keys=None,
        should_sync_default=False,
        page_size=COSTS_PAGE_SIZE,
        params={"order": "asc"},
        fanout=DependentEndpointConfig(
            parent_name="cost_reports",
            resolve_param="cost_report_token",
            resolve_field="token",
            include_from_parent=["token"],
            parent_field_renames={"token": "cost_report_token"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
    # The same resource can appear in several resource reports, so the report token is in the key.
    "resources": VantageEndpointConfig(
        name="resources",
        path="/resources?resource_report_token={resource_report_token}",
        data_key="resources",
        primary_keys=["resource_report_token", "token"],
        partition_key="created_at",
        should_sync_default=False,
        fanout=DependentEndpointConfig(
            parent_name="resource_reports",
            resolve_param="resource_report_token",
            resolve_field="token",
            include_from_parent=["token"],
            parent_field_renames={"token": "resource_report_token"},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(VANTAGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in VANTAGE_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in VANTAGE_ENDPOINTS.items()}
