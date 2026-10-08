from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass(frozen=True)
class HexEndpointConfig:
    name: str
    path: str
    data_selector: str
    primary_keys: tuple[str, ...]
    # "cursor" endpoints page via the `after` token in `pagination.after`; "offset" endpoints
    # (GetProjectRuns) page via numeric `limit`/`offset` params.
    pagination: Literal["cursor", "offset"]
    page_size: int = 100
    # Static query params sent on every request (explicit stable sort where the API supports one,
    # so page boundaries don't shift mid-sync).
    params: dict[str, Any] = field(default_factory=dict)
    # Stable, immutable field to partition by (never a field that mutates on edits).
    partition_key: Optional[str] = None
    # Endpoint that must be paginated first to resolve `{placeholder}` in `path` (fan-out).
    parent: Optional[str] = None
    resolve_param: Optional[str] = None
    resolve_field: Optional[str] = None
    # Parent fields copied onto each child row, as `{parent field: child column}`.
    include_from_parent: dict[str, str] = field(default_factory=dict)
    sort_mode: Literal["asc", "desc"] = "asc"


HEX_ENDPOINTS: dict[str, HexEndpointConfig] = {
    "projects": HexEndpointConfig(
        name="projects",
        path="/v1/projects",
        data_selector="values",
        primary_keys=("id",),
        pagination="cursor",
        page_size=100,
        # createdAt never changes, so it is both a stable sort (page boundaries can't shift as
        # projects are edited mid-sync) and the partition key. Archived projects are included so
        # the table keeps the full inventory; `archivedAt` marks them.
        params={"sortBy": "CREATED_AT", "sortDirection": "ASC", "includeArchived": "true"},
        partition_key="createdAt",
    ),
    "project_runs": HexEndpointConfig(
        name="project_runs",
        path="/v1/projects/{projectId}/runs",
        data_selector="runs",
        # runId is a UUID, but runs are fetched per project, so the parent id stays in the key.
        primary_keys=("projectId", "runId"),
        pagination="offset",
        page_size=100,
        parent="projects",
        resolve_param="projectId",
        resolve_field="id",
        # GetProjectRuns has no sort param and returns run history newest-first.
        sort_mode="desc",
        # startTime is null for pending runs, so it can't be a partition key.
    ),
    "users": HexEndpointConfig(
        name="users",
        path="/v1/users",
        data_selector="values",
        primary_keys=("id",),
        pagination="cursor",
        page_size=500,
        # Email is the most stable of the two supported sort attributes (NAME, EMAIL).
        params={"sortBy": "EMAIL", "sortDirection": "ASC"},
    ),
    "groups": HexEndpointConfig(
        name="groups",
        path="/v1/groups",
        data_selector="values",
        primary_keys=("id",),
        pagination="cursor",
        page_size=500,
        params={"sortBy": "CREATED_AT", "sortDirection": "ASC"},
    ),
    "collections": HexEndpointConfig(
        name="collections",
        path="/v1/collections",
        data_selector="values",
        primary_keys=("id",),
        pagination="cursor",
        page_size=100,
        # ListCollections only supports sortBy=NAME (and no sortDirection param).
        params={"sortBy": "NAME"},
    ),
    "data_connections": HexEndpointConfig(
        name="data_connections",
        path="/v1/data-connections",
        data_selector="values",
        primary_keys=("id",),
        pagination="cursor",
        page_size=100,
        # createdAt is not returned, but it is the stable sort of the two supported (NAME, CREATED_AT).
        params={"sortBy": "CREATED_AT", "sortDirection": "ASC"},
    ),
    "queried_tables": HexEndpointConfig(
        name="queried_tables",
        path="/v1/projects/{projectId}/queriedTables",
        data_selector="values",
        # Rows carry no project id, so it is injected from the parent to keep the key table-wide unique.
        primary_keys=("projectId", "dataConnectionId", "tableName"),
        pagination="cursor",
        page_size=100,
        parent="projects",
        resolve_param="projectId",
        resolve_field="id",
        include_from_parent={"id": "projectId"},
    ),
    "cells": HexEndpointConfig(
        name="cells",
        # ListCells takes the project as a required query param, which the framework can only
        # resolve from the path.
        path="/v1/cells?projectId={projectId}",
        data_selector="values",
        primary_keys=("projectId", "id"),
        pagination="cursor",
        page_size=100,
        parent="projects",
        resolve_param="projectId",
        resolve_field="id",
    ),
    "threads": HexEndpointConfig(
        name="threads",
        path="/v1/threads",
        data_selector="threads",
        primary_keys=("id",),
        pagination="cursor",
        page_size=100,
        # ListThreads has no sort param and returns the newest threads first.
        sort_mode="desc",
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(HEX_ENDPOINTS.keys())

# The Hex API exposes no usable server-side timestamp filter on any list endpoint (ListProjects only
# filters by status/category/creator/owner/collection; GetProjectRuns only by run status and
# trigger; ListThreads' `numDays` bounds whole days of creation, but threads keep changing after
# that), so every endpoint is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
