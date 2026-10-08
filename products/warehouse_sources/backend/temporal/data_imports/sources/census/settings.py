from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

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


CENSUS_ENDPOINTS: dict[str, CensusEndpointConfig] = {
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

ENDPOINTS = tuple(CENSUS_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CENSUS_ENDPOINTS.items()
}
