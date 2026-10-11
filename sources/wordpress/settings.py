from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class WordpressEndpointConfig:
    name: str
    path: str  # Path under /wp-json/wp/v2, e.g. "/posts"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Maps an incremental field name to the WordPress query param that bounds it server-side.
    # WordPress filters on the local `post_date`/`post_modified` columns: `after`/`before` bound
    # `date`, `modified_after`/`modified_before` bound `modified`. Only fields listed here actually
    # filter server-side (verified against the live API — comments silently ignore `modified_after`).
    incremental_filter_params: dict[str, str] = field(default_factory=dict)
    # Column to order by on a full / first sync. Every wp/v2 list endpoint accepts `orderby`; the
    # incremental field name doubles as its `orderby` value (date, modified, id all valid).
    stable_order_by: str = "id"
    partition_key: Optional[str] = None
    primary_key: str = "id"
    page_size: int = 100  # WordPress caps per_page at 100; larger values 400


# Core REST API (wp/v2) collections the canonical WordPress connectors (Airbyte/Fivetran) expose.
# Incremental support is only declared where a server-side timestamp filter actually drops rows
# (verified against the live API with a future-date cutoff).
WORDPRESS_ENDPOINTS: dict[str, WordpressEndpointConfig] = {
    "posts": WordpressEndpointConfig(
        name="posts",
        path="/posts",
        incremental_fields=[
            _datetime_incremental_field("modified"),
            _datetime_incremental_field("date"),
        ],
        default_incremental_field="modified",
        incremental_filter_params={"modified": "modified_after", "date": "after"},
        stable_order_by="date",
        partition_key="date",
    ),
    "pages": WordpressEndpointConfig(
        name="pages",
        path="/pages",
        incremental_fields=[
            _datetime_incremental_field("modified"),
            _datetime_incremental_field("date"),
        ],
        default_incremental_field="modified",
        incremental_filter_params={"modified": "modified_after", "date": "after"},
        stable_order_by="date",
        partition_key="date",
    ),
    "comments": WordpressEndpointConfig(
        name="comments",
        path="/comments",
        # Comments expose only a `date` column and silently ignore `modified_after`/`orderby=modified`
        # (both verified against the live API), so `date`/`after` is the only incremental cursor.
        incremental_fields=[
            _datetime_incremental_field("date"),
        ],
        default_incremental_field="date",
        incremental_filter_params={"date": "after"},
        stable_order_by="date",
        partition_key="date",
    ),
    "media": WordpressEndpointConfig(
        name="media",
        path="/media",
        incremental_fields=[
            _datetime_incremental_field("modified"),
            _datetime_incremental_field("date"),
        ],
        default_incremental_field="modified",
        incremental_filter_params={"modified": "modified_after", "date": "after"},
        stable_order_by="date",
        partition_key="date",
    ),
    # Taxonomy terms and users have no date column and no server-side timestamp filter -> full refresh
    # only. Ordered by id for stable pagination.
    "categories": WordpressEndpointConfig(
        name="categories",
        path="/categories",
        stable_order_by="id",
    ),
    "tags": WordpressEndpointConfig(
        name="tags",
        path="/tags",
        stable_order_by="id",
    ),
    "users": WordpressEndpointConfig(
        name="users",
        path="/users",
        stable_order_by="id",
    ),
}

ENDPOINTS = tuple(WORDPRESS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WORDPRESS_ENDPOINTS.items()
}
