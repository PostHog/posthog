from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.backend.types import IncrementalField

# The OnCall API caps `perpage` at 100.
ONCALL_PAGE_SIZE = 100
INCIDENT_PAGE_SIZE = 50

IrmApi = Literal["oncall", "incident"]


@dataclass(frozen=True)
class GrafanaIRMEndpointConfig:
    name: str
    # "oncall": the OnCall REST API on the OnCall API URL, page-number paginated.
    # "incident": the Incident JSON RPC API on the stack URL, cursor paginated POSTs.
    api: IrmApi
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    # Stable creation-time field for datetime partitioning; never a mutable field.
    partition_key: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    json: dict[str, Any] = field(default_factory=dict)
    data_selector: str = "results"
    # Credential-like fields dropped from every row before it reaches the warehouse.
    dropped_fields: tuple[str, ...] = ()
    description: str | None = None


GRAFANA_IRM_ENDPOINTS: dict[str, GrafanaIRMEndpointConfig] = {
    "alert_groups": GrafanaIRMEndpointConfig(
        name="alert_groups",
        api="oncall",
        path="/api/v1/alert_groups/",
        partition_key="created_at",
        description="OnCall alert groups. Full refresh only: the API lists newest first and states change after creation",
    ),
    "resolution_notes": GrafanaIRMEndpointConfig(
        name="resolution_notes",
        api="oncall",
        path="/api/v1/resolution_notes/",
        partition_key="created_at",
    ),
    "integrations": GrafanaIRMEndpointConfig(
        name="integrations",
        api="oncall",
        path="/api/v1/integrations/",
        # `link` and `inbound_email` are the integration's inbound endpoints; anyone holding them can send alerts.
        dropped_fields=("link", "inbound_email"),
    ),
    "routes": GrafanaIRMEndpointConfig(
        name="routes",
        api="oncall",
        path="/api/v1/routes/",
    ),
    "escalation_chains": GrafanaIRMEndpointConfig(
        name="escalation_chains",
        api="oncall",
        path="/api/v1/escalation_chains/",
    ),
    "escalation_policies": GrafanaIRMEndpointConfig(
        name="escalation_policies",
        api="oncall",
        path="/api/v1/escalation_policies/",
    ),
    "schedules": GrafanaIRMEndpointConfig(
        name="schedules",
        api="oncall",
        path="/api/v1/schedules/",
        # External iCal feed URLs are often private calendar links that grant read access on their own.
        dropped_fields=("ical_url_primary", "ical_url_overrides"),
    ),
    "on_call_shifts": GrafanaIRMEndpointConfig(
        name="on_call_shifts",
        api="oncall",
        path="/api/v1/on_call_shifts/",
    ),
    "shift_swaps": GrafanaIRMEndpointConfig(
        name="shift_swaps",
        api="oncall",
        path="/api/v1/shift_swaps/",
        partition_key="created_at",
        # Without `starting_after` the API only returns swaps that start in the future.
        params={"starting_after": "1970-01-01T00:00:00Z"},
    ),
    "users": GrafanaIRMEndpointConfig(
        name="users",
        api="oncall",
        path="/api/v1/users/",
    ),
    "teams": GrafanaIRMEndpointConfig(
        name="teams",
        api="oncall",
        path="/api/v1/teams/",
    ),
    "user_groups": GrafanaIRMEndpointConfig(
        name="user_groups",
        api="oncall",
        path="/api/v1/user_groups/",
    ),
    "incidents": GrafanaIRMEndpointConfig(
        name="incidents",
        api="incident",
        path="/IncidentsService.QueryIncidentPreviews",
        primary_keys=("incidentID",),
        partition_key="createdTime",
        json={
            "query": {"limit": INCIDENT_PAGE_SIZE, "orderField": "createdTime", "orderDirection": "ASC"},
            "includeCustomFieldValues": True,
            "includeMembershipPreview": True,
        },
        data_selector="incidentPreviews",
    ),
    "incident_activity": GrafanaIRMEndpointConfig(
        name="incident_activity",
        api="incident",
        path="/ActivityService.QueryActivity",
        # Activity item IDs are only documented as unique within their incident.
        primary_keys=("incidentID", "activityItemID"),
        partition_key="createdTime",
        json={"query": {"limit": INCIDENT_PAGE_SIZE, "orderDirection": "ASC"}},
        data_selector="activityItems",
        description="Timeline entries of every incident. Fetched per incident, so large incident histories take longer",
    ),
}

ENDPOINTS = tuple(GRAFANA_IRM_ENDPOINTS.keys())

# No endpoint exposes a server-side updated-since filter with ascending order, so every table is full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
