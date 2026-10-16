from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# Endpoint paths below already carry the `/v1` segment (matching the official OpenAPI spec's
# `servers` entry), so the base URL stops at `/api`.
DOVETAIL_BASE_URL = "https://dovetail.com/api"

# Dovetail's `page[limit]` caps at 100 items/request (see
# https://developers.dovetail.com/docs/pagination).
PAGE_SIZE = 100


@frozen
class DovetailEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = "created_at"
    page_size: int = PAGE_SIZE
    sort_mode: Literal["asc", "desc"] = "asc"
    primary_key: str | list[str] = "id"
    fanout: DependentEndpointConfig | None = None
    # A fan-out child whose API requires a filter with no "all" value is synced as the union of
    # one pass per value; each entry holds the extra child params for one pass.
    fanout_param_variants: tuple[dict[str, str], ...] = ()


DOVETAIL_ENDPOINTS: dict[str, DovetailEndpointConfig] = {
    # Projects, Tags, Contacts, and Users have no server-side date filter (only `page`/`sort`,
    # plus non-date filters like `folder_id`/`title`/`name`), so these are full refresh only.
    "Projects": DovetailEndpointConfig(
        name="Projects",
        path="/v1/projects",
    ),
    "Data": DovetailEndpointConfig(
        name="Data",
        path="/v1/data",
        incremental_fields=[incremental_field("created_at")],
    ),
    "Docs": DovetailEndpointConfig(
        name="Docs",
        path="/v1/docs",
        incremental_fields=[incremental_field("created_at")],
    ),
    "Highlights": DovetailEndpointConfig(
        name="Highlights",
        path="/v1/highlights",
        # Highlights also expose `filter[updated_at]`, but the endpoint's `sort` param only
        # offers `created_at:asc`/`created_at:desc` (verified against the live OpenAPI spec) -
        # there is no way to have the API return rows in updated_at order, so updated_at is not
        # safe to advertise as an incremental cursor (sort_mode would not match arrival order).
        incremental_fields=[incremental_field("created_at")],
    ),
    "Tags": DovetailEndpointConfig(
        name="Tags",
        path="/v1/tags",
    ),
    "Contacts": DovetailEndpointConfig(
        name="Contacts",
        path="/v1/contacts",
    ),
    "Users": DovetailEndpointConfig(
        name="Users",
        path="/v1/users",
    ),
    "DocComments": DovetailEndpointConfig(
        name="DocComments",
        path="/v1/docs/{doc_id}/comments",
        # Comment ids are only documented per-doc; this table aggregates comments across every
        # doc in the workspace, so the parent doc id is part of the key to keep it unique
        # table-wide.
        primary_key=["doc_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="Docs",
            resolve_param="doc_id",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "doc_id"},
        ),
    ),
    "Fields": DovetailEndpointConfig(
        name="Fields",
        # `/v1/fields` requires `filter[project_id]` (or a workspace field group id) alongside
        # `filter[field_set_type]`. The framework binds a resolved param in the path only, so the
        # project filter rides in the path and the field set type is a per-pass child param.
        path="/v1/fields?filter[project_id]={project_id}",
        # The endpoint offers no date filter, only `project_id` / `workspace_field_group_id` /
        # `field_set_type`, so this table is full refresh. A workspace field group's fields are
        # listed under every project the group is linked to, so the project is part of the key.
        primary_key=["project_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="Projects",
            resolve_param="project_id",
            resolve_field="id",
            # Field rows already carry `project_id`, so nothing needs injecting from the parent.
            include_from_parent=[],
        ),
        fanout_param_variants=(
            {"filter[field_set_type]": "data"},
            {"filter[field_set_type]": "doc"},
        ),
    ),
}

ENDPOINTS = tuple(DOVETAIL_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DOVETAIL_ENDPOINTS.items()
}
