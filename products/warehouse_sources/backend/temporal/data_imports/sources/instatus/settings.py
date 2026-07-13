from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class InstatusEndpointConfig:
    name: str
    # Full path including the version prefix. Instatus is inconsistent here: the status-page
    # listing lives under /v2/pages, while every page-scoped child lives under /v1/{page_id}/...
    # Page-scoped paths carry a {page_id} placeholder filled in per page during fan-out.
    path: str
    # Unique across the whole table. Page-scoped children include "page_id" because a single sync
    # aggregates rows from every status page the token can see, and the bare resource id is only
    # documented as unique within its parent page.
    primary_key: list[str]
    # Stable datetime field used for datetime partitioning, or None when the resource exposes no
    # immutable timestamp. We never partition on updatedAt — only creation-time fields that don't
    # move (createdAt, an incident's `started`, a maintenance's `start`).
    partition_key: Optional[str] = None
    # True when the resource lives under /v1/{page_id}/... and must be fanned out over every page.
    # False only for the top-level /v2/pages listing itself.
    page_scoped: bool = True
    # Instatus exposes no server-side updated_after/since filter on any list endpoint (only
    # status include/exclude on incidents and a free-text search on subscribers), so every
    # endpoint is full-refresh only (empty incremental_fields).
    incremental_fields: list[IncrementalField] = field(default_factory=list)


INSTATUS_ENDPOINTS: dict[str, InstatusEndpointConfig] = {
    "pages": InstatusEndpointConfig(
        name="pages",
        path="/v2/pages",
        primary_key=["id"],
        partition_key="createdAt",
        page_scoped=False,
    ),
    "components": InstatusEndpointConfig(
        name="components",
        path="/v1/{page_id}/components",
        primary_key=["page_id", "id"],
        partition_key="createdAt",
    ),
    "incidents": InstatusEndpointConfig(
        name="incidents",
        path="/v1/{page_id}/incidents",
        primary_key=["page_id", "id"],
        # Incidents have no createdAt; `started` is the immutable time the incident began.
        partition_key="started",
    ),
    "maintenances": InstatusEndpointConfig(
        name="maintenances",
        path="/v1/{page_id}/maintenances",
        primary_key=["page_id", "id"],
        # Maintenances have no createdAt; `start` is the immutable scheduled start time.
        partition_key="start",
    ),
    "subscribers": InstatusEndpointConfig(
        name="subscribers",
        path="/v1/{page_id}/subscribers",
        primary_key=["page_id", "id"],
    ),
    "metrics": InstatusEndpointConfig(
        name="metrics",
        path="/v1/{page_id}/metrics",
        primary_key=["page_id", "id"],
    ),
    "templates": InstatusEndpointConfig(
        name="templates",
        path="/v1/{page_id}/templates",
        primary_key=["page_id", "id"],
        partition_key="createdAt",
    ),
    "team": InstatusEndpointConfig(
        name="team",
        path="/v1/{page_id}/team",
        primary_key=["page_id", "id"],
    ),
    "audience_groups": InstatusEndpointConfig(
        name="audience_groups",
        path="/v1/{page_id}/audience-groups",
        primary_key=["page_id", "id"],
    ),
}

ENDPOINTS = tuple(INSTATUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in INSTATUS_ENDPOINTS.items()
}
