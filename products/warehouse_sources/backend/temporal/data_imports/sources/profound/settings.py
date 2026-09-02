from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Profound splits into two shapes: the organization reference lists, and the v2 report endpoints.
# A report is a POST whose body names one category, so reports fan out over the category list.
EndpointKind = Literal["reference", "report"]


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
