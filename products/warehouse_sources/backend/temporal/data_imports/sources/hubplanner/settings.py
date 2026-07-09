from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class HubPlannerEndpointConfig:
    name: str
    path: str  # e.g. "/booking" (base path, joined onto https://api.hubplanner.com/v1)
    incremental_fields: list[IncrementalField]
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    # Stable creation-time field used for datetime partitioning. Never a mutable field
    # (`updatedDate`) — those rewrite partitions on every sync. None => no partitioning.
    partition_key: Optional[str] = None
    # Some resources have no GET-all endpoint and can only be listed via POST /<path>/search
    # with an empty body (e.g. milestones). When True, list through search instead of GET.
    list_via_search: bool = False
    # Server-side incremental filter field. It MUST be a *searchable* property on the
    # /<path>/search endpoint (Hub Planner only filters searchable fields). None => full
    # refresh only. Only `bookings` and `time_entries` expose a searchable `updatedDate`,
    # so they're the only incremental endpoints; every other area's search omits it.
    incremental_search_field: Optional[str] = None
    should_sync_default: bool = True


def _updated_date_incremental_fields() -> list[IncrementalField]:
    return [
        {
            "label": "updatedDate",
            "type": IncrementalFieldType.DateTime,
            "field": "updatedDate",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


HUBPLANNER_ENDPOINTS: dict[str, HubPlannerEndpointConfig] = {
    # Full-refresh core catalog resources. GET /project and GET /resource return every row
    # (Hub Planner ignores pagination on them), but we still page defensively at limit=1000.
    "projects": HubPlannerEndpointConfig(
        name="projects",
        path="/project",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    "resources": HubPlannerEndpointConfig(
        name="resources",
        path="/resource",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    # Bookings and time entries default to 20 rows per page and MUST be paginated. Both expose
    # a searchable `updatedDate`, so they support server-side incremental sync via POST search.
    "bookings": HubPlannerEndpointConfig(
        name="bookings",
        path="/booking",
        partition_key="createdDate",
        incremental_search_field="updatedDate",
        incremental_fields=_updated_date_incremental_fields(),
    ),
    "time_entries": HubPlannerEndpointConfig(
        name="time_entries",
        path="/timeentry",
        partition_key="createdDate",
        incremental_search_field="updatedDate",
        incremental_fields=_updated_date_incremental_fields(),
    ),
    "events": HubPlannerEndpointConfig(
        name="events",
        path="/event",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    "clients": HubPlannerEndpointConfig(
        name="clients",
        path="/client",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    # Milestones have no GET-all endpoint — list them via POST /milestone/search with {}.
    "milestones": HubPlannerEndpointConfig(
        name="milestones",
        path="/milestone",
        list_via_search=True,
        incremental_fields=[],
    ),
    "project_groups": HubPlannerEndpointConfig(
        name="project_groups",
        path="/projectgroup",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    "resource_groups": HubPlannerEndpointConfig(
        name="resource_groups",
        path="/resourcegroup",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    "billing_rates": HubPlannerEndpointConfig(
        name="billing_rates",
        path="/billingRate",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    "holidays": HubPlannerEndpointConfig(
        name="holidays",
        path="/holiday",
        partition_key="createdDate",
        incremental_fields=[],
    ),
    # Vacations carry no creation timestamp (start/end only), so we don't partition them.
    "vacations": HubPlannerEndpointConfig(
        name="vacations",
        path="/vacation",
        incremental_fields=[],
    ),
    "project_managers": HubPlannerEndpointConfig(
        name="project_managers",
        path="/project-manager",
        partition_key="createdDate",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(HUBPLANNER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in HUBPLANNER_ENDPOINTS.items()
}
