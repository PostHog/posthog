from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Braze list endpoints paginate either with a 0-indexed ``page`` param
# (campaigns/canvas/segments/events) or a ``limit``/``offset`` pair
# (templates/content blocks). The cursor we persist for resume is the raw page
# index or row offset respectively.
PaginationStyle = Literal["page", "offset"]


@dataclass
class BrazeEndpointConfig:
    name: str
    path: str
    # Key in the JSON response body holding the list of rows.
    data_key: str
    primary_key: str
    pagination: PaginationStyle
    page_size: int = 100
    # Stable (immutable) datetime field used for partitioning. Only set when the
    # response actually carries a creation timestamp — never an updated/last-edit
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side "modified since" query param. Set only for endpoints where Braze
    # genuinely filters by it (templates/email, content_blocks). When None the
    # endpoint is full-refresh only.
    modified_after_param: Optional[str] = None
    # events/list returns a bare list of event-name strings rather than objects;
    # wrap each string under this key so the row is a dict with a stable primary key.
    wrap_scalar_as: Optional[str] = None


def _datetime_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


BRAZE_ENDPOINTS: dict[str, BrazeEndpointConfig] = {
    "campaigns": BrazeEndpointConfig(
        name="campaigns",
        path="/campaigns/list",
        data_key="campaigns",
        primary_key="id",
        pagination="page",
        # /campaigns/list documents a `last_edit.time[gte]` filter, but its bracketed
        # param syntax is fragile and we couldn't curl-verify it filters server-side
        # (no API key available), so we ship full refresh. last_edit is also mutable,
        # so it can't serve as a partition key.
    ),
    "canvases": BrazeEndpointConfig(
        name="canvases",
        path="/canvas/list",
        data_key="canvases",
        primary_key="id",
        pagination="page",
        # See campaigns: a documented but unverified `last_edit.time[gte]` filter exists.
    ),
    "segments": BrazeEndpointConfig(
        name="segments",
        path="/segments/list",
        data_key="segments",
        primary_key="id",
        pagination="page",
    ),
    "events": BrazeEndpointConfig(
        name="events",
        path="/events/list",
        data_key="events",
        primary_key="event_name",
        pagination="page",
        page_size=250,
        wrap_scalar_as="event_name",
    ),
    "email_templates": BrazeEndpointConfig(
        name="email_templates",
        path="/templates/email/list",
        data_key="templates",
        primary_key="email_template_id",
        pagination="offset",
        partition_key="created_at",
        incremental_fields=[_datetime_field("updated_at")],
        modified_after_param="modified_after",
    ),
    "content_blocks": BrazeEndpointConfig(
        name="content_blocks",
        path="/content_blocks/list",
        data_key="content_blocks",
        primary_key="content_block_id",
        pagination="offset",
        partition_key="created_at",
        # The mutable field on a content block is `last_edited`; offer it as the
        # incremental cursor since the server-side `modified_after` filter keys off it.
        incremental_fields=[_datetime_field("last_edited")],
        modified_after_param="modified_after",
    ),
}

ENDPOINTS = tuple(BRAZE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BRAZE_ENDPOINTS.items()
}
