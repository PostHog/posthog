from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# `/api/search` accepts a limit of up to 5000; the teams / service-accounts search endpoints
# default `perpage` to 1000. 1000 everywhere keeps individual responses comfortably sized.
DEFAULT_PAGE_SIZE = 1000

# Verified against a live instance: `/api/annotations` honors limits of at least 1000.
# The documented default is 100, so anything above that must be confirmed to actually apply —
# a silently-capped limit would make the window walk think a saturated window was complete.
ANNOTATIONS_LIMIT = 1000

# Each dashboard version carries the full dashboard JSON in `data`, so pages stay small to keep a
# response well under MAX_RESPONSE_BYTES even for large dashboards.
DASHBOARD_VERSIONS_PAGE_SIZE = 50

PaginationStyle = Literal["page", "time_window", "continue_token", "none"]


@dataclass(frozen=True)
class GrafanaFanOutConfig:
    # Page-paginated endpoint whose rows drive the fan-out.
    parent: str
    # Parent row field substituted into the child path's `{parent_id}` placeholder.
    parent_field: str
    # Child row field that holds the parent identifier. Filled from the parent when the response
    # omits it, so the composite primary key is never null.
    child_field: str


@dataclass(frozen=True)
class GrafanaEndpointConfig:
    name: str
    path: str
    # "page": page-number pagination (`page` + a page-size param); "time_window": the
    # annotations from/to epoch-ms walk; "continue_token": the dashboard versions walk;
    # "none": one request returns the whole collection.
    pagination: PaginationStyle = "none"
    page_size_param: str = "limit"
    # Number of the first page for "page" pagination; `/api/orgs` counts pages from 0.
    first_page: int = 1
    # Key holding the rows when the response is wrapped (e.g. {"teams": [...], "totalCount": N});
    # None when the endpoint returns a bare JSON array.
    data_key: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    fan_out: GrafanaFanOutConfig | None = None


GRAFANA_ENDPOINTS: dict[str, GrafanaEndpointConfig] = {
    "dashboards": GrafanaEndpointConfig(
        name="dashboards",
        path="/api/search",
        pagination="page",
        params={"type": "dash-db"},
        primary_keys=["uid"],
    ),
    # `version` is only unique within a dashboard, and `uid` on a version row is the dashboard's uid.
    "dashboard_versions": GrafanaEndpointConfig(
        name="dashboard_versions",
        path="/api/dashboards/uid/{parent_id}/versions",
        pagination="continue_token",
        data_key="versions",
        fan_out=GrafanaFanOutConfig(parent="dashboards", parent_field="uid", child_field="uid"),
        primary_keys=["uid", "version"],
    ),
    "folders": GrafanaEndpointConfig(
        name="folders",
        path="/api/folders",
        pagination="page",
        primary_keys=["uid"],
    ),
    "teams": GrafanaEndpointConfig(
        name="teams",
        path="/api/teams/search",
        pagination="page",
        page_size_param="perpage",
        data_key="teams",
        primary_keys=["id"],
    ),
    "team_members": GrafanaEndpointConfig(
        name="team_members",
        path="/api/teams/{parent_id}/members",
        fan_out=GrafanaFanOutConfig(parent="teams", parent_field="id", child_field="teamId"),
        primary_keys=["teamId", "userId"],
    ),
    "users": GrafanaEndpointConfig(
        name="users",
        path="/api/org/users",
        primary_keys=["userId"],
    ),
    # Lists every organization on the instance, so Grafana only serves it to a server admin
    # authenticating with basic auth. Service account tokens are org-scoped and get a 403.
    "orgs": GrafanaEndpointConfig(
        name="orgs",
        path="/api/orgs",
        pagination="page",
        page_size_param="perpage",
        first_page=0,
        primary_keys=["id"],
    ),
    "datasources": GrafanaEndpointConfig(
        name="datasources",
        path="/api/datasources",
        primary_keys=["uid"],
    ),
    "service_accounts": GrafanaEndpointConfig(
        name="service_accounts",
        path="/api/serviceaccounts/search",
        pagination="page",
        page_size_param="perpage",
        data_key="serviceAccounts",
        primary_keys=["id"],
    ),
    "alert_rules": GrafanaEndpointConfig(
        name="alert_rules",
        path="/api/v1/provisioning/alert-rules",
        primary_keys=["uid"],
    ),
    # Restricted to user/API-created annotations (`type=annotation`): alert-state history rows
    # returned by the same endpoint carry no `id` at all (only a repeating `alertId`), so they
    # have no usable primary key and are excluded.
    "annotations": GrafanaEndpointConfig(
        name="annotations",
        path="/api/annotations",
        pagination="time_window",
        params={"type": "annotation"},
        primary_keys=["id"],
        incremental_fields=[
            {
                "label": "time",
                "type": IncrementalFieldType.Integer,
                "field": "time",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
}

ENDPOINTS = tuple(GRAFANA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GRAFANA_ENDPOINTS.items()
}
