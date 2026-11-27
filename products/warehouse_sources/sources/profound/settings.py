from dataclasses import field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

# Profound splits into three shapes: the organization reference lists, the per-category reference
# lists, and the v2 report endpoints. The last two take one category each, so they fan out over the
# category list.
EndpointKind = Literal["reference", "category_reference", "report"]


@frozen
class ProfoundEndpointConfig:
    name: str
    path: str
    kind: EndpointKind
    # Wrapper key holding the array. `None` for the reference endpoints that return a bare array.
    data_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    # Report-only: the metrics to request. They come back as named fields on each row.
    metrics: list[str] = field(default_factory=list)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Extra query params for the GET list endpoints.
    params: dict[str, Any] = field(default_factory=dict)
    # Path to the next-page cursor in the body. `None` for the lists that return everything at once.
    cursor_path: Optional[str] = None


def _date_field() -> list[IncrementalField]:
    return [
        {
            "label": "date",
            "type": IncrementalFieldType.Date,
            "field": "date",
            "field_type": IncrementalFieldType.Date,
        }
    ]


PROFOUND_ENDPOINTS: dict[str, ProfoundEndpointConfig] = {
    # Reference lists. Small, unpaginated, and full refresh: they carry no time filter.
    "Categories": ProfoundEndpointConfig(
        name="Categories",
        path="/v1/org/categories",
        kind="reference",
    ),
    "Models": ProfoundEndpointConfig(
        name="Models",
        path="/v1/org/models",
        kind="reference",
    ),
    "Regions": ProfoundEndpointConfig(
        name="Regions",
        path="/v1/org/regions",
        kind="reference",
    ),
    "Domains": ProfoundEndpointConfig(
        name="Domains",
        path="/v1/org/domains",
        kind="reference",
        partition_key="created_at",
    ),
    # These two wrap their array in `data` where the four above return it bare.
    "Assets": ProfoundEndpointConfig(
        name="Assets",
        path="/v1/org/assets",
        kind="reference",
        data_key="data",
        partition_key="created_at",
    ),
    "Personas": ProfoundEndpointConfig(
        name="Personas",
        path="/v1/org/personas",
        kind="reference",
        data_key="data",
    ),
    # Per-category lists, keyed by `value` because these carry no id. `value` is unique only within a
    # category, so the key needs `category_id` too.
    "CitationCategories": ProfoundEndpointConfig(
        name="CitationCategories",
        path="/v1/org/categories/{category_id}/citation-categories",
        kind="category_reference",
        data_key="data",
        primary_keys=["category_id", "value"],
    ),
    "CitationTags": ProfoundEndpointConfig(
        name="CitationTags",
        path="/v1/org/categories/{category_id}/citation-tags",
        kind="category_reference",
        data_key="data",
        primary_keys=["category_id", "value"],
    ),
    # Topic and tag ids are not documented as unique across categories, so the key carries the category.
    "Topics": ProfoundEndpointConfig(
        name="Topics",
        path="/v1/org/categories/{category_id}/topics",
        kind="category_reference",
        primary_keys=["category_id", "id"],
    ),
    "Tags": ProfoundEndpointConfig(
        name="Tags",
        path="/v1/org/categories/{category_id}/tags",
        kind="category_reference",
        primary_keys=["category_id", "id"],
    ),
    # The prompt list has no time filter, so it stays full refresh.
    "Prompts": ProfoundEndpointConfig(
        name="Prompts",
        path="/v1/org/categories/{category_id}/prompts",
        kind="category_reference",
        data_key="data",
        primary_keys=["category_id", "id"],
        partition_key="created_at",
        params={
            "limit": 1000,
            # The API returns only active prompts unless asked for both.
            "status": ["active", "disabled"],
            "order_by": "created_at",
            "order_dir": "asc",
        },
        cursor_path="info.next_cursor",
    ),
    # Reports, one row per category per day. `category_id` is injected from the fan-out because the
    # response echoes only what was grouped on.
    "Visibility": ProfoundEndpointConfig(
        name="Visibility",
        path="/v2/reports/visibility",
        kind="report",
        data_key="data",
        primary_keys=["category_id", "date", "asset_name"],
        partition_key="date",
        metrics=["visibility_score", "share_of_voice", "average_position"],
        incremental_fields=_date_field(),
    ),
    "Citations": ProfoundEndpointConfig(
        name="Citations",
        path="/v2/reports/citations",
        kind="report",
        data_key="data",
        primary_keys=["category_id", "date", "domain"],
        partition_key="date",
        metrics=["count", "citation_share", "rank"],
        incremental_fields=_date_field(),
    ),
}

ENDPOINTS = tuple(PROFOUND_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PROFOUND_ENDPOINTS.items()
}
