from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import IncrementalField


@dataclass(frozen=False)
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
    # Set for an endpoint two levels under /pages: the page-scoped endpoint whose rows bind the
    # second id in `path` (e.g. "components" for /components/{component_id}/uptime).
    parent: Optional[str] = None
    # The `path` placeholder bound to each parent row's id.
    parent_param: Optional[str] = None
    # Parent row fields copied onto every child row, keyed by the parent field, valued by the column.
    parent_fields: dict[str, str] = field(default_factory=dict)
    # Drops parent rows the child endpoint can't serve, before any request is made for them.
    parent_filter: Optional[Callable[[dict[str, Any]], bool]] = None
    # The child endpoint returns one object per parent instead of a paginated list.
    single_object: bool = False
    # Child statuses that mean "nothing to read for this parent" rather than a failed sync.
    ignore_statuses: tuple[int, ...] = ()


def _has_uptime_showcase(component: dict[str, Any]) -> bool:
    # The uptime endpoint answers 422 for a component without uptime showcase, and a group
    # container has its own endpoint under component-groups.
    return bool(component.get("showcase")) and not component.get("group")


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
    # Uptime is computed over the API's default range: the last 90 days, or since the component's
    # start_date when that is more recent. A full refresh replaces the snapshot.
    "component_uptime": StatuspageEndpointConfig(
        name="component_uptime",
        path="/pages/{page_id}/components/{component_id}/uptime",
        primary_key=["page_id", "id"],
        partition_key=None,
        parent="components",
        parent_param="component_id",
        parent_fields={"page_id": "page_id"},
        parent_filter=_has_uptime_showcase,
        single_object=True,
        ignore_statuses=(404, 422),
    ),
    "component_group_uptime": StatuspageEndpointConfig(
        name="component_group_uptime",
        path="/pages/{page_id}/component-groups/{id}/uptime",
        primary_key=["page_id", "id"],
        partition_key=None,
        parent="component_groups",
        parent_param="id",
        parent_fields={"page_id": "page_id"},
        single_object=True,
        # A group answers 422 when none of its components has uptime showcase. The group object
        # lists only component ids, so the groups can't be filtered before the request.
        ignore_statuses=(404, 422),
    ),
    "page_access_user_components": StatuspageEndpointConfig(
        name="page_access_user_components",
        path="/pages/{page_id}/page_access_users/{page_access_user_id}/components",
        primary_key=["page_id", "page_access_user_id", "id"],
        parent="page_access_users",
        parent_param="page_access_user_id",
        parent_fields={"page_id": "page_id", "id": "page_access_user_id"},
        ignore_statuses=(404,),
    ),
}

ENDPOINTS = tuple(STATUSPAGE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STATUSPAGE_ENDPOINTS.items()
}
