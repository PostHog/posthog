from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# CompanyCam's documented ceiling for `per_page` is 100 (default 50). Requesting the max on
# every endpoint minimises round trips; endpoints without a documented cap accept it too.
PER_PAGE = 100


@dataclass(frozen=True)
class CompanycamEndpointConfig:
    name: str
    path: str  # Path under https://api.companycam.com/v2
    # Field CompanyCam filters on server-side for this endpoint (`modified_since` on Projects,
    # `start_date` on Photos/Videos), or None when the endpoint has no time filter.
    incremental_query_param: Optional[str] = None
    # The rows come back newest-first for every incremental-capable list endpoint here, so the
    # watermark can only be finalized once a full sync completes (see SourceResponse.sort_mode).
    sort_mode: SortMode = "desc"
    # Stable field to partition by. Capture time for photos/videos, creation time otherwise.
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether this endpoint's cursor pagination comes from the `X-Next-Cursor` response header
    # (Photos) rather than `page`/`per_page`.
    cursor_paginated: bool = False
    # False for endpoints the docs show no page/per_page params for (ChecklistTemplates returns
    # a company's full template list in one response).
    paginated: bool = True
    # Set for child resources CompanyCam only exposes per parent (e.g. labels under a project).
    fanout: Optional[DependentEndpointConfig] = None
    # Off by default for fan-outs that cost one request per parent row on every sync.
    should_sync_default: bool = True
    page_size: int = PER_PAGE
    # Read by the fan-out helper's FanoutEndpointLike protocol. Every fan-out child here is full
    # refresh, so it is never used to build an incremental request.
    default_incremental_field: Optional[str] = None


def _incremental_field(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.Integer,
        },
    ]


def _project_fanout() -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="Projects",
        resolve_param="project_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "project_id"},
    )


COMPANYCAM_ENDPOINTS: dict[str, CompanycamEndpointConfig] = {
    "Projects": CompanycamEndpointConfig(
        name="Projects",
        path="/projects",
        incremental_query_param="modified_since",
        incremental_fields=_incremental_field("updated_at"),
    ),
    "Photos": CompanycamEndpointConfig(
        name="Photos",
        path="/photos",
        incremental_query_param="start_date",
        incremental_fields=_incremental_field("captured_at"),
        partition_key="captured_at",
        cursor_paginated=True,
    ),
    "Videos": CompanycamEndpointConfig(
        name="Videos",
        path="/videos",
        incremental_query_param="start_date",
        incremental_fields=_incremental_field("captured_at"),
        partition_key="captured_at",
    ),
    "Users": CompanycamEndpointConfig(
        name="Users",
        path="/users",
    ),
    "Tags": CompanycamEndpointConfig(
        name="Tags",
        path="/tags",
    ),
    "Groups": CompanycamEndpointConfig(
        name="Groups",
        path="/groups",
    ),
    "Checklists": CompanycamEndpointConfig(
        name="Checklists",
        path="/checklists",
    ),
    "ChecklistTemplates": CompanycamEndpointConfig(
        name="ChecklistTemplates",
        path="/templates/checklists",
        paginated=False,
    ),
    # Fan-out children. The child rows carry no parent reference, so the parent id is injected and
    # kept in the primary key: the same user, label, or tag appears under many parents.
    "ProjectAssignedUsers": CompanycamEndpointConfig(
        name="ProjectAssignedUsers",
        path="/projects/{project_id}/assigned_users",
        primary_keys=["project_id", "id"],
        fanout=_project_fanout(),
    ),
    "ProjectLabels": CompanycamEndpointConfig(
        name="ProjectLabels",
        path="/projects/{project_id}/labels",
        primary_keys=["project_id", "id"],
        fanout=_project_fanout(),
    ),
    "ProjectDocuments": CompanycamEndpointConfig(
        name="ProjectDocuments",
        path="/projects/{project_id}/documents",
        primary_keys=["project_id", "id"],
        fanout=_project_fanout(),
    ),
    "PhotoTags": CompanycamEndpointConfig(
        name="PhotoTags",
        path="/photos/{photo_id}/tags",
        primary_keys=["photo_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="Photos",
            resolve_param="photo_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "photo_id"},
        ),
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(COMPANYCAM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COMPANYCAM_ENDPOINTS.items()
}

SHOULD_SYNC_DEFAULT: dict[str, bool] = {
    name: config.should_sync_default for name, config in COMPANYCAM_ENDPOINTS.items()
}
