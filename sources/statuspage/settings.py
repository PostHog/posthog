from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class StatuspageEndpointConfig:
    name: str
    # Path template. Top-level endpoints are absolute (e.g. "/pages"); page-scoped
    # endpoints carry a {page_id} placeholder filled in per page during fan-out.
    path: str
    # Unique across the whole table. Page-scoped children include "page_id" because a
    # single sync aggregates rows from every page the API key can see — the bare
    # resource id is only documented as unique within its parent page.
    primary_key: list[str]
    # Stable datetime field used for datetime partitioning. Every Statuspage resource
    # we sync exposes an immutable created_at, so we never partition on updated_at.
    partition_key: Optional[str] = "created_at"
    page_size: int = 100  # Statuspage caps per_page/limit at 100.
    # Most list endpoints page with `per_page`; subscribers uses `limit` instead.
    page_size_param: str = "per_page"
    # True when the resource lives under /pages/{page_id}/... and must be fanned out
    # over every page. False only for the top-level /pages listing itself.
    page_scoped: bool = True
    # Statuspage exposes no server-side updated_after/since filter on its list
    # endpoints, so every endpoint is full-refresh only (empty incremental_fields).
    incremental_fields: list[IncrementalField] = field(default_factory=list)


STATUSPAGE_ENDPOINTS: dict[str, StatuspageEndpointConfig] = {
    "pages": StatuspageEndpointConfig(
        name="pages",
        path="/pages",
        primary_key=["id"],
        page_scoped=False,
    ),
    "components": StatuspageEndpointConfig(
        name="components",
        path="/pages/{page_id}/components",
        primary_key=["page_id", "id"],
    ),
    "component_groups": StatuspageEndpointConfig(
        name="component_groups",
        path="/pages/{page_id}/component-groups",
        primary_key=["page_id", "id"],
    ),
    "incidents": StatuspageEndpointConfig(
        name="incidents",
        path="/pages/{page_id}/incidents",
        primary_key=["page_id", "id"],
    ),
    "incident_templates": StatuspageEndpointConfig(
        name="incident_templates",
        path="/pages/{page_id}/incident_templates",
        primary_key=["page_id", "id"],
    ),
    "subscribers": StatuspageEndpointConfig(
        name="subscribers",
        path="/pages/{page_id}/subscribers",
        primary_key=["page_id", "id"],
        page_size_param="limit",
    ),
    "metrics": StatuspageEndpointConfig(
        name="metrics",
        path="/pages/{page_id}/metrics",
        primary_key=["page_id", "id"],
    ),
    "metric_providers": StatuspageEndpointConfig(
        name="metric_providers",
        path="/pages/{page_id}/metrics_providers",
        primary_key=["page_id", "id"],
    ),
    "page_access_users": StatuspageEndpointConfig(
        name="page_access_users",
        path="/pages/{page_id}/page_access_users",
        primary_key=["page_id", "id"],
    ),
    "page_access_groups": StatuspageEndpointConfig(
        name="page_access_groups",
        path="/pages/{page_id}/page_access_groups",
        primary_key=["page_id", "id"],
    ),
}

ENDPOINTS = tuple(STATUSPAGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STATUSPAGE_ENDPOINTS.items()
}
