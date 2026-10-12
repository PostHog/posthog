from dataclasses import dataclass, field
from typing import Optional

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


def _incremental_field(field_name: str) -> list[IncrementalField]:
    return [
        {
            "label": field_name,
            "type": IncrementalFieldType.DateTime,
            "field": field_name,
            "field_type": IncrementalFieldType.Integer,
        },
    ]


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
}

ENDPOINTS = tuple(COMPANYCAM_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in COMPANYCAM_ENDPOINTS.items()
}
