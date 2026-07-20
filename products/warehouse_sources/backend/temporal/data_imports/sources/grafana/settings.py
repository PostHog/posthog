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

PaginationStyle = Literal["page", "time_window", "none"]


@dataclass
class GrafanaEndpointConfig:
    name: str
    path: str
    # "page": page-number pagination (`page` + a page-size param); "time_window": the
    # annotations from/to epoch-ms walk; "none": one request returns the whole collection.
    pagination: PaginationStyle = "none"
    page_size_param: str = "limit"
    # Key holding the rows when the response is wrapped (e.g. {"teams": [...], "totalCount": N});
    # None when the endpoint returns a bare JSON array.
    data_key: str | None = None
    params: dict[str, str] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)


GRAFANA_ENDPOINTS: dict[str, GrafanaEndpointConfig] = {
    "dashboards": GrafanaEndpointConfig(
        name="dashboards",
        path="/api/search",
        pagination="page",
        params={"type": "dash-db"},
        primary_keys=["uid"],
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
    "users": GrafanaEndpointConfig(
        name="users",
        path="/api/org/users",
        primary_keys=["userId"],
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
