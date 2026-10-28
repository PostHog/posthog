import dataclasses
from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import UNVERSIONED_API_VERSION
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

CENSUS_API_V1 = UNVERSIONED_API_VERSION
CENSUS_API_V2 = "v2"

CENSUS_HOSTS = {
    "us": "https://app.getcensus.com",
    "eu": "https://app-eu.getcensus.com",
}

# Census documents `per_page` with a default of 25 and a hard cap of 100.
PAGE_SIZE = 100


@dataclass(frozen=True)
class CensusEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None
    page_size: int = PAGE_SIZE
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None
    # Response fields dropped from every row before it is yielded. Census `connection_details`
    # on sources/destinations carries warehouse account identifiers (account, user, warehouse
    # name) that shouldn't be copied into a table any project member can query.
    strip_fields: tuple[str, ...] = ()
    # Set when an otherwise-valid token can be refused for this endpoint. `get_endpoint_permissions`
    # probes those endpoints so the schema picker names the token the table needs instead of letting
    # the user select a table that can only fail at sync time.
    permission_denied_reason: str | None = None


_V1_ENDPOINTS: dict[str, CensusEndpointConfig] = {
    # Census has no server-side `updated_since`/`created_since` filter on any list endpoint
    # (only `page`/`per_page`/`order`), so every table is full refresh only.
    "syncs": CensusEndpointConfig(
        name="syncs",
        path="/api/v1/syncs",
        partition_key="created_at",
    ),
    "sync_runs": CensusEndpointConfig(
        name="sync_runs",
        path="/api/v1/syncs/{sync_id}/sync_runs",
        partition_key="created_at",
        # `id` is only documented per-sync ("List Sync Runs" scopes it under a sync_id path
        # param); this table aggregates runs across every sync, so the parent id is part of
        # the key to keep it unique table-wide.
        primary_key=["sync_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="syncs",
            resolve_param="sync_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "sync_id"},
            # `order=asc` keeps the parent page walk stable (see `get_resource`'s comment).
            parent_params={"order": "asc"},
        ),
    ),
    "sources": CensusEndpointConfig(
        name="sources",
        path="/api/v1/sources",
        partition_key="created_at",
        strip_fields=("connection_details",),
    ),
    "destinations": CensusEndpointConfig(
        name="destinations",
        path="/api/v1/destinations",
        partition_key="created_at",
        strip_fields=("connection_details",),
    ),
    "datasets": CensusEndpointConfig(
        name="datasets",
        path="/api/v1/datasets",
        # The published list schema echoes the create-dataset request body (`type`, `query`,
        # `source_id`) and names no timestamp, so there is nothing stable to partition on.
        # Datasets are addressable at `/api/v1/datasets/{dataset_id}`, so `id` stays the key.
        permission_denied_reason="Census refused access to datasets. Check that datasets are enabled for your Census organization, then reconnect.",
    ),
    "workspaces": CensusEndpointConfig(
        name="workspaces",
        path="/api/v1/workspaces",
        partition_key="created_at",
        strip_fields=("notification_emails",),
        # Workspaces is an organization-level endpoint, so a workspace-scoped token cannot read it.
        permission_denied_reason="Listing workspaces needs an organization-level Census API token. Reconnect with an organization token, or deselect this table.",
    ),
}

# V2 serves the same pagination and response envelope under `/api/v2`. Workspaces have no V2
# equivalent (the vendor retires them with V1), so that table exists only on V1.
_V2_PATHS: dict[str, str] = {
    "syncs": "/api/v2/syncs",
    "sync_runs": "/api/v2/syncs/{sync_id}/sync_runs",
    "sources": "/api/v2/sources",
    # V2 replaces destination connections with activations. The table keeps its name so a repinned
    # source does not orphan it.
    "destinations": "/api/v2/activations",
    "datasets": "/api/v2/datasets",
}

# V2 source rows add `notification_emails`, which carries people's addresses, and `storage_backend`,
# whose custom-storage configuration can hold cloud credentials such as service-account keys.
_V2_EXTRA_STRIP_FIELDS: dict[str, tuple[str, ...]] = {
    "sources": ("notification_emails", "storage_backend"),
}

CENSUS_ENDPOINTS_BY_VERSION: dict[str, dict[str, CensusEndpointConfig]] = {
    CENSUS_API_V1: _V1_ENDPOINTS,
    CENSUS_API_V2: {
        name: dataclasses.replace(
            _V1_ENDPOINTS[name],
            path=path,
            strip_fields=_V1_ENDPOINTS[name].strip_fields + _V2_EXTRA_STRIP_FIELDS.get(name, ()),
        )
        for name, path in _V2_PATHS.items()
    },
}


def get_census_endpoints(api_version: str) -> dict[str, CensusEndpointConfig]:
    endpoints = CENSUS_ENDPOINTS_BY_VERSION.get(api_version)
    if endpoints is None:
        raise ValueError(f"Unsupported Census API version: {api_version}")
    return endpoints
