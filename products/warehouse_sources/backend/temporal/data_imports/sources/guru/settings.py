from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
class GuruEndpointConfig:
    name: str
    path: str
    primary_key: str | list[str] = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an
    # updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Static query params sent on the first request of a page chain.
    extra_params: dict[str, str] = field(default_factory=dict)
    # Query param that takes the incremental cursor as an inclusive lower bound. When unset,
    # incremental endpoints filter with a Guru Query Language `q` expression instead.
    date_filter_param: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None

    @property
    def default_incremental_field(self) -> Optional[str]:
        return self.incremental_fields[0]["field"] if self.incremental_fields else None

    @property
    def page_size(self) -> int:
        # Guru fixes the page size per endpoint and takes no page-size param.
        return 0


# Guru responses are bare JSON arrays paginated via a `Link: <url>; rel="next-page"`
# header with an opaque continuation token. Only the card search surface (Guru Query
# Language `lastModified >= <ISO8601>`) and the analytics event export (`fromDate`) support
# a server-side date filter; the dimension tables are full refresh per run. A `{team_id}`
# path placeholder is filled from the authenticated user's team.
GURU_ENDPOINTS: dict[str, GuruEndpointConfig] = {
    "cards": GuruEndpointConfig(
        name="cards",
        path="/search/query",
        partition_key="dateCreated",
        extra_params={"queryType": "cards", "maxResults": "50"},
        incremental_fields=[
            {
                "label": "lastModified",
                "type": IncrementalFieldType.DateTime,
                "field": "lastModified",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "collections": GuruEndpointConfig(
        name="collections",
        path="/collections",
    ),
    "groups": GuruEndpointConfig(
        name="groups",
        path="/groups",
    ),
    "members": GuruEndpointConfig(
        name="members",
        path="/members",
        # Member rows have no top-level id; the transport copies user.email to a
        # top-level `email` so it can serve as the primary key.
        primary_key="email",
    ),
    "group_members": GuruEndpointConfig(
        name="group_members",
        path="/groups/{groupId}/members",
        # Members carry no top-level id; email (copied from user.email) plus the parent group
        # is unique across the table.
        primary_key=["group_id", "email"],
        fanout=DependentEndpointConfig(
            parent_name="groups",
            resolve_param="groupId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "group_id"},
        ),
    ),
    "folders": GuruEndpointConfig(
        name="folders",
        path="/folders",
    ),
    "folder_items": GuruEndpointConfig(
        name="folder_items",
        path="/folders/{folderId}/items",
        # A card can sit in several folders, so the item id is only unique per folder.
        primary_key=["folder_id", "id"],
        fanout=DependentEndpointConfig(
            parent_name="folders",
            resolve_param="folderId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "folder_id"},
        ),
    ),
    "tag_categories": GuruEndpointConfig(
        name="tag_categories",
        path="/teams/{team_id}/tagcategories",
    ),
    "tags": GuruEndpointConfig(
        name="tags",
        # Guru has no tag list endpoint; tags are flattened out of each tag category.
        path="/teams/{team_id}/tagcategories",
    ),
    "analytics_events": GuruEndpointConfig(
        name="analytics_events",
        path="/teams/{team_id}/analytics",
        partition_key="eventDate",
        date_filter_param="fromDate",
        incremental_fields=[
            {
                "label": "eventDate",
                "type": IncrementalFieldType.DateTime,
                "field": "eventDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(GURU_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GURU_ENDPOINTS.items() if config.incremental_fields
}
