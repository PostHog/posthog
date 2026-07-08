from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class DelightedEndpointConfig:
    name: str
    path: str
    # "page" = page/per_page offset pagination, "link" = RFC 5988 Link header cursor,
    # "none" = single-object endpoint with no pagination.
    pagination: Literal["page", "link", "none"]
    primary_key: Optional[str] = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental cursor field to the query param that filters on it server-side.
    incremental_param_map: dict[str, str] = field(default_factory=dict)
    # Maps an incremental cursor field to the `order` query param value that sorts by it.
    # Only survey_responses documents an `order` param; other endpoints return oldest-first.
    order_param_map: dict[str, str] = field(default_factory=dict)
    default_order: Optional[str] = None
    # Stable event-time field used for datetime partitioning. Never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    extra_params: dict[str, str] = field(default_factory=dict)


# Delighted timestamps are UNIX epoch seconds, so candidate incremental fields are stored as
# integers even though the UI presents them as datetimes. survey_responses supports a true
# updated_at cursor (`updated_since` + `order=asc:updated_at`); the other list endpoints only
# filter on their event timestamp via `since`, so they are append-only incremental.
DELIGHTED_ENDPOINTS: dict[str, DelightedEndpointConfig] = {
    "survey_responses": DelightedEndpointConfig(
        name="survey_responses",
        path="/survey_responses.json",
        pagination="page",
        partition_key="created_at",
        # eNPS responses are anonymous and carry no person record, so the expanded
        # `person` object can be null on a response.
        extra_params={"expand[]": "person"},
        incremental_param_map={"updated_at": "updated_since", "created_at": "since"},
        order_param_map={"updated_at": "asc:updated_at", "created_at": "asc"},
        default_order="asc",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "people": DelightedEndpointConfig(
        name="people",
        path="/people.json",
        pagination="link",
        partition_key="created_at",
        incremental_param_map={"created_at": "since"},
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # Unsubscribes and bounces have no `id` field; person_id is the only stable identifier
    # documented, so we key on it (one row per person is assumed, matching other connectors).
    "unsubscribes": DelightedEndpointConfig(
        name="unsubscribes",
        path="/unsubscribes.json",
        pagination="page",
        primary_key="person_id",
        partition_key="unsubscribed_at",
        incremental_param_map={"unsubscribed_at": "since"},
        incremental_fields=[
            {
                "label": "unsubscribed_at",
                "type": IncrementalFieldType.DateTime,
                "field": "unsubscribed_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "bounces": DelightedEndpointConfig(
        name="bounces",
        path="/bounces.json",
        pagination="page",
        primary_key="person_id",
        partition_key="bounced_at",
        incremental_param_map={"bounced_at": "since"},
        incremental_fields=[
            {
                "label": "bounced_at",
                "type": IncrementalFieldType.DateTime,
                "field": "bounced_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    # Point-in-time snapshot of account NPS metrics — a single object, full refresh only.
    "metrics": DelightedEndpointConfig(
        name="metrics",
        path="/metrics.json",
        pagination="none",
        primary_key=None,
    ),
}

ENDPOINTS = tuple(DELIGHTED_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DELIGHTED_ENDPOINTS.items() if config.incremental_fields
}
