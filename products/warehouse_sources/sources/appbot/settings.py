from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, incremental_field

APPBOT_V2 = "v2"

EndpointKind = Literal["apps", "reviews", "ratings"]


@dataclass(frozen=True)
class AppbotEndpointConfig:
    name: str
    kind: EndpointKind
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_key: str | None = None


APPBOT_ENDPOINTS: dict[str, AppbotEndpointConfig] = {
    "apps": AppbotEndpointConfig(name="apps", kind="apps", primary_keys=["id"]),
    "reviews": AppbotEndpointConfig(
        name="reviews",
        kind="reviews",
        # Review ids are only documented per app, so the app id is part of the key.
        primary_keys=["app_id", "id"],
        partition_key="published_at",
        incremental_fields=[incremental_field("published_at", IncrementalFieldType.Date)],
    ),
    "ratings": AppbotEndpointConfig(
        name="ratings",
        kind="ratings",
        # `id` is built from the app, the country and the snapshot time, because the all-country
        # summary rows have no country_id and a null key column cannot be merged.
        primary_keys=["id"],
        partition_key="created_at",
        incremental_fields=[incremental_field("created_at")],
    ),
}

ENDPOINTS = tuple(APPBOT_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in APPBOT_ENDPOINTS.items()
}
