from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

BASE_URLS = {
    "us": "https://api.rudderstack.com",
    "eu": "https://api.eu.rudderstack.com",
}
CATALOG_MAX_PAGES = 50


@frozen
class RudderStackEndpoint:
    name: str
    path: str
    data_selector: str
    paginator: Literal["single_page", "json_response", "catalog"] = "json_response"
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "createdAt"
    params: dict[str, str | int] = field(default_factory=dict)
    fanout: DependentEndpointConfig | None = None
    page_size: int = 100
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


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
}
