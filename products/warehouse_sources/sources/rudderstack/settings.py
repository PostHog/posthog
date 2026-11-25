from dataclasses import field
from typing import Literal

from products.warehouse_sources.sources.sdk import (
    DependentEndpointConfig,
    IncrementalField,
    IncrementalFieldType,
    frozen,
)

BASE_URLS = {
    "us": "https://api.rudderstack.com",
    "eu": "https://api.eu.rudderstack.com",
}
CATALOG_MAX_PAGES = 50
# The usage API rejects a daily `start` older than 60 days.
USAGE_MAX_LOOKBACK_DAYS = 59
# Recent daily buckets keep counting events, so incremental syncs read them again.
USAGE_REFRESH_DAYS = 2


@frozen
class RudderStackEndpoint:
    name: str
    path: str
    data_selector: str
    paginator: Literal["single_page", "json_response", "catalog"] = "json_response"
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "createdAt"
    params: dict[str, str | int] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None
    page_size: int = 100
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    organization_token: bool = False
    usage_window: bool = False


# Timestamp filters for audit logs and sync history need account verification before enabling incremental sync.
ENDPOINTS: dict[str, RudderStackEndpoint] = {
    "sources": RudderStackEndpoint(name="sources", path="/v2/sources", data_selector="sources"),
    "destinations": RudderStackEndpoint(name="destinations", path="/v2/destinations", data_selector="destinations"),
    "connections": RudderStackEndpoint(name="connections", path="/v2/connections", data_selector="connections"),
    "transformations": RudderStackEndpoint(
        name="transformations", path="/transformations", data_selector="transformations", paginator="single_page"
    ),
    "libraries": RudderStackEndpoint(
        name="libraries", path="/libraries", data_selector="libraries", paginator="single_page"
    ),
    "tracking_plans": RudderStackEndpoint(
        name="tracking_plans", path="/v2/catalog/tracking-plans", data_selector="trackingPlans", paginator="single_page"
    ),
    "catalog_events": RudderStackEndpoint(
        name="catalog_events",
        path="/v2/catalog/events",
        data_selector="data",
        paginator="catalog",
        params={"orderBy": "createdAt:asc"},
    ),
    "catalog_properties": RudderStackEndpoint(
        name="catalog_properties",
        path="/v2/catalog/properties",
        data_selector="data",
        paginator="catalog",
        params={"orderBy": "createdAt:asc"},
    ),
    "catalog_categories": RudderStackEndpoint(
        name="catalog_categories",
        path="/v2/catalog/categories",
        data_selector="data",
        paginator="catalog",
        params={"orderBy": "createdAt:asc"},
    ),
    "audit_logs": RudderStackEndpoint(
        name="audit_logs",
        path="/v2/audit-logs",
        data_selector="data",
        params={"per_page": 100},
        organization_token=True,
    ),
    "retl_connections": RudderStackEndpoint(
        name="retl_connections",
        path="/v2/retl-connections",
        data_selector="data",
        params={"pageSize": 100},
    ),
    "retl_syncs": RudderStackEndpoint(
        name="retl_syncs",
        path="/v2/retl-connections/{connection_id}/syncs",
        data_selector="syncs",
        primary_keys=("connection_id", "id"),
        partition_key="startedAt",
        fanout=DependentEndpointConfig(
            parent_name="retl_connections",
            resolve_param="connection_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "connection_id"},
            parent_params={"pageSize": 100},
            child_params={"per_page": 100},
        ),
    ),
    "tracking_plan_events": RudderStackEndpoint(
        name="tracking_plan_events",
        path="/v2/catalog/tracking-plans/{tracking_plan_id}/events",
        data_selector="data",
        paginator="catalog",
        primary_keys=("tracking_plan_id", "id"),
        fanout=DependentEndpointConfig(
            parent_name="tracking_plans",
            resolve_param="tracking_plan_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "tracking_plan_id"},
            # Cached plan data avoids a schema rebuild that blocks concurrent plan edits.
            child_params={"rebuildSchemas": "false"},
        ),
    ),
    "custom_types": RudderStackEndpoint(
        name="custom_types", path="/v2/catalog/custom-types", data_selector="data", paginator="catalog"
    ),
    "regulations": RudderStackEndpoint(
        name="regulations", path="/v2/regulations", data_selector="data", partition_key=None
    ),
    "event_metrics_usage": RudderStackEndpoint(
        name="event_metrics_usage",
        path="/v2/organizations/usage/event-metrics",
        data_selector="data",
        paginator="single_page",
        primary_keys=("workspaceId", "sourceId", "bucket"),
        partition_key="bucket",
        params={"granularity": "day"},
        incremental_fields=[
            {
                "label": "bucket",
                "type": IncrementalFieldType.Date,
                "field": "bucket",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        organization_token=True,
        usage_window=True,
    ),
}
